"""
次要分類（secondary classifications）的唯一讀寫入口。

【AI 回傳的真實結構】
    舊格式（legacy prompt、既有測試、舊版 Gemini 回覆）：
        "secondary_sub_category": "B2 支援協作" 或 null
        ——只有子類別，沒有大類別，一次最多一個。
    新格式（taxonomy prompt / 批次輸出格式，見 taxonomy_service 與
    classify_v2.BATCH_OUTPUT_FORMAT_OVERRIDE）：
        "secondary_categories": [{"main_category": "...", "sub_category": "..."}, ...]
    parse_ai_secondaries() 兩種都接受（也接受字串陣列），不會因為模型
    回舊格式就丟掉次要分類。

【保存】
    Response_Classification_Secondary 子表：每個次要分類一列，大類別 /
    子類別一起存，加上 taxonomy_version_id + taxonomy_category_id（分類
    架構的 identity，不只顯示名稱）。大類別以分類架構為準：AI 給的子類別
    在分類架構裡 -> 用架構裡的大類別（AI 寫錯大類別也會被校正）；不在
    分類架構裡 -> in_taxonomy=False，保留紀錄但不計入彙整。
    舊欄位 secondary_* / final_secondary_* 存第一個次要分類的鏡像值。

【讀取】
    get_secondaries(row, kind)：子表有資料就用子表；舊資料（沒有子表列）
    由舊欄位推導，大類別缺漏時用該列當時的分類架構查回來（舊資料只有
    secondary_sub_category 也能正確彙整）。
    effective_secondaries(row)：modified -> 人工 final；其餘 -> AI 且
    in_taxonomy。Workspace、Report、Export、Chat 追問、Admin 審核都
    透過 effective_view()（見 effective_classification_service）讀同一份。
"""

from classification_models import (
    REVIEW_STATUS_MODIFIED,
    SECONDARY_KIND_AI,
    SECONDARY_KIND_FINAL,
    Response_Classification_Secondary,
)
from extensions import db

MAX_SECONDARIES = 5
_EMPTY_VALUES = {"", "null", "none", "無", "n/a", "na", "-"}


def _clean(value):
    if value is None:
        return None
    text = str(value).strip()
    return None if text.lower() in _EMPTY_VALUES else text


def parse_ai_secondaries(parsed) -> list:
    """Gemini 回覆 -> [{"main_category", "sub_category"}]（未查表、已去重）。"""
    items = []
    raw = parsed.get("secondary_categories") if isinstance(parsed, dict) else None
    if isinstance(raw, list):
        for entry in raw:
            if isinstance(entry, dict):
                items.append({"main_category": _clean(entry.get("main_category")),
                              "sub_category": _clean(entry.get("sub_category"))})
            elif isinstance(entry, str):
                items.append({"main_category": None, "sub_category": _clean(entry)})
    legacy = parsed.get("secondary_sub_category") if isinstance(parsed, dict) else None
    if isinstance(legacy, list):
        items.extend({"main_category": None, "sub_category": _clean(v)} for v in legacy)
    elif legacy is not None:
        items.append({"main_category": _clean(parsed.get("secondary_main_category")), "sub_category": _clean(legacy)})

    seen, result = set(), []
    for item in items:
        sub = item["sub_category"]
        if not sub or sub in seen:
            continue
        seen.add(sub)
        result.append(item)
    return result


def resolve_secondaries(items, category_lookup, primary_sub_category=None) -> list:
    """查分類架構：補上大類別、methodology、citation、category identity。"""
    from services.classification_persistence import normalize_main_category

    resolved = []
    for item in items or []:
        sub = item.get("sub_category")
        if not sub or sub == primary_sub_category:
            continue
        info = category_lookup(sub) if category_lookup else None
        if info:
            resolved.append({
                "main_category": info.get("main_category") or item.get("main_category"),
                "sub_category": sub,
                "methodology": info.get("methodology"),
                "citation": info.get("citation"),
                "taxonomy_category_id": info.get("category_id"),
                "in_taxonomy": True,
            })
        else:
            resolved.append({
                "main_category": normalize_main_category(item.get("main_category")) or None,
                "sub_category": sub,
                "methodology": None,
                "citation": None,
                "taxonomy_category_id": None,
                "in_taxonomy": False,
            })
        if len(resolved) >= MAX_SECONDARIES:
            break
    return resolved


def legacy_fields(resolved) -> dict:
    """舊欄位鏡像：第一個「在分類架構裡」的次要分類（跟以前一樣，查不到
    就不填）。"""
    first = next((s for s in resolved or [] if s.get("in_taxonomy")), None)
    return {
        "secondary_main_category": first["main_category"] if first else None,
        "secondary_sub_category": first["sub_category"] if first else None,
        "secondary_methodology": first["methodology"] if first else None,
        "secondary_citation": first["citation"] if first else None,
    }


# ═══════════════════════════════════════════════════════════════
# 寫入
# ═══════════════════════════════════════════════════════════════

def attach_ai_secondaries(row, resolved, taxonomy_version_id):
    """新建的分類列：寫入 AI 次要分類子表 + 舊欄位鏡像。"""
    for position, item in enumerate(resolved or []):
        row.secondaries.append(Response_Classification_Secondary(
            kind=SECONDARY_KIND_AI, position=position,
            main_category=item.get("main_category"), sub_category=item["sub_category"],
            taxonomy_version_id=taxonomy_version_id, taxonomy_category_id=item.get("taxonomy_category_id"),
            methodology=item.get("methodology"), citation=item.get("citation"),
            in_taxonomy=bool(item.get("in_taxonomy")),
        ))
    mirror = legacy_fields(resolved)
    row.secondary_main_category = mirror["secondary_main_category"]
    row.secondary_sub_category = mirror["secondary_sub_category"]
    row.secondary_methodology = mirror["secondary_methodology"]
    row.secondary_citation = mirror["secondary_citation"]


def set_final_secondaries(row, items, admin_id=None):
    """人工最終次要分類（modified）：取代這筆列既有的 final 子表列，並寫入
    final_secondary_* 鏡像。items: [{"main_category", "sub_category",
    "methodology"?, "citation"?, "taxonomy_category_id"?}]（呼叫端已驗證）。"""
    for child in [c for c in row.secondaries if c.kind == SECONDARY_KIND_FINAL]:
        row.secondaries.remove(child)
    db.session.flush()
    seen = set()
    position = 0
    for item in items or []:
        sub = item.get("sub_category")
        if not sub or sub in seen or sub == row.final_sub_category:
            continue
        seen.add(sub)
        row.secondaries.append(Response_Classification_Secondary(
            kind=SECONDARY_KIND_FINAL, position=position,
            main_category=item.get("main_category"), sub_category=sub,
            taxonomy_version_id=row.taxonomy_version_id, taxonomy_category_id=item.get("taxonomy_category_id"),
            methodology=item.get("methodology"), citation=item.get("citation"),
            in_taxonomy=True, created_by_admin_id=admin_id,
        ))
        position += 1
    finals = [c for c in row.secondaries if c.kind == SECONDARY_KIND_FINAL]
    row.final_secondary_main_category = finals[0].main_category if finals else None
    row.final_secondary_sub_category = finals[0].sub_category if finals else None


# ═══════════════════════════════════════════════════════════════
# 讀取
# ═══════════════════════════════════════════════════════════════

def _lookup_for(row):
    """該列當時使用的分類架構查表（legacy 列查 legacy 表），回傳含 main_category。"""
    from services.effective_classification_service import _methodology_lookup_for

    try:
        return _methodology_lookup_for(row)
    except Exception:  # 測試替身 / 缺資料：查不到就是查不到
        return lambda _sub: None


def get_secondaries(row, kind=SECONDARY_KIND_AI) -> list:
    children = getattr(row, "secondaries", None)
    if children:
        own = sorted((c for c in children if c.kind == kind), key=lambda c: c.position)
        if own:
            return [c.to_dict() for c in own]

    # 舊資料（沒有這一種的子表列）：由舊欄位推導。新資料的舊欄位是子表的
    # 鏡像，沒有次要分類時一定是 NULL，所以這裡不會重複產生。
    return [
        dict(item, taxonomy_version_id=getattr(row, "taxonomy_version_id", None), position=0)
        for item in _legacy_items(row, kind)
    ]


def effective_secondaries(row, primary_sub_category=None) -> list:
    """計入彙整的次要分類：modified 用人工 final，其他用 AI 且在分類架構裡的。"""
    if getattr(row, "review_status", None) == REVIEW_STATUS_MODIFIED:
        items = get_secondaries(row, SECONDARY_KIND_FINAL)
    else:
        items = [s for s in get_secondaries(row, SECONDARY_KIND_AI) if s["in_taxonomy"]]
    seen, result = set(), []
    for item in items:
        sub = item["sub_category"]
        if not sub or sub == primary_sub_category or sub in seen or not item.get("main_category"):
            continue
        seen.add(sub)
        result.append(item)
    return result


# ═══════════════════════════════════════════════════════════════
# 舊資料回填（runtime migration；冪等）
# ═══════════════════════════════════════════════════════════════

def backfill_legacy_secondaries(batch_size=500, logger=None) -> dict:
    """把舊欄位（secondary_sub_category / final_secondary_sub_category）
    轉成子表列，只處理「還沒有對應 kind 子表列」的分類，所以重複執行不會
    重複寫入；(classification_id, kind, position) 唯一索引擋併發重複。

    不改動、不刪除任何既有欄位的值；只在 secondary_main_category 原本是
    NULL 且能從分類架構查到時補上（修正舊資料缺大類別、彙整被略過的問題）。
    """
    from sqlalchemy import and_, exists
    from sqlalchemy.exc import IntegrityError

    from classification_models import Response_Classification

    stats = {"ai": 0, "final": 0, "main_filled": 0, "conflicts": 0}
    for kind, column in ((SECONDARY_KIND_AI, Response_Classification.secondary_sub_category),
                         (SECONDARY_KIND_FINAL, Response_Classification.final_secondary_sub_category)):
        has_child = exists().where(and_(
            Response_Classification_Secondary.classification_id == Response_Classification.classification_id,
            Response_Classification_Secondary.kind == kind,
        ))
        last_id = 0
        while True:
            rows = (
                Response_Classification.query
                .filter(column.isnot(None), column != "", ~has_child,
                        Response_Classification.classification_id > last_id)
                .order_by(Response_Classification.classification_id.asc())
                .limit(batch_size).all()
            )
            if not rows:
                break
            last_id = rows[-1].classification_id
            for row in rows:
                legacy = _legacy_item(row, kind)
                if legacy is None:
                    continue
                if kind == SECONDARY_KIND_AI and not row.secondary_main_category and legacy["main_category"]:
                    row.secondary_main_category = legacy["main_category"]
                    stats["main_filled"] += 1
                db.session.add(Response_Classification_Secondary(
                    classification_id=row.classification_id, kind=kind, position=0,
                    main_category=legacy["main_category"], sub_category=legacy["sub_category"],
                    taxonomy_version_id=row.taxonomy_version_id, taxonomy_category_id=legacy["taxonomy_category_id"],
                    methodology=legacy["methodology"], citation=legacy["citation"],
                    in_taxonomy=legacy["in_taxonomy"],
                ))
                stats[kind] += 1
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()  # 另一個 process 同時在回填：交給它
                stats["conflicts"] += 1
    if logger:
        logger.info("[SECONDARY_BACKFILL] %s", stats)
    return stats


def _legacy_item(row, kind):
    items = _legacy_items(row, kind)
    return items[0] if items else None


def _legacy_items(row, kind):
    """舊欄位 -> 次要分類（最多一個）。可以吃 ORM 列，也可以吃測試替身。"""
    if kind == SECONDARY_KIND_FINAL:
        sub = getattr(row, "final_secondary_sub_category", None)
        main = getattr(row, "final_secondary_main_category", None)
    else:
        sub = getattr(row, "secondary_sub_category", None)
        main = getattr(row, "secondary_main_category", None)
    if not sub:
        return []
    info = _lookup_for(row)(sub) or {}
    methodology = getattr(row, "secondary_methodology", None)
    citation = getattr(row, "secondary_citation", None)
    return [{
        "main_category": main or info.get("main_category"),
        "sub_category": sub,
        "taxonomy_category_id": info.get("category_id"),
        "methodology": info.get("methodology") if kind == SECONDARY_KIND_FINAL else (methodology or info.get("methodology")),
        "citation": info.get("citation") if kind == SECONDARY_KIND_FINAL else (citation or info.get("citation")),
        "in_taxonomy": kind == SECONDARY_KIND_FINAL or bool(info) or bool(methodology),
    }]
