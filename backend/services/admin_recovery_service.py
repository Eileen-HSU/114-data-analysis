"""
Admin 未分類 / 失敗資料的恢復流程（assign topic / reroute / reclassify /
retry failed）。

【「未分類」的 domain definition】（Admin 未分類頁的三個分頁，彼此不混用）

    unrouted      ：Uploaded_Answer 已保存原文，但從來沒有產生分類結果
                    （沒有 Response_Segmentation_Status）。原因依
                    routing_status 細分：
                        unrouted             routing 判斷不出 Topic（含信心不足）
                        routing_failed       routing API 失敗
                        no_topic_candidates  當下沒有任何 published Topic
                        taxonomy_unavailable 有 Topic 但沒有可用 published taxonomy
                    舊資料（routing_status IS NULL）依 question_type 推導：
                    NULL / "other" -> unrouted，其他 -> taxonomy_unavailable。
    legacy_other  ：舊流程寫下、question_id IS NULL 或 = "other" 的
                    Response_Classification（尚未被取代、尚未排除）。
    failed        ：Response_Classification.status = failed（尚未排除）。
                    failed 是「分類失敗」，不是「未 routing」，兩者分開顯示。

【重新處理（reprocess）規則】——同一則回答不會產生重複計數：
    - 一則回答（survey：response_id + question_id；user_upload：
      uploaded_answer_id）底下，只要有任何一筆「人工定案」的列
      （confirmed / modified，或非 failed 的 excluded），就拒絕重新處理
      （409 REPROCESS_BLOCKED_BY_REVIEW），請先 reopen。
    - 允許重新處理時，舊的 pending / failed 列一律標記為
      status=superseded（保留作為 attempt history，永遠不計入統計），
      舊的 Response_Segmentation_Status（只存最新一次）刪除後重建。
    - 新 attempt 寫入新的 Response_Classification；每次 attempt 都有一筆
      Admin_Audit_Log（before / after / taxonomy version / 結果）。
    - taxonomy：預設使用 Topic 目前的 published version；也可以指定
      version_id，但只接受 published / archived（fail-closed：draft /
      in_review 不能拿來做正式分類，也絕不 fallback 到 hardcoded 分類）。
"""

from extensions import db, taiwan_now
from models import (
    Response_Classification,
    Response_Segmentation_Status,
    Survey_Response,
    Taxonomy_Version,
    Topic,
    Uploaded_Answer,
)
from classification_models import (
    REVIEW_STATUS_CONFIRMED,
    REVIEW_STATUS_EXCLUDED,
    REVIEW_STATUS_MODIFIED,
    REVIEW_STATUS_PENDING,
    SOURCE_TYPE_SURVEY,
    SOURCE_TYPE_USER_UPLOAD,
)
from services import audit_service
from services.failure_explainer import explain_failure, routing_failure
from services.safe_error import safe_error_summary
from services.effective_classification_service import (
    CLASSIFICATION_STATUS_FAILED,
    CLASSIFICATION_STATUS_SUPERSEDED,
    NON_COUNTABLE_STATUSES,
)

KIND_UNROUTED = "unrouted"
KIND_LEGACY_OTHER = "legacy_other"
KIND_FAILED = "failed"
UNASSIGNED_KINDS = (KIND_UNROUTED, KIND_FAILED, KIND_LEGACY_OTHER)

MAX_PAGE_SIZE = 100


class RecoveryError(Exception):
    def __init__(self, code, message, http_status=400, extra=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.extra = extra or {}


# ═══════════════════════════════════════════════════════════════
# 查詢
# ═══════════════════════════════════════════════════════════════

def _unrouted_answers_query():
    return (
        Uploaded_Answer.query
        .outerjoin(Response_Segmentation_Status, Response_Segmentation_Status.uploaded_answer_id == Uploaded_Answer.id)
        .filter(Response_Segmentation_Status.id.is_(None))
    )


def _failed_query():
    return Response_Classification.query.filter(
        Response_Classification.status == CLASSIFICATION_STATUS_FAILED,
        Response_Classification.review_status != REVIEW_STATUS_EXCLUDED,
    )


def _legacy_other_query():
    return Response_Classification.query.filter(
        db.or_(Response_Classification.question_id.is_(None), Response_Classification.question_id == "other"),
        Response_Classification.review_status != REVIEW_STATUS_EXCLUDED,
        db.or_(
            Response_Classification.status.is_(None),
            Response_Classification.status != CLASSIFICATION_STATUS_SUPERSEDED,
        ),
    )


def derive_unrouted_reason(answer) -> str:
    if answer.routing_status and answer.routing_status not in ("routed", "assigned"):
        return answer.routing_status
    if answer.question_type in (None, "", "other"):
        return "unrouted"
    return "taxonomy_unavailable"


def _answer_item(answer):
    data = answer.to_dict()
    data["kind"] = KIND_UNROUTED
    data["reason"] = derive_unrouted_reason(answer)
    data["processing_status"] = "not_classified"
    data["failure"] = routing_failure(answer.routing_status, answer.routing_detail)
    return data


def _classification_item(row, kind):
    data = row.to_dict()
    data["kind"] = kind
    data["segment"] = row.answer_text[row.segment_start:row.segment_end] if row.answer_text else ""
    data["reason"] = (row.reasoning or "")[:500] if kind == KIND_FAILED else "legacy_question_other"
    data["processing_status"] = row.status
    data["failure"] = explain_failure(row.reasoning) if kind == KIND_FAILED else None
    return data


def unassigned_counts() -> dict:
    return {
        KIND_UNROUTED: _unrouted_answers_query().count(),
        KIND_FAILED: _failed_query().count(),
        KIND_LEGACY_OTHER: _legacy_other_query().count(),
    }


def list_unassigned(kind, page=1, page_size=50) -> dict:
    if kind not in UNASSIGNED_KINDS:
        raise RecoveryError("INVALID_KIND", f"kind 只能是 {list(UNASSIGNED_KINDS)}", 400)
    page = max(int(page or 1), 1)
    page_size = min(max(int(page_size or 50), 1), MAX_PAGE_SIZE)

    if kind == KIND_UNROUTED:
        query = _unrouted_answers_query().order_by(Uploaded_Answer.created_at.desc(), Uploaded_Answer.id.desc())
        total = query.count()
        items = [_answer_item(a) for a in query.offset((page - 1) * page_size).limit(page_size).all()]
    else:
        base = _failed_query() if kind == KIND_FAILED else _legacy_other_query()
        query = base.order_by(Response_Classification.created_at.desc(), Response_Classification.classification_id.desc())
        total = query.count()
        items = [_classification_item(r, kind) for r in query.offset((page - 1) * page_size).limit(page_size).all()]

    return {
        "kind": kind,
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "counts": unassigned_counts(),
    }


def answer_detail(answer_id) -> dict:
    answer = db.session.get(Uploaded_Answer, answer_id)
    if answer is None:
        raise RecoveryError("ANSWER_NOT_FOUND", "找不到這筆上傳回答", 404)
    rows = Response_Classification.query.filter_by(uploaded_answer_id=answer_id).order_by(
        Response_Classification.classification_id.asc()
    ).all()
    status_row = Response_Segmentation_Status.query.filter_by(uploaded_answer_id=answer_id).first()
    data = answer.to_dict()
    data["reason"] = derive_unrouted_reason(answer) if status_row is None else answer.routing_status
    data["failure"] = routing_failure(answer.routing_status, answer.routing_detail)
    data["segmentation"] = status_row.to_dict() if status_row else None
    data["classifications"] = [r.to_dict() for r in rows]
    data["audit"] = [a.to_dict() for a in audit_service.list_for_entity(audit_service.ENTITY_UPLOADED_ANSWER, answer_id)]
    return data


# ═══════════════════════════════════════════════════════════════
# taxonomy 解析（fail-closed）
# ═══════════════════════════════════════════════════════════════

def _resolve_taxonomy(topic_key, taxonomy_version_id=None):
    from services.taxonomy_service import (
        PublishedTaxonomyIntegrityError,
        PublishedTaxonomyNotFoundError,
        build_classification_prompt,
        get_published_taxonomy_version,
        methodology_lookup_for_taxonomy_version,
    )

    if not topic_key or db.session.get(Topic, topic_key) is None:
        raise RecoveryError("TOPIC_NOT_FOUND", f"找不到 Topic：{topic_key!r}", 404)

    if taxonomy_version_id is not None:
        version = db.session.get(Taxonomy_Version, int(taxonomy_version_id))
        if version is None or version.topic_key != topic_key:
            raise RecoveryError("TAXONOMY_VERSION_NOT_FOUND", "taxonomy version 不存在或不屬於這個 Topic", 404)
        if version.status not in ("published", "archived"):
            raise RecoveryError(
                "TAXONOMY_VERSION_NOT_USABLE",
                f"只有 published / archived 版本可以用於正式分類（目前 status={version.status}）",
                422,
            )
        if not version.categories:
            raise RecoveryError("TAXONOMY_VERSION_EMPTY", "這個 taxonomy version 沒有任何分類", 422)
    else:
        from services.open_classification import usable_version_for
        try:
            # 已發布版本優先；開放式分類下，還沒發布的自動主題 / 新主題可以
            # 先用暫定草稿分類（見 services/open_classification.py）。
            version, _provisional = usable_version_for(topic_key)
        except PublishedTaxonomyIntegrityError as exc:
            raise RecoveryError("TAXONOMY_INTEGRITY_ERROR", str(exc), 409)
        if version is None:
            raise RecoveryError("TAXONOMY_UNAVAILABLE", f"主題 {topic_key} 目前沒有可用的分類架構", 422)

    from services.open_classification import open_mode_enabled
    return (
        build_classification_prompt(version, open_set=open_mode_enabled()),
        methodology_lookup_for_taxonomy_version(version),
        version,
    )


# ═══════════════════════════════════════════════════════════════
# reprocess 核心
# ═══════════════════════════════════════════════════════════════

def _scope_for_answer(answer):
    return {
        "source_type": SOURCE_TYPE_USER_UPLOAD,
        "answer_text": answer.answer_text,
        "question_id": f"{answer.source_column}_row{answer.row_index}",
        "response_id": None,
        "upload_batch_id": answer.upload_batch_id,
        "uploaded_answer_id": answer.id,
        "answer": answer,
    }


def _scope_for_classification(row):
    if row.source_type == SOURCE_TYPE_USER_UPLOAD:
        answer = (
            Uploaded_Answer.query.filter_by(id=row.uploaded_answer_id).with_for_update().first()
        )
        if answer is None:
            raise RecoveryError("ANSWER_NOT_FOUND", "找不到這筆分類對應的上傳回答", 404)
        return _scope_for_answer(answer)
    return {
        "source_type": SOURCE_TYPE_SURVEY,
        "answer_text": row.answer_text,
        "question_id": row.question_id,
        "response_id": row.response_id,
        "upload_batch_id": None,
        "uploaded_answer_id": None,
        "answer": None,
    }


def _existing_rows(scope):
    query = Response_Classification.query
    if scope["source_type"] == SOURCE_TYPE_USER_UPLOAD:
        query = query.filter_by(uploaded_answer_id=scope["uploaded_answer_id"])
    else:
        query = query.filter_by(response_id=scope["response_id"], question_id=scope["question_id"])
    return query.with_for_update().all()


def _existing_status(scope):
    if scope["source_type"] == SOURCE_TYPE_USER_UPLOAD:
        return Response_Segmentation_Status.query.filter_by(uploaded_answer_id=scope["uploaded_answer_id"]).first()
    return Response_Segmentation_Status.query.filter_by(
        response_id=scope["response_id"], question_id=scope["question_id"],
    ).first()


def _is_human_finalized(row):
    if row.status in NON_COUNTABLE_STATUSES:
        return False
    return row.review_status in (REVIEW_STATUS_CONFIRMED, REVIEW_STATUS_MODIFIED, REVIEW_STATUS_EXCLUDED)


def _row_source(scope):
    if scope["source_type"] == SOURCE_TYPE_USER_UPLOAD:
        return (SOURCE_TYPE_USER_UPLOAD, None, scope["upload_batch_id"])
    response = db.session.get(Survey_Response, scope["response_id"])
    return (SOURCE_TYPE_SURVEY, response.template_id, None) if response else None


def _reprocess(scope, topic_key, admin_id, action, taxonomy_version_id=None, reason=None,
               require_unclassified=False):
    """重新分類一則回答（見檔案開頭規則）。成功或 AI 回傳失敗都會 commit；
    非預期例外會 rollback 後把失敗原因持久化再往外拋 RecoveryError。"""
    from routes.classifications.classification import _persist_segmentation_result
    from services.classify_v2 import classify_response_multi_segment
    from services.report_service import OUTDATED_CLASSIFICATION_RERUN, mark_reports_outdated_for_sources

    existing = _existing_rows(scope)
    status_row = _existing_status(scope)

    if require_unclassified and status_row is not None and any(
        r.status not in NON_COUNTABLE_STATUSES for r in existing
    ):
        raise RecoveryError(
            "ALREADY_CLASSIFIED", "這筆回答已經有分類結果，不會重複建立；如需重跑請使用重新分類", 409,
        )
    blocked = [r.classification_id for r in existing if _is_human_finalized(r)]
    if blocked:
        raise RecoveryError(
            "REPROCESS_BLOCKED_BY_REVIEW",
            "這則回答已有人工確認 / 修改 / 排除的分類結果，請先重新開啟審核後再重新處理",
            409,
            extra={"classification_ids": blocked},
        )

    # 進行中的審核對話：別人正在審 -> 409；自己的在重新分類成功後關閉（closed_reason=superseded）
    from classification_models import Classification_Review
    open_reviews = Classification_Review.query.filter(
        Classification_Review.classification_id.in_([r.classification_id for r in existing] or [-1]),
        Classification_Review.status == "in_progress",
    ).all()
    others = [rv for rv in open_reviews if rv.admin_id != admin_id]
    if others:
        from services.review_service import _admin_display_name
        raise RecoveryError(
            "REVIEW_IN_PROGRESS_BY_OTHER", "這筆分類目前正由其他管理員審核中", 409,
            extra={"reviewing_admin_id": others[0].admin_id,
                   "reviewing_admin_name": _admin_display_name(others[0].admin_id)},
        )

    prompt_content, category_lookup, version = _resolve_taxonomy(topic_key, taxonomy_version_id)

    answer = scope["answer"]
    before = {
        "question_type": answer.question_type if answer else None,
        "routing_status": answer.routing_status if answer else None,
        "classification_ids": [r.classification_id for r in existing],
        "statuses": [r.status for r in existing],
    }

    try:
        result = classify_response_multi_segment(
            scope["answer_text"], prompt_content, topic_key,
            category_lookup=category_lookup, taxonomy_version_id=version.version_id,
        )
    except Exception as exc:  # AI 服務本身失敗：把原因持久化，不留半套資料
        db.session.rollback()
        if answer is not None:
            answer = db.session.get(Uploaded_Answer, answer.id)
            answer.routing_status = "classification_failed"
            answer.routing_detail = f"{action}: {safe_error_summary(exc, limit=1500)}"
            audit_service.record(
                action, audit_service.ENTITY_UPLOADED_ANSWER, answer.id, admin_id,
                before=before, after={"error": safe_error_summary(exc, limit=500), "topic_key": topic_key}, reason=reason,
            )
            db.session.commit()
        explained = explain_failure(safe_error_summary(exc, limit=1000))
        raise RecoveryError(
            explained["code"], explained["message"], 502, extra={"raw_error": explained["raw"]},
        )

    try:
        now = taiwan_now()
        for row in existing:
            if row.review_status == REVIEW_STATUS_PENDING or row.status in NON_COUNTABLE_STATUSES:
                row.status = CLASSIFICATION_STATUS_SUPERSEDED
                row.updated_at = now
        for review in open_reviews:
            review.status = "closed"
            review.closed_at = now
            review.closed_reason = "superseded"
        db.session.flush()

        # 舊結果保留（superseded），Response_Segmentation_Status 原地更新成新的 attempt，
        # 不刪除重建（見 services/classification_attempt_service.py）。
        if status_row is None:
            _, new_rows = _persist_segmentation_result(
                result,
                source_type=scope["source_type"],
                answer_text=scope["answer_text"],
                question_id=scope["question_id"],
                response_id=scope["response_id"],
                upload_batch_id=scope["upload_batch_id"],
                uploaded_answer_id=scope["uploaded_answer_id"],
                taxonomy_version_id=version.version_id,
            )
        else:
            from services.classification_persistence import build_classification_rows

            next_attempt = (status_row.attempt_no or 1) + 1
            status_row.segmentation_status = result["segmentation_status"]
            status_row.error_detail = result.get("segmentation_error_detail")
            status_row.attempt_no = next_attempt
            status_row.last_attempt_error = None
            status_row.last_attempt_at = now
            new_rows = build_classification_rows(scope, result["segments"], version.version_id, attempt_no=next_attempt)
        db.session.flush()

        succeeded = any(r.status != CLASSIFICATION_STATUS_FAILED for r in new_rows)
        if answer is not None:
            answer.question_type = topic_key
            if action in (audit_service.ACTION_ASSIGN_TOPIC,):
                answer.assigned_by_admin_id = admin_id
                answer.assigned_at = now
            if succeeded:
                answer.routing_status = "assigned" if action == audit_service.ACTION_ASSIGN_TOPIC else "routed"
                answer.routing_detail = reason
            else:
                answer.routing_status = "classification_failed"
                answer.routing_detail = (result.get("segmentation_error_detail") or "all segments failed")[:2000]

        after = {
            "topic_key": topic_key,
            "taxonomy_version_id": version.version_id,
            "segmentation_status": result.get("segmentation_status"),
            "new_classification_ids": [r.classification_id for r in new_rows],
            "new_statuses": [r.status for r in new_rows],
            "superseded_ids": [r.classification_id for r in existing if r.status == CLASSIFICATION_STATUS_SUPERSEDED],
        }
        entity_type = audit_service.ENTITY_UPLOADED_ANSWER if answer is not None else audit_service.ENTITY_CLASSIFICATION
        entity_id = answer.id if answer is not None else (existing[0].classification_id if existing else scope["question_id"])
        audit_service.record(action, entity_type, entity_id, admin_id, before=before, after=after, reason=reason)
        mark_reports_outdated_for_sources([_row_source(scope)], OUTDATED_CLASSIFICATION_RERUN)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return {
        "succeeded": succeeded,
        "topic_key": topic_key,
        "taxonomy_version_id": version.version_id,
        "segmentation_status": result.get("segmentation_status"),
        "segmentation_error_detail": result.get("segmentation_error_detail"),
        "failure": None if succeeded else explain_failure(
            result.get("segmentation_error_detail")
            or next((r.reasoning for r in new_rows if r.status == CLASSIFICATION_STATUS_FAILED), None)
            or "all segments failed"
        ),
        "classifications": [r.to_dict() for r in new_rows],
        "superseded_ids": after["superseded_ids"],
    }


# ═══════════════════════════════════════════════════════════════
# 對外操作
# ═══════════════════════════════════════════════════════════════

def _lock_answer(answer_id):
    answer = Uploaded_Answer.query.filter_by(id=answer_id).with_for_update().first()
    if answer is None:
        raise RecoveryError("ANSWER_NOT_FOUND", "找不到這筆上傳回答", 404)
    return answer


def assign_topic_to_answer(answer_id, admin_id, topic_key, taxonomy_version_id=None, reason=None):
    """未分類的上傳回答：Admin 指派 Topic -> 立即以該 Topic 的 taxonomy 分類。
    已經有成功分類結果的回答會被拒絕（防止重複建立 classification）。"""
    answer = _lock_answer(answer_id)
    return _reprocess(
        _scope_for_answer(answer), topic_key, admin_id, audit_service.ACTION_ASSIGN_TOPIC,
        taxonomy_version_id=taxonomy_version_id, reason=reason, require_unclassified=True,
    )


def reroute_answer(answer_id, admin_id):
    """重新 routing：用同一欄位名稱 + 同批次遮罩樣本重新判斷 Topic。

    - 判斷出主題 -> 直接分類
    - 模型成功判斷「沒有適合主題」（undetermined / no_candidates）且開放式
      分類開啟 -> 依同一個範圍（Uploaded_Answer.analysis_scope）建立 / 沿用
      自動主題後分類
    - AI 呼叫失敗（429 / 5xx / timeout / 金鑰 / 回應格式）-> 維持
      routing_failed，記錄安全的錯誤摘要，不建立自動主題
    """
    from routes.classifications.classification import _build_routing_context
    from services.open_classification import open_mode_enabled, resolve_for_unrouted
    from services.privacy_service import PiiMaskingError, mask_pii
    from services.question_routing_service import (
        ROUTING_REASON_API_FAILURE,
        ROUTING_REASON_NO_CANDIDATES,
        ROUTING_REASON_UNDETERMINED,
        route_question_type_detailed,
    )

    answer = _lock_answer(answer_id)
    scope = answer.analysis_scope or f"user:{answer.user_id}"
    samples = []
    peers = (
        Uploaded_Answer.query.filter_by(upload_batch_id=answer.upload_batch_id, source_column=answer.source_column)
        .order_by(Uploaded_Answer.row_index.asc()).all()
    )
    for peer in peers[:5]:
        try:
            samples.append(mask_pii(peer.answer_text))
        except PiiMaskingError:
            continue
    outcome = route_question_type_detailed(_build_routing_context(answer.source_column, samples), scope=scope)
    topic_key, routing_reason = outcome["topic_key"], outcome["reason"]
    before = {"routing_status": answer.routing_status, "question_type": answer.question_type}

    if topic_key is None and routing_reason in (ROUTING_REASON_UNDETERMINED, ROUTING_REASON_NO_CANDIDATES) \
            and open_mode_enabled():
        db.session.commit()  # 自動歸納會自己 commit / rollback：先釋放這筆的鎖
        taxonomy = resolve_for_unrouted(answer.source_column, [p.answer_text for p in peers], scope=scope)
        if taxonomy["prompt"] is not None:
            answer = _lock_answer(answer_id)
            result = _reprocess(
                _scope_for_answer(answer), taxonomy["topic_key"], admin_id, audit_service.ACTION_REROUTE,
                reason=f"reroute -> auto topic {taxonomy['topic_key']}", require_unclassified=True,
            )
            answer = db.session.get(Uploaded_Answer, answer_id)
            if answer.routing_status == "routed":
                answer.routing_status = "auto_topic"
                db.session.commit()
            return {"routed": True, "auto_topic": True, "routing_reason": routing_reason, **result}
        answer = _lock_answer(answer_id)
        answer.routing_status = "unrouted"
        answer.routing_detail = f"reroute: routing_reason={routing_reason}; {taxonomy['error']}"[:2000]
        audit_service.record(
            audit_service.ACTION_REROUTE, audit_service.ENTITY_UPLOADED_ANSWER, answer.id, admin_id,
            before=before, after={"routing_status": answer.routing_status, "routing_reason": routing_reason},
        )
        db.session.commit()
        return {"routed": False, "routing_reason": routing_reason, "routing_status": answer.routing_status,
                "error": taxonomy["error"]}

    if topic_key is None:
        if routing_reason == ROUTING_REASON_API_FAILURE:
            answer.routing_status = "routing_failed"
            answer.routing_detail = f"reroute: routing_error={outcome['error_kind']}; {outcome['error_summary']}"[:2000]
        else:
            answer.routing_status = {ROUTING_REASON_NO_CANDIDATES: "no_topic_candidates"}.get(routing_reason, "unrouted")
            answer.routing_detail = f"reroute: routing_reason={routing_reason}"
        audit_service.record(
            audit_service.ACTION_REROUTE, audit_service.ENTITY_UPLOADED_ANSWER, answer.id, admin_id,
            before=before, after={"routing_status": answer.routing_status, "routing_reason": routing_reason,
                                  "routing_error": outcome["error_kind"]},
        )
        db.session.commit()
        return {"routed": False, "routing_reason": routing_reason, "routing_status": answer.routing_status,
                "routing_error": outcome["error_kind"]}

    result = _reprocess(
        _scope_for_answer(answer), topic_key, admin_id, audit_service.ACTION_REROUTE,
        reason=f"reroute -> {topic_key}", require_unclassified=True,
    )
    return {"routed": True, "routing_reason": routing_reason, **result}


def reclassify_classification(classification_id, admin_id, topic_key=None, taxonomy_version_id=None, reason=None,
                              action=None):
    """legacy_other / failed 分類結果：指定（或沿用）Topic 重新分類整則回答。"""
    row = Response_Classification.query.filter_by(classification_id=classification_id).with_for_update().first()
    if row is None:
        raise RecoveryError("CLASSIFICATION_NOT_FOUND", "找不到這筆分類結果", 404)
    if row.status == CLASSIFICATION_STATUS_SUPERSEDED:
        raise RecoveryError("ALREADY_SUPERSEDED", "這筆分類已經被新的處理結果取代", 409)

    if topic_key is None:
        topic_key = _infer_topic(row)
        if topic_key is None:
            raise RecoveryError("TOPIC_REQUIRED", "無法判斷這筆資料的 Topic，請指定 topic_key", 422)

    return _reprocess(
        _scope_for_classification(row), topic_key, admin_id, action or audit_service.ACTION_RECLASSIFY,
        taxonomy_version_id=taxonomy_version_id, reason=reason,
    )


def retry_failed_classification(classification_id, admin_id, reason=None):
    row = db.session.get(Response_Classification, classification_id)
    if row is None:
        raise RecoveryError("CLASSIFICATION_NOT_FOUND", "找不到這筆分類結果", 404)
    if row.status != CLASSIFICATION_STATUS_FAILED:
        raise RecoveryError("NOT_FAILED", "只有 failed 的分類結果可以使用重新處理", 409)
    return reclassify_classification(
        classification_id, admin_id, reason=reason, action=audit_service.ACTION_RETRY_FAILED,
    )


def _infer_topic(row):
    if row.taxonomy_version_id is not None:
        version = db.session.get(Taxonomy_Version, row.taxonomy_version_id)
        if version is not None:
            return version.topic_key
    from services.source_lookup_service import resolve_question_type
    topic = resolve_question_type(row)
    return topic if topic and topic != "other" else None


def attempt_history(classification_id):
    """同一則回答的所有 attempt（含 superseded）＋ 相關 audit。"""
    row = db.session.get(Response_Classification, classification_id)
    if row is None:
        raise RecoveryError("CLASSIFICATION_NOT_FOUND", "找不到這筆分類結果", 404)
    if row.source_type == SOURCE_TYPE_USER_UPLOAD:
        rows = Response_Classification.query.filter_by(uploaded_answer_id=row.uploaded_answer_id)
        audit = audit_service.list_for_entity(audit_service.ENTITY_UPLOADED_ANSWER, row.uploaded_answer_id)
    else:
        rows = Response_Classification.query.filter_by(response_id=row.response_id, question_id=row.question_id)
        audit = audit_service.list_for_entity(audit_service.ENTITY_CLASSIFICATION, classification_id)
    return {
        "attempts": [r.to_dict() for r in rows.order_by(Response_Classification.classification_id.asc()).all()],
        "audit": [a.to_dict() for a in audit],
    }


# ═══════════════════════════════════════════════════════════════
# 主題分錯了：整個主題併入另一個主題
# ═══════════════════════════════════════════════════════════════

ACTION_MERGE_TOPIC = "merge_topic"


def merge_topic(source_topic_key, target_topic_key, admin_id):
    """管理員判斷「這個主題（通常是 AI 自動建立的主題）其實屬於另一個主題」：

    1. 來源主題記錄 merged_into = 目標主題：之後同樣的資料（例如同名欄位）
       直接用目標主題，來源主題不再列入 routing 候選、也不會再自動歸納。
    2. 來源主題還沒發布的草稿改為 archived（保留歷史，不刪除）。
    3. 來源主題底下的資料，逐則用目標主題的分類架構重新分類（舊結果標記
       superseded 保留歷史）；已有人工定案結果的回答會跳過並回報。

    只允許合併「沒有已發布版本」的主題（自動主題 / 草稿主題），避免誤把
    正式主題整個搬走。
    """
    from models import Topic
    from services.open_classification import usable_version_for
    from taxonomy import TAXONOMY_VERSION_STATUS_ARCHIVED

    if not target_topic_key or target_topic_key == source_topic_key:
        raise RecoveryError("INVALID_TARGET_TOPIC", "請選擇另一個主題", 400)
    source = db.session.get(Topic, source_topic_key)
    target = db.session.get(Topic, target_topic_key)
    if source is None or target is None:
        raise RecoveryError("TOPIC_NOT_FOUND", "找不到主題", 404)
    if target.merged_into:
        raise RecoveryError("TARGET_ALREADY_MERGED", f"目標主題已經併入「{target.merged_into}」，請直接選那個主題", 409)
    if any(v.status == "published" for v in source.taxonomy_versions):
        raise RecoveryError(
            "SOURCE_HAS_PUBLISHED_TAXONOMY",
            "這個主題已經有正式發布的分類架構，不能整個併入其他主題；請改用單筆「移到其他主題」。",
            409,
        )
    target_version, _ = usable_version_for(target_topic_key)
    if target_version is None:
        raise RecoveryError("TAXONOMY_UNAVAILABLE", f"目標主題「{target.title}」目前沒有可用的分類架構", 422)

    now = taiwan_now()
    source.merged_into = target_topic_key
    archived = []
    for version in source.taxonomy_versions:
        if version.status in ("draft", "in_review"):
            version.status = TAXONOMY_VERSION_STATUS_ARCHIVED
            version.archived_at = now
            archived.append(version.version_id)
    audit_service.record(
        ACTION_MERGE_TOPIC, "topic", source_topic_key, admin_id,
        before={"merged_into": None}, after={"merged_into": target_topic_key, "archived_version_ids": archived},
    )
    db.session.commit()

    # 重新分類來源主題底下的資料
    answer_ids = [a.id for a in Uploaded_Answer.query.filter_by(question_type=source_topic_key).all()]
    source_version_ids = [v.version_id for v in source.taxonomy_versions]
    survey_rows = []
    if source_version_ids:
        seen = set()
        for row in Response_Classification.query.filter(
            Response_Classification.taxonomy_version_id.in_(source_version_ids),
            Response_Classification.source_type == SOURCE_TYPE_SURVEY,
            Response_Classification.status != CLASSIFICATION_STATUS_SUPERSEDED,
        ).all():
            key = (row.response_id, row.question_id)
            if key not in seen:
                seen.add(key)
                survey_rows.append(row.classification_id)

    moved, skipped = 0, []
    for answer_id in answer_ids:
        try:
            answer = _lock_answer(answer_id)
            _reprocess(_scope_for_answer(answer), target_topic_key, admin_id, ACTION_MERGE_TOPIC,
                       reason=f"主題 {source_topic_key} 併入 {target_topic_key}")
            moved += 1
        except RecoveryError as exc:
            db.session.rollback()
            skipped.append({"uploaded_answer_id": answer_id, "code": exc.code, "message": exc.message})
    for classification_id in survey_rows:
        try:
            reclassify_classification(classification_id, admin_id, topic_key=target_topic_key,
                                      reason=f"主題 {source_topic_key} 併入 {target_topic_key}",
                                      action=ACTION_MERGE_TOPIC)
            moved += 1
        except RecoveryError as exc:
            db.session.rollback()
            skipped.append({"classification_id": classification_id, "code": exc.code, "message": exc.message})

    return {
        "source_topic_key": source_topic_key,
        "target_topic_key": target_topic_key,
        "archived_version_ids": archived,
        "moved_count": moved,
        "skipped_count": len(skipped),
        "skipped": skipped[:100],
    }
