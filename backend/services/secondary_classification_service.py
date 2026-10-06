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
    子表是次要分類唯一的保存位置；Response_Classification 舊的單值鏡像
    欄位（secondary_* / final_secondary_*）已於 2026-09 資料庫整理時移除。

【讀取】
    get_secondaries(row, kind)：只讀子表。
    舊資料在舊欄位移除前，由 backfill_legacy_secondaries()（app 啟動時
    執行）一次搬進子表。
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
    """AI 結果 dict 的相容 key：第一個「在分類架構裡」的次要分類（查不到
    就不填）。只用在記憶體裡的分類結果 / API 回應，不寫入資料庫。"""
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
    """新建的分類列：寫入 AI 次要分類子表。"""
    for position, item in enumerate(resolved or []):
        row.secondaries.append(Response_Classification_Secondary(
            kind=SECONDARY_KIND_AI, position=position,
            main_category=item.get("main_category"), sub_category=item["sub_category"],
            taxonomy_version_id=taxonomy_version_id, taxonomy_category_id=item.get("taxonomy_category_id"),
            methodology=item.get("methodology"), citation=item.get("citation"),
            in_taxonomy=bool(item.get("in_taxonomy")),
        ))


def set_final_secondaries(row, items, admin_id=None):
    """人工最終次要分類（modified）：取代這筆列既有的 final 子表列。items: [{"main_category", "sub_category",
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
    children = getattr(row, "secondaries", None) or []
    own = sorted((c for c in children if c.kind == kind), key=lambda c: c.position)
    return [c.to_dict() for c in own]


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
#
# Response_Classification 舊的單值欄位已經從 model 移除，但正式資料庫在
# 執行清理 SQL（backend/db_cleanup/）之前仍然有這些欄位。app 啟動時用
# 原生 SQL 讀舊欄位、把「還沒有子表列」的資料搬進子表；舊欄位不存在
# （已經清掉）時直接略過。

LEGACY_SECONDARY_COLUMNS = (
    "secondary_main_category", "secondary_sub_category",
    "secondary_methodology", "secondary_citation",
    "final_secondary_main_category", "final_secondary_sub_category",
)


def _legacy_columns_present() -> set:
    from sqlalchemy import inspect

    try:
        columns = inspect(db.session.get_bind()).get_columns("Response_Classification")
    except Exception:
        return set()
    names = {c["name"] for c in columns}
    return {c for c in LEGACY_SECONDARY_COLUMNS if c in names}


class _LegacyRow:
    """ORM 列 + 舊欄位值（舊欄位已不在 model 上）。給 _legacy_items 查表用。"""

    def __init__(self, row, legacy):
        self._row = row
        self._legacy = legacy

    def __getattr__(self, name):
        if name in LEGACY_SECONDARY_COLUMNS:
            return self._legacy.get(name)
        return getattr(self._row, name)


def backfill_legacy_secondaries(batch_size=500, logger=None) -> dict:
    """把舊欄位（secondary_sub_category / final_secondary_sub_category）
    轉成子表列，只處理「還沒有對應 kind 子表列」的分類，所以重複執行不會
    重複寫入；(classification_id, kind, position) 唯一索引擋併發重複。
    只讀舊欄位、不改寫舊欄位。舊欄位已移除時回傳 {"skipped": True}。
    """
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    from classification_models import Response_Classification

    present = _legacy_columns_present()
    stats = {"ai": 0, "final": 0, "conflicts": 0}
    if not present:
        stats["skipped"] = True
        if logger:
            logger.info("[SECONDARY_BACKFILL] legacy columns not present, skipped")
        return stats

    select_cols = ", ".join(f"`{c}`" for c in sorted(present))
    for kind, column in ((SECONDARY_KIND_AI, "secondary_sub_category"),
                         (SECONDARY_KIND_FINAL, "final_secondary_sub_category")):
        if column not in present:
            continue
        last_id = 0
        while True:
            rows = db.session.execute(text(
                f"SELECT rc.`classification_id`, {select_cols} FROM `Response_Classification` rc "
                f"WHERE rc.`{column}` IS NOT NULL AND rc.`{column}` <> '' "
                "AND rc.`classification_id` > :last_id "
                "AND NOT EXISTS (SELECT 1 FROM `Response_Classification_Secondary` s "
                "WHERE s.`classification_id` = rc.`classification_id` AND s.`kind` = :kind) "
                "ORDER BY rc.`classification_id` ASC LIMIT :limit"
            ), {"last_id": last_id, "kind": kind, "limit": batch_size}).mappings().all()
            if not rows:
                break
            last_id = rows[-1]["classification_id"]
            for raw in rows:
                row = db.session.get(Response_Classification, raw["classification_id"])
                if row is None:
                    continue
                legacy = _legacy_item(_LegacyRow(row, dict(raw)), kind)
                if legacy is None:
                    continue
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
            db.session.expire_all()
    if logger:
        logger.info("[SECONDARY_BACKFILL] %s", stats)
    return stats


def count_unmigrated_legacy_secondaries() -> int:
    """清理 SQL 執行前的安全檢查：還有幾筆舊欄位資料沒有對應子表列。"""
    from sqlalchemy import text

    present = _legacy_columns_present()
    total = 0
    for kind, column in ((SECONDARY_KIND_AI, "secondary_sub_category"),
                         (SECONDARY_KIND_FINAL, "final_secondary_sub_category")):
        if column not in present:
            continue
        total += db.session.execute(text(
            f"SELECT COUNT(*) FROM `Response_Classification` rc WHERE rc.`{column}` IS NOT NULL "
            f"AND rc.`{column}` <> '' AND NOT EXISTS (SELECT 1 FROM `Response_Classification_Secondary` s "
            "WHERE s.`classification_id` = rc.`classification_id` AND s.`kind` = :kind)"
        ), {"kind": kind}).scalar() or 0
    return total


def _legacy_item(row, kind):
    items = _legacy_items(row, kind)
    return items[0] if items else None


def _legacy_items(row, kind):
    """舊欄位 -> 次要分類（最多一個）。row 需提供舊欄位屬性（_LegacyRow）。"""
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
