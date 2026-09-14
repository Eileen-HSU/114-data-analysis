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


logger = logging.getLogger(__name__)
ppt_survey_ai_bp = Blueprint("ppt_survey_ai", __name__)


def _require_auth():
    user_id, auth_error = verify_token(request)
    if auth_error:
        logger.warning("PPT survey AI request rejected: missing or invalid auth token")
        return None, (jsonify({"error": "Please log in to generate surveys with AI."}), 401)
    return user_id, None


@ppt_survey_ai_bp.route("/api/ai/ppt-survey/generate", methods=["POST"])
def generate_ppt_survey():
    user_id, auth_response = _require_auth()
    if auth_response:
        return auth_response

    try:
        uploaded_file = request.files.get("file")
        filename, file_bytes = validate_upload(uploaded_file)
        raw_config = request.form.get("config") or "{}"
        try:
            config = json.loads(raw_config)
        except json.JSONDecodeError:
            logger.warning("Invalid PPT survey config JSON: %s", raw_config[:1000])
            config = {}

        logger.info(
            "PPT survey generation started: user_id=%s filename=%s size=%s config_keys=%s",
            user_id,
            filename,
            len(file_bytes),
            sorted(config.keys()) if isinstance(config, dict) else [],
        )
        draft = generate_survey_from_material(filename, file_bytes, config)
        logger.info(
            "PPT survey generation finished: user_id=%s filename=%s questions=%s",
            user_id,
            filename,
            len(draft.get("questions", [])),
        )
        return jsonify({"draft": draft}), 200
    except PptSurveyAiError as exc:
        logger.exception(
            "PPT survey generation handled error: user_id=%s status=%s message=%s",
            user_id,
            exc.status_code,
            str(exc),
        )
        return jsonify({"error": str(exc)}), exc.status_code
    except Exception as exc:
        logger.exception("PPT survey generation unexpected failure: user_id=%s", user_id)
        return jsonify({"error": "AI survey generation failed. Please try again later."}), 500


@ppt_survey_ai_bp.route("/api/ai/ppt-survey/chat", methods=["POST"])
def revise_ppt_survey():
    user_id, auth_response = _require_auth()
    if auth_response:
        return auth_response

    data = request.get_json(silent=True) or {}
    try:
        logger.info(
            "PPT survey revision started: user_id=%s message_chars=%s",
            user_id,
            len(str(data.get("message") or "")),
        )
        draft = revise_survey_with_ai(data.get("draft"), data.get("message"))
        logger.info(
            "PPT survey revision finished: user_id=%s questions=%s",
            user_id,
            len(draft.get("questions", [])),
        )
        return jsonify({"draft": draft}), 200
    except PptSurveyAiError as exc:
        logger.exception(
            "PPT survey revision handled error: user_id=%s status=%s message=%s",
            user_id,
            exc.status_code,
            str(exc),
        )
        return jsonify({"error": str(exc)}), exc.status_code
    except Exception as exc:
        logger.exception("PPT survey revision unexpected failure: user_id=%s", user_id)
        return jsonify({"error": "AI survey editing failed. Please try again later."}), 500
