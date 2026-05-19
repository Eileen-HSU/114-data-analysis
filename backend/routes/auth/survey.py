import logging
import random
import string
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from extensions import db
from models import Survey_Template, Survey_Response

survey_bp = Blueprint('survey', __name__)

def generate_unique_access_code():
    """產生不重複的 5 碼邀請碼"""
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
        if not Survey_Template.query.filter_by(access_code=code).first():
            return code

@survey_bp.route('/api/surveys', methods=['POST'])
@jwt_required()
def create_survey():
    """建立新問卷"""
    data = request.get_json(silent=True) or {}
    title     = data.get('title')
    questions = data.get('questions')

    if not title or not isinstance(questions, list):
        return jsonify({"error": "缺少問卷標題或題目資料"}), 400

    try:
        access_code = generate_unique_access_code()
        survey_content = {
            "description": data.get('description'),
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

        response = Survey_Response(
            template_id = survey.template_id,
            answer_json = data.get('answers'),
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