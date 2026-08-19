"""

get_effective_classification()：Aggregation 唯一該呼叫的「這筆
classification 最終要拿哪個版本的分類結果來用」判斷入口。

不要讓各處各自重複判斷 confirmed 用 AI original、modified 用 final_*
——這裡集中處理一次，Aggregation 相關 service 全部呼叫這個函式，
不自己重寫判斷邏輯。

規則（對應需求文件第十二節）：
    confirmed：使用 AI original classification（main_category /
        sub_category / secondary_* / reasoning / methodology / citation
        等欄位，都是 classify_v2.py 當初寫入、Human Review 完全沒有
        動過的原始值）。
    modified ：使用 final classification（final_main_category /
        final_sub_category / final_secondary_* / final_reasoning）。
        methodology / citation 不是存在 final_* 欄位裡（Phase 2 沒有
        新增 final_methodology/final_citation 這兩個欄位），而是這裡
        當場用 final_sub_category 查
        services/subcategory_methodology.get_methodology() 表取得
        ——因為 methodology/citation 本來就是 sub_category 的確定性
        函式，不需要重複存一份，也避免「查表規則之後改了，final_*
        裡存的舊 methodology 沒跟著更新」這種資料不一致風險。
    pending_review / excluded：沒有 effective classification，呼叫
        這個函式屬於呼叫端邏輯錯誤（Aggregation 的資料來源本來就該
        先篩選成只剩 confirmed/modified，見
        services/source_lookup_service.fetch_classifications_in_scope()
        的 review_statuses 參數），這裡用明確的例外擋下來，不要讓
        呼叫端不小心把 pending/excluded 的 None 分類值也算進統計。
"""

from response_classification import REVIEW_STATUS_CONFIRMED, REVIEW_STATUS_MODIFIED
from services.source_lookup_service import resolve_question_type
from services.subcategory_methodology import get_methodology


class EffectiveClassificationError(ValueError):
    """呼叫端傳進一筆 review_status 不是 confirmed/modified 的
    classification 時使用——這是呼叫端的篩選邏輯有誤，不是資料損毀，
    fail loud 比 fail silent 安全。"""


def get_effective_classification(classification) -> dict:
    """
    Returns:
        {
            "main_category": str, "sub_category": str,
            "secondary_main_category": str or None,
            "secondary_sub_category": str or None,
            "reasoning": str,
            "methodology": str or None, "citation": str or None,
            "secondary_methodology": str or None, "secondary_citation": str or None,
        }
    """
    if classification.review_status == REVIEW_STATUS_CONFIRMED:
        return {
            "main_category": classification.main_category,
            "sub_category": classification.sub_category,
            "secondary_main_category": classification.secondary_main_category,
            "secondary_sub_category": classification.secondary_sub_category,
            "reasoning": classification.reasoning,
            "methodology": classification.methodology,
            "citation": classification.citation,
            "secondary_methodology": classification.secondary_methodology,
            "secondary_citation": classification.secondary_citation,
        }

    if classification.review_status == REVIEW_STATUS_MODIFIED:
        question_type = resolve_question_type(classification)

        methodology = citation = None
        if question_type and classification.final_sub_category:
            info = get_methodology(question_type, classification.final_sub_category)
            if info:
                methodology, citation = info["methodology"], info["citation"]

        secondary_methodology = secondary_citation = None
        if question_type and classification.final_secondary_sub_category:
            secondary_info = get_methodology(question_type, classification.final_secondary_sub_category)
            if secondary_info:
                secondary_methodology = secondary_info["methodology"]
                secondary_citation = secondary_info["citation"]

        return {
            "main_category": classification.final_main_category,
            "sub_category": classification.final_sub_category,
            "secondary_main_category": classification.final_secondary_main_category,
            "secondary_sub_category": classification.final_secondary_sub_category,
            "reasoning": classification.final_reasoning,
            "methodology": methodology,
            "citation": citation,
            "secondary_methodology": secondary_methodology,
            "secondary_citation": secondary_citation,
        }

    raise EffectiveClassificationError(
        f"review_status={classification.review_status!r}（classification_id="
        f"{classification.classification_id}）沒有 effective classification，"
        "只有 confirmed/modified 才有；呼叫端應該先用 "
        "fetch_classifications_in_scope(review_statuses=[...]) 篩選過。"
    )
