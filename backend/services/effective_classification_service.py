"""

Effective classification：「這筆 Response_Classification 在 Workspace /
Report / Export / Chat 追問 / Admin 清單裡，最終要拿哪一個版本的分類
結果來用」的**唯一**判斷入口。

不要讓各 route / service 各自重複判斷 confirmed 用 AI original、
modified 用 final_*、excluded 要排除、failed 不算成功——這裡集中處理
一次，所有讀取端都呼叫這裡，不自己重寫判斷邏輯。

【規則】（同時兼容 legacy（taxonomy_version_id IS NULL）與動態 taxonomy
classification）

    status（AI 處理結果）：
        failed      ：AI 沒有成功分類，永遠不是有效分類結果，不進任何
                      統計／彙整／報表／匯出（只會出現在 Admin 的
                      failed 清單等待 retry）。
        superseded  ：重新處理（retry / reclassify）後被新 attempt 取代的
                      舊列，保留作為 attempt history，同樣永遠不計入。
        其他（completed / methodology_not_found / pending ...）：可以被計入，
            再依 review_status 決定用哪個版本。

    review_status（人工審核結果）：
        excluded       ：人工決定不納入分析——不出現在任何統計／彙整／
                         報表／匯出。
        modified       ：使用人工確認後的 final_* 欄位（final_main_category /
                         final_sub_category / final_reasoning），次要分類用
                         Response_Classification_Secondary（kind="final"）。methodology / citation 不另外
                         存 final_* 版本，而是依 final_sub_category 重新查表：
                         有 taxonomy_version_id 時查該版 Taxonomy_Category，
                         legacy 列（taxonomy_version_id IS NULL）查產生當時
                         使用的 legacy SUBCATEGORY_METHODOLOGY 表。
        confirmed      ：人工確認 AI 原始結果——使用 AI original 欄位。
        pending_review ：尚未人工確認（含「有進行中的 review session」，
                         也就是 in_review）。
                           - Workspace 即時彙整 / 匯出：依產品定案沿用 AI
                             original 並計入（is_human_reviewed=False，
                             不會被當成人工確認結果）。
                           - Report 正式快照：不計入（只收 confirmed /
                             modified，見 REPORT_ELIGIBLE_REVIEW_STATUSES），
                             Readiness 另外回報 pending 數量。

    Schema 對照（需求文件使用的欄位名 → 實際欄位）：
        final_primary_category     → final_main_category / final_sub_category
        final_secondary_categories → Response_Classification_Secondary（kind="final"）
        final_reasoning            → final_reasoning
        final_summary / final_sentiment / final_keywords /
        final_recommended_actions  → 目前 schema 不存在（Human Review 只能改
                                     分類與理由），summary 一律沿用 AI 原始值。
"""

from classification_models import (
    REVIEW_STATUS_CONFIRMED,
    REVIEW_STATUS_EXCLUDED,
    REVIEW_STATUS_MODIFIED,
    REVIEW_STATUS_PENDING,
)
from extensions import db

# ── AI 處理狀態（Response_Classification.status）──────────────────────
CLASSIFICATION_STATUS_FAILED = "failed"
CLASSIFICATION_STATUS_SUPERSEDED = "superseded"
# 這些 status 永遠不是「成功的分類結果」，任何統計都不能計入。
NON_COUNTABLE_STATUSES = frozenset({CLASSIFICATION_STATUS_FAILED, CLASSIFICATION_STATUS_SUPERSEDED})

# 人工（或系統自動）確認過的審核狀態。is_human_reviewed 另外排除自動通過。
REVIEWED_STATUSES = (REVIEW_STATUS_CONFIRMED, REVIEW_STATUS_MODIFIED)

# Report 正式快照收哪些結果：待審的也算。報告不等人工審核——審核是
# 「發現錯了可以改」，不是「沒審就不能用」。只排除 excluded（人工決定不納入）
# 與 failed / superseded（見 NON_COUNTABLE_STATUSES）。
REPORT_ELIGIBLE_REVIEW_STATUSES = (REVIEW_STATUS_PENDING, REVIEW_STATUS_CONFIRMED, REVIEW_STATUS_MODIFIED)


class EffectiveClassificationError(ValueError):
    """呼叫端傳進一筆沒有「人工確認後 effective classification」的列給
    get_effective_classification()（例如 pending/excluded/failed）——這是
    呼叫端的篩選邏輯有誤，不是資料損毀，fail loud 比 fail silent 安全。"""


# ═══════════════════════════════════════════════════════════════
# 判斷函式（純 Python，不查 DB；可以吃 ORM 物件，也可以吃
# SimpleNamespace 之類的測試替身）
# ═══════════════════════════════════════════════════════════════

def is_failed(row) -> bool:
    return getattr(row, "status", None) == CLASSIFICATION_STATUS_FAILED


def is_countable(row) -> bool:
    """這筆列可不可以出現在 Workspace 即時彙整 / 匯出 / Chat 追問 context。"""
    if getattr(row, "review_status", None) == REVIEW_STATUS_EXCLUDED:
        return False
    if getattr(row, "status", None) in NON_COUNTABLE_STATUSES:
        return False
    return True


def is_report_eligible(row) -> bool:
    return is_countable(row) and getattr(row, "review_status", None) in REPORT_ELIGIBLE_REVIEW_STATUSES


def _uses_final(row) -> bool:
    return getattr(row, "review_status", None) == REVIEW_STATUS_MODIFIED


def effective_view(row, include_methodology: bool = False) -> dict | None:
    """
    回傳這筆列的 effective 分類 dict；不可計入（excluded / failed /
    superseded）時回傳 None，呼叫端必須整筆跳過。

    Returns:
        {
            "main_category", "sub_category",
            "secondary_main_category", "secondary_sub_category",
            "reasoning", "summary",
            "review_status", "is_human_reviewed", "auto_confirmed",
            # include_methodology=True 時才有（需要查 DB）：
            "methodology", "citation", "secondary_methodology", "secondary_citation",
        }
    """
    if not is_countable(row):
        return None

    if _uses_final(row):
        view = {
            "main_category": getattr(row, "final_main_category", None),
            "sub_category": getattr(row, "final_sub_category", None),
            "reasoning": getattr(row, "final_reasoning", None),
        }
    else:
        view = {
            "main_category": getattr(row, "main_category", None),
            "sub_category": getattr(row, "sub_category", None),
            "reasoning": getattr(row, "reasoning", None),
        }

    # 次要分類：可能不只一個（見 services/secondary_classification_service.py）；
    # 回傳 dict 的 secondary_main_category / secondary_sub_category 是第一個
    # 次要分類，給舊的讀取端用（不是資料庫欄位）。
    from services.secondary_classification_service import effective_secondaries

    secondaries = effective_secondaries(row, view["sub_category"])
    view["secondary_categories"] = secondaries
    view["secondary_main_category"] = secondaries[0]["main_category"] if secondaries else None
    view["secondary_sub_category"] = secondaries[0]["sub_category"] if secondaries else None

    review_status = getattr(row, "review_status", None) or REVIEW_STATUS_PENDING
    view["summary"] = getattr(row, "summary", None)
    view["review_status"] = review_status
    auto_confirmed = bool(getattr(row, "auto_confirmed", False))
    view["auto_confirmed"] = auto_confirmed
    view["is_human_reviewed"] = review_status in REVIEWED_STATUSES and not auto_confirmed

    if include_methodology:
        view.update(_methodology_fields(row, view))
    return view


def _methodology_fields(row, view) -> dict:
    lookup = None
    if _uses_final(row):
        lookup = _methodology_lookup_for(row)
        primary = lookup(view["sub_category"]) if view["sub_category"] else None
        fields = {
            "methodology": primary["methodology"] if primary else None,
            "citation": primary["citation"] if primary else None,
        }
    else:
        fields = {"methodology": getattr(row, "methodology", None), "citation": getattr(row, "citation", None)}

    # 每個次要分類補齊 methodology / citation（子表有存就用，沒有就查該列當時的分類架構）
    for item in view["secondary_categories"]:
        if item.get("methodology") is None and item.get("sub_category"):
            lookup = lookup or _methodology_lookup_for(row)
            info = lookup(item["sub_category"]) or {}
            item["methodology"] = info.get("methodology")
            item["citation"] = info.get("citation")
    first = view["secondary_categories"][0] if view["secondary_categories"] else {}
    fields["secondary_methodology"] = first.get("methodology")
    fields["secondary_citation"] = first.get("citation")
    return fields


def _methodology_lookup_for(row):
    """依這筆列「產生當時使用的 taxonomy」回傳 sub_category -> {methodology,
    citation} 的查表函式。

    - 動態 taxonomy 列：查 taxonomy_version_id 那一版的 Taxonomy_Category
      （不是目前 published 版，避免 taxonomy 改版後舊結果被誤查）。
    - legacy 列（taxonomy_version_id IS NULL）：查 legacy
      SUBCATEGORY_METHODOLOGY 表——這只是補齊「當初就是用這份表分類」
      的 metadata，不是 classification fallback，不會產生任何新分類。
    """
    from models import Taxonomy_Version
    from services.taxonomy_service import methodology_lookup_for_taxonomy_version

    version_id = getattr(row, "taxonomy_version_id", None)
    if version_id is not None:
        version = db.session.get(Taxonomy_Version, version_id)
        lookup = methodology_lookup_for_taxonomy_version(version) if version is not None else None
        return lookup or (lambda _sub: None)

    from services.subcategory_methodology import SUBCATEGORY_METHODOLOGY
    from services.source_lookup_service import resolve_question_type

    question_type = None
    try:
        question_type = resolve_question_type(row)
    except Exception:  # SimpleNamespace / 缺 FK 的資料：退回跨表搜尋
        question_type = None

    def _pick(info):
        return {"main_category": info.get("main_category"), "methodology": info["methodology"],
                "citation": info["citation"]}

    def _lookup(sub_category):
        if question_type in SUBCATEGORY_METHODOLOGY:
            info = SUBCATEGORY_METHODOLOGY[question_type].get(sub_category)
            return _pick(info) if info else None
        matches = [t[sub_category] for t in SUBCATEGORY_METHODOLOGY.values() if sub_category in t]
        if len(matches) == 1:
            return _pick(matches[0])
        return None

    return _lookup


def get_effective_classification(classification) -> dict:
    """Report 正式快照專用的嚴格版本：只接受 pending_review / confirmed /
    modified 且 status 可計入的列，其他一律 EffectiveClassificationError。

    Returns:
        {
            "main_category", "sub_category",
            "secondary_main_category", "secondary_sub_category",
            "reasoning", "methodology", "citation",
            "secondary_methodology", "secondary_citation",
        }
    """
    if not is_report_eligible(classification):
        raise EffectiveClassificationError(
            f"review_status={getattr(classification, 'review_status', None)!r} / "
            f"status={getattr(classification, 'status', None)!r}（classification_id="
            f"{getattr(classification, 'classification_id', None)}）沒有 effective "
            "classification，只有 pending_review/confirmed/modified 且非 failed 才有；呼叫端應該先用 "
            "fetch_classifications_in_scope(review_statuses=[...]) 篩選過。"
        )
    view = effective_view(classification, include_methodology=True)
    return {
        key: view[key]
        for key in (
            "main_category", "sub_category",
            "secondary_main_category", "secondary_sub_category",
            "reasoning", "methodology", "citation",
            "secondary_methodology", "secondary_citation", "secondary_categories",
        )
    }


# ═══════════════════════════════════════════════════════════════
# SQL 條件（DB 查詢端用，跟上面的 Python 判斷是同一套規則）
# ═══════════════════════════════════════════════════════════════

def countable_clause(model=None):
    """SQLAlchemy 條件：等同 is_countable()。"""
    if model is None:
        from classification_models import Response_Classification as model
    return db.and_(
        model.review_status != REVIEW_STATUS_EXCLUDED,
        db.or_(model.status.is_(None), ~model.status.in_(tuple(NON_COUNTABLE_STATUSES))),
    )


def display_fingerprint_entry(row, mode: str = "effective"):
    """用來判斷「畫面上的彙整結果是否需要重新產生」的單筆指紋。

    mode="effective"：目前 effective 規則下，這筆列在畫面上的呈現。
    mode="legacy_original"：本次修正之前 _build_aggregated_groups() 的
        行為（無條件使用 AI 原始欄位、不排除任何列），用來判斷舊訊息
        是否真的受 Human Review 影響。
    """
    classification_id = getattr(row, "classification_id", None)
    if mode == "legacy_original":
        return (classification_id, getattr(row, "main_category", None), getattr(row, "sub_category", None))
    view = effective_view(row)
    if view is None:
        return (classification_id, None, None)
    secondaries = tuple(
        (item.get("main_category"), item.get("sub_category")) for item in view.get("secondary_categories") or []
    )
    if secondaries:
        # 次要分類也會出現在畫面分組裡：改變時 Workspace 快照要重建。沒有次要
        # 分類的列維持原本的 3-tuple，既有 Chat_History 的 review_revision 不受影響。
        return (classification_id, view["main_category"], view["sub_category"], secondaries)
    return (classification_id, view["main_category"], view["sub_category"])
