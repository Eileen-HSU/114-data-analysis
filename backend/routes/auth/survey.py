import logging
import os
import random
import string
import jwt
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Blueprint, request, jsonify
from extensions import db
from models import Survey_Template, Survey_Response

survey_bp = Blueprint('survey', __name__)

def get_jwt_secret():
    secret = os.getenv("JWT_SECRET_KEY")
    if not secret:
        raise RuntimeError("JWT_SECRET_KEY 環境變數未設定")
    return secret


def verify_token(request):
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None, "Unauthorized"

    token = auth_header.split(" ")[1]
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=["HS256"])
        return payload.get("user_id"), None
    except jwt.ExpiredSignatureError:
        return None, "Token expired"
    except jwt.InvalidTokenError:
        return None, "Invalid token"


def generate_unique_access_code():
    """產生不重複的 5 碼邀請碼"""
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
        if not Survey_Template.query.filter_by(access_code=code).first():
            return code

def parse_deadline(deadline_at):
    if not deadline_at:
        return None
    try:
        normalized = str(deadline_at).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo("Asia/Taipei"))
        return parsed
    except ValueError:
        return None

def is_survey_expired(question_json):
    deadline = parse_deadline((question_json or {}).get("deadline_at"))
    return bool(deadline and datetime.now(ZoneInfo("Asia/Taipei")) > deadline)

@survey_bp.route('/api/surveys', methods=['POST'])
def create_survey():
    """建立新問卷"""
    auth_user_id, auth_error = verify_token(request)
    if auth_error:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    title     = data.get('title')
    questions = data.get('questions')
    deadline_at = data.get('deadline_at')

    if not title or not isinstance(questions, list) or not deadline_at:
        return jsonify({"error": "缺少問卷標題、題目資料或截止時間"}), 400

    deadline = parse_deadline(deadline_at)
    if not deadline:
        return jsonify({"error": "截止時間格式不正確"}), 400
    if deadline <= datetime.now(ZoneInfo("Asia/Taipei")):
        return jsonify({"error": "截止時間必須晚於現在"}), 400

    try:
        access_code = generate_unique_access_code()
        survey_content = {
            "description": data.get('description'),
            "identity_mode": data.get('identity_mode') if data.get('identity_mode') in ["anonymous", "identified"] else "anonymous",
            "deadline_at": deadline_at,
            "items":       questions,
        }
        new_template = Survey_Template(
            project_id    = data.get('project_id'),
            title         = title,
            access_code   = access_code,
            question_json = survey_content,
        )
        db.session.add(new_template)
        db.session.commit()
        return jsonify({
            "message":     "問卷建立成功",
            "access_code": access_code,
            "template_id": new_template.template_id,
        }), 201

    except Exception as e:
        logging.error(f"Survey creation failed: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({"error": "問卷建立失敗", "detail": str(e)}), 500  

@survey_bp.route('/api/surveys/<access_code>', methods=['GET'])
def get_survey(access_code):
    """用邀請碼取得公開填答用問卷內容"""
    try:
        survey = Survey_Template.query.filter_by(access_code=access_code.upper()).first()
        if not survey or not survey.is_active:
            return jsonify({"error": "找不到這份問卷"}), 404

        question_json = survey.question_json or {}
        if is_survey_expired(question_json):
            return jsonify({
                "error": "這份問卷已截止",
                "expired": True,
                "deadline_at": question_json.get("deadline_at"),
                "title": survey.title,
                "access_code": survey.access_code,
            }), 410

        return jsonify({
            "template_id": survey.template_id,
            "title": survey.title,
            "description": question_json.get("description") or "",
            "identity_mode": question_json.get("identity_mode") or "anonymous",
            "deadline_at": question_json.get("deadline_at"),
            "questions": question_json.get("items") or [],
            "access_code": survey.access_code,
            "created_at": survey.created_at.isoformat() if survey.created_at else None,
        }), 200

    except Exception as e:
        logging.error(f"Survey lookup failed: {e}", exc_info=True)
        return jsonify({"error": "讀取問卷失敗", "detail": str(e)}), 500

@survey_bp.route('/api/surveys/<access_code>/responses', methods=['POST'])
def submit_survey_response(access_code):
    """提交問卷回覆"""
    data = request.get_json(silent=True) or {}
    if not isinstance(data.get('answers'), dict):
        return jsonify({"error": "缺少問卷答案資料"}), 400

    try:
        survey = Survey_Template.query.filter_by(access_code=access_code.upper()).first()
        if not survey:
            return jsonify({"error": "找不到此邀請碼對應的問卷"}), 404

        question_json = survey.question_json or {}
        if is_survey_expired(question_json):
            return jsonify({
                "error": "這份問卷已截止",
                "expired": True,
                "deadline_at": question_json.get("deadline_at"),
            }), 410

        response = Survey_Response(
            template_id = survey.template_id,
            answer_json = {
                "answers": data.get('answers'),
                "respondent_identity": data.get('respondent_identity'),
            },
        )
        db.session.add(response)
        db.session.commit()
        return jsonify({
            "message":     "問卷送出成功",
            "response_id": response.response_id,
        }), 201

    except Exception as e:
        logging.error(f"Survey response submission failed: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({"error": "問卷送出失敗", "detail": str(e)}), 500
