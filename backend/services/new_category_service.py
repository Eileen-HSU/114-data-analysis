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
ACTION_EXCLUDE_NEW_CATEGORY = "exclude_new_category"

# 殘留／舊候選的原因（一組候選可以同時有多個原因）
RESIDUAL_LEGACY = "legacy"                # 舊版資料（沒有分類架構版本、舊欄位、舊上傳）
RESIDUAL_NO_TOPIC = "no_topic"            # 找不到所屬主題（版本遺失 / topic_key 為空）
RESIDUAL_TOPIC_MISSING = "topic_missing"  # 版本還在，但主題已不存在
RESIDUAL_TOPIC_MERGED = "topic_merged"    # 主題已被合併到其他主題（搬遷沒做完留下來的）

# 排除的影響說明：後端要求明確確認（acknowledged），前端對話框也用同一句
EXCLUDE_IMPACT_MESSAGE = "排除後，這些回答將不再納入分析、彙整、匯出與報告。此操作可透過 reopen 復原。"


class NewCategoryError(Exception):
    def __init__(self, code, message, http_status=400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def _residual_expr():
    """殘留／舊候選的 SQL 條件：legacy、找不到主題、主題已被合併。"""
    from models import Topic
    from services.admin_recovery_service import _legacy_classification_clause

    return db.or_(
        _legacy_classification_clause(),
        Taxonomy_Version.topic_key.is_(None),
        Topic.topic_key.is_(None),
        db.and_(Topic.merged_into.isnot(None), Topic.merged_into != ""),
    )


def _candidate_query():
    from models import Topic

    return (
        db.session.query(Response_Classification, Taxonomy_Version.topic_key, Topic.topic_key, Topic.merged_into)
        .outerjoin(Taxonomy_Version, Response_Classification.taxonomy_version_id == Taxonomy_Version.version_id)
        .outerjoin(Topic, Taxonomy_Version.topic_key == Topic.topic_key)
        .filter(
            Response_Classification.status == NEW_CATEGORY_STATUS,
            Response_Classification.review_status == "pending_review",
        )
    )


def _candidate_entries(topic_key=None, residual=False):
    """[(classification, topic_key, topic_exists, merged_into)]。

    residual=False：正常現行候選（採用 / 合併只作用在這一組）。
    residual=True ：殘留／舊候選（legacy、找不到主題、主題已被合併），不進正常清單。"""
    expr = _residual_expr()
    query = _candidate_query().filter(expr if residual else ~expr)
    if topic_key:
        query = query.filter(Taxonomy_Version.topic_key == topic_key)
    return [
        (row, version_topic, topic_row is not None, merged_into)
        for row, version_topic, topic_row, merged_into in query.order_by(Response_Classification.classification_id.asc()).all()
    ]


def _candidate_rows(topic_key=None, residual=False):
    return [(row, version_topic) for row, version_topic, _exists, _merged in _candidate_entries(topic_key, residual)]


def _legacy_candidate_ids():
    from services.admin_recovery_service import _legacy_classification_clause

    return {
        cid for (cid,) in db.session.query(Response_Classification.classification_id).filter(
            Response_Classification.status == NEW_CATEGORY_STATUS,
            Response_Classification.review_status == "pending_review",
            _legacy_classification_clause(),
        ).all()
    }


def _group_entries(entries, residual=False):
    from models import Topic

    legacy_ids = _legacy_candidate_ids() if residual else set()
    groups = {}
    for row, row_topic, topic_exists, merged_into in entries:
        key = (row_topic, row.main_category, row.sub_category)
        group = groups.setdefault(key, {
            "topic_key": row_topic,
            "main_category": row.main_category,
            "sub_category": row.sub_category,
            "count": 0,
            "classification_ids": [],
            "examples": [],
            "reasons": [],
            "taxonomy_version_ids": [],
        })
        if residual:
            group.setdefault("residual_reasons", set())
            group["merged_into"] = merged_into or group.get("merged_into")
            if row.classification_id in legacy_ids:
                group["residual_reasons"].add(RESIDUAL_LEGACY)
            if row_topic is None:
                group["residual_reasons"].add(RESIDUAL_NO_TOPIC)
            elif not topic_exists:
                group["residual_reasons"].add(RESIDUAL_TOPIC_MISSING)
            if merged_into:
                group["residual_reasons"].add(RESIDUAL_TOPIC_MERGED)
        group["count"] += 1
        group["classification_ids"].append(row.classification_id)
        if row.taxonomy_version_id is not None and row.taxonomy_version_id not in group["taxonomy_version_ids"]:
            group["taxonomy_version_ids"].append(row.taxonomy_version_id)
        if len(group["examples"]) < 3:
            group["examples"].append(row.answer_text[row.segment_start:row.segment_end])
        if row.reasoning and len(group["reasons"]) < 3:
            group["reasons"].append(row.reasoning)

    titles = {t.topic_key: t.title for t in Topic.query.filter(Topic.topic_key.in_({k[0] for k in groups if k[0]})).all()} if groups else {}
    items = sorted(groups.values(), key=lambda g: (-g["count"], g["topic_key"] or "", g["sub_category"] or ""))
    for item in items:
        item["topic_title"] = titles.get(item["topic_key"], item["topic_key"])
        item["classification_ids"] = item["classification_ids"][:500]
        item["taxonomy_version_ids"] = sorted(item["taxonomy_version_ids"])
        # 同一組回答綁定了不同版本的分類架構：合併時每筆各自驗證目標類別
        item["version_mismatch"] = len(item["taxonomy_version_ids"]) > 1
        if residual:
            item["residual_reasons"] = sorted(item["residual_reasons"])
    return items


def list_candidates(topic_key=None):
    """正常現行候選放 items / total（既有欄位不變）；殘留／舊候選另放
    residual_items / residual_total，不計入主要徽章、也不出現在正常清單。"""
    items = _group_entries(_candidate_entries(topic_key, residual=False))
    residual_items = _group_entries(_candidate_entries(topic_key, residual=True), residual=True)
    return {
        "items": items, "total": len(items),
        "residual_items": residual_items, "residual_total": len(residual_items),
    }


def residual_group_count():
    """殘留／舊候選有幾組（給 overview 另外顯示，不併進主要徽章）。"""
    return len({(t, r.main_category, r.sub_category) for r, t in _candidate_rows(residual=True)})


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
            skipped.append({"classification_id": row.classification_id, "code": exc.code, "message": exc.message,
                            "taxonomy_version_id": row.taxonomy_version_id})
    return {"merged_ids": merged, "skipped": skipped, "merged_count": len(merged)}


# ── 合併目標（專用於「新類別候選 → 合併到既有類別」下拉）─────────────────────

def _version_label(version):
    return {
        "version_id": version.version_id,
        "version_number": version.version_number,
        "version_status": version.status,
    }


def merge_targets(topic_key, main_category=None, sub_category=None):
    """這個候選群組可以合併到的既有類別。

    規則（以候選群組的 topic_key 為基準，不再借用單筆審核的 taxonomy_options）：
      - Topic 有 published 版本 -> 目前 published 版本（target_source=published）
      - 尚未發布（AI 自動主題）  -> 最新一個有分類的 draft / in_review（provisional_draft）
      - 以上都沒有               -> 退回群組內最新的綁定版本（bound_fallback），避免空清單
      - 只列目標版本實際存在的類別；舊綁定版本才有、目前已不存在的類別不列，避免混亂。

    版本不一致：群組內每筆回答仍綁著「分類當時」的版本。合併時 confirm_manual 逐筆
    以該筆綁定版本驗證，所以每個類別帶 valid_rows（群組內有幾筆的綁定版本含此類別）；
    bound_versions 列出各綁定版本與筆數，bound_versions_consistent 標示是否一致。
    傳 main_category + sub_category 時只統計該群組，否則統計整個 Topic 的候選。
    """
    from models import Topic
    from services.open_classification import is_auto_topic, usable_version_for
    from services.taxonomy_service import PublishedTaxonomyIntegrityError

    if not topic_key:
        raise NewCategoryError("TOPIC_REQUIRED", "這個新類別候選沒有所屬主題，無法列出可合併的類別", 400)
    topic = db.session.get(Topic, topic_key)
    if topic is None:
        raise NewCategoryError("TOPIC_NOT_FOUND", "找不到主題", 404)

    rows = [r for r, _t in _candidate_rows(topic_key)]
    if main_category is not None or sub_category is not None:
        rows = [r for r in rows if r.main_category == main_category and r.sub_category == sub_category]

    # 群組內各綁定版本
    bound_counts = {}
    for row in rows:
        bound_counts[row.taxonomy_version_id] = bound_counts.get(row.taxonomy_version_id, 0) + 1
    bound_ids = [vid for vid in bound_counts if vid is not None]
    bound_versions = {}
    if bound_ids:
        bound_versions = {
            v.version_id: v
            for v in Taxonomy_Version.query.filter(Taxonomy_Version.version_id.in_(bound_ids)).all()
        }

    try:
        version, provisional = usable_version_for(topic_key)
    except PublishedTaxonomyIntegrityError as exc:  # 同一主題有多個 published
        raise NewCategoryError("TAXONOMY_INTEGRITY_ERROR", str(exc), 409)
    target_source = "provisional_draft" if provisional else "published"
    if version is None:
        if bound_versions:
            version = max(bound_versions.values(), key=lambda v: v.version_number)
            target_source = "bound_fallback"

    has_published = Taxonomy_Version.query.filter_by(topic_key=topic_key, status="published").count() > 0

    bound_sub_sets = {vid: {c.sub_category for c in v.categories} for vid, v in bound_versions.items()}
    categories = []
    if version is not None:
        for category in version.categories:
            if not category.sub_category:
                continue
            categories.append({
                "category_id": category.category_id,
                "main_category": category.main_category,
                "sub_category": category.sub_category,
                # confirm_manual 以 sub_category 比對該筆綁定版本的清單，這裡用同一個標準
                "valid_rows": sum(
                    count for vid, count in bound_counts.items()
                    if vid is not None and category.sub_category in bound_sub_sets.get(vid, set())
                ),
            })

    target_id = version.version_id if version is not None else None
    result = {
        "topic_key": topic_key,
        "topic_title": topic.title,
        "is_auto_topic": is_auto_topic(topic_key),
        "has_published": has_published,
        "merged_into": topic.merged_into,
        "target_source": target_source if version is not None else None,
        "version_id": target_id,
        "version_number": version.version_number if version is not None else None,
        "version_status": version.status if version is not None else None,
        "category_count": len(categories),
        "categories": categories,
        "row_total": len(rows),
        "bound_versions": sorted(
            [
                {**(_version_label(bound_versions[vid]) if vid in bound_versions else
                    {"version_id": vid, "version_number": None, "version_status": None}),
                 "row_count": count}
                for vid, count in bound_counts.items()
            ],
            key=lambda b: (b["version_number"] is None, b["version_number"] or 0, b["version_id"] or 0),
        ),
        "bound_versions_consistent": len(bound_counts) <= 1,
        "rows_on_other_version": sum(count for vid, count in bound_counts.items() if vid != target_id),
    }
    return result


# ── 殘留／舊候選：排除 ────────────────────────────────────────────────────────

def exclude_residual(topic_key, main_category, sub_category, admin_id, *, acknowledged=False, reason=None, batch_id=None):
    """把一組「殘留／舊候選」逐筆排除（呼叫既有 review_service.exclude，本身不改）。

    排除 = review_status 變成 excluded：這些回答不再納入分析、彙整、匯出與報告
    （報告會標記過期），可以用既有的 reopen 復原。所以呼叫端必須明確確認
    （acknowledged=True），否則 400 ACK_REQUIRED。

    只作用在殘留 bucket：正常現行候選要走採用 / 合併，不能用這個入口排除。
    逐筆處理、各自 commit：
      success_ids —— 排除成功
      skipped     —— 被既有規則擋下（別的管理員審核中、已人工定案…），保留原狀
      failed      —— 非預期錯誤（已 rollback，不影響其他筆）
    共用 batch_id：每筆 exclude 的 audit 都補上 batch_id，另寫一筆群組層級的
    exclude_new_category audit。
    """
    import uuid

    from audit import Admin_Audit_Log
    from services import review_service

    if acknowledged is not True:
        raise NewCategoryError("ACK_REQUIRED", EXCLUDE_IMPACT_MESSAGE, 400)
    if not sub_category:
        raise NewCategoryError("INVALID_CATEGORY", "缺少要排除的子類別", 400)

    rows = [
        r for r, row_topic in _candidate_rows(residual=True)
        if row_topic == (topic_key or None) and r.main_category == main_category and r.sub_category == sub_category
    ]
    if not rows:
        raise NewCategoryError("NOTHING_TO_EXCLUDE", "這個殘留候選目前沒有待處理的回答（正常候選請用採用 / 合併）", 404)

    batch_id = (str(batch_id).strip() if batch_id is not None else "") or uuid.uuid4().hex
    if len(batch_id) > 64:
        raise NewCategoryError("INVALID_BATCH_ID", "batch_id 長度不可超過 64", 400)
    reason_text = (reason or "").strip()[:1000] or f"殘留／舊新類別候選「{sub_category}」排除"

    success, skipped, failed = [], [], []
    for row in rows:
        cid = row.classification_id
        try:
            review_service.exclude(cid, admin_id, reason=reason_text)
        except review_service.ReviewError as exc:
            skipped.append({"classification_id": cid, "code": exc.code, "message": exc.message})
            continue
        except Exception as exc:  # 非預期：rollback 後繼續處理下一筆
            db.session.rollback()
            failed.append({"classification_id": cid, "message": f"{type(exc).__name__}: {str(exc)[:300]}"})
            continue
        success.append(cid)

    try:
        for cid in success:
            entry = (
                Admin_Audit_Log.query
                .filter_by(action=audit_service.ACTION_EXCLUDE, entity_type=audit_service.ENTITY_CLASSIFICATION, entity_id=str(cid))
                .order_by(Admin_Audit_Log.audit_id.desc())
                .first()
            )
            if entry is not None and entry.batch_id is None:
                entry.batch_id = batch_id
        audit_service.record(
            ACTION_EXCLUDE_NEW_CATEGORY, "new_category_group",
            f"{topic_key or '-'}|{main_category}|{sub_category}", admin_id,
            before={"candidate_count": len(rows)},
            after={
                "success_ids": success,
                "skipped_ids": [x["classification_id"] for x in skipped],
                "failed_ids": [x["classification_id"] for x in failed],
            },
            reason=reason_text, batch_id=batch_id,
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return {
        "batch_id": batch_id,
        "topic_key": topic_key or None,
        "main_category": main_category,
        "sub_category": sub_category,
        "success_ids": success, "success_count": len(success),
        "skipped": skipped, "skipped_count": len(skipped),
        "failed": failed, "failed_count": len(failed),
    }
