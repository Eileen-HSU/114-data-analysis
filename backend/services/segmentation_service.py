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

import google.generativeai as genai

from services.privacy_service import PlaceholderBoundaryError

genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

SEGMENTATION_PROMPT = """你是問卷回覆的語意拆分助手。判斷這則回覆是否包含多個可獨立分開的
意義單元（不同主題、不同訴求）。可以乾淨拆開才拆，拆不開的內容
（同一句話同時涉及兩個主題但無法切開）保留成一個片段就好，不要
硬拆。

規則：
1. 每個片段必須是原文的逐字內容，不可以改寫、摘要、補字。
2. 片段之間不可以重複。
3. 只回傳以下 JSON 格式，不要加任何其他文字：

{"segments": ["片段1原文", "片段2原文", ...]}"""


class SegmentValidationError(ValueError):
    """單一 segment 驗證失敗時使用（找不到、切在標籤中間、重疊）。"""


def _call_gemini_segmentation(masked_text: str) -> list:
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


def _locate_and_validate(masked_text: str, segment_texts: list, position_map):
    """
    依序在 masked_text 裡定位每個 segment_text，驗證不重疊、
    不切在遮罩標籤中間，換算成原文座標。

    回傳 (valid_segments, failed_segments)：
        valid_segments: [{"orig_start": int, "orig_end": int, "masked_text": str}, ...]
        failed_segments: [{"segment_text": str, "reason": str}, ...]
    """
    valid_segments = []
    failed_segments = []
    search_from = 0  # 依序往後找，避免同一段文字重複比對到前面已用過的位置

    for seg_text in segment_texts:
        try:
            if not seg_text:
                raise SegmentValidationError("空字串片段")

            m_start = masked_text.index(seg_text, search_from)
            m_end = m_start + len(seg_text)

            orig_start, orig_end = position_map.to_original_range(m_start, m_end)

            valid_segments.append({
                "orig_start": orig_start,
                "orig_end": orig_end,
                "masked_text": seg_text,  # 送去 Gemini #2 分類用，本來就是遮罩後內容
            })
            search_from = m_end  # 天然保證不重疊：下一段只往後找

        except ValueError:
            failed_segments.append({
                "segment_text": seg_text,
                "reason": "在 masked_text 裡找不到逐字相符內容（或跟前一段重疊）",
            })
        except PlaceholderBoundaryError as e:
            failed_segments.append({"segment_text": seg_text, "reason": str(e)})

    return valid_segments, failed_segments


def segment_answer(masked_text: str, position_map) -> dict:
    """
    對外主要介面。

    回傳：
    {
        "segments": [{"orig_start": int, "orig_end": int, "masked_text": str}, ...],
        "segmentation_status": "completed" / "partial_failed" / "failed",
        "error_detail": str or None,
    }
    """
    try:
        segment_texts = _call_gemini_segmentation(masked_text)
    except Exception as e:
        return {
            "segments": [],
            "segmentation_status": "failed",
            "error_detail": f"SEGMENTATION_CALL_FAILED: {str(e)[:180]}",
        }

    valid, failed = _locate_and_validate(masked_text, segment_texts, position_map)

    if not valid:
        status = "failed"
    elif failed:
        status = "partial_failed"
    else:
        status = "completed"

    error_detail = None
    if failed:
        reasons = "; ".join(f"{f['segment_text'][:20]!r}: {f['reason']}" for f in failed)
        error_detail = reasons[:500]

    return {
        "segments": valid,
        "segmentation_status": status,
        "error_detail": error_detail,
    }