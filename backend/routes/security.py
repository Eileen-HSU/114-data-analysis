"""安全標頭相關：後端 API 安全標頭、CSP 違規回報（公開）、Admin 彙總、登出（token 失效）。"""

import hashlib
import json
import logging
import os
import threading
import time
from datetime import datetime
from urllib.parse import urlsplit

import jwt
from flask import Blueprint, jsonify, request
from sqlalchemy import text, update
from sqlalchemy.exc import IntegrityError

from extensions import db
from security_models import CspViolation
from routes.auth.admin_guard import verify_admin_token, get_jwt_secret
from routes.auth.token_service import bump_token_version, token_is_current

logger = logging.getLogger(__name__)
security_bp = Blueprint("security", __name__)

MAX_REPORT_BYTES = 10 * 1024      # 單筆回報上限 10KB
MAX_DISTINCT_VIOLATIONS = 500     # 不同違規種類上限，避免被灌爆
REPORT_LIMIT_PER_MIN = 30         # 每個 IP 每分鐘最多幾筆回報

_hits = {}
_hits_lock = threading.Lock()


def _report_allowed(ip, now=None):
    """公開端點的簡易頻率限制（記憶體；回報本身不重要，不需要跨 instance 精準）。"""
    now = now if now is not None else time.time()
    window = int(now // 60)
    with _hits_lock:
        for k in [k for k in _hits if k[1] != window]:
            _hits.pop(k, None)
        _hits[(ip, window)] = _hits.get((ip, window), 0) + 1
        return _hits[(ip, window)] <= REPORT_LIMIT_PER_MIN


# ---- 後端 API 安全標頭 ----

def add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    if request.is_secure or request.headers.get("X-Forwarded-Proto", "").lower() == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


# ---- CSP 回報 ----

def _host_path(url, keep_special=True):
    """只保留「網域＋路徑」，去掉查詢參數與 fragment。inline/eval/data 等特殊值照存。"""
    url = (url or "").strip()
    if not url:
        return ""
    if "://" not in url:
        return url[:60] if keep_special else ""
    parts = urlsplit(url)
    return f"{parts.netloc}{parts.path}"[:200]


def _normalize(report):
    """支援舊式 report-uri（{"csp-report": {...}}）與 Reporting API（{"type":..., "body": {...}}）。"""
    if not isinstance(report, dict):
        return None
    if "csp-report" in report and isinstance(report["csp-report"], dict):
        r = report["csp-report"]
        directive = r.get("effective-directive") or r.get("violated-directive")
        blocked, document = r.get("blocked-uri"), r.get("document-uri")
    elif isinstance(report.get("body"), dict):
        r = report["body"]
        directive = r.get("effectiveDirective") or r.get("violatedDirective")
        blocked, document = r.get("blockedURL") or r.get("blockedURI"), r.get("documentURL") or r.get("documentURI")
    else:
        return None
    if not isinstance(directive, str) or not directive.strip():
        return None
    directive = directive.split()[0][:40]
    blocked = _host_path(blocked if isinstance(blocked, str) else "") or "(none)"
    doc_path = urlsplit(document).path[:200] if isinstance(document, str) and "://" in document else ""
    return directive, blocked, doc_path


def record_violation(directive, blocked, doc_path, now=None):
    now = now or datetime.utcnow()
    key = hashlib.sha256(f"{directive}|{blocked}|{doc_path}".encode("utf-8")).hexdigest()[:40]
    upd = update(CspViolation).where(CspViolation.violation_key == key).values(
        hit_count=CspViolation.hit_count + 1, last_seen=now)
    with db.engine.begin() as conn:
        if conn.execute(upd).rowcount:
            return True
        if (conn.execute(text("SELECT COUNT(*) FROM Csp_Violation")).scalar() or 0) >= MAX_DISTINCT_VIOLATIONS:
            return False
        try:
            with conn.begin_nested():
                conn.execute(CspViolation.__table__.insert().values(
                    violation_key=key, directive=directive, blocked=blocked, document_path=doc_path,
                    hit_count=1, first_seen=now, last_seen=now))
        except IntegrityError:
            conn.execute(upd)
    return True


@security_bp.route("/api/csp-report", methods=["POST", "OPTIONS"])
def csp_report():
    if request.method == "OPTIONS":
        return "", 204
    if not _report_allowed(request.remote_addr or "unknown"):
        return "", 429
    if request.content_length is not None and request.content_length > MAX_REPORT_BYTES:
        return "", 413
    raw = request.get_data(cache=True)
    if len(raw) > MAX_REPORT_BYTES:
        return "", 413
    try:
        payload = json.loads(raw.decode("utf-8") or "null")
    except (ValueError, UnicodeDecodeError):
        return "", 204
    reports = payload if isinstance(payload, list) else [payload]
    for rep in reports[:10]:
        norm = _normalize(rep)
        if not norm:
            continue
        try:
            record_violation(*norm)
        except Exception:
            logger.error("csp report store failed", exc_info=True)
    return "", 204


@security_bp.route("/api/admin/security/csp", methods=["GET"])
def admin_csp_summary():
    admin_id, error = verify_admin_token(request)
    if error:
        return jsonify({"error": error}), (403 if error == "Admin access required" else 401)
    rows = CspViolation.query.order_by(CspViolation.last_seen.desc()).limit(50).all()
    total = db.session.query(db.func.coalesce(db.func.sum(CspViolation.hit_count), 0)).scalar() or 0
    mode = (os.getenv("CSP_MODE", "report-only") or "report-only").strip().lower()
    return jsonify({
        "mode": "enforce" if mode == "enforce" else "report-only",
        "total_reports": int(total),
        "distinct": db.session.query(CspViolation).count(),
        "items": [
            {
                "directive": r.directive,
                "blocked": r.blocked,
                "document_path": r.document_path,
                "count": r.hit_count,
                "first_seen": r.first_seen.isoformat() + "Z" if r.first_seen else None,
                "last_seen": r.last_seen.isoformat() + "Z" if r.last_seen else None,
            }
            for r in rows
        ],
    }), 200


# ---- 登出：token 版本號 +1，舊 token 立即失效 ----

@security_bp.route("/api/auth/logout", methods=["POST", "OPTIONS"])
def logout():
    if request.method == "OPTIONS":
        return "", 204
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return jsonify({"error": "Unauthorized"}), 401
    try:
        payload = jwt.decode(header.split(" ", 1)[1], get_jwt_secret(), algorithms=["HS256"])
    except jwt.InvalidTokenError:
        return jsonify({"message": "已登出"}), 200  # token 本來就無效，視為已登出
    user_id = payload.get("user_id")
    if payload.get("account_type") == "user" and user_id and token_is_current(payload):
        try:
            bump_token_version(user_id)
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.error("logout bump failed", exc_info=True)
            return jsonify({"error": "登出失敗，請稍後再試"}), 500
    return jsonify({"message": "已登出"}), 200


# ---- 初始化（由 app.py 呼叫一次） ----

def _ensure_schema(app):
    """User.token_version 欄位與 Csp_Violation 表：只在不存在時補上，不動既有資料。"""
    with app.app_context():
        if db.engine.dialect.name != "mysql":
            return
        try:
            has_col = db.session.execute(text(
                "SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() "
                "AND TABLE_NAME = 'User' AND COLUMN_NAME = 'token_version'")).scalar()
            if not has_col:
                db.session.execute(text(
                    "ALTER TABLE `User` ADD COLUMN `token_version` INT NOT NULL DEFAULT 0"))
            has_tbl = db.session.execute(text(
                "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() "
                "AND TABLE_NAME = 'Csp_Violation'")).scalar()
            if not has_tbl:
                db.metadata.create_all(bind=db.session.get_bind(), tables=[CspViolation.__table__])
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.error("security schema check failed", exc_info=True)


def init_security(app):
    _ensure_schema(app)
    app.register_blueprint(security_bp)
    app.after_request(add_security_headers)
