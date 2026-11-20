"""Google 帳號綁定與 Google 登入。

規則（見複評規格第 5 項）：
- 使用者先用密碼登入，再到個人資料頁自行綁定「email 完全相同」的 Google 帳號。
- 以 Google 的 sub（帳號唯一 ID）綁定，存 User.google_sub 並設唯一值；email 只用來比對。
- 綁定／解除需重新輸入密碼；已開啟雙因子驗證者，綁定時另需 email 驗證碼。
- Google 登入不需 email 驗證碼；未綁定的 Google 帳號一律拒絕，不自動建立帳號。
- Admin 帳號不開放 Google 登入（只查 User 表）。
- 綁定、解除、Google 登入都寄通知信（寄信失敗不影響操作）。
- 後端驗證 ID token 的簽章、aud（自己的 Client ID）、iss、效期；只需要 Client ID，不需要 Client Secret。
"""

import logging
import os
import time

import jwt
from flask import Blueprint, jsonify, request
from sqlalchemy import inspect, text
from werkzeug.security import check_password_hash

from extensions import db
from models import User, UserVerification
from services import rate_limit_service as rl

logger = logging.getLogger(__name__)
google_bp = Blueprint("google_auth", __name__)

DEFAULT_GOOGLE_CLIENT_ID = "18983228474-n1kofqobn8fjit1i0e5vuk51jit254f2.apps.googleusercontent.com"
GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}
MAX_CREDENTIAL_CHARS = 4096
UNBOUND_MESSAGE = "此 Google 帳號尚未綁定。請先用密碼登入後，到個人資料頁綁定 Google 帳號。"

_jwk_client = None


class GoogleTokenError(Exception):
    pass


def google_client_id():
    return (os.getenv("GOOGLE_CLIENT_ID") or DEFAULT_GOOGLE_CLIENT_ID).strip()


def google_login_enabled():
    return os.getenv("GOOGLE_LOGIN_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}


def _normalize_email(value):
    return str(value or "").strip().lower()


def verify_google_credential(credential):
    """驗證 Google Identity Services 回傳的 ID token，回傳 payload（dict）。"""
    global _jwk_client
    if not isinstance(credential, str) or not credential or len(credential) > MAX_CREDENTIAL_CHARS:
        raise GoogleTokenError("invalid credential")
    try:
        if _jwk_client is None:
            _jwk_client = jwt.PyJWKClient(GOOGLE_CERTS_URL, cache_keys=True, lifespan=3600)
        signing_key = _jwk_client.get_signing_key_from_jwt(credential)
        payload = jwt.decode(
            credential,
            signing_key.key,
            algorithms=["RS256"],
            audience=google_client_id(),
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            leeway=60,
        )
    except jwt.PyJWTError as exc:
        raise GoogleTokenError(str(exc)) from exc
    if payload.get("iss") not in GOOGLE_ISSUERS:
        raise GoogleTokenError("bad issuer")
    return payload


def _identity(payload):
    """從已驗證的 payload 取出 (sub, email)；email 必須已被 Google 驗證。"""
    sub = str(payload.get("sub") or "").strip()
    email = _normalize_email(payload.get("email"))
    verified = payload.get("email_verified") in (True, "true", "True")
    if not sub or not email or not verified:
        raise GoogleTokenError("email not verified")
    return sub[:64], email


# ---- google_sub 欄位（用 SQL 讀寫，不改 models.py，避免與其他修改衝突） ----

def _get_sub(user_id):
    return db.session.execute(
        text("SELECT google_sub FROM `User` WHERE user_id = :u"), {"u": user_id}
    ).scalar()


def _set_sub(user_id, sub):
    db.session.execute(
        text("UPDATE `User` SET google_sub = :s WHERE user_id = :u"), {"s": sub, "u": user_id}
    )


def _user_by_sub(sub):
    user_id = db.session.execute(
        text("SELECT user_id FROM `User` WHERE google_sub = :s"), {"s": sub}
    ).scalar()
    return db.session.get(User, user_id) if user_id is not None else None


def ensure_google_schema(app):
    """只在欄位／索引不存在時補上，不動既有資料。"""
    with app.app_context():
        try:
            insp = inspect(db.engine)
            cols = {c["name"] for c in insp.get_columns("User")}
            if "google_sub" not in cols:
                db.session.execute(text("ALTER TABLE `User` ADD COLUMN google_sub VARCHAR(64) NULL"))
                db.session.commit()
            indexes = {i["name"] for i in inspect(db.engine).get_indexes("User")}
            if "uq_user_google_sub" not in indexes:
                db.session.execute(text("CREATE UNIQUE INDEX uq_user_google_sub ON `User` (google_sub)"))
                db.session.commit()
        except Exception:
            db.session.rollback()
            logger.error("google schema check failed", exc_info=True)


# ---- 共用 ----

def _auth_user():
    """驗證 User token（沿用 profile 的 verify_token，含 token 失效檢查）。"""
    from routes.users.profile import verify_token
    user_id, error = verify_token(request)
    if error or not user_id:
        return None, (jsonify({"error": "Unauthorized"}), 401)
    user = db.session.get(User, user_id)
    if not user:
        return None, (jsonify({"error": "Unauthorized"}), 401)
    return user, None


def _too_many(wait):
    resp = jsonify({"error": f"嘗試次數過多，請約 {max(1, (int(wait) + 59) // 60)} 分鐘後再試", "retry_after": int(wait)})
    resp.status_code = 429
    resp.headers["Retry-After"] = str(int(wait))
    return resp


def _notify(user, subject, body):
    try:
        from routes.auth.pwd import send_email_via_brevo
        send_email_via_brevo(user.email, subject, body)
    except Exception:
        logger.warning("google notify email failed", exc_info=True)


def _now_text():
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime(time.time() + 8 * 3600)) + "（台灣時間）"


def _check_sensitive_attempt(user):
    key = f"google:user:{user.user_id}"
    ip = rl.client_ip()
    b1, w1 = rl.blocked("disable2fa_account", key)
    b2, w2 = rl.blocked("disable2fa_ip", ip)
    return key, ip, (b1 or b2), max(w1, w2)


def _record_sensitive_failure(key, ip):
    rl.record_failure("disable2fa_account", key)
    rl.record_failure("disable2fa_ip", ip)


def _consume_2fa_code(user, otp):
    """驗證並使用一組 2FA 驗證碼（由 /api/auth/2fa/send 寄出）。回傳錯誤訊息或 None。"""
    from routes.auth.pwd import taiwan_now
    record = UserVerification.query.filter_by(
        target_email=user.email, type="2FA", is_used=False
    ).order_by(UserVerification.created_at.desc()).first()
    if not record or record.expires_at < taiwan_now().replace(tzinfo=None):
        return "驗證碼不存在或已過期，請重新取得"
    if record.attempts >= 5:
        record.is_used = True
        db.session.commit()
        return "嘗試次數過多，請重新取得驗證碼"
    if not check_password_hash(record.code_hash, str(otp or "")):
        record.attempts += 1
        db.session.commit()
        return "驗證碼錯誤"
    record.is_used = True
    return None


# ---- 端點 ----

@google_bp.route("/api/auth/google/config", methods=["GET"])
def google_config():
    return jsonify({"enabled": google_login_enabled(), "client_id": google_client_id()}), 200


@google_bp.route("/api/auth/google/status", methods=["GET"])
def google_status():
    user, err = _auth_user()
    if err:
        return err
    return jsonify({"bound": bool(_get_sub(user.user_id)), "email": user.email}), 200


@google_bp.route("/api/auth/google/bind", methods=["POST"])
def google_bind():
    if not google_login_enabled():
        return jsonify({"error": "目前未開放 Google 登入"}), 403
    user, err = _auth_user()
    if err:
        return err
    data = request.get_json(silent=True) or {}

    key, ip, blocked, wait = _check_sensitive_attempt(user)
    if blocked:
        return _too_many(wait)

    if not check_password_hash(user.password_hash, str(data.get("password") or "")):
        _record_sensitive_failure(key, ip)
        return jsonify({"error": "密碼錯誤"}), 403

    if user.email_2fa_enabled:
        if not data.get("otp"):
            return jsonify({"error": "已開啟雙因子驗證，請先取得並輸入 Email 驗證碼", "require_otp": True}), 400
        otp_error = _consume_2fa_code(user, data.get("otp"))
        if otp_error:
            _record_sensitive_failure(key, ip)
            return jsonify({"error": otp_error, "require_otp": True}), 400

    try:
        sub, google_email = _identity(verify_google_credential(data.get("credential")))
    except GoogleTokenError:
        logger.info("google bind: invalid credential user_id=%s", user.user_id)
        return jsonify({"error": "Google 驗證失敗，請重新選擇 Google 帳號"}), 400

    if google_email != _normalize_email(user.email):
        return jsonify({"error": "只能綁定與本帳號 Email 完全相同的 Google 帳號"}), 400

    other = _user_by_sub(sub)
    if other and other.user_id != user.user_id:
        return jsonify({"error": "這個 Google 帳號已綁定其他帳號"}), 409

    try:
        _set_sub(user.user_id, sub)
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.error("google bind failed", exc_info=True)
        return jsonify({"error": "綁定失敗，請稍後再試"}), 500

    rl.reset("disable2fa_account", key)
    _notify(user, "【DataAnalysis】已綁定 Google 帳號",
            f"您的帳號已於 {_now_text()} 綁定 Google 帳號，之後可使用 Google 登入。\n"
            "使用 Google 登入時將略過本系統的 Email 驗證碼，建議為您的 Google 帳號開啟兩步驟驗證。\n"
            "若非本人操作，請立即登入並解除綁定、變更密碼。")
    return jsonify({"message": "已綁定 Google 帳號", "bound": True}), 200


@google_bp.route("/api/auth/google/unbind", methods=["POST"])
def google_unbind():
    user, err = _auth_user()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    key, ip, blocked, wait = _check_sensitive_attempt(user)
    if blocked:
        return _too_many(wait)
    if not check_password_hash(user.password_hash, str(data.get("password") or "")):
        _record_sensitive_failure(key, ip)
        return jsonify({"error": "密碼錯誤"}), 403
    if not _get_sub(user.user_id):
        return jsonify({"message": "尚未綁定 Google 帳號", "bound": False}), 200
    try:
        _set_sub(user.user_id, None)
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.error("google unbind failed", exc_info=True)
        return jsonify({"error": "解除綁定失敗，請稍後再試"}), 500
    rl.reset("disable2fa_account", key)
    _notify(user, "【DataAnalysis】已解除 Google 帳號綁定",
            f"您的帳號已於 {_now_text()} 解除 Google 帳號綁定，之後請使用密碼登入。\n若非本人操作，請立即變更密碼。")
    return jsonify({"message": "已解除綁定", "bound": False}), 200


@google_bp.route("/api/auth/google/login", methods=["POST"])
def google_login():
    if not google_login_enabled():
        return jsonify({"error": "目前未開放 Google 登入"}), 403
    ip = rl.client_ip()
    blocked, wait = rl.blocked("login_ip", ip)
    if blocked:
        return _too_many(wait)

    data = request.get_json(silent=True) or {}
    try:
        sub, google_email = _identity(verify_google_credential(data.get("credential")))
    except GoogleTokenError:
        rl.record_failure("login_ip", ip)
        return jsonify({"error": "Google 驗證失敗，請再試一次"}), 401

    account_key = f"google:{sub}"
    blocked, wait = rl.blocked("login_account", account_key)
    if blocked:
        return _too_many(wait)

    user = _user_by_sub(sub)
    if not user:
        rl.record_failure("login_ip", ip)
        rl.record_failure("login_account", account_key)
        return jsonify({"error": UNBOUND_MESSAGE, "code": "GOOGLE_NOT_BOUND"}), 403

    if _normalize_email(user.email) != google_email:
        try:
            _set_sub(user.user_id, None)
            db.session.commit()
        except Exception:
            db.session.rollback()
        return jsonify({"error": "帳號 Email 已變更，Google 綁定已解除，請用密碼登入後重新綁定", "code": "GOOGLE_NOT_BOUND"}), 403

    from routes.auth.login import build_token
    token = build_token(user.user_id)
    _notify(user, "【DataAnalysis】Google 登入通知",
            f"您的帳號於 {_now_text()} 使用 Google 登入。若非本人操作，請立即解除 Google 綁定並變更密碼。")
    return jsonify({
        "token": token,
        "account_type": "user",
        "user_id": user.user_id,
        "user_name": user.user_name,
        "email": user.email,
        "email_2fa_enabled": bool(user.email_2fa_enabled),
        "login_method": "google",
    }), 200


def init_google_auth(app):
    ensure_google_schema(app)
    app.register_blueprint(google_bp)
