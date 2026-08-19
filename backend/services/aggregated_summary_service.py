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

import google.generativeai as genai

from services.privacy_service import mask_pii, PiiMaskingError

genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))


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
        raise AggregatedSummaryError(
            f"group ({main_category}/{sub_category}) 摘要產生失敗：{str(e)[:180]}"
        ) from e
