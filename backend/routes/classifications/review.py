"""
Human Review API（Admin-only）：
  GET  /api/classification/<id>/review                 取得 AI original + review state
  POST /api/classification/<id>/review/start            開始/取得 conversation
  POST /api/classification/<id>/review/message           Admin 傳送 review message
  POST /api/classification/<id>/review/confirm-original
  POST /api/classification/<id>/review/confirm-candidate
  POST /api/classification/<id>/review/exclude
  GET  /api/classification/<id>/review/history

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
    body = {"error": e.message}
    body.update(e.extra)
    return jsonify(body), e.http_status


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


@review_bp.route("/api/classification/<int:classification_id>/review/exclude", methods=["POST"])
def exclude_classification(classification_id):
    admin_id, err = _require_admin(request)
    if err:
        return err
    try:
        classification = review_service.exclude(classification_id, admin_id)
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


@review_bp.route("/api/classification/review/exclude-legacy", methods=["POST"])
def exclude_legacy_pending():
    admin_id, err = _require_admin(request)
    if err:
        return err
    try:
        affected_count = review_service.exclude_legacy_pending_classifications(admin_id)
        return jsonify({"affected_count": affected_count}), 200
    except ReviewError as e:
        return _error_response(e)


