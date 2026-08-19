"""
Human Review API：
  GET  /api/classification/<id>/review                 取得 AI original + review state
  POST /api/classification/<id>/review/start            開始/取得 conversation
  POST /api/classification/<id>/review/message           User 傳送 review message
  POST /api/classification/<id>/review/confirm-original
  POST /api/classification/<id>/review/confirm-candidate
  POST /api/classification/<id>/review/exclude
  GET  /api/classification/<id>/review/history

沿用既有 routes/surveys/survey.py 的 verify_token()，不另建第二套
authentication。這裡只負責解析 request/組 HTTP response，實際業務
邏輯（ownership、conversation 讀寫、confirm/exclude 規則）全部在
services/review_service.py，不在這裡重複寫。
"""

from flask import Blueprint, jsonify, request

from routes.surveys.survey import verify_token
from services.review_service import ReviewError
from services import review_service

review_bp = Blueprint("classification_review", __name__)


def _require_auth(req):
    auth_user_id, auth_error = verify_token(req)
    if auth_error:
        return None, (jsonify({"error": "Unauthorized"}), 401)
    return auth_user_id, None


@review_bp.route("/api/classification/<int:classification_id>/review", methods=["GET"])
def get_review(classification_id):
    auth_user_id, err = _require_auth(request)
    if err:
        return err
    try:
        state = review_service.get_review_state(classification_id, auth_user_id)
        return jsonify(state), 200
    except ReviewError as e:
        return jsonify({"error": e.message}), e.http_status


@review_bp.route("/api/classification/<int:classification_id>/review/start", methods=["POST"])
def start_review(classification_id):
    auth_user_id, err = _require_auth(request)
    if err:
        return err
    try:
        review = review_service.start_review(classification_id, auth_user_id)
        return jsonify(review.to_dict(include_messages=True)), 200
    except ReviewError as e:
        return jsonify({"error": e.message}), e.http_status


@review_bp.route("/api/classification/<int:classification_id>/review/message", methods=["POST"])
def send_message(classification_id):
    auth_user_id, err = _require_auth(request)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    message_text = data.get("message")
    try:
        result = review_service.send_message(classification_id, auth_user_id, message_text)
        return jsonify(result), 201
    except ReviewError as e:
        return jsonify({"error": e.message}), e.http_status


@review_bp.route("/api/classification/<int:classification_id>/review/confirm-original", methods=["POST"])
def confirm_original(classification_id):
    auth_user_id, err = _require_auth(request)
    if err:
        return err
    try:
        classification = review_service.confirm_original(classification_id, auth_user_id)
        return jsonify(classification.to_dict()), 200
    except ReviewError as e:
        return jsonify({"error": e.message}), e.http_status


@review_bp.route("/api/classification/<int:classification_id>/review/confirm-candidate", methods=["POST"])
def confirm_candidate(classification_id):
    auth_user_id, err = _require_auth(request)
    if err:
        return err
    try:
        classification = review_service.confirm_candidate(classification_id, auth_user_id)
        return jsonify(classification.to_dict()), 200
    except ReviewError as e:
        return jsonify({"error": e.message}), e.http_status


@review_bp.route("/api/classification/<int:classification_id>/review/exclude", methods=["POST"])
def exclude_classification(classification_id):
    auth_user_id, err = _require_auth(request)
    if err:
        return err
    try:
        classification = review_service.exclude(classification_id, auth_user_id)
        return jsonify(classification.to_dict()), 200
    except ReviewError as e:
        return jsonify({"error": e.message}), e.http_status


@review_bp.route("/api/classification/<int:classification_id>/review/history", methods=["GET"])
def get_history(classification_id):
    auth_user_id, err = _require_auth(request)
    if err:
        return err
    try:
        history = review_service.get_history(classification_id, auth_user_id)
        return jsonify({"reviews": history}), 200
    except ReviewError as e:
        return jsonify({"error": e.message}), e.http_status
