"""
系統錯誤紀錄：把伺服器錯誤集中存進 System_Error_Log，讓 Admin 在後台查看、
標記已處理或忽略（手冊 4.3 系統紀錄管理）。

錯誤從兩個地方進來：
    1. 非預期的 500：install() 註冊的 error handler 記錄完整（去敏）stack trace，
       回給前端的只有一般訊息和 error_id，不再把內部錯誤細節傳到瀏覽器。
    2. 程式裡任何 logging.error / logger.exception（例如登入錯誤、背景工作錯誤、
       AI 呼叫失敗）：install() 在 root logger 掛一個 handler 寫進資料庫。

設計重點：
    - 永遠不讓記錄錯誤這件事本身造成錯誤：任何失敗都吞掉（只回傳 None）。
    - 用獨立的資料庫連線寫入，不會跟著請求本身的 transaction 一起 commit 或 rollback
      （請求失敗被 rollback 時，錯誤紀錄還是要留下來）。
    - 同一種錯誤（來源、代碼、路徑相同，訊息除了數字以外相同）還沒處理時只累加次數，
      例如 AI 額度用完一分鐘發生 30 次，只會是一筆「發生 30 次」。
    - 所有文字都經過 safe_error.redact()：不會存下 API key、token、密碼。
"""

import hashlib
import logging
import re
import threading
import traceback
from datetime import timedelta

from sqlalchemy import func, insert, select, update

from extensions import db, taiwan_now
from system_status import ERROR_STATUS_IGNORED, ERROR_STATUS_OPEN, ERROR_STATUS_RESOLVED, System_Error_Log

logger = logging.getLogger(__name__)

CODE_SERVER_ERROR = "SERVER_ERROR"
CODE_LOGGED_ERROR = "LOGGED_ERROR"
_MESSAGE_LIMIT = 1000
_DETAIL_LIMIT = 8000
# 這些 logger 的錯誤不記錄：資料庫／HTTP 底層自己的訊息太吵，而且寫入失敗時可能遞迴
_IGNORED_LOGGER_PREFIXES = ("sqlalchemy", "werkzeug", "urllib3", "apscheduler", "httpx", "httpcore", __name__)
_state = threading.local()


class ErrorLogError(Exception):
    def __init__(self, code, message, http_status=400):
        super().__init__(message)
        self.code, self.message, self.http_status = code, message, http_status


# ── 寫入 ──────────────────────────────────────────────────────────

def _fingerprint(source, code, message, path) -> str:
    normalized = re.sub(r"\d+", "#", message or "")[:200]
    return hashlib.sha256(f"{source}|{code}|{path or ''}|{normalized}".encode("utf-8")).hexdigest()


def _derive_code(message) -> str:
    """AI 相關的錯誤用 failure_explainer 的代碼（例如 AI_QUOTA_EXCEEDED），其他用一般代碼。"""
    from services.failure_explainer import explain_failure

    explained = explain_failure(message) or {}
    code = explained.get("code")
    if code and code != "CLASSIFICATION_FAILED_UNKNOWN":
        return code
    return CODE_LOGGED_ERROR


def record_error(*, source, message, code=None, detail=None, path=None, method=None, status_code=None):
    """記錄一筆錯誤，回傳 error_id；任何失敗都回傳 None，不會往外拋。"""
    if getattr(_state, "busy", False):
        return None  # 記錄錯誤時又發生錯誤：不要遞迴
    _state.busy = True
    try:
        from services.safe_error import redact

        clean_message = " ".join(redact(str(message or "")).split())[:_MESSAGE_LIMIT] or "（沒有訊息）"
        clean_detail = redact(detail)[-_DETAIL_LIMIT:] if detail else None
        code = (code or _derive_code(clean_message))[:60]
        source = (source or "unknown")[:100]
        path = (path or None) and path[:300]
        fingerprint = _fingerprint(source, code, clean_message, path)
        table = System_Error_Log.__table__
        now = taiwan_now()
        with db.engine.begin() as conn:
            existing = conn.execute(
                select(table.c.error_id)
                .where(table.c.fingerprint == fingerprint, table.c.status == ERROR_STATUS_OPEN)
                .order_by(table.c.error_id.desc()).limit(1)
            ).first()
            if existing is not None:
                values = {"occurrence_count": table.c.occurrence_count + 1, "last_seen_at": now,
                          "message": clean_message}
                if clean_detail:
                    values["detail"] = clean_detail
                conn.execute(update(table).where(table.c.error_id == existing.error_id).values(**values))
                return existing.error_id
            result = conn.execute(insert(table).values(
                fingerprint=fingerprint, source=source, code=code, message=clean_message, detail=clean_detail,
                path=path, method=method, status_code=status_code, occurrence_count=1,
                first_seen_at=now, last_seen_at=now, status=ERROR_STATUS_OPEN,
            ))
            return result.inserted_primary_key[0]
    except Exception:  # noqa: BLE001 — 記錄錯誤絕對不能再造成錯誤
        return None
    finally:
        _state.busy = False


def _request_info():
    from flask import has_request_context, request

    if has_request_context():
        return request.path, request.method
    return None, None


class DatabaseErrorHandler(logging.Handler):
    """root logger 上的 handler：ERROR 以上的 log 寫進 System_Error_Log。"""

    def __init__(self, app):
        super().__init__(level=logging.ERROR)
        self.app = app

    def emit(self, record):
        if record.name.startswith(_IGNORED_LOGGER_PREFIXES) or getattr(record, "skip_error_log", False):
            return
        try:
            from flask import has_app_context

            detail = "".join(traceback.format_exception(*record.exc_info)) if record.exc_info else None
            path, method = _request_info()
            kwargs = dict(source=record.name or "root", message=record.getMessage(), detail=detail,
                          path=path, method=method)
            if has_app_context():
                record_error(**kwargs)
            else:
                with self.app.app_context():
                    record_error(**kwargs)
        except Exception:  # noqa: BLE001
            pass


class RedactingFormatter(logging.Formatter):
    """包住原本的 formatter：印到主機 log 的內容（含 stack trace）也去除 key、token、密碼。
    主機平台的 log 頁面是第三方服務，不該出現任何密鑰。"""

    def __init__(self, inner=None):
        super().__init__()
        self.inner = inner or logging.Formatter(logging.BASIC_FORMAT)

    def format(self, record):
        from services.safe_error import redact

        return redact(self.inner.format(record))


def install(app):
    """註冊錯誤處理：500 的去敏回應 + 寫入錯誤紀錄、root logger 的資料庫 handler。"""
    from flask import jsonify
    from werkzeug.exceptions import HTTPException

    root = logging.getLogger()
    if not root.handlers:
        # 沒有設定過 logging 時，先保留原本「印到主機 log」的行為，再加資料庫 handler
        logging.basicConfig(level=logging.INFO)
    for handler in root.handlers:
        if not isinstance(handler, DatabaseErrorHandler) and not isinstance(handler.formatter, RedactingFormatter):
            handler.setFormatter(RedactingFormatter(handler.formatter))
    if not any(isinstance(h, DatabaseErrorHandler) for h in root.handlers):
        root.addHandler(DatabaseErrorHandler(app))

    @app.errorhandler(Exception)
    def handle_exception(e):
        if isinstance(e, HTTPException):
            return jsonify({"error": e.description, "type": str(type(e)), "message": e.name}), e.code

        # 先把這個失敗請求寫到一半的資料 rollback（也盡快釋放資料庫鎖），再記錄錯誤
        try:
            db.session.rollback()
        except Exception:  # noqa: BLE001
            pass
        path, method = _request_info()
        error_id = record_error(
            source="request", code=CODE_SERVER_ERROR, message=f"{type(e).__name__}: {e}",
            detail=traceback.format_exc(), path=path, method=method, status_code=500,
        )
        # 主機 log 仍然看得到（但不要再被資料庫 handler 重複記一次）
        logger.error("Unhandled error on %s %s (error_id=%s)", method, path, error_id,
                     exc_info=e, extra={"skip_error_log": True})
        # 不把內部錯誤細節（SQL、主機名稱、檔案路徑）傳給瀏覽器
        message = "伺服器發生錯誤，請稍後再試" + (f"（錯誤編號 {error_id}）" if error_id else "")
        return jsonify({"error": message, "message": message, "type": "ServerError", "error_id": error_id}), 500

    return app


# ── 查詢與處理（Admin API）─────────────────────────────────────────

def list_errors(status=None, code=None, search=None, page=1, page_size=50) -> dict:
    query = System_Error_Log.query
    if status in (ERROR_STATUS_OPEN, ERROR_STATUS_RESOLVED, ERROR_STATUS_IGNORED):
        query = query.filter(System_Error_Log.status == status)
    if code:
        query = query.filter(System_Error_Log.code == code)
    if search:
        like = f"%{search.strip()[:100]}%"
        query = query.filter(db.or_(System_Error_Log.message.ilike(like), System_Error_Log.path.ilike(like)))
    total = query.count()
    rows = (query.order_by(System_Error_Log.last_seen_at.desc(), System_Error_Log.error_id.desc())
            .offset((page - 1) * page_size).limit(page_size).all())
    codes = [c for (c,) in db.session.query(System_Error_Log.code).distinct().order_by(System_Error_Log.code).all()]
    return {"errors": [r.to_dict() for r in rows], "total": total, "page": page, "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size, "codes": codes}


def get_error(error_id) -> dict:
    row = db.session.get(System_Error_Log, error_id)
    if row is None:
        raise ErrorLogError("ERROR_NOT_FOUND", "找不到這筆錯誤紀錄", 404)
    return row.to_dict(include_detail=True)


def set_status(error_id, admin_id, status, note=None) -> dict:
    if status not in (ERROR_STATUS_OPEN, ERROR_STATUS_RESOLVED, ERROR_STATUS_IGNORED):
        raise ErrorLogError("INVALID_STATUS", "狀態只能是 open、resolved 或 ignored", 400)
    row = db.session.get(System_Error_Log, error_id)
    if row is None:
        raise ErrorLogError("ERROR_NOT_FOUND", "找不到這筆錯誤紀錄", 404)
    row.status = status
    if status == ERROR_STATUS_OPEN:
        row.resolved_by_admin_id, row.resolved_at, row.resolution_note = None, None, None
    else:
        row.resolved_by_admin_id, row.resolved_at = admin_id, taiwan_now()
        row.resolution_note = (note or "").strip()[:2000] or None
    db.session.commit()
    return row.to_dict()


def summary() -> dict:
    """後台首頁／系統狀態用：還沒處理的錯誤數量、最近 24 小時發生次數、最常見的代碼。"""
    since = taiwan_now() - timedelta(hours=24)
    open_rows = System_Error_Log.query.filter(System_Error_Log.status == ERROR_STATUS_OPEN)
    by_code = (db.session.query(System_Error_Log.code, func.sum(System_Error_Log.occurrence_count))
               .filter(System_Error_Log.status == ERROR_STATUS_OPEN)
               .group_by(System_Error_Log.code).order_by(func.sum(System_Error_Log.occurrence_count).desc())
               .limit(5).all())
    return {
        "open": open_rows.count(),
        "open_last_24h": open_rows.filter(System_Error_Log.last_seen_at >= since).count(),
        "top_codes": [{"code": c, "occurrences": int(n or 0)} for c, n in by_code],
    }


def purge_old(days_closed=90, days_open=180) -> int:
    """已處理／忽略超過 90 天、未處理超過 180 天的紀錄刪掉（排程每天執行）。"""
    now = taiwan_now()
    deleted = System_Error_Log.query.filter(db.or_(
        db.and_(System_Error_Log.status != ERROR_STATUS_OPEN,
                System_Error_Log.last_seen_at < now - timedelta(days=days_closed)),
        System_Error_Log.last_seen_at < now - timedelta(days=days_open),
    )).delete(synchronize_session=False)
    db.session.commit()
    return deleted
