import logging
import os
import random
import string
import jwt
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Blueprint, request, jsonify
from sqlalchemy.orm.attributes import flag_modified
from extensions import db
from models import Survey_Template, Survey_Response

survey_bp = Blueprint('survey', __name__)
TAIPEI_TZ = ZoneInfo("Asia/Taipei")
BASE36_ALPHABET = string.digits + string.ascii_uppercase

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
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5)).upper()
        if not Survey_Template.query.filter_by(access_code=code.upper()).first():
            return code


def encode_survey_short_code(template_id):
    template_id = int(template_id or 0)
    if template_id <= 0:
        return ""

    chars = []
    while template_id:
        template_id, remainder = divmod(template_id, 36)
        chars.append(BASE36_ALPHABET[remainder])
    return ''.join(reversed(chars))


def decode_survey_short_code(short_code):
    token = (short_code or "").strip().upper()
    if not token or any(char not in BASE36_ALPHABET for char in token):
        return None

    value = 0
    for char in token:
        value = value * 36 + BASE36_ALPHABET.index(char)
    return value or None


def find_survey_by_access_or_short_code(raw_code):
    token = (raw_code or "").strip().upper()
    if not token:
        return None

    survey = Survey_Template.query.filter_by(access_code=token).first()
    if survey:
        return survey

    template_id = decode_survey_short_code(token)
    if not template_id:
        return None
    return Survey_Template.query.filter_by(template_id=template_id).first()


def survey_short_code(survey):
    return encode_survey_short_code(survey.template_id)


def normalize_deadline(deadline):
    if not deadline:
        return None

    if isinstance(deadline, str):
        return parse_deadline(deadline)

    if deadline.tzinfo is None:
        return deadline.replace(tzinfo=TAIPEI_TZ)

    return deadline.astimezone(TAIPEI_TZ)


def parse_deadline(deadline_at):
    if not deadline_at:
        return None

    try:
        normalized = str(deadline_at).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        return normalize_deadline(parsed)
    except ValueError:
        return None

def deadline_to_iso(deadline):
    normalized = normalize_deadline(deadline)
    if not normalized:
        return None
    return normalized.isoformat()


def get_survey_deadline_at(survey, question_json=None):
    question_json = question_json if question_json is not None else (survey.question_json or {})
    return deadline_to_iso(survey.due_date) or question_json.get("deadline_at")


def is_survey_expired(question_json, due_date=None):
    deadline = normalize_deadline(due_date) or parse_deadline((question_json or {}).get("deadline_at"))
    return bool(deadline and datetime.now(TAIPEI_TZ) > deadline)

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
    identity_mode = data.get('identity_mode') if data.get('identity_mode') in ["anonymous", "identified"] else "anonymous"

    if not title or not isinstance(questions, list) or not deadline_at:
        return jsonify({"error": "缺少問卷標題、題目資料或截止時間"}), 400

    deadline = parse_deadline(deadline_at)
    if not deadline:
        return jsonify({"error": "截止時間格式不正確"}), 400
    if deadline <= datetime.now(TAIPEI_TZ):
        return jsonify({"error": "截止時間必須晚於現在"}), 400

    try:
        access_code = generate_unique_access_code()
        survey_content = {
            "description": data.get('description'),
            "identity_mode": identity_mode,
            "items":       questions,
        }
        new_template = Survey_Template(
            project_id    = data.get('project_id'),
            title         = title,
            access_code   = access_code.upper(),
            question_json = survey_content,
            user_id       = auth_user_id,
            due_date      = deadline,
            is_anonymous  = identity_mode == "anonymous",
        )
        db.session.add(new_template)
        db.session.commit()
        return jsonify({
            "message":     "問卷建立成功",
            "access_code": access_code.upper(),
            "short_code":  survey_short_code(new_template),
            "template_id": new_template.template_id,
        }), 201

    except Exception as e:
        logging.error(f"Survey creation failed: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({"error": "問卷建立失敗", "detail": str(e)}), 500  
    
@survey_bp.route('/api/surveys/mine', methods=['GET'])
def get_user_surveys():
    """取得目前登入用戶的所有問卷"""
    auth_user_id, auth_error = verify_token(request)
    if auth_error:
        return jsonify({"error": "Unauthorized"}), 401

    try:
        surveys = Survey_Template.query.filter_by(
            user_id=auth_user_id,
            is_active=True
        ).order_by(Survey_Template.created_at.desc()).all()

        result = []
        for survey in surveys:
            question_json = survey.question_json or {}
            response_count = Survey_Response.query.filter_by(
                template_id=survey.template_id
            ).count()
            result.append({
                "template_id":    survey.template_id,
                "title":          survey.title,
                "access_code":    survey.access_code,
                "short_code":     survey_short_code(survey),
                "created_at":     survey.created_at.isoformat() if survey.created_at else "",
                "deadline_at":    get_survey_deadline_at(survey, question_json),
                "response_count": response_count,
            })

        return jsonify(result), 200

    except Exception as e:
        logging.error(f"Get user surveys failed: {e}", exc_info=True)
        return jsonify({"error": "取得問卷失敗"}), 500

@survey_bp.route('/api/surveys/<access_code>', methods=['GET'])
def get_survey(access_code):
    """用邀請碼取得公開填答用問卷內容"""
    try:
        auth_user_id = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            auth_user_id, _ = verify_token(request)

        survey = find_survey_by_access_or_short_code(access_code)
        if not survey or not survey.is_active:
            return jsonify({"error": "找不到這份問卷"}), 404

        question_json = survey.question_json or {}
        deadline_at = get_survey_deadline_at(survey, question_json)
        identity_mode = question_json.get("identity_mode") or ("anonymous" if survey.is_anonymous else "identified")
        is_owner = auth_user_id is not None and survey.user_id == auth_user_id

        if is_survey_expired(question_json, survey.due_date) and not is_owner:
            return jsonify({
                "error": "這份問卷已截止",
                "expired": True,
                "deadline_at": deadline_at,
                "title": survey.title,
                "access_code": survey.access_code,
                "short_code": survey_short_code(survey),
            }), 410

        response_data = {
            "template_id": survey.template_id,
            "title": survey.title,
            "description": question_json.get("description") or "",
            "identity_mode": identity_mode,
            "deadline_at": deadline_at,
            "questions": question_json.get("items") or [],
            "access_code": survey.access_code,
            "short_code": survey_short_code(survey),
            "created_at": survey.created_at.isoformat() if survey.created_at else None,
        }

        if is_owner and is_survey_expired(question_json, survey.due_date):
            response_data["expired"] = True
        return jsonify(response_data), 200

    except Exception as e:
        logging.error(f"Survey lookup failed: {e}", exc_info=True)
        return jsonify({"error": "讀取問卷失敗", "detail": str(e)}), 500

@survey_bp.route('/api/surveys/<access_code>/deadline', methods=['PATCH'])
def update_survey_deadline(access_code):
    """更新問卷截止時間"""
    auth_user_id, auth_error = verify_token(request)
    if auth_error:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    deadline_at = data.get("deadline_at")
    deadline = parse_deadline(deadline_at)
    if not deadline:
        return jsonify({"error": "截止時間格式不正確"}), 400

    if deadline <= datetime.now(TAIPEI_TZ):
        return jsonify({"error": "截止時間必須晚於現在。"}), 400

    try:
        survey = find_survey_by_access_or_short_code(access_code)
        if not survey:
            return jsonify({"error": "找不到這份問卷"}), 404

        question_json = dict(survey.question_json or {})
        question_json.pop("deadline_at", None)
        survey.question_json = question_json
        flag_modified(survey, "question_json")
        survey.due_date = deadline
        db.session.commit()
        return jsonify({
            "message": "截止時間已更新",
            "access_code": survey.access_code,
            "short_code": survey_short_code(survey),
            "deadline_at": get_survey_deadline_at(survey, question_json),
        }), 200

    except Exception as e:
        logging.error(f"Survey deadline update failed: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({"error": "截止時間更新失敗", "detail": str(e)}), 500

@survey_bp.route('/api/surveys/<access_code>/responses', methods=['POST'])
def submit_survey_response(access_code):
    """提交問卷回覆"""
    data = request.get_json(silent=True) or {}
    if not isinstance(data.get('answers'), dict):
        return jsonify({"error": "缺少問卷答案資料"}), 400

    try:
        survey = find_survey_by_access_or_short_code(access_code)
        if not survey:
            return jsonify({"error": "找不到此邀請碼對應的問卷"}), 404

        question_json = survey.question_json or {}
        deadline_at = get_survey_deadline_at(survey, question_json)
        if is_survey_expired(question_json, survey.due_date):
            return jsonify({
                "error": "這份問卷已截止",
                "expired": True,
                "deadline_at": deadline_at,
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
    
@survey_bp.route('/api/surveys/<access_code>/responses', methods=['GET'])
def get_survey_responses(access_code):
    """取得問卷所有回覆（限問卷建立者）"""
    auth_user_id, auth_error = verify_token(request)
    if auth_error:
        return jsonify({"error": "Unauthorized"}), 401

    try:
        survey = find_survey_by_access_or_short_code(access_code)

        if not survey or not survey.is_active:
            return jsonify({"error": "找不到這份問卷"}), 404

        if survey.user_id != auth_user_id:
            return jsonify({"error": "無權限查看此問卷回覆"}), 403

        responses = Survey_Response.query.filter_by(
            template_id=survey.template_id
        ).order_by(Survey_Response.submitted_at.asc()).all()

        result = []
        for r in responses:
            result.append({
                "response_id":   r.response_id,
                "submitted_at":  r.submitted_at.isoformat() if r.submitted_at else None,
                "answers":       (r.answer_json or {}).get("answers", {}),
                "respondent_identity": (r.answer_json or {}).get("respondent_identity"),
            })

        return jsonify({
            "template_id":    survey.template_id,
            "title":          survey.title,
            "access_code":    survey.access_code,
            "short_code":     survey_short_code(survey),
            "response_count": len(result),
            "responses":      result,
        }), 200

    except Exception as e:
        logging.error(f"Get survey responses failed: {e}", exc_info=True)
        return jsonify({"error": "取得回覆失敗", "detail": str(e)}), 500
