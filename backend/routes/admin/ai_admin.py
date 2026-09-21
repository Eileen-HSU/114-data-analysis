"""Internal AI administration API.

All endpoints are deliberately read-only or candidate-only until a Golden Test
run marks the candidate as publishable.  Production classifications are never
changed by this blueprint.
"""

from flask import Blueprint, jsonify, request

from extensions import db
from models import Admin, Prompt_Template
from classification_models import Response_Classification, ALLOWED_REVIEW_STATUSES
from taxonomy import Taxonomy_Version
from routes.auth.admin_guard import verify_admin_token
from services.classify_v2 import _run_classification
from services.prompt_admin_service import (
    GOLDEN_TEST_SET,
    update_draft,
    test_draft_prompt,
    publish_prompt,
)
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


def _topic(row):
    return {
        "prompt_key": row.prompt_key,
        "production_status": "published" if row.live_content else "not_published",
        "candidate_status": "validated" if row.draft_validated else "needs_validation",
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@ai_admin_bp.get("/topics")
def list_topics():
    _, failure = _admin_or_error()
    if failure:
        return failure
    rows = Prompt_Template.query.order_by(Prompt_Template.prompt_key).all()
    return jsonify({"topics": [_topic(row) for row in rows]})


@ai_admin_bp.route("/topics/<prompt_key>", methods=["GET", "PUT"])
def candidate(prompt_key):
    _, failure = _admin_or_error()
    if failure:
        return failure
    row = Prompt_Template.query.get(prompt_key)
    if not row:
        return jsonify({"error": "Classification topic not found"}), 404
    if request.method == "GET":
        return jsonify(row.to_dict())

    payload = request.get_json(silent=True) or {}
    content = payload.get("draft_content")
    if not isinstance(content, str) or not content.strip():
        return jsonify({"error": "draft_content is required"}), 400
    # update_draft invalidates a previous validation result by design.
    return jsonify(update_draft(prompt_key, content))


@ai_admin_bp.post("/topics/<prompt_key>/sandbox")
def sandbox(prompt_key):
    _, failure = _admin_or_error()
    if failure:
        return failure
    row = Prompt_Template.query.get(prompt_key)
    if not row:
        return jsonify({"error": "Classification topic not found"}), 404
    payload = request.get_json(silent=True) or {}
    answer_text = (payload.get("answer_text") or "").strip()
    if not answer_text:
        return jsonify({"error": "answer_text is required"}), 400
    # _run_classification only calls the model; it never persists a production row.
    result = _run_classification(answer_text, row.draft_content, prompt_key)
    return jsonify({"result": result})


@ai_admin_bp.post("/topics/<prompt_key>/validate")
def validate_candidate(prompt_key):
    _, failure = _admin_or_error()
    if failure:
        return failure
    try:
        return jsonify(test_draft_prompt(prompt_key))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@ai_admin_bp.post("/topics/<prompt_key>/publish")
def publish_candidate(prompt_key):
    _, failure = _admin_or_error()
    if failure:
        return failure
    try:
        return jsonify(publish_prompt(prompt_key))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 409


@ai_admin_bp.get("/classifications")
def reviewed_classifications():
    """
    review_status 可選；topic 可選——不傳＝查全部（既有行為，不可改壞）。

    topic="__unassigned__" 是這次 Topic-centric IA 重構新增的特殊值
    （internal-only，前端 UI 不會顯示這個字串，只顯示「其他 / 未歸屬
    資料」），對應「不屬於任何目前 Topic 的分類結果」：
      - question_id IS NULL（schema 允許但目前寫入路徑不會產生，
        可能是更早期的歷史資料）
      - question_id == "other"（QUESTION_OTHER，routing 判斷不出來，
        不是一個真正的 Topic，Topic 表裡不會有這個 topic_key）
    這條路徑存在的目的：Topic-centric 首頁拿掉「全部 Topic 混看」的
    下拉選單後，這類資料不能因此變得完全不可達（見需求文件第五節）。
    """
    _, failure = _admin_or_error()
    if failure:
        return failure
    review_status = request.args.get("review_status")
    topic = request.args.get("topic")
    query = Response_Classification.query
    if review_status:
        if review_status not in ALLOWED_REVIEW_STATUSES:
            return jsonify({"error": "Invalid review_status"}), 400
        query = query.filter_by(review_status=review_status)
    if topic == "__unassigned__":
        query = query.filter(
            db.or_(
                Response_Classification.question_id.is_(None),
                Response_Classification.question_id == "other",
            )
        )
    elif topic:
        # 【修正】topic 是 Topic.topic_key（例如 "leadership_and_dept"），
        # 不是 Response_Classification.question_id（那是問卷題目 UUID，
        # 或外部上傳的欄位名稱/列號識別碼，兩者是完全不同的值域，直接
        # 比較必然查不到）。正確路徑是透過寫入分類結果時就一併保存的
        # taxonomy_version_id 反查 Taxonomy_Version.topic_key：
        #     Response_Classification.taxonomy_version_id
        #       -> Taxonomy_Version.version_id
        #       -> Taxonomy_Version.topic_key
        # 這個 join 天然同時涵蓋 survey 與 user_upload 兩種來源（兩邊
        # 寫入時都是透過同一個 _resolve_taxonomy_for_topic() 取得
        # taxonomy_version_id，不需要依 source_type 分開處理），也會
        # 涵蓋這個 topic 底下所有版本（draft/published/archived）產生
        # 的分類結果，不只是目前 published 的那一版。
        #
        # taxonomy_version_id 是 nullable（Phase B 之前的舊資料一律是
        # NULL）：這裡刻意不做任何回填或臆測式歸類，這些舊資料在
        # topic 篩選下就是查不到，跟 __unassigned__ 是兩件不同的事
        # （__unassigned__ 對應的是 question_id 本身的狀態，不是
        # taxonomy_version_id 缺失），不在這次修正的範圍內處理。
        query = query.join(
            Taxonomy_Version,
            Response_Classification.taxonomy_version_id == Taxonomy_Version.version_id,
        ).filter(Taxonomy_Version.topic_key == topic)
    if request.args.get("needs_human_review") == "true":
        query = query.filter_by(needs_human_review=True)
    rows = query.order_by(Response_Classification.created_at.desc()).limit(200).all()
    results = []
    for row in rows:
        item = row.to_dict()
        item["segment"] = row.answer_text[row.segment_start:row.segment_end]
        item["effective_result"] = {
            "main_category": row.final_main_category if row.review_status == "modified" else row.main_category,
            "sub_category": row.final_sub_category if row.review_status == "modified" else row.sub_category,
            "secondary_category": row.final_secondary_sub_category if row.review_status == "modified" else row.secondary_sub_category,
            "reasoning": row.final_reasoning if row.review_status == "modified" else row.reasoning,
        }
        results.append(item)
    return jsonify({"classifications": results})


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


@ai_admin_bp.get("/golden-tests")
def golden_tests():
    _, failure = _admin_or_error()
    if failure:
        return failure
    cases = []
    for prompt_key, items in GOLDEN_TEST_SET.items():
        cases.extend({"prompt_key": prompt_key, **item} for item in items)
    return jsonify({"cases": cases})


@ai_admin_bp.post("/topics/<topic_key>/taxonomy/generate")
def generate_taxonomy(topic_key):
    """
    Phase C：Taxonomy Generation。輸入一批初始回答，由 AI 歸納出一份
    結構化 draft taxonomy（Taxonomy_Version.status=draft），交給
    Phase D 的 Admin Review 流程。

    這個端點刻意跟上面 candidate（Prompt_Template draft）系列的
    /topics/<prompt_key>/... 路由分開：topic_key 這裡指的是
    Topic.topic_key（taxonomy 概念），不是 Prompt_Template.prompt_key
    （prompt 概念），兩者目前是同一套字串 key 空間但語意不同，沿用
    Phase A/B 已經定案的區分，不因為路由方便就混用。

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
# 這些路由跟上面 candidate（Prompt_Template draft）系列的
# /topics/<prompt_key>/... 完全分開資料流：這裡一律透過
# services/taxonomy_service.py（taxo 別名）操作 Topic/Taxonomy_Version/
# Taxonomy_Category，不會touchPrompt_Template，也不會被誤認成「修改
# Prompt 草稿」（需求文件第 2、15 節）。


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
    _, failure = _admin_or_error()
    if failure:
        return failure
    try:
        version = taxo.publish_taxonomy_version_with_validation(topic_key, version_id)
    except taxo.TaxonomyPublishValidationError as exc:
        return jsonify({"error": str(exc)}), 422
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
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
