import json
import logging
import os
import threading
import traceback
import uuid
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request, url_for

from routes.surveys.survey import verify_token
from services.ppt_survey_ai_service import (
    PptSurveyAiError,
    generate_survey_from_material,
    revise_survey_with_ai,
    validate_upload,
)


logger = logging.getLogger(__name__)
ppt_survey_ai_bp = Blueprint("ppt_survey_ai", __name__)

TASK_TTL_HOURS = int(os.getenv("PPT_SURVEY_TASK_TTL_HOURS", "2"))
TASKS = {}
TASK_LOCK = threading.Lock()


def _now():
    return datetime.now(timezone.utc)


def _debug_errors_enabled():
    return os.getenv("PPT_SURVEY_DEBUG_ERRORS", "").lower() in {"1", "true", "yes", "on"}


def _require_auth():
    user_id, auth_error = verify_token(request)
    if auth_error:
        logger.warning("PPT survey AI request rejected: missing or invalid auth token")
        return None, (jsonify({"error": "請先登入後再使用 AI 問卷功能。"}), 401)
    return user_id, None


def _serialize_task(task):
    payload = {
        "task_id": task["task_id"],
        "status": task["status"],
        "message": task.get("message") or "",
        "created_at": task["created_at"].isoformat(),
        "updated_at": task["updated_at"].isoformat(),
    }
    if task.get("draft") is not None:
        payload["draft"] = task["draft"]
    if task.get("error"):
        payload["error"] = task["error"]
    if task.get("error_type"):
        payload["error_type"] = task["error_type"]
    if task.get("traceback") and _debug_errors_enabled():
        payload["traceback"] = task["traceback"]
    return payload


def _set_task(task_id, **updates):
    with TASK_LOCK:
        task = TASKS.get(task_id)
        if not task:
            return
        task.update(updates)
        task["updated_at"] = _now()


def _cleanup_tasks():
    expires_before = _now() - timedelta(hours=TASK_TTL_HOURS)
    with TASK_LOCK:
        expired_ids = [
            task_id
            for task_id, task in TASKS.items()
            if task.get("updated_at", task["created_at"]) < expires_before
        ]
        for task_id in expired_ids:
            TASKS.pop(task_id, None)
    if expired_ids:
        logger.info("Cleaned up expired PPT survey tasks: count=%s", len(expired_ids))


def _create_task(user_id, filename, file_size):
    task_id = uuid.uuid4().hex
    now = _now()
    task = {
        "task_id": task_id,
        "user_id": user_id,
        "filename": filename,
        "file_size": file_size,
        "status": "queued",
        "message": "任務已建立，等待背景處理。",
        "draft": None,
        "error": None,
        "error_type": None,
        "traceback": None,
        "created_at": now,
        "updated_at": now,
    }
    with TASK_LOCK:
        TASKS[task_id] = task
    return task


def _start_generation_thread(task_id, user_id, filename, file_bytes, config):
    worker = threading.Thread(
        target=_run_generation_task,
        args=(task_id, user_id, filename, file_bytes, config),
        name=f"ppt-survey-ai-{task_id[:8]}",
        daemon=True,
    )
    worker.start()
    return worker


def _run_generation_task(task_id, user_id, filename, file_bytes, config):
    logger.info(
        "PPT survey background task started: task_id=%s user_id=%s filename=%s size=%s",
        task_id,
        user_id,
        filename,
        len(file_bytes),
    )
    _set_task(task_id, status="processing", message="AI 正在分析檔案並產生問卷草稿。")
    try:
        draft = generate_survey_from_material(filename, file_bytes, config)
        _set_task(
            task_id,
            status="completed",
            message="問卷草稿已產生。",
            draft=draft,
        )
        logger.info(
            "PPT survey background task completed: task_id=%s user_id=%s questions=%s",
            task_id,
            user_id,
            len(draft.get("questions", [])),
        )
    except PptSurveyAiError as exc:
        tb = traceback.format_exc()
        logger.error(
            "PPT survey background task handled error: task_id=%s user_id=%s status=%s error=%s\n%s",
            task_id,
            user_id,
            exc.status_code,
            str(exc),
            tb,
        )
        _set_task(
            task_id,
            status="failed",
            message="問卷產生失敗。",
            error=str(exc),
            error_type=exc.__class__.__name__,
            status_code=exc.status_code,
            traceback=tb,
        )
    except Exception as exc:
        tb = traceback.format_exc()
        logger.error(
            "PPT survey background task unexpected failure: task_id=%s user_id=%s error=%s\n%s",
            task_id,
            user_id,
            str(exc),
            tb,
        )
        _set_task(
            task_id,
            status="failed",
            message="問卷產生失敗。",
            error=f"{exc.__class__.__name__}: {exc}",
            error_type=exc.__class__.__name__,
            status_code=500,
            traceback=tb,
        )


@ppt_survey_ai_bp.route("/api/ai/ppt-survey/generate", methods=["POST"])
def generate_ppt_survey():
    user_id, auth_response = _require_auth()
    if auth_response:
        return auth_response

    try:
        _cleanup_tasks()
        uploaded_file = request.files.get("file")
        filename, file_bytes = validate_upload(uploaded_file)
        raw_config = request.form.get("config") or "{}"
        try:
            config = json.loads(raw_config)
        except json.JSONDecodeError:
            logger.warning("Invalid PPT survey config JSON: %s", raw_config[:1000])
            config = {}

        task = _create_task(user_id=user_id, filename=filename, file_size=len(file_bytes))
        _set_task(task["task_id"], status="processing", message="AI 正在背景分析檔案並產生問卷草稿。")
        _start_generation_thread(task["task_id"], user_id, filename, file_bytes, config)

        logger.info(
            "PPT survey generation queued: task_id=%s user_id=%s filename=%s size=%s config_keys=%s",
            task["task_id"],
            user_id,
            filename,
            len(file_bytes),
            sorted(config.keys()) if isinstance(config, dict) else [],
        )
        return jsonify({
            "task_id": task["task_id"],
            "status": "processing",
            "message": "AI 正在背景分析檔案並產生問卷草稿。",
            "poll_interval_seconds": 3,
            "status_url": url_for("ppt_survey_ai.get_ppt_survey_task", task_id=task["task_id"]),
        }), 202
    except PptSurveyAiError as exc:
        tb = traceback.format_exc()
        logger.error(
            "PPT survey generation request rejected: user_id=%s status=%s error=%s\n%s",
            user_id,
            exc.status_code,
            str(exc),
            tb,
        )
        payload = {"error": str(exc), "error_type": exc.__class__.__name__}
        if _debug_errors_enabled():
            payload["traceback"] = tb
        return jsonify(payload), exc.status_code
    except Exception as exc:
        tb = traceback.format_exc()
        logger.error(
            "PPT survey generation request unexpected failure: user_id=%s error=%s\n%s",
            user_id,
            str(exc),
            tb,
        )
        payload = {
            "error": f"{exc.__class__.__name__}: {exc}",
            "error_type": exc.__class__.__name__,
        }
        if _debug_errors_enabled():
            payload["traceback"] = tb
        return jsonify(payload), 500


@ppt_survey_ai_bp.route("/api/ai/ppt-survey/tasks/<task_id>", methods=["GET"])
def get_ppt_survey_task(task_id):
    user_id, auth_response = _require_auth()
    if auth_response:
        return auth_response

    _cleanup_tasks()
    with TASK_LOCK:
        task = TASKS.get(task_id)
        if task:
            task = dict(task)

    if not task:
        return jsonify({"error": "找不到這個 AI 問卷任務，可能已過期，請重新上傳。"}), 404
    if task["user_id"] != user_id:
        logger.warning(
            "PPT survey task access denied: task_id=%s owner=%s requester=%s",
            task_id,
            task["user_id"],
            user_id,
        )
        return jsonify({"error": "你沒有權限讀取這個任務。"}), 403

    return jsonify(_serialize_task(task)), 200


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
        tb = traceback.format_exc()
        logger.error(
            "PPT survey revision handled error: user_id=%s status=%s error=%s\n%s",
            user_id,
            exc.status_code,
            str(exc),
            tb,
        )
        payload = {"error": str(exc), "error_type": exc.__class__.__name__}
        if _debug_errors_enabled():
            payload["traceback"] = tb
        return jsonify(payload), exc.status_code
    except Exception as exc:
        tb = traceback.format_exc()
        logger.error(
            "PPT survey revision unexpected failure: user_id=%s error=%s\n%s",
            user_id,
            str(exc),
            tb,
        )
        payload = {
            "error": f"{exc.__class__.__name__}: {exc}",
            "error_type": exc.__class__.__name__,
        }
        if _debug_errors_enabled():
            payload["traceback"] = tb
        return jsonify(payload), 500
