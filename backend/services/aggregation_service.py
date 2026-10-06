"""

Primary + Secondary Aggregation（對應需求文件第十二～十五節）。

只負責「組出分組後的資料結構」，不寫 DB、不呼叫 Gemini、不產生
aggregated_summary（那是 Phase 5 services/aggregated_summary_service.py
搭配 Report 產生流程的職責）。這裡的輸出直接對應 Phase 2 已經建好的
Report_Aggregation / Report_Aggregation_Item schema 形狀，Phase 5
report_service.py 可以直接拿這個結果寫進那兩張表、再補上
aggregated_summary。

分組規則：
    - 只使用 review_status in (confirmed, modified) 的列（呼叫
      services/source_lookup_service.fetch_classifications_in_scope()
      時已經用 review_statuses 篩過，pending_review/excluded 從一開始
      就不會出現在這裡處理的列表裡）。
    - 每筆有效分類透過 effective_classification_service 取得
      effective 版本（confirmed 用 AI original，modified 用 final_*）。
    - Primary 一定貢獻一個 (main_category, sub_category) 分組；
      每個 effective 次要分類（effective_view()["secondary_categories"]，
      已排除跟 primary 相同、不在分類架構裡的）各自另外貢獻一個分組。
    - 同一個 (main_category, sub_category) 分組內，「同一份原始回答」
      （同一個 response_id 或同一個 uploaded_answer_id）只算一次
      response_count，但每個 segment 各自的 matched_segment_text /
      effective_reasoning 都個別保留成一筆 item，segment_count 是
      item 數量。
"""

from services.source_lookup_service import fetch_classifications_in_scope, response_dedup_key
from services.effective_classification_service import (
    NON_COUNTABLE_STATUSES,
    REPORT_ELIGIBLE_REVIEW_STATUSES,
    get_effective_classification,
)


def _segment_text(classification):
    return classification.answer_text[classification.segment_start:classification.segment_end]


def _make_item(classification, reasoning):
    return {
        "classification_id": classification.classification_id,
        "original_answer_text": classification.answer_text,
        "matched_segment_text": _segment_text(classification),
        "effective_reasoning": reasoning,
        "response_id": classification.response_id,
        "upload_batch_id": classification.upload_batch_id,
        "uploaded_answer_id": classification.uploaded_answer_id,
    }


def build_aggregation(source_type, template_id=None, upload_batch_id=None) -> list:
    """
    Returns: [
        {
            "main_category": str, "sub_category": str,
            "methodology": str or None, "citation": str or None,
            "response_count": int, "segment_count": int,
            "items": [{"classification_id", "original_answer_text",
                       "matched_segment_text", "effective_reasoning",
                       "response_id", "upload_batch_id", "uploaded_answer_id"}, ...],
        },
        ...
    ]
    分組沒有固定順序保證（dict 迭代順序），呼叫端如果需要穩定順序
    請自行排序（例如按 main_category, sub_category）。
    """
    rows = fetch_classifications_in_scope(
        source_type=source_type,
        template_id=template_id,
        upload_batch_id=upload_batch_id,
        review_statuses=list(REPORT_ELIGIBLE_REVIEW_STATUSES),
        exclude_statuses=list(NON_COUNTABLE_STATUSES),
    )

    groups = {}  # (main_category, sub_category) -> {"methodology","citation","items":[],"response_keys":set()}

    for row in rows:
        effective = get_effective_classification(row)
        dedup_key = response_dedup_key(row)

        contributions = []
        if effective["main_category"] and effective["sub_category"]:
            contributions.append((
                effective["main_category"], effective["sub_category"],
                effective["reasoning"], effective["methodology"], effective["citation"],
            ))
        # 次要分類可能不只一個，每個各自貢獻一個分組（大類別 + 子類別都
        # 有值才計入；舊資料缺大類別時已經由分類架構查回來）。
        for secondary in effective.get("secondary_categories") or []:
            if secondary.get("main_category") and secondary.get("sub_category"):
                contributions.append((
                    secondary["main_category"], secondary["sub_category"],
                    effective["reasoning"], secondary.get("methodology"), secondary.get("citation"),
                ))

        for index, (main_category, sub_category, reasoning, methodology, citation) in enumerate(contributions):
            key = (main_category, sub_category)
            group = groups.get(key)
            if group is None:
                group = {
                    "main_category": main_category,
                    "sub_category": sub_category,
                    "methodology": methodology,
                    "citation": citation,
                    "items": [],
                    "response_keys": set(),
                }
                groups[key] = group

            group["response_keys"].add(dedup_key)
            item = _make_item(row, reasoning)
            item["is_secondary"] = index > 0  # 第 0 個是 primary，其餘是次要分類的貢獻
            group["items"].append(item)

    result = []
    for group in groups.values():
        result.append({
            "main_category": group["main_category"],
            "sub_category": group["sub_category"],
            "methodology": group["methodology"],
            "citation": group["citation"],
            "response_count": len(group["response_keys"]),
            "segment_count": len(group["items"]),
            "items": group["items"],
        })
    return result
