"""

Aggregated Summary：Aggregation 階段唯一需要新增的 AI synthesis
（對應需求文件第十六節）。

輸入是 services/aggregation_service.build_aggregation() 算出的單一
group（一個 (main_category, sub_category) 底下所有 confirmed/modified
的 matched segment + effective reasoning），輸出一段 category 層級的
摘要文字。

【隔離範圍，避免跟其他 AI synthesis 混淆】
    - 不重新判斷分類（那是 classify_v2.py / review_ai_service.py 的
      職責）。
    - 不重新選 methodology / citation（那是查表結果，見
      effective_classification_service.py）。
    - 只做「這個 group 底下的內容，摘要成一段話」這一件事。
    - individual classification.summary（AI original 對單一 segment
      的摘要）完全不會被這裡覆寫或引用改寫，這裡只新增
      Report_Aggregation.aggregated_summary 這個獨立欄位的值。

【Privacy】送進 Gemini 前，每一段 matched_segment_text 都先用
services/privacy_service.mask_pii() 遮罩，沿用既有 privacy_service
的安全原則，不繞過既有 PII masking flow（呼應需求文件第二十四節、
以及本次 Phase 5 的要求 7）。
"""

import json
import os
import re
import time

from services import gemini_client as genai

from services.privacy_service import mask_pii, PiiMaskingError

genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))


# 免費層 429 錯誤的訊息裡，Google 自己會附建議的等待秒數，例如：
#   "Please retry in 34.07s"
#   "retryDelay": "15s"
# 這個秒數才是限流視窗真正重置所需的時間，遠比隨便寫死的 2/4 秒準確。
_RETRY_DELAY_PATTERNS = (
    re.compile(r"[Rr]etry in ([\d.]+)s"),
    re.compile(r'"retryDelay"\s*:\s*"([\d.]+)s"'),
)


def _extract_retry_delay_seconds(exc: Exception) -> float | None:
    """從例外訊息裡解析 Gemini 建議的等待秒數；解析不到就回傳 None，
    交給呼叫端用預設值 fallback（例如非 429 的其他錯誤）。"""
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


AGGREGATED_SUMMARY_SYSTEM_INSTRUCTION = """你是問卷開放式回覆的量化前彙整助手，負責把「已經人工確認過分類」
的一組回覆片段，摘要成一段給報告閱讀者看的重點描述。

【絕對規則】
1. 只能根據下面提供的片段內容摘要，不可以加入原文沒有表達的意見、
   情緒、動機或因果推論。
2. 不可以改寫、刪除、或引用原始資料以外的內容；不是在幫這些片段
   重新分類，分類已經確定，你只需要摘要「這些片段共同在說什麼」。
3. 摘要限一段話，簡潔扼要（建議 1-3 句），使用繁體中文。
4. 不要提到「片段」「分類」「AI」等後設詞彙，直接寫出摘要內容本身，
   像是給報告讀者看的重點描述。

只回傳以下 JSON 格式，不要加任何其他文字：

{"summary": "摘要文字"}"""


class AggregatedSummaryError(RuntimeError):
    """呼叫失敗、解析失敗、或 PII 遮罩失敗時使用。呼叫端
    （services/report_service.py）應該把這個例外視為整個 Report
    generation 失敗，不產生半份看起來成功的 Report。"""


def _parse_json(raw_text: str) -> dict:
    cleaned = re.sub(r"```json|```", "", raw_text).strip()
    return json.loads(cleaned)


def build_aggregated_summary(main_category: str, sub_category: str, items: list) -> str:
    """
    Args:
        items: services/aggregation_service.build_aggregation() 回傳的
            單一 group 裡的 "items" 清單，每個元素至少要有
            "matched_segment_text"。

    Returns:
        摘要文字（str）。

    Raises:
        AggregatedSummaryError: PII 遮罩失敗、Gemini 呼叫失敗、或回傳
            格式錯誤。呼叫端不應該吞掉這個例外繼續產生報告。
    """
    if not items:
        raise AggregatedSummaryError(f"group ({main_category}/{sub_category}) 沒有任何 item，無法產生摘要")

    masked_segments = []
    for item in items:
        try:
            masked_segments.append(mask_pii(item["matched_segment_text"]))
        except PiiMaskingError as e:
            raise AggregatedSummaryError(
                f"group ({main_category}/{sub_category}) PII 遮罩失敗：{str(e)[:180]}"
            ) from e

    segments_block = "\n".join(f"- {s}" for s in masked_segments)
    user_content = (
        f"類別：{main_category} / {sub_category}\n\n"
        f"這個類別底下的回覆片段：\n{segments_block}"
    )

    # 【重試機制】平常完全不等待，一次就過；只有真的撞到免費額度的
    # 速率限制（429 / ResourceExhausted）時，才照 Gemini 錯誤訊息裡
    # 自己附的建議秒數（retryDelay，免費層常見是 15~60 秒左右）等待，
    # 而不是用猜的 2/4 秒——限流視窗還沒重置就重打，等於白白浪費重試
    # 次數。非限流的其他錯誤（暫時性網路問題等）才用短間隔重試。
    last_error = None
    for attempt in range(3):
        try:
            model = genai.GenerativeModel(
                model_name="gemini-3.1-flash-lite",
                system_instruction=AGGREGATED_SUMMARY_SYSTEM_INSTRUCTION,
            )
            response = model.generate_content(
                user_content,
                generation_config={"temperature": 0},
            )
            parsed = _parse_json(response.text)
            summary = parsed.get("summary")
            if not summary or not isinstance(summary, str):
                raise AggregatedSummaryError(
                    f"group ({main_category}/{sub_category}) Gemini 回傳格式缺少有效的 summary 欄位"
                )
            return summary
        except AggregatedSummaryError:
            raise
        except Exception as e:
            last_error = e
            if attempt < 2:
                if _is_rate_limit_error(e):
                    delay = _extract_retry_delay_seconds(e) or 20.0
                    time.sleep(delay + 1.0)  # 多留 1 秒緩衝，避免卡在重置臨界點
                else:
                    time.sleep(2 * (attempt + 1))
                continue
            raise AggregatedSummaryError(
                f"group ({main_category}/{sub_category}) 摘要產生失敗（重試 3 次後放棄）："
                f"{type(last_error).__name__}: {str(last_error)[:180]}"
            ) from last_error


AGGREGATED_PAIR_SYSTEM_INSTRUCTION = """你是問卷開放式回覆的量化前彙整助手，負責把「已經人工確認過分類」
的一組回覆片段，摘要成一段給報告閱讀者看的重點描述。這次要同時處理
兩組獨立的片段清單（reasoning 跟 summary），彼此不要互相混用或參照。

【絕對規則】
1. 只能根據各自提供的片段內容摘要，不可以加入原文沒有表達的意見、
   情緒、動機或因果推論。
2. 不可以改寫、刪除、或引用原始資料以外的內容；不是在重新分類，
   分類已經確定，你只需要摘要「這些片段共同在說什麼」。
3. 每組摘要限一段話，簡潔扼要（建議 1-3 句），使用繁體中文。
4. 不要提到「片段」「分類」「AI」等後設詞彙，直接寫出摘要內容本身。
5. 如果某一組片段清單是空的，該組回傳空字串 ""。

只回傳以下 JSON 格式，不要加任何其他文字：

{"reasoning_summary": "摘要文字或空字串", "summary_summary": "摘要文字或空字串"}"""


def build_aggregated_summary_pair(
    main_category: str,
    sub_category: str,
    reasoning_items: list,
    summary_items: list,
) -> tuple[str, str]:
    """
    跟 build_aggregated_summary() 做同一件事，但一次處理 reasoning 跟
    summary 兩組片段，只打 1 次 Gemini（原本呼叫端各別呼叫
    build_aggregated_summary() 兩次，一個 group 就要 2 次呼叫，這裡
    合併成 1 次，直接把這個 call site 的呼叫量減半，降低撞到免費層
    RPM 限制的機率）。

    兩組片段清單其中一個可以是空的（傳空 list），該組回傳空字串，
    不會為了空清單額外打 Gemini。兩組都空時直接回傳 ("", "")，
    不呼叫 Gemini。

    Returns:
        (aggregated_reasoning, aggregated_summary) 兩個字串的 tuple。

    Raises:
        AggregatedSummaryError: 同 build_aggregated_summary()。
    """
    if not reasoning_items and not summary_items:
        return "", ""

    def _mask_block(items: list) -> str:
        masked = []
        for item in items:
            try:
                masked.append(mask_pii(item["matched_segment_text"]))
            except PiiMaskingError as e:
                raise AggregatedSummaryError(
                    f"group ({main_category}/{sub_category}) PII 遮罩失敗：{str(e)[:180]}"
                ) from e
        return "\n".join(f"- {s}" for s in masked) if masked else "（此組沒有片段）"

    user_content = (
        f"類別：{main_category} / {sub_category}\n\n"
        f"【reasoning 片段】\n{_mask_block(reasoning_items)}\n\n"
        f"【summary 片段】\n{_mask_block(summary_items)}"
    )

    last_error = None
    for attempt in range(3):
        try:
            model = genai.GenerativeModel(
                model_name="gemini-3.1-flash-lite",
                system_instruction=AGGREGATED_PAIR_SYSTEM_INSTRUCTION,
            )
            response = model.generate_content(
                user_content,
                generation_config={"temperature": 0},
            )
            parsed = _parse_json(response.text)
            reasoning_summary = parsed.get("reasoning_summary")
            summary_summary = parsed.get("summary_summary")
            if not isinstance(reasoning_summary, str) or not isinstance(summary_summary, str):
                raise AggregatedSummaryError(
                    f"group ({main_category}/{sub_category}) Gemini 回傳格式缺少有效的欄位"
                )
            # 沒有片段的那一組本來就預期是空字串，不是錯誤
            if reasoning_items and not reasoning_summary:
                raise AggregatedSummaryError(
                    f"group ({main_category}/{sub_category}) reasoning_summary 為空"
                )
            if summary_items and not summary_summary:
                raise AggregatedSummaryError(
                    f"group ({main_category}/{sub_category}) summary_summary 為空"
                )
            return reasoning_summary, summary_summary
        except AggregatedSummaryError:
            raise
        except Exception as e:
            last_error = e
            if attempt < 2:
                if _is_rate_limit_error(e):
                    delay = _extract_retry_delay_seconds(e) or 20.0
                    time.sleep(delay + 1.0)
                else:
                    time.sleep(2 * (attempt + 1))
                continue
            raise AggregatedSummaryError(
                f"group ({main_category}/{sub_category}) 摘要產生失敗（重試 3 次後放棄）："
                f"{type(last_error).__name__}: {str(last_error)[:180]}"
            ) from last_error
