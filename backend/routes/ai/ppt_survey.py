import json
import logging
import os
import threading
import traceback
import uuid
from datetime import datetime, timedelta, timezone

from flask import Blueprint, current_app, jsonify, request, url_for

from extensions import db
from models import PPT_Survey_Task
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
ACTIVE_TASK_STATUSES = {"queued", "processing"}
TASKS = {}
TASK_LOCK = threading.Lock()


def _now():
    return datetime.now(timezone.utc)


def _debug_errors_enabled():
    return os.getenv("PPT_SURVEY_DEBUG_ERRORS", "").lower() in {"1", "true", "yes", "on"}


def _task_for_storage(task):
    stored = dict(task)
    for key in ("created_at", "updated_at"):
        value = stored.get(key)
        if isinstance(value, datetime):
            stored[key] = value.isoformat()
    return stored


def _parse_task_datetime(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return _now()


def _task_from_storage(payload):
    task = dict(payload or {})
    task["created_at"] = _parse_task_datetime(task.get("created_at"))
    task["updated_at"] = _parse_task_datetime(task.get("updated_at"))
    return task


def _task_from_row(row):
    if not row:
        return None
    return _task_from_storage({
        "task_id": row.task_id,
        "user_id": row.user_id,
        "filename": row.filename,
        "file_size": row.file_size,
        "status": row.status,
        "message": row.message,
        "draft": row.draft_json,
        "error": row.error,
        "error_type": row.error_type,
        "status_code": row.status_code,
        "traceback": row.traceback,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    })


def _write_task_file(task):
    row = db.session.get(PPT_Survey_Task, task["task_id"])
    if not row:
        row = PPT_Survey_Task(task_id=task["task_id"])
        db.session.add(row)
    row.user_id = task["user_id"]
    row.filename = task["filename"]
    row.file_size = task.get("file_size")
    row.status = task["status"]
    row.message = task.get("message")
    row.draft_json = task.get("draft")
    row.error = task.get("error")
    row.error_type = task.get("error_type")
    row.status_code = task.get("status_code")
    row.traceback = task.get("traceback")
    row.created_at = _parse_task_datetime(task.get("created_at"))
    row.updated_at = _parse_task_datetime(task.get("updated_at"))
    db.session.commit()


def _read_task_file(task_id):
    try:
        return _task_from_row(db.session.get(PPT_Survey_Task, task_id))
    except Exception:
        db.session.rollback()
        logger.exception("Failed to read PPT survey task from DB: task_id=%s", task_id)
        return None


def _delete_task_file(task_id):
    try:
        row = db.session.get(PPT_Survey_Task, task_id)
        if row:
            db.session.delete(row)
            db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("Failed to delete PPT survey task from DB: task_id=%s", task_id)


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
    try:
        with TASK_LOCK:
            task = _read_task_file(task_id)
            if not task:
                return
            task.update(updates)
            task["updated_at"] = _now()
            _write_task_file(task)
            TASKS[task_id] = task
    except Exception:
        db.session.rollback()
        logger.exception("Failed to update PPT survey task: task_id=%s", task_id)


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
        logger.info("Cleaned up expired PPT survey task cache entries: count=%s", len(expired_ids))


def _mark_stale_task_if_needed(task):
    if not task or task.get("status") not in ACTIVE_TASK_STATUSES:
        return task
    updated_at = task.get("updated_at", task.get("created_at"))
    if updated_at >= _now() - timedelta(hours=TASK_TTL_HOURS):
        return task
    _set_task(
        task["task_id"],
        status="failed",
        message="AI survey task expired. Please upload again.",
        error="AI survey task expired before completion. Please upload again.",
        error_type="TaskExpired",
        status_code=410,
    )
    return _read_task_file(task["task_id"]) or task


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
    try:
        with TASK_LOCK:
            _write_task_file(task)
            TASKS[task_id] = task
    except Exception:
        db.session.rollback()
        logger.exception("Failed to create PPT survey task: task_id=%s", task_id)
        raise
    return task


def _start_generation_thread(task_id, user_id, filename, file_bytes, config):
    app = current_app._get_current_object()
    worker = threading.Thread(
        target=_run_generation_task_safely,
        args=(app, task_id, user_id, filename, file_bytes, config),
        name=f"ppt-survey-ai-{task_id[:8]}",
        daemon=True,
    )
    worker.start()
    return worker


def _run_generation_task_safely(app, task_id, user_id, filename, file_bytes, config):
    with app.app_context():
        try:
            _run_generation_task_safely_in_context(task_id, user_id, filename, file_bytes, config)
        finally:
            db.session.remove()


def _run_generation_task_safely_in_context(task_id, user_id, filename, file_bytes, config):
    try:
        _run_generation_task(task_id, user_id, filename, file_bytes, config)
    except Exception as exc:
        tb = traceback.format_exc()
        logger.critical(
            "PPT survey worker escaped task handler: task_id=%s user_id=%s error=%s\n%s",
            task_id,
            user_id,
            str(exc),
            tb,
        )
        _set_task(
            task_id,
            status="failed",
            message="AI 問卷產生失敗。",
            error=f"{exc.__class__.__name__}: {exc}",
            error_type=exc.__class__.__name__,
            status_code=500,
            traceback=tb,
        )


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
        task = _read_task_file(task_id)
        if task:
            TASKS[task_id] = task
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

    task = _mark_stale_task_if_needed(task)
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
