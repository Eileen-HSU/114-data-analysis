"""
Human Review API（Admin-only）：
  GET  /api/classification/<id>/review                 取得 AI original + review state
  POST /api/classification/<id>/review/start            開始/取得 conversation
  POST /api/classification/<id>/review/message           Admin 傳送 review message
  POST /api/classification/<id>/review/confirm-original
  POST /api/classification/<id>/review/confirm-candidate
  POST /api/classification/<id>/review/confirm-manual      直接從分類清單指定最終分類
  POST /api/classification/<id>/review/exclude
  GET  /api/classification/<id>/review/history
  POST /api/classification/<id>/review/reopen            confirmed/modified/excluded -> pending（+ 新 session）
  GET  /api/classification/<id>/review/audit              Admin 操作稽核紀錄
  POST /api/classification/review/batch-confirm           批次維持 AI 分類（單一 transaction、可重試）
  GET  /api/classification/review/exclude-legacy/preview  bulk exclude 預覽（eligible / skipped 原因）
  POST /api/classification/review/exclude-legacy          bulk exclude 執行（batch_id 冪等）

【Admin-only 定案】這裡改用 routes/auth/admin_guard.py 既有的
verify_admin_token()，跟 routes/admin/ai_admin.py 用同一套驗證邏輯
（account_type=="admin" 且 role=="admin"）。不再使用
routes/surveys/survey.py 的 verify_token()（User JWT），一般 User
的 token 呼叫這裡一律被拒絕——User token 沒有 account_type/role 這兩個
claim，會直接落入 "Admin access required" 分支回 403（token 本身若
過期/簽章錯誤則回 401，跟 verify_admin_token() 的錯誤語意一致）。

這裡只負責解析 request/組 HTTP response，實際業務邏輯（conversation
讀寫、confirm/exclude 規則、併發控制）全部在 services/review_service.py，
不在這裡重複寫。
"""

from flask import Blueprint, jsonify, request

from routes.auth.admin_guard import verify_admin_token
from services.review_service import ReviewError
from services import review_service

review_bp = Blueprint("classification_review", __name__)

# 跟 routes/admin/ai_admin.py 的 _TOKEN_ERROR_STATUS 用同一套判斷：
# token 本身有問題（不存在/過期/簽章錯）→ 401；token 有效但不是
# admin（例如一般 User 的 token）→ 403。
_TOKEN_ERROR_STATUS = {
    "Unauthorized": 401,
    "Token expired": 401,
    "Invalid token": 401,
}


def _require_admin(req):
    admin_id, error = verify_admin_token(req)
    if error:
        status = _TOKEN_ERROR_STATUS.get(error, 403)
        return None, (jsonify({"error": error}), status)
    return admin_id, None


def _error_response(e: ReviewError):
    body = {"code": e.code, "message": e.message, "error": e.message}
    body.update(e.extra)
    return jsonify(body), e.http_status


def _reason_from_body():
    data = request.get_json(silent=True) or {}
    reason = data.get("reason")
    return reason.strip()[:1000] if isinstance(reason, str) and reason.strip() else None


@review_bp.route("/api/classification/<int:classification_id>/review", methods=["GET"])
def get_review(classification_id):
    admin_id, err = _require_admin(request)
    if err:
        return err
    try:
        state = review_service.get_review_state(classification_id, admin_id)
        return jsonify(state), 200
    except ReviewError as e:
        return _error_response(e)


@review_bp.route("/api/classification/<int:classification_id>/review/start", methods=["POST"])
def start_review(classification_id):
    admin_id, err = _require_admin(request)
    if err:
        return err
    try:
        review = review_service.start_review(classification_id, admin_id)
        return jsonify(review.to_dict(include_messages=True)), 200
    except ReviewError as e:
        return _error_response(e)


@review_bp.route("/api/classification/<int:classification_id>/review/reopen", methods=["POST"])
def reopen_review(classification_id):
    admin_id, err = _require_admin(request)
    if err:
        return err
    try:
        review = review_service.reopen_review(classification_id, admin_id, reason=_reason_from_body())
        return jsonify(review.to_dict(include_messages=True)), 200
    except ReviewError as e:
        return _error_response(e)


@review_bp.route("/api/classification/<int:classification_id>/review/message", methods=["POST"])
def send_message(classification_id):
    admin_id, err = _require_admin(request)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    message_text = data.get("message")
    try:
        result = review_service.send_message(classification_id, admin_id, message_text)
        return jsonify(result), 201
    except ReviewError as e:
        return _error_response(e)


@review_bp.route("/api/classification/<int:classification_id>/review/confirm-original", methods=["POST"])
def confirm_original(classification_id):
    admin_id, err = _require_admin(request)
    if err:
        return err
    try:
        classification = review_service.confirm_original(classification_id, admin_id)
        return jsonify(classification.to_dict()), 200
    except ReviewError as e:
        return _error_response(e)


@review_bp.route("/api/classification/<int:classification_id>/review/confirm-candidate", methods=["POST"])
def confirm_candidate(classification_id):
    admin_id, err = _require_admin(request)
    if err:
        return err
    try:
        classification = review_service.confirm_candidate(classification_id, admin_id)
        return jsonify(classification.to_dict()), 200
    except ReviewError as e:
        return _error_response(e)


@review_bp.route("/api/classification/<int:classification_id>/review/confirm-manual", methods=["POST"])
def confirm_manual(classification_id):
    """Body: {"sub_category": "...", "secondary_sub_category": 選填, "reasoning": 選填}
    Admin 直接從合法分類清單指定最終分類（不需要先跟 AI 對話）。"""
    admin_id, err = _require_admin(request)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        classification = review_service.confirm_manual(
            classification_id, admin_id,
            sub_category=data.get("sub_category"),
            secondary_sub_category=data.get("secondary_sub_category") or None,
            reasoning=data.get("reasoning"),
        )
        return jsonify(classification.to_dict()), 200
    except ReviewError as e:
        return _error_response(e)


@review_bp.route("/api/classification/<int:classification_id>/review/exclude", methods=["POST"])
def exclude_classification(classification_id):
    admin_id, err = _require_admin(request)
    if err:
        return err
    try:
        classification = review_service.exclude(classification_id, admin_id, reason=_reason_from_body())
        return jsonify(classification.to_dict()), 200
    except ReviewError as e:
        return _error_response(e)


@review_bp.route("/api/classification/<int:classification_id>/review/history", methods=["GET"])
def get_history(classification_id):
    admin_id, err = _require_admin(request)
    if err:
        return err
    try:
        history = review_service.get_history(classification_id, admin_id)
        return jsonify({"reviews": history}), 200
    except ReviewError as e:
        return _error_response(e)


@review_bp.route("/api/classification/<int:classification_id>/review/audit", methods=["GET"])
def get_audit(classification_id):
    admin_id, err = _require_admin(request)
    if err:
        return err
    try:
        return jsonify({"audit": review_service.get_audit_history(classification_id)}), 200
    except ReviewError as e:
        return _error_response(e)


@review_bp.route("/api/classification/review/batch-confirm", methods=["POST"])
def batch_confirm():
    """Body: {"classification_ids": [...], "batch_id": "選填，重試時帶同一個"}"""
    admin_id, err = _require_admin(request)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        result = review_service.batch_confirm(data.get("classification_ids"), admin_id, batch_id=data.get("batch_id"))
        return jsonify(result), 200
    except ReviewError as e:
        return _error_response(e)


@review_bp.route("/api/classification/review/exclude-legacy/preview", methods=["GET"])
def exclude_legacy_preview():
    admin_id, err = _require_admin(request)
    if err:
        return err
    return jsonify(review_service.preview_legacy_bulk_exclude()), 200


@review_bp.route("/api/classification/review/exclude-legacy", methods=["POST"])
def exclude_legacy_pending():
    """Body（皆選填）: {"batch_id": "...", "expected_ids": [...]}
    回應保留 affected_count（向後相容），另外回傳 batch_id / affected_ids /
    skipped 明細。"""
    admin_id, err = _require_admin(request)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    expected_ids = data.get("expected_ids")
    if expected_ids is not None and not isinstance(expected_ids, list):
        return jsonify({"code": "INVALID_IDS", "message": "expected_ids 必須是陣列", "error": "expected_ids 必須是陣列"}), 400
    try:
        result = review_service.execute_legacy_bulk_exclude(
            admin_id, batch_id=data.get("batch_id"), expected_ids=expected_ids,
        )
        return jsonify(result), 200
    except ReviewError as e:
        return _error_response(e)
