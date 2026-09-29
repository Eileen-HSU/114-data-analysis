"""

意義單元拆分：呼叫 Gemini #1 取得 segment_text 清單，本地驗證後
換算成原文座標。只有驗證通過的 segment 才能送進分類（Gemini #2）。

Gemini 只回傳逐字 segment_text，不提供任何位置資訊；位置完全由
這裡在 masked_text 上定位、驗證、再用 privacy_service 的
PiiPositionMap 換算回原文座標。
"""

import json
import os
import re
import time
import unicodedata

from services import gemini_client as genai

from services.privacy_service import PlaceholderBoundaryError

genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

_RETRY_DELAY_PATTERNS = (
    re.compile(r"[Rr]etry in ([\d.]+)s"),
    re.compile(r'"retryDelay"\s*:\s*"([\d.]+)s"'),
)


def _extract_retry_delay_seconds(exc: Exception):
    text = str(exc)
    for pattern in _RETRY_DELAY_PATTERNS:
        match = pattern.search(text)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                continue
    return None


def _is_rate_limit_error(exc: Exception) -> bool:
    text = str(exc)
    return "429" in text or "ResourceExhausted" in type(exc).__name__ or "RESOURCE_EXHAUSTED" in text


SEGMENTATION_PROMPT = """你是問卷回覆的語意拆分助手。判斷這則回覆是否包含多個可獨立分開的
意義單元（不同主題、不同訴求）。可以乾淨拆開才拆，拆不開的內容
（同一句話同時涉及兩個主題但無法切開）保留成一個片段就好，不要
硬拆。

規則：
1. 每個片段必須是原文的逐字內容，不可以改寫、摘要、補字。
2. 片段之間不可以重複。
3. 【重要】所有片段依序接起來，必須完整涵蓋原文全部內容，中間不
   能有任何遺漏——轉折詞（例如「但」「不過」「而且」）、逗號、頓號
   等連接文字，都要算進前一個片段的結尾或後一個片段的開頭，不可以
   被丟在兩個片段中間、完全不屬於任何一個片段。
   例如原文「內容很好，但時間太趕。」如果要拆成兩段，應該拆成
   「內容很好，」與「但時間太趕。」（逗號和「但」都有被涵蓋），
   不可以拆成「內容很好」與「時間太趕。」（丟掉了逗號跟「但」）。
4. 只回傳以下 JSON 格式，不要加任何其他文字：

{"segments": ["片段1原文", "片段2原文", ...]}"""


class SegmentValidationError(ValueError):
    """單一 segment 驗證失敗時使用（找不到、切在標籤中間、重疊）。"""


def _call_gemini_segmentation(masked_text: str) -> list:
    """429 限流照建議秒數重試（最多 2 次）；503 / UNAVAILABLE（模型暫時
    過載）依 genai.UNAVAILABLE_RETRY_DELAYS_SECONDS 退避重試；其他錯誤
    （含 JSON 解析失敗）直接往上拋。"""
    rate_limit_retries = 0
    unavailable_retries = 0
    while True:
        try:
            model = genai.GenerativeModel(
                model_name="gemini-3.1-flash-lite",
                system_instruction=SEGMENTATION_PROMPT,
            )
            response = model.generate_content(
                f"問卷回覆內容:\n{masked_text}",
                generation_config={"temperature": 0},
            )
            cleaned = re.sub(r"```json|```", "", response.text).strip()
            parsed = json.loads(cleaned)
            return parsed["segments"]
        except Exception as e:
            if _is_rate_limit_error(e) and rate_limit_retries < 2:
                rate_limit_retries += 1
                delay = _extract_retry_delay_seconds(e) or 20.0
                time.sleep(delay + 1.0)
                continue
            if genai.is_transient_unavailable_error(e) and unavailable_retries < len(genai.UNAVAILABLE_RETRY_DELAYS_SECONDS):
                delay = genai.UNAVAILABLE_RETRY_DELAYS_SECONDS[unavailable_retries]
                unavailable_retries += 1
                print(f"[SEGMENTATION_RETRY][UNAVAILABLE] attempt={unavailable_retries} retry_in={delay}s", repr(e)[:200])
                time.sleep(delay)
                continue
            raise



def is_trivial_gap_text(text: str) -> bool:
    """片段之間的空隙如果只有空白或標點符號（不含任何文字、數字、
    遮罩標籤），視為「沒有語意內容」，可以安全併入相鄰片段。

    遮罩標籤「【姓名】」的括號本身是標點，但標籤內的文字不是，所以
    只要空隙碰到任何一個標籤字元（例如「姓」）就不算 trivial。"""
    for ch in text:
        if ch.isspace():
            continue
        if unicodedata.category(ch).startswith("P"):
            continue
        return False
    return True


def find_coverage_gaps(text: str, spans) -> list:
    """回傳 text 裡「沒有被任何 span 涵蓋、且不是 trivial」的區間。

    spans: [(start, end), ...]，必須已經依序且互不重疊。
    檢查範圍包含：原文開頭到第一段之前、片段與片段之間、最後一段到
    原文結尾。回傳 [(gap_start, gap_end), ...]；空清單代表完整涵蓋
    （只剩空白 / 標點空隙）。"""
    gaps = []
    cursor = 0
    for start, end in list(spans) + [(len(text), len(text))]:
        if start > cursor and not is_trivial_gap_text(text[cursor:start]):
            gaps.append((cursor, start))
        cursor = max(cursor, end)
    return gaps


def _locate_and_validate(masked_text: str, segment_texts: list, position_map):
    """
    依序在 masked_text 裡定位每個 segment_text，驗證不重疊、
    不切在遮罩標籤中間，換算成原文座標。

    回傳 (valid_segments, failed_segments)：
        valid_segments: [{"orig_start", "orig_end", "masked_text",
                          "m_start", "m_end"}, ...]（m_* 是 masked_text
                          座標，只供本模組做完整涵蓋檢查，不對外回傳）
        failed_segments: [{"segment_text": str, "reason": str}, ...]
    """
    valid_segments = []
    failed_segments = []
    search_from = 0  # 依序往後找，避免同一段文字重複比對到前面已用過的位置

    for seg_text in segment_texts:
        try:
            if not isinstance(seg_text, str) or not seg_text:
                raise SegmentValidationError("空字串片段")

            m_start = masked_text.find(seg_text, search_from)
            if m_start == -1:
                raise SegmentValidationError("在 masked_text 裡找不到逐字相符內容（或跟前一段重疊）")
            m_end = m_start + len(seg_text)

            orig_start, orig_end = position_map.to_original_range(m_start, m_end)

            valid_segments.append({
                "orig_start": orig_start,
                "orig_end": orig_end,
                "masked_text": seg_text,  # 送去 Gemini #2 分類用，本來就是遮罩後內容
                "m_start": m_start,
                "m_end": m_end,
            })
            search_from = m_end  # 天然保證不重疊：下一段只往後找

        # PlaceholderBoundaryError 也是 ValueError 的子類別，必須先接住，
        # 否則原因會被誤記成「找不到」。
        except PlaceholderBoundaryError as e:
            failed_segments.append({"segment_text": seg_text, "reason": str(e)})
        except SegmentValidationError as e:
            failed_segments.append({"segment_text": seg_text, "reason": str(e)})

    return valid_segments, failed_segments


def _absorb_trivial_gaps(masked_text: str, valid_segments: list, position_map):
    """把只含空白 / 標點的空隙併進相鄰片段，讓片段從原文開頭到結尾
    連續、無空隙。開頭的空隙併入第一段，其餘併入前一段的結尾。

    換算失敗（理論上不會發生，因為 trivial 空隙不含標籤文字）時回傳
    None，由呼叫端改走整則回退。"""
    bounds = [[seg["m_start"], seg["m_end"]] for seg in valid_segments]
    bounds[0][0] = 0
    for i in range(len(bounds) - 1):
        bounds[i][1] = bounds[i + 1][0]
    bounds[-1][1] = len(masked_text)

    absorbed = []
    for m_start, m_end in bounds:
        try:
            orig_start, orig_end = position_map.to_original_range(m_start, m_end)
        except PlaceholderBoundaryError:
            return None
        absorbed.append({
            "orig_start": orig_start,
            "orig_end": orig_end,
            "masked_text": masked_text[m_start:m_end],
        })
    return absorbed


def _whole_answer_segment(masked_text: str, position_map) -> list:
    orig_start, orig_end = position_map.to_original_range(0, len(masked_text))
    return [{"orig_start": orig_start, "orig_end": orig_end, "masked_text": masked_text}]


def segment_answer(masked_text: str, position_map) -> dict:
    """
    對外主要介面。

    回傳：
    {
        "segments": [{"orig_start": int, "orig_end": int, "masked_text": str}, ...],
        "segmentation_status": "completed" / "partial_failed" / "failed",
        "error_detail": str or None,
    }

    完整涵蓋原則：只有「所有片段依序接起來涵蓋原文開頭到結尾、片段間
    只剩空白 / 標點」時才會是 completed（空白 / 標點會被併進相鄰片段，
    回傳的片段彼此連續）。只要 AI 回傳的片段漏掉任何文字（首段、中間、
    尾段），或有任何片段定位失敗，就不採用這次拆分，改把「整則回答」
    當成單一片段送分類，狀態標成 partial_failed 並在 error_detail 記錄
    SEGMENTATION_COVERAGE_GAP 與漏掉的內容——原文不會無聲消失在分類
    與報告中，管理員也能從失敗清單看到並重跑。
    """
    if not masked_text or not masked_text.strip():
        return {"segments": [], "segmentation_status": "failed", "error_detail": "EMPTY_ANSWER"}

    try:
        segment_texts = _call_gemini_segmentation(masked_text)
        if not isinstance(segment_texts, list):
            raise ValueError("segments 不是清單")
    except Exception as e:
        return {
            "segments": [],
            "segmentation_status": "failed",
            "error_detail": f"SEGMENTATION_CALL_FAILED: {str(e)[:180]}",
        }

    valid, failed = _locate_and_validate(masked_text, segment_texts, position_map)
    gaps = find_coverage_gaps(masked_text, [(seg["m_start"], seg["m_end"]) for seg in valid])

    segments = None
    if valid and not failed and not gaps:
        segments = _absorb_trivial_gaps(masked_text, valid, position_map)
        if segments is not None:
            return {"segments": segments, "segmentation_status": "completed", "error_detail": None}

    # ── 回退：拆分結果不完整，整則回答當成單一片段 ──
    problems = []
    if gaps:
        missing = "; ".join(repr(masked_text[s:e][:30]) for s, e in gaps[:5])
        problems.append(f"片段未完整涵蓋原文，缺漏 {len(gaps)} 處: {missing}")
    if failed:
        problems.append("; ".join(f"{f['segment_text'][:20]!r}: {f['reason']}" for f in failed if isinstance(f['segment_text'], str)) or "片段格式錯誤")
    if not problems:
        problems.append("併入標點空隙時換算原文座標失敗")
    error_detail = (
        "SEGMENTATION_COVERAGE_GAP: 已改以整則回答作為單一片段分類。" + " | ".join(problems)
    )[:500]

    return {
        "segments": _whole_answer_segment(masked_text, position_map),
        "segmentation_status": "partial_failed",
        "error_detail": error_detail,
    }
