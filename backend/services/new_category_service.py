"""
開放式分類的「新類別候選」管理（見 services/open_classification.py）。

AI 在分類時提出清單外的新類別（Response_Classification.status=new_category），
這裡把它們依（主題, 大類別, 子類別）彙整給管理員決定：

    採用（adopt）：一鍵完成——把新類別加進分類架構、立刻發布、這一組回答
        全部確認。之後類似的回答就會直接歸到這個類別。主題還沒有已發布的
        分類架構（AI 自動主題）時只加進草稿（見 adopt() 說明）。
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


def _default_definition(sub_category):
    """管理員沒有填定義時的預設定義。會直接進入分類 prompt，所以寫成
    跟其他類別一致的判斷規則句型，不放「請補充定義」這類給人看的提示。"""
    return f"當回覆主要涉及「{sub_category}」相關內容時，歸入此類別。"


def _group_rows(topic_key, main_category, sub_category):
    return [r for r, t in _candidate_rows(topic_key)
            if r.main_category == main_category and r.sub_category == sub_category]


def _adopt_into_draft_only(topic_key, main_category, sub_category, admin_id, definition):
    """主題還沒有已發布的分類架構（AI 自動建立的主題）：維持原本行為，
    只加進草稿、回答維持待處理。自動主題要怎麼處理還沒決定，這裡不發布
    AI 自己歸納、沒有人審過的草稿。"""
    from services import taxonomy_service as taxo

    draft, cloned = _editable_draft(topic_key, admin_id)
    if any(c.sub_category == sub_category for c in draft.categories):
        raise NewCategoryError("CATEGORY_EXISTS", f"草稿 v{draft.version_number} 已經有「{sub_category}」", 409)
    try:
        category = taxo.add_category(topic_key, draft.version_id, {
            "main_category": main_category, "sub_category": sub_category, "definition": definition,
        })
    except (taxo.TaxonomyEditNotAllowedError, taxo.TaxonomyVersionConflictError, ValueError) as exc:
        raise NewCategoryError("ADOPT_FAILED", str(exc), 409)
    audit_service.record(
        ACTION_ADOPT_NEW_CATEGORY, audit_service.ENTITY_TAXONOMY_VERSION, draft.version_id, admin_id,
        after={"topic_key": topic_key, "main_category": main_category, "sub_category": sub_category,
               "draft_cloned": cloned, "category_id": category.category_id, "published": False},
    )
    db.session.commit()
    return {
        "published": False,
        "taxonomy_version": draft.to_dict(), "category": category.to_dict(), "draft_created": cloned,
        "confirmed_ids": [], "confirmed_count": 0, "skipped": [],
        "message": "這個主題還沒有已發布的分類架構（AI 自動建立的主題），新類別只加入草稿，回答維持待處理。",
    }


def adopt(topic_key, main_category, sub_category, admin_id, definition=None):
    """一鍵採用：加入分類架構 → 發布 → 這一組回答全部確認。

    1. 從目前已發布的版本複製一份草稿，加入新類別。
    2. 立刻發布這份草稿（舊版本封存、相關報告標記過期，同一般發布）。
    3. 這一組待處理的回答逐筆確認（維持 AI 提出的類別，寫 audit）。

    這個主題如果已經有「還沒發布的草稿」會拒絕（409 DRAFT_IN_PROGRESS）：
    那份草稿可能有其他人正在編輯、還沒準備好的修改，一鍵發布會把它們
    一起發布出去。請先到分類架構頁發布或刪除那份草稿。

    主題還沒有已發布版本（AI 自動主題）時，維持舊行為：只加進草稿。
    """
    from services import taxonomy_service as taxo
    from services.review_service import ReviewError, confirm_original

    if not topic_key or not main_category or not sub_category:
        raise NewCategoryError("INVALID_CATEGORY", "缺少主題、大類別或子類別", 400)
    definition = (definition or "").strip() or _default_definition(sub_category)

    try:
        published = taxo.get_published_taxonomy_version(topic_key)
    except taxo.PublishedTaxonomyNotFoundError:
        published = None
    except taxo.PublishedTaxonomyIntegrityError as exc:
        raise NewCategoryError("TAXONOMY_UNAVAILABLE", f"主題 {topic_key} 的分類架構狀態異常：{exc}", 422)
    if published is None:
        return _adopt_into_draft_only(topic_key, main_category, sub_category, admin_id, definition)

    if any(c.sub_category == sub_category for c in published.categories):
        raise NewCategoryError(
            "CATEGORY_EXISTS", f"已發布的分類架構已經有「{sub_category}」，請改用合併", 409,
        )
    rows = _group_rows(topic_key, main_category, sub_category)
    if not rows:
        raise NewCategoryError("NOTHING_TO_ADOPT", "這個新類別目前沒有待處理的回答", 404)
    pending_draft = (
        Taxonomy_Version.query.filter(
            Taxonomy_Version.topic_key == topic_key,
            Taxonomy_Version.status.in_(("draft", "in_review")),
        ).order_by(Taxonomy_Version.version_number.desc()).first()
    )
    if pending_draft is not None:
        raise NewCategoryError(
            "DRAFT_IN_PROGRESS",
            f"這個主題有尚未發布的草稿 v{pending_draft.version_number}，一鍵採用會把草稿裡的其他修改一起發布。"
            "請先到「分類架構」發布或刪除那份草稿，再採用新類別。",
            409,
        )

    # 1. 複製 + 加入新類別
    try:
        draft = taxo.clone_taxonomy_version(topic_key, published.version_id, created_by=admin_id)
    except taxo.TaxonomyVersionConflictError as exc:
        raise NewCategoryError("ADOPT_FAILED", str(exc), 409)
    try:
        category = taxo.add_category(topic_key, draft.version_id, {
            "main_category": main_category, "sub_category": sub_category, "definition": definition,
        })
        # 2. 發布（失敗時刪掉剛複製的草稿，不留半套狀態）
        version = taxo.publish_taxonomy_version_with_validation(topic_key, draft.version_id, admin_id=admin_id)
    except (taxo.TaxonomyEditNotAllowedError, taxo.TaxonomyVersionConflictError,
            taxo.TaxonomyPublishValidationError, ValueError) as exc:
        db.session.rollback()
        try:
            taxo.delete_taxonomy_version(topic_key, draft.version_id)
        except Exception:  # noqa: BLE001 — 清理失敗不能蓋掉原本的錯誤
            db.session.rollback()
        raise NewCategoryError("ADOPT_FAILED", f"發布失敗，分類架構維持原樣：{exc}", 409)

    audit_service.record(
        ACTION_ADOPT_NEW_CATEGORY, audit_service.ENTITY_TAXONOMY_VERSION, version.version_id, admin_id,
        after={"topic_key": topic_key, "main_category": main_category, "sub_category": sub_category,
               "category_id": category.category_id, "published": True,
               "classification_ids": [r.classification_id for r in rows]},
    )
    db.session.commit()

    # 3. 這一組回答全部確認
    confirmed, skipped = [], []
    for row in rows:
        try:
            confirm_original(
                row.classification_id, admin_id,
                action=ACTION_ADOPT_NEW_CATEGORY, _allow_new_category=True,
            )
            confirmed.append(row.classification_id)
        except ReviewError as exc:
            skipped.append({"classification_id": row.classification_id, "code": exc.code, "message": exc.message})

    return {
        "published": True,
        "taxonomy_version": version.to_dict(), "category": category.to_dict(), "draft_created": True,
        "confirmed_ids": confirmed, "confirmed_count": len(confirmed), "skipped": skipped,
        "message": f"已加入並發布 v{version.version_number}，{len(confirmed)} 筆回答已確認。",
    }


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
