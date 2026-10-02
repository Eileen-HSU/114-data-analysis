"""Internal AI administration API.

Admin-only endpoints for topics / taxonomy versions, classification review,
unassigned-answer recovery and report lifecycle.
"""

from flask import Blueprint, jsonify, request

from extensions import db
from models import Admin
from classification_models import Response_Classification, Classification_Review, ALLOWED_REVIEW_STATUSES
from services.review_service import derive_review_state
from taxonomy import Taxonomy_Version
from routes.auth.admin_guard import verify_admin_token
from services.effective_classification_service import effective_view
from services.failure_explainer import explain_failure
from routes.api_errors import api_error
from services import admin_recovery_service as recovery
from services import report_service
from services import new_category_service
from services.subcategory_methodology import SUBCATEGORY_METHODOLOGY
from services.taxonomy_generation_service import (
    generate_taxonomy_draft,
    load_reference_material,
    TaxonomyGenerationError,
    TaxonomyGenerationValidationError,
)
from services import taxonomy_service as taxo
from services.taxonomy_sandbox_service import (
    run_sandbox_classification,
    SandboxValidationError,
    SandboxExecutionError,
)


ai_admin_bp = Blueprint("ai_admin", __name__, url_prefix="/api/admin/ai")

# 這裡的錯誤字串沿用 verify_admin_token 回傳的內容，用來決定 401 / 403：
# token 本身有問題（不存在/過期/簽章錯）→ 401；token 有效但不是
# admin（例如一般 User 的 token）→ 403。
_TOKEN_ERROR_STATUS = {
    "Unauthorized": 401,
    "Token expired": 401,
    "Invalid token": 401,
}


def _admin_or_error():
    """驗證 Admin JWT（account_type == "admin" 且 role == "admin"），
    完全不查 User table、不看 User.role（對應需求 #5、#7）。
    """
    admin_id, error = verify_admin_token(request)
    if error:
        status = _TOKEN_ERROR_STATUS.get(error, 403)
        return None, (jsonify({"error": error}), status)
    admin = db.session.get(Admin, admin_id)
    if not admin:
        return None, (jsonify({"error": "Admin access required"}), 403)
    return admin, None


CLASSIFICATION_STATES = ("pending_review", "in_review", "failed", "confirmed", "modified", "excluded")
_DEFAULT_PAGE_SIZE = 50
_MAX_PAGE_SIZE = 200


def _active_review_exists():
    return db.session.query(Classification_Review.review_id).filter(
        Classification_Review.classification_id == Response_Classification.classification_id,
        Classification_Review.status == "in_progress",
    ).exists()


def _state_clause(state):
    """前後端共用的狀態定義（跟 review_service.derive_review_state 一致）：
    failed         ：status=failed 且未排除（不論 review_status）
    pending_review ：review_status=pending_review 且非 failed（含 in_review）
    in_review      ：pending_review 中、有 in_progress session 的子集合
    confirmed / modified / excluded：對應 review_status
    """
    not_failed = db.or_(Response_Classification.status.is_(None), Response_Classification.status != "failed")
    if state == "failed":
        return db.and_(Response_Classification.status == "failed", Response_Classification.review_status != "excluded")
    if state == "pending_review":
        return db.and_(Response_Classification.review_status == "pending_review", not_failed)
    if state == "in_review":
        return db.and_(Response_Classification.review_status == "pending_review", not_failed, _active_review_exists())
    return Response_Classification.review_status == state


@ai_admin_bp.get("/classifications")
def reviewed_classifications():
    """
    Admin 分類審查清單（server-side pagination）。

    Query 參數（全部選填，可 AND 疊加）：
        state             ：pending_review / in_review / failed / confirmed /
                            modified / excluded（見 _state_clause）
        review_status     ：舊參數，直接比對 review_status（向後相容）
        topic             ：Topic.topic_key，或 "__unassigned__"
                            （question_id IS NULL / "other" 的舊資料）
        needs_human_review：true 只看被 Confidence Gate flag 的列
        auto_confirmed    ：true 只看系統自動通過的列（重新審核用）；
                            false 排除自動通過的列
        page / page_size  ：預設 1 / 50，page_size 上限 200

    回應：
        classifications：這一頁的資料（穩定排序：created_at DESC,
                         classification_id DESC）
        total          ：符合全部條件的總筆數
        status_counts  ：套用 topic / needs_human_review 之後、各狀態的
                         總筆數（不受 state/review_status/page 影響），
                         前端分頁籤數字直接用這個，不再用目前頁面自行計算。
    被 retry / reclassify 取代的舊 attempt（status=superseded）不會出現在清單。
    """
    _, failure = _admin_or_error()
    if failure:
        return failure
    review_status = request.args.get("review_status")
    state = request.args.get("state")
    topic = request.args.get("topic")
    page = max(request.args.get("page", 1, type=int) or 1, 1)
    page_size = min(max(request.args.get("page_size", _DEFAULT_PAGE_SIZE, type=int) or _DEFAULT_PAGE_SIZE, 1), _MAX_PAGE_SIZE)

    base = Response_Classification.query.filter(
        db.or_(Response_Classification.status.is_(None), Response_Classification.status != "superseded")
    )
    if topic == "__unassigned__":
        base = base.filter(
            db.or_(
                Response_Classification.question_id.is_(None),
                Response_Classification.question_id == "other",
            )
        )
    elif topic:
        # topic 是 Topic.topic_key，透過寫入分類時保存的 taxonomy_version_id
        # 反查 Taxonomy_Version.topic_key（同時涵蓋 survey 與 user_upload、
        # 以及這個 topic 底下所有版本產生的分類結果）。
        base = base.join(
            Taxonomy_Version,
            Response_Classification.taxonomy_version_id == Taxonomy_Version.version_id,
        ).filter(Taxonomy_Version.topic_key == topic)
    if request.args.get("needs_human_review") == "true":
        base = base.filter(Response_Classification.needs_human_review.is_(True))

    status_counts = {s: base.filter(_state_clause(s)).count() for s in CLASSIFICATION_STATES}
    auto_confirmed_count = base.filter(Response_Classification.auto_confirmed.is_(True)).count()
    auto_confirmed_arg = request.args.get("auto_confirmed")
    if auto_confirmed_arg == "true":
        base = base.filter(Response_Classification.auto_confirmed.is_(True))
    elif auto_confirmed_arg == "false":
        base = base.filter(Response_Classification.auto_confirmed.is_(False))

    query = base
    if review_status:
        if review_status not in ALLOWED_REVIEW_STATUSES:
            return api_error("INVALID_REVIEW_STATUS", "Invalid review_status", 400)
        query = query.filter(Response_Classification.review_status == review_status)
    if state:
        if state not in CLASSIFICATION_STATES:
            return api_error("INVALID_STATE", f"state 只能是 {list(CLASSIFICATION_STATES)}", 400)
        query = query.filter(_state_clause(state))

    total = query.count()
    rows = (
        query.order_by(Response_Classification.created_at.desc(), Response_Classification.classification_id.desc())
        .offset((page - 1) * page_size).limit(page_size).all()
    )

    active_by_classification = {}
    if rows:
        for review in Classification_Review.query.filter(
            Classification_Review.classification_id.in_([r.classification_id for r in rows]),
            Classification_Review.status == "in_progress",
        ).all():
            active_by_classification.setdefault(review.classification_id, review)
    admin_names = {}
    if active_by_classification:
        admin_names = {
            a.admin_id: a.admin_name for a in Admin.query.filter(
                Admin.admin_id.in_({r.admin_id for r in active_by_classification.values()})
            ).all()
        }

    results = []
    for row in rows:
        item = row.to_dict()
        item["segment"] = row.answer_text[row.segment_start:row.segment_end]
        active = active_by_classification.get(row.classification_id)
        item["review_state"] = derive_review_state(row, active)
        item["active_review"] = None if active is None else {
            "review_id": active.review_id,
            "admin_id": active.admin_id,
            "admin_name": admin_names.get(active.admin_id),
        }
        item["failure"] = explain_failure(row.reasoning) if row.status == "failed" else None
        view = effective_view(row)
        item["effective_result"] = None if view is None else {
            "main_category": view["main_category"],
            "sub_category": view["sub_category"],
            "secondary_category": view["secondary_sub_category"],
            "secondary_categories": [
                {"main_category": sc["main_category"], "sub_category": sc["sub_category"]}
                for sc in view["secondary_categories"]
            ],
            "reasoning": view["reasoning"],
        }
        results.append(item)
    return jsonify({
        "classifications": results,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": (total + page_size - 1) // page_size,
        "status_counts": status_counts,
        "auto_confirmed_count": auto_confirmed_count,
    })


# ── 未分類 / 失敗資料恢復（見 services/admin_recovery_service.py）──────

def _recovery_error(exc):
    return api_error(exc.code, exc.message, exc.http_status, **exc.extra)


def _optional_int(value):
    if value in (None, ""):
        return None
    return int(value)


# ── 全部重試（背景，見 services/bulk_retry_service.py）────────────────

def _bulk_retry_error(exc):
    extra = {"job": exc.job} if exc.job else {}
    return api_error(exc.code, exc.message, exc.http_status, **extra)


@ai_admin_bp.get("/unassigned/retry-all")
def bulk_retry_status():
    """目前／最近一次全部重試的進度，以及還剩多少無法分類的資料。"""
    _, failure = _admin_or_error()
    if failure:
        return failure
    from services import bulk_retry_service

    return jsonify(bulk_retry_service.status()), 200


@ai_admin_bp.post("/unassigned/retry-all")
def bulk_retry_start():
    """在背景把所有分類失敗、判斷不出主題的資料重跑一遍。202：已開始；
    409 BULK_RETRY_RUNNING：已經有一個在跑；409 NOTHING_TO_RETRY：沒有資料。"""
    admin, failure = _admin_or_error()
    if failure:
        return failure
    from flask import current_app
    from services import bulk_retry_service

    try:
        job = bulk_retry_service.start(admin.admin_id, app=current_app._get_current_object())
    except bulk_retry_service.BulkRetryError as exc:
        return _bulk_retry_error(exc)
    return jsonify({"job": job}), 202


@ai_admin_bp.post("/unassigned/retry-all/cancel")
def bulk_retry_cancel():
    """停止執行中的全部重試（處理完目前這一筆就停）。"""
    admin, failure = _admin_or_error()
    if failure:
        return failure
    from services import bulk_retry_service

    try:
        job = bulk_retry_service.cancel(admin.admin_id)
    except bulk_retry_service.BulkRetryError as exc:
        return _bulk_retry_error(exc)
    return jsonify({"job": job}), 200


@ai_admin_bp.get("/unassigned")
def list_unassigned():
    _, failure = _admin_or_error()
    if failure:
        return failure
    try:
        return jsonify(recovery.list_unassigned(
            request.args.get("kind", recovery.KIND_UNROUTED),
            page=request.args.get("page", 1, type=int),
            page_size=request.args.get("page_size", 50, type=int),
        ))
    except recovery.RecoveryError as exc:
        return _recovery_error(exc)


@ai_admin_bp.get("/unassigned/answers/<int:answer_id>")
def unassigned_answer_detail(answer_id):
    _, failure = _admin_or_error()
    if failure:
        return failure
    try:
        return jsonify(recovery.answer_detail(answer_id))
    except recovery.RecoveryError as exc:
        return _recovery_error(exc)


@ai_admin_bp.post("/unassigned/answers/<int:answer_id>/assign")
def assign_unassigned_answer(answer_id):
    """Body: {"topic_key": "...", "taxonomy_version_id": 選填, "reason": 選填}"""
    admin, failure = _admin_or_error()
    if failure:
        return failure
    data = request.get_json(silent=True) or {}
    try:
        result = recovery.assign_topic_to_answer(
            answer_id, admin.admin_id, data.get("topic_key"),
            taxonomy_version_id=_optional_int(data.get("taxonomy_version_id")),
            reason=data.get("reason"),
        )
        return jsonify(result), 200
    except (TypeError, ValueError):
        return api_error("INVALID_TAXONOMY_VERSION_ID", "taxonomy_version_id 必須是整數", 400)
    except recovery.RecoveryError as exc:
        return _recovery_error(exc)


@ai_admin_bp.post("/unassigned/answers/<int:answer_id>/retry")
def retry_failed_answer(answer_id):
    """零片段失敗的上傳回答（failed 分頁 target=answer）重新分析。
    Body（選填）: {"topic_key": "...", "taxonomy_version_id": ..., "reason": "..."}；
    不帶 topic_key 時沿用這筆回答原本的主題。"""
    admin, failure = _admin_or_error()
    if failure:
        return failure
    data = request.get_json(silent=True) or {}
    try:
        return jsonify(recovery.retry_failed_answer(
            answer_id, admin.admin_id, topic_key=data.get("topic_key") or None,
            taxonomy_version_id=_optional_int(data.get("taxonomy_version_id")),
            reason=data.get("reason"),
        )), 200
    except (TypeError, ValueError):
        return api_error("INVALID_TAXONOMY_VERSION_ID", "taxonomy_version_id 必須是整數", 400)
    except recovery.RecoveryError as exc:
        return _recovery_error(exc)


@ai_admin_bp.post("/unassigned/answers/<int:answer_id>/reroute")
def reroute_unassigned_answer(answer_id):
    admin, failure = _admin_or_error()
    if failure:
        return failure
    try:
        return jsonify(recovery.reroute_answer(answer_id, admin.admin_id)), 200
    except recovery.RecoveryError as exc:
        return _recovery_error(exc)


@ai_admin_bp.post("/classifications/<int:classification_id>/reclassify")
def reclassify_classification(classification_id):
    """legacy_other / failed：指定 Topic（或沿用原 Topic）重新分類整則回答。"""
    admin, failure = _admin_or_error()
    if failure:
        return failure
    data = request.get_json(silent=True) or {}
    try:
        result = recovery.reclassify_classification(
            classification_id, admin.admin_id,
            topic_key=data.get("topic_key") or None,
            taxonomy_version_id=_optional_int(data.get("taxonomy_version_id")),
            reason=data.get("reason"),
        )
        return jsonify(result), 200
    except (TypeError, ValueError):
        return api_error("INVALID_TAXONOMY_VERSION_ID", "taxonomy_version_id 必須是整數", 400)
    except recovery.RecoveryError as exc:
        return _recovery_error(exc)


@ai_admin_bp.post("/classifications/<int:classification_id>/retry")
def retry_failed_classification(classification_id):
    admin, failure = _admin_or_error()
    if failure:
        return failure
    try:
        return jsonify(recovery.retry_failed_classification(classification_id, admin.admin_id)), 200
    except recovery.RecoveryError as exc:
        return _recovery_error(exc)


@ai_admin_bp.post("/topics/<topic_key>/merge-into")
def merge_topic_into(topic_key):
    """Body: {"target_topic_key": "..."}：整個主題（自動主題 / 草稿主題）併入另一個
    主題，並用目標主題重新分類這個主題底下的資料。"""
    admin, failure = _admin_or_error()
    if failure:
        return failure
    data = request.get_json(silent=True) or {}
    try:
        return jsonify(recovery.merge_topic(topic_key, data.get("target_topic_key"), admin.admin_id)), 200
    except recovery.RecoveryError as exc:
        return _recovery_error(exc)


@ai_admin_bp.get("/system/health")
def system_health():
    """Admin：taxonomy bootstrap 狀態（失敗時間、安全的錯誤摘要、目前有沒有
    已發布的分類架構）。不回傳 stack trace；一般使用者無法存取。"""
    from services.system_health_service import taxonomy_bootstrap_health

    _, failure = _admin_or_error()
    if failure:
        return failure
    return jsonify({"taxonomy_bootstrap": taxonomy_bootstrap_health()})


@ai_admin_bp.get("/topics/<topic_key>/answers")
def topic_answers(topic_key):
    """這個主題底下的原始回答：來源欄位 / 題目、筆數、每個類別的回答範例。
    Query: per_category（預設 5，最多 200）、main_category + sub_category（只看某一類）。"""
    from services.topic_answers_service import TopicAnswersError, list_topic_answers

    _, failure = _admin_or_error()
    if failure:
        return failure
    try:
        per_category = int(request.args.get("per_category", 5))
    except ValueError:
        per_category = 5
    try:
        return jsonify(list_topic_answers(
            topic_key, per_category=per_category,
            main_category=request.args.get("main_category"),
            sub_category=request.args.get("sub_category"),
        ))
    except TopicAnswersError as exc:
        return api_error(exc.code, exc.message, exc.http_status)


@ai_admin_bp.get("/classifications/<int:classification_id>/attempts")
def classification_attempts(classification_id):
    _, failure = _admin_or_error()
    if failure:
        return failure
    try:
        return jsonify(recovery.attempt_history(classification_id))
    except recovery.RecoveryError as exc:
        return _recovery_error(exc)


# ── Admin Report 管理（lifecycle / regenerate / export）──────────────

def _report_error(exc):
    return api_error(exc.code, exc.message, exc.http_status)


def _parse_report_source(source_type, identifier):
    if source_type == "survey":
        try:
            return int(identifier), None
        except (TypeError, ValueError):
            raise report_service.ReportError("survey 的 identifier 必須是 template_id（整數）", 400, code="INVALID_IDENTIFIER")
    if source_type == "user_upload":
        return None, identifier
    raise report_service.ReportError("source_type 只能是 survey 或 user_upload", 400, code="INVALID_SOURCE_TYPE")


@ai_admin_bp.get("/reports")
def admin_list_reports():
    _, failure = _admin_or_error()
    if failure:
        return failure
    return jsonify(report_service.admin_list_report_units(
        page=request.args.get("page", 1, type=int),
        page_size=request.args.get("page_size", 20, type=int),
        only_needs_regeneration=request.args.get("needs_regeneration") == "true",
    ))


@ai_admin_bp.get("/reports/<source_type>/<identifier>")
def admin_report_unit(source_type, identifier):
    _, failure = _admin_or_error()
    if failure:
        return failure
    try:
        template_id, upload_batch_id = _parse_report_source(source_type, identifier)
        return jsonify(report_service.admin_unit_detail(source_type, template_id, upload_batch_id))
    except report_service.ReportError as exc:
        return _report_error(exc)


@ai_admin_bp.post("/reports/<source_type>/<identifier>/generate")
def admin_generate_report(source_type, identifier):
    admin, failure = _admin_or_error()
    if failure:
        return failure
    try:
        template_id, upload_batch_id = _parse_report_source(source_type, identifier)
        report = report_service.admin_generate_report(
            source_type, admin.admin_id, template_id=template_id, upload_batch_id=upload_batch_id,
        )
    except report_service.ReportError as exc:
        return _report_error(exc)
    if report.status != "completed":
        explained = explain_failure(report.error_detail)
        return api_error(
            "REPORT_GENERATION_FAILED",
            f"報告產生失敗：{explained['message'] if explained else '未知原因'}", 500,
            report=report.to_dict(), failure=explained,
        )
    return jsonify({"report": report.to_dict()}), 201


@ai_admin_bp.get("/reports/detail/<int:report_id>")
def admin_report_detail(report_id):
    _, failure = _admin_or_error()
    if failure:
        return failure
    try:
        return jsonify(report_service.admin_report_detail(report_id))
    except report_service.ReportError as exc:
        return _report_error(exc)


@ai_admin_bp.get("/reports/detail/<int:report_id>/export")
def admin_export_report(report_id):
    from urllib.parse import quote
    from flask import Response

    _, failure = _admin_or_error()
    if failure:
        return failure
    fmt = request.args.get("format", "xlsx")
    try:
        data, title = report_service.admin_export_report(report_id, fmt)
    except report_service.ReportError as exc:
        return _report_error(exc)
    mimetype = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if fmt == "xlsx"
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    filename = quote(f"{title}.{fmt}")
    return Response(data, mimetype=mimetype, headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
    })


# ── 開放式分類：新類別候選 ─────────────────────────────────────────

@ai_admin_bp.get("/new-categories")
def list_new_categories():
    _, failure = _admin_or_error()
    if failure:
        return failure
    return jsonify(new_category_service.list_candidates(request.args.get("topic") or None))


@ai_admin_bp.post("/new-categories/adopt")
def adopt_new_category():
    """一鍵採用：加入分類架構、發布、這一組回答全部確認（見 new_category_service.adopt）。
    Body: {topic_key, main_category, sub_category, definition?}
    回應 201：{published, taxonomy_version, category, confirmed_ids, confirmed_count, skipped, message}
    409 DRAFT_IN_PROGRESS：這個主題有尚未發布的草稿，要先發布或刪除。"""
    admin, failure = _admin_or_error()
    if failure:
        return failure
    data = request.get_json(silent=True) or {}
    try:
        result = new_category_service.adopt(
            data.get("topic_key"), data.get("main_category"), data.get("sub_category"),
            admin.admin_id, definition=data.get("definition"),
        )
    except new_category_service.NewCategoryError as exc:
        return api_error(exc.code, exc.message, exc.http_status)
    return jsonify(result), 201


@ai_admin_bp.post("/new-categories/merge")
def merge_new_category():
    """Body: {topic_key, main_category, sub_category, target_sub_category}"""
    admin, failure = _admin_or_error()
    if failure:
        return failure
    data = request.get_json(silent=True) or {}
    try:
        result = new_category_service.merge(
            data.get("topic_key"), data.get("main_category"), data.get("sub_category"),
            data.get("target_sub_category"), admin.admin_id,
        )
    except new_category_service.NewCategoryError as exc:
        return api_error(exc.code, exc.message, exc.http_status)
    return jsonify(result), 200


@ai_admin_bp.get("/overview")
def overview():
    """AI 管理首頁的待辦彙整（見 services/admin_overview_service.py）。"""
    _, failure = _admin_or_error()
    if failure:
        return failure
    from services.admin_overview_service import build_overview

    return jsonify(build_overview()), 200


@ai_admin_bp.post("/classifications/auto-confirm")
def auto_confirm_existing():
    """把已經存在、符合自動通過條件但還在待審的結果補做自動通過
    （自動通過功能上線前分析的資料）。規則見 services/auto_confirm_service.py。
    Body: {dry_run?: bool = true}。預設只預覽筆數，dry_run=false 才寫入。"""
    admin, failure = _admin_or_error()
    if failure:
        return failure
    from services.auto_confirm_service import backfill_existing

    data = request.get_json(silent=True) or {}
    dry_run = data.get("dry_run", True) is not False
    return jsonify(backfill_existing(admin.admin_id, dry_run=dry_run)), 200


@ai_admin_bp.get("/taxonomy")
def taxonomy():
    _, failure = _admin_or_error()
    if failure:
        return failure
    topics = []
    for key, subcategories in SUBCATEGORY_METHODOLOGY.items():
        items = [
            {"sub_category": sub, **metadata}
            for sub, metadata in subcategories.items()
        ]
        topics.append({"prompt_key": key, "subcategories": items})
    return jsonify({"topics": topics})


@ai_admin_bp.post("/topics/<topic_key>/taxonomy/generate")
def generate_taxonomy(topic_key):
    """
    Phase C：Taxonomy Generation。輸入一批初始回答，由 AI 歸納出一份
    結構化 draft taxonomy（Taxonomy_Version.status=draft），交給
    Phase D 的 Admin Review 流程。

    請求 body：
        answer_texts (必填)：這批要拿來歸納的原始回答文字陣列。
        topic_title：Topic 不存在時必填；已存在時會被忽略。
        question_text：選填，問卷題目原文。
        global_instructions：選填，額外分析原則。
        reference_topic_keys：選填，從這些既有 Topic 的 published
            taxonomy 抽取少量格式範例 + citation 白名單（見
            services.taxonomy_generation_service.load_reference_material）。

    絕對不會發布：回傳的版本一律是 draft，不會 archive 任何既有
    published 版本，也不會讓 production classification 切換過去。
    """
    admin, failure = _admin_or_error()
    if failure:
        return failure

    payload = request.get_json(silent=True) or {}
    answer_texts = payload.get("answer_texts")
    if not isinstance(answer_texts, list) or not answer_texts:
        return jsonify({"error": "answer_texts is required and must be a non-empty array"}), 400

    reference_topic_keys = payload.get("reference_topic_keys") or []
    if not isinstance(reference_topic_keys, list):
        return jsonify({"error": "reference_topic_keys must be an array"}), 400

    reference_examples, reference_citations = load_reference_material(reference_topic_keys)

    try:
        version = generate_taxonomy_draft(
            topic_key=topic_key,
            answer_texts=answer_texts,
            topic_title=payload.get("topic_title"),
            question_text=payload.get("question_text"),
            global_instructions=payload.get("global_instructions"),
            reference_examples=reference_examples,
            reference_citations=reference_citations,
            created_by=admin.admin_id,
        )
    except ValueError as exc:
        # topic_key 不存在且未提供 topic_title
        return jsonify({"error": str(exc)}), 400
    except TaxonomyGenerationValidationError as exc:
        # Gemini 輸出不合法，或 answer_texts 批次超過安全上限，沒有任何 DB 寫入
        return jsonify({"error": str(exc)}), 422
    except taxo.TaxonomyVersionConflictError as exc:
        # version_number 撞號（併發生成），rollback 已在 service 層完成
        return jsonify({"error": str(exc)}), 409
    except TaxonomyGenerationError as exc:
        # Gemini 呼叫本身失敗（API 錯誤/逾時等），沒有任何 DB 寫入
        return jsonify({"error": str(exc)}), 502

    return jsonify({"taxonomy_version": version.to_dict(include_categories=True)}), 201


# ── Phase D：Admin Taxonomy Review / Edit / Publish ────────────────
#
# 這些路由一律透過 services/taxonomy_service.py（taxo 別名）操作
# Topic/Taxonomy_Version/Taxonomy_Category。


@ai_admin_bp.get("/taxonomy-topics")
def list_taxonomy_topics():
    """Admin Topic List：全部 Topic + 由版本資料推導出的狀態
    （no_taxonomy / draft / in_review / published / draft_and_published），
    不另存第二份 status。"""
    _, failure = _admin_or_error()
    if failure:
        return failure
    return jsonify({"topics": taxo.list_topics_with_status()})


@ai_admin_bp.get("/topics/<topic_key>/taxonomy/<int:version_id>")
def taxonomy_version_detail(topic_key, version_id):
    """單一 taxonomy version 的完整內容，含依 sort_order 排序的
    categories（每筆都回 source_raw_text，供 legacy v1 沒有結構化
    欄位時 Admin 參考用；不自動拆分或改寫）。"""
    _, failure = _admin_or_error()
    if failure:
        return failure
    version = taxo.get_taxonomy_version(topic_key, version_id)
    if version is None:
        return jsonify({"error": "taxonomy version not found"}), 404
    return jsonify({"taxonomy_version": version.to_dict(include_categories=True)})


@ai_admin_bp.put("/topics/<topic_key>/taxonomy/<int:version_id>/categories/<int:category_id>")
def update_taxonomy_category(topic_key, version_id, category_id):
    _, failure = _admin_or_error()
    if failure:
        return failure
    updates = request.get_json(silent=True) or {}
    try:
        category = taxo.update_category(topic_key, version_id, category_id, updates)
    except taxo.TaxonomyEditNotAllowedError as exc:
        return jsonify({"error": str(exc)}), 409
    except taxo.TaxonomyVersionConflictError as exc:
        return jsonify({"error": str(exc)}), 409
    except ValueError as exc:
        status = 404 if "not found" in str(exc) else 400
        return jsonify({"error": str(exc)}), status
    return jsonify({"category": category.to_dict()})


@ai_admin_bp.post("/topics/<topic_key>/taxonomy/<int:version_id>/categories")
def add_taxonomy_category(topic_key, version_id):
    _, failure = _admin_or_error()
    if failure:
        return failure
    data = request.get_json(silent=True) or {}
    try:
        category = taxo.add_category(topic_key, version_id, data)
    except taxo.TaxonomyEditNotAllowedError as exc:
        return jsonify({"error": str(exc)}), 409
    except taxo.TaxonomyVersionConflictError as exc:
        return jsonify({"error": str(exc)}), 409
    except ValueError as exc:
        status = 404 if "not found" in str(exc) else 400
        return jsonify({"error": str(exc)}), status
    return jsonify({"category": category.to_dict()}), 201


@ai_admin_bp.delete("/topics/<topic_key>/taxonomy/<int:version_id>/categories/<int:category_id>")
def delete_taxonomy_category(topic_key, version_id, category_id):
    _, failure = _admin_or_error()
    if failure:
        return failure
    try:
        taxo.delete_category(topic_key, version_id, category_id)
    except taxo.TaxonomyEditNotAllowedError as exc:
        return jsonify({"error": str(exc)}), 409
    except ValueError as exc:
        status = 404 if "not found" in str(exc) else 400
        return jsonify({"error": str(exc)}), status
    return jsonify({"deleted": True})


@ai_admin_bp.post("/topics/<topic_key>/taxonomy/<int:version_id>/categories/reorder")
def reorder_taxonomy_categories(topic_key, version_id):
    """Body: {"ordered_category_ids": [3, 1, 2, ...]}——前端不需要真的
    支援 drag-and-drop，上下移動只要把兩個 id 互換位置後，把目前完整
    的順序清單丟進來即可（見 services.taxonomy_service.reorder_categories
    的說明）。"""
    _, failure = _admin_or_error()
    if failure:
        return failure
    data = request.get_json(silent=True) or {}
    ordered_ids = data.get("ordered_category_ids")
    if not isinstance(ordered_ids, list) or not all(isinstance(i, int) for i in ordered_ids):
        return jsonify({"error": "ordered_category_ids must be an array of integers"}), 400
    try:
        categories = taxo.reorder_categories(topic_key, version_id, ordered_ids)
    except taxo.TaxonomyEditNotAllowedError as exc:
        return jsonify({"error": str(exc)}), 409
    except ValueError as exc:
        status = 404 if "not found" in str(exc) else 400
        return jsonify({"error": str(exc)}), status
    return jsonify({"categories": [c.to_dict() for c in categories]})


@ai_admin_bp.post("/topics/<topic_key>/taxonomy/<int:version_id>/clone")
def clone_taxonomy(topic_key, version_id):
    """複製任一版本（通常是 published）成一份新的 draft，供 Admin
    要修改正式 taxonomy時使用；原版本完全不受影響。"""
    admin, failure = _admin_or_error()
    if failure:
        return failure
    try:
        new_version = taxo.clone_taxonomy_version(topic_key, version_id, created_by=admin.admin_id)
    except taxo.TaxonomyVersionConflictError as exc:
        return jsonify({"error": str(exc)}), 409
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    return jsonify({"taxonomy_version": new_version.to_dict(include_categories=True)}), 201


@ai_admin_bp.post("/topics/<topic_key>/taxonomy/<int:version_id>/publish")
def publish_taxonomy(topic_key, version_id):
    """驗證通過才呼叫 services.taxonomy_service.publish_taxonomy_version()
    （同一 transaction：舊 published -> archived，新版 -> published）。
    production classification 下一次呼叫 get_published_taxonomy_version()
    立即讀到新版，這裡不維護任何第二份「目前 taxonomy id」欄位。"""
    admin, failure = _admin_or_error()
    if failure:
        return failure
    try:
        version = taxo.publish_taxonomy_version_with_validation(topic_key, version_id, admin_id=admin.admin_id)
    except taxo.TaxonomyPublishValidationError as exc:
        return api_error("TAXONOMY_PUBLISH_INVALID", str(exc), 422)
    except taxo.TaxonomyVersionConflictError as exc:
        return api_error("TAXONOMY_PUBLISH_CONFLICT", str(exc), 409)
    except ValueError as exc:
        return api_error("TAXONOMY_VERSION_NOT_FOUND", str(exc), 404)
    return jsonify({"taxonomy_version": version.to_dict(include_categories=True)})


@ai_admin_bp.post("/topics/<topic_key>/taxonomy/<int:version_id>/sandbox")
def sandbox_taxonomy_classification(topic_key, version_id):
    """
    Taxonomy-based Sandbox：用指定的 Taxonomy Version 試跑一批測試
    文字，回傳跟正式分類完全一致邏輯產生的結果，但不寫入任何
    Response_Classification / Uploaded_Answer / 其他正式資料（見
    services/taxonomy_sandbox_service.py 開頭的架構保證說明）。

    允許測試 archived 版本（歷史比較/問題重現用途），不在這裡擋，
    前端預設選單另外處理「不鼓勵但不禁止」的呈現方式。
    """
    _, failure = _admin_or_error()
    if failure:
        return failure

    data = request.get_json(silent=True) or {}
    answer_texts = data.get("answer_texts")

    if not isinstance(answer_texts, list) or not answer_texts:
        return jsonify({"error": "answer_texts is required and must be a non-empty array"}), 400

    try:
        result = run_sandbox_classification(topic_key, version_id, answer_texts)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    except SandboxValidationError as exc:
        return jsonify({"error": str(exc)}), 422
    except SandboxExecutionError as exc:
        return jsonify({"error": str(exc)}), 502

    return jsonify(result)


@ai_admin_bp.get("/topics/<topic_key>/taxonomy")
def list_topic_taxonomy_versions(topic_key):
    """
    列出這個 topic 的全部 Taxonomy_Version（含 archived），供 Admin
    Sandbox 的版本選擇清單使用（見
    services/taxonomy_service.list_versions_for_topic() 的說明：
    既有 taxonomy-topics 列表只給「目前 published」+「最新草稿」兩筆
    摘要，沒辦法列出 archived 版本）。不含 categories。
    """
    _, failure = _admin_or_error()
    if failure:
        return failure
    versions = taxo.list_versions_for_topic(topic_key)
    return jsonify({"versions": [v.to_dict() for v in versions]})


@ai_admin_bp.delete("/topics/<topic_key>/taxonomy/<int:version_id>")
def delete_taxonomy(topic_key, version_id):
    """
    刪除一個 draft 版本（含底下全部 category）。只有 draft 可刪，
    published/archived/in_review 一律 409；已被
    Response_Classification 引用的版本也一律 409（見
    services/taxonomy_service.delete_taxonomy_version() 的完整說明）。
    不做 version_number renumber，不影響同一 topic 底下其他版本。
    """
    _, failure = _admin_or_error()
    if failure:
        return failure
    try:
        taxo.delete_taxonomy_version(topic_key, version_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    except taxo.TaxonomyEditNotAllowedError as exc:
        return jsonify({"error": str(exc)}), 409
    return jsonify({"deleted": True})
