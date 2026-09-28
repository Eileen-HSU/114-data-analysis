"""
開放式分類的「新類別候選」管理（見 services/open_classification.py）。

AI 在分類時提出清單外的新類別（Response_Classification.status=new_category），
這裡把它們依（主題, 大類別, 子類別）彙整給管理員決定：

    採用（adopt）：把新類別加進該主題可編輯的分類架構草稿（沒有草稿就從
        目前已發布版本複製一份），管理員在「分類架構」頁檢查後發布；之後
        類似的回答就會直接歸到這個類別。已經歸到這個新類別的回答維持
        待處理，照一般流程確認即可。
    合併（merge）：這個新類別其實就是某個既有類別——把這組所有待處理的
        回答以 confirm-manual 改成指定的既有類別（逐筆寫 audit、報告過期）。
"""

from extensions import db
from models import Response_Classification, Taxonomy_Version
from services import audit_service
from services.open_classification import NEW_CATEGORY_STATUS

ACTION_ADOPT_NEW_CATEGORY = "adopt_new_category"
ACTION_MERGE_NEW_CATEGORY = "merge_new_category"


class NewCategoryError(Exception):
    def __init__(self, code, message, http_status=400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def _candidate_rows(topic_key=None):
    query = (
        db.session.query(Response_Classification, Taxonomy_Version.topic_key)
        .outerjoin(Taxonomy_Version, Response_Classification.taxonomy_version_id == Taxonomy_Version.version_id)
        .filter(
            Response_Classification.status == NEW_CATEGORY_STATUS,
            Response_Classification.review_status == "pending_review",
        )
    )
    if topic_key:
        query = query.filter(Taxonomy_Version.topic_key == topic_key)
    return query.order_by(Response_Classification.classification_id.asc()).all()


def list_candidates(topic_key=None):
    from models import Topic

    groups = {}
    for row, row_topic in _candidate_rows(topic_key):
        key = (row_topic, row.main_category, row.sub_category)
        group = groups.setdefault(key, {
            "topic_key": row_topic,
            "main_category": row.main_category,
            "sub_category": row.sub_category,
            "count": 0,
            "classification_ids": [],
            "examples": [],
            "reasons": [],
        })
        group["count"] += 1
        group["classification_ids"].append(row.classification_id)
        if len(group["examples"]) < 3:
            group["examples"].append(row.answer_text[row.segment_start:row.segment_end])
        if row.reasoning and len(group["reasons"]) < 3:
            group["reasons"].append(row.reasoning)

    titles = {t.topic_key: t.title for t in Topic.query.filter(Topic.topic_key.in_({k[0] for k in groups if k[0]})).all()} if groups else {}
    items = sorted(groups.values(), key=lambda g: (-g["count"], g["topic_key"] or "", g["sub_category"] or ""))
    for item in items:
        item["topic_title"] = titles.get(item["topic_key"], item["topic_key"])
        item["classification_ids"] = item["classification_ids"][:500]
    return {"items": items, "total": len(items)}


def _editable_draft(topic_key, admin_id):
    """該主題可編輯的草稿；沒有就從已發布版本複製一份。"""
    from services import taxonomy_service as taxo

    draft = (
        Taxonomy_Version.query.filter(
            Taxonomy_Version.topic_key == topic_key,
            Taxonomy_Version.status.in_(("draft", "in_review")),
        )
        .order_by(Taxonomy_Version.version_number.desc())
        .first()
    )
    if draft is not None:
        return draft, False
    try:
        published = taxo.get_published_taxonomy_version(topic_key)
    except (taxo.PublishedTaxonomyNotFoundError, taxo.PublishedTaxonomyIntegrityError) as exc:
        raise NewCategoryError("TAXONOMY_UNAVAILABLE", f"主題 {topic_key} 沒有可以複製的分類架構：{exc}", 422)
    return taxo.clone_taxonomy_version(topic_key, published.version_id, created_by=admin_id), True


def adopt(topic_key, main_category, sub_category, admin_id, definition=None):
    from services import taxonomy_service as taxo

    if not topic_key or not main_category or not sub_category:
        raise NewCategoryError("INVALID_CATEGORY", "缺少主題、大類別或子類別", 400)
    draft, cloned = _editable_draft(topic_key, admin_id)
    if any(c.sub_category == sub_category for c in draft.categories):
        raise NewCategoryError("CATEGORY_EXISTS", f"草稿 v{draft.version_number} 已經有「{sub_category}」", 409)

    if not definition or not definition.strip():
        reasons = [r.reasoning for r, t in _candidate_rows(topic_key)
                   if r.sub_category == sub_category and r.reasoning][:3]
        definition = "（AI 提出的新類別，請管理員補充定義）" + ("\n參考判斷原因：" + "；".join(reasons) if reasons else "")

    try:
        category = taxo.add_category(topic_key, draft.version_id, {
            "main_category": main_category,
            "sub_category": sub_category,
            "definition": definition.strip(),
        })
    except (taxo.TaxonomyEditNotAllowedError, taxo.TaxonomyVersionConflictError, ValueError) as exc:
        raise NewCategoryError("ADOPT_FAILED", str(exc), 409)

    audit_service.record(
        ACTION_ADOPT_NEW_CATEGORY, audit_service.ENTITY_TAXONOMY_VERSION, draft.version_id, admin_id,
        after={"topic_key": topic_key, "main_category": main_category, "sub_category": sub_category,
               "draft_cloned": cloned, "category_id": category.category_id},
    )
    db.session.commit()
    return {"taxonomy_version": draft.to_dict(), "category": category.to_dict(), "draft_created": cloned}


def merge(topic_key, main_category, sub_category, target_sub_category, admin_id):
    from services.review_service import ReviewError, confirm_manual

    rows = [r for r, t in _candidate_rows(topic_key)
            if r.main_category == main_category and r.sub_category == sub_category]
    if not rows:
        raise NewCategoryError("NOTHING_TO_MERGE", "這個新類別目前沒有待處理的回答", 404)
    merged, skipped = [], []
    for row in rows:
        try:
            confirm_manual(
                row.classification_id, admin_id, sub_category=target_sub_category,
                reasoning=f"新類別「{sub_category}」合併到既有類別",
            )
            merged.append(row.classification_id)
        except ReviewError as exc:
            skipped.append({"classification_id": row.classification_id, "code": exc.code, "message": exc.message})
    return {"merged_ids": merged, "skipped": skipped, "merged_count": len(merged)}
