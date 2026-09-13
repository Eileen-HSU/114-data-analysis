import json
import logging

from flask import Blueprint, jsonify, request

from routes.surveys.survey import verify_token
from services.ppt_survey_ai_service import (
    PptSurveyAiError,
    generate_survey_from_material,
    revise_survey_with_ai,
    validate_upload,
)


ppt_survey_ai_bp = Blueprint("ppt_survey_ai", __name__)


def _require_auth():
    user_id, auth_error = verify_token(request)
    if auth_error:
        return None, (jsonify({"error": "請先登入後再使用 AI 生成問卷。"}), 401)
    return user_id, None


@ppt_survey_ai_bp.route("/api/ai/ppt-survey/generate", methods=["POST"])
def generate_ppt_survey():
    _, auth_response = _require_auth()
    if auth_response:
        return auth_response

    try:
        filename, file_bytes = validate_upload(request.files.get("file"))
        raw_config = request.form.get("config") or "{}"
        try:
            config = json.loads(raw_config)
        except json.JSONDecodeError:
            config = {}

        draft = generate_survey_from_material(filename, file_bytes, config)
        return jsonify({"draft": draft}), 200
    except PptSurveyAiError as exc:
        return jsonify({"error": str(exc)}), exc.status_code
    except Exception as exc:
        logging.exception("PPT/PDF survey generation failed: %s", exc)
        return jsonify({"error": "AI 生成問卷失敗，請稍後再試。"}), 500


@ppt_survey_ai_bp.route("/api/ai/ppt-survey/chat", methods=["POST"])
def revise_ppt_survey():
    _, auth_response = _require_auth()
    if auth_response:
        return auth_response

    data = request.get_json(silent=True) or {}
    try:
        draft = revise_survey_with_ai(data.get("draft"), data.get("message"))
        return jsonify({"draft": draft}), 200
    except PptSurveyAiError as exc:
        return jsonify({"error": str(exc)}), exc.status_code
    except Exception as exc:
        logging.exception("PPT/PDF survey revision failed: %s", exc)
        return jsonify({"error": "AI 修改問卷失敗，請稍後再試。"}), 500
