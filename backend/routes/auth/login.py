from datetime import timedelta
import logging
import os
import secrets

import jwt
from flask import Blueprint, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db
from models import Admin, User, UserVerification
from routes.auth.admin_guard import build_admin_token
from routes.auth.pwd import send_email_via_brevo, taiwan_now
from services import rate_limit_service as rl

login_bp = Blueprint("login", __name__)

_JWT_SECRET: str | None = None


def get_jwt_secret() -> str:
    global _JWT_SECRET
    if _JWT_SECRET is None:
        _JWT_SECRET = os.getenv("JWT_SECRET_KEY")
        if not _JWT_SECRET:
            raise RuntimeError("JWT_SECRET_KEY 環境變數未設定")
    return _JWT_SECRET


def build_token(user_id: int, now=None) -> str:
    """User 專用 token。管理員權限一律看 account_type=="admin"（Admin 另有
    自己的帳號表與 token），User 沒有角色欄位。
    """
    if now is None:
        now = taiwan_now()
    exp_time = (now + timedelta(hours=24)).replace(tzinfo=None)
    return jwt.encode(
        {
            "account_type": "user",
            "user_id": user_id,
            "exp": exp_time,
        },
        get_jwt_secret(),
        algorithm="HS256",
    )


def _too_many(wait_seconds):
    minutes = max(1, (int(wait_seconds) + 59) // 60)
    resp = jsonify({"error": f"密碼已連續輸錯多次，為保護帳號暫時停止登入，約 {minutes} 分鐘後可再試。"})
    resp.status_code = 429
    resp.headers["Retry-After"] = str(int(wait_seconds))
    return resp


def _invalidate_old_codes(email: str, otp_type: str):
    """將同一 email 所有未使用的舊驗證碼標記為已使用（不單獨 commit，由呼叫端統一 commit）"""
    UserVerification.query.filter_by(
        target_email=email,
        type=otp_type,
        is_used=False,
    ).update({"is_used": True}, synchronize_session=False)


@login_bp.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"error": "請輸入電子郵件和密碼"}), 400

    ip = rl.client_ip()
    account_key = str(email).strip().lower()
    blocked_acct, wait_a = rl.blocked("login_account", account_key)
    blocked_ip, wait_i = rl.blocked("login_ip", ip)
    if blocked_acct or blocked_ip:
        return _too_many(max(wait_a, wait_i))

    try:
        
        admin = Admin.query.filter_by(email=email).first()
        if admin and check_password_hash(admin.password_hash, password):
            rl.reset("login_account", account_key)
            return _login_admin(admin)

        user = User.query.filter_by(email=email).first()

        if not user or not check_password_hash(user.password_hash, password):
            # 失敗才計數；訊息不顯示剩餘次數，也不透露帳號是否存在
            rl.record_failure("login_account", account_key)
            rl.record_failure("login_ip", ip)
            # 這次失敗剛好達到上限：馬上告知冷卻，不要等到下一次才跳出
            now_blocked_acct, wait_a = rl.blocked("login_account", account_key)
            now_blocked_ip, wait_i = rl.blocked("login_ip", ip)
            if now_blocked_acct or now_blocked_ip:
                return _too_many(max(wait_a, wait_i))
            return jsonify({"error": "帳號或密碼錯誤"}), 401

        # 登入成功只清除「帳號」計數，不清除「IP」計數
        rl.reset("login_account", account_key)

        user_info = {
            "account_type": "user",
            "user_id": user.user_id,
            "user_name": user.user_name,
            "email": user.email,
            "email_2fa_enabled": user.email_2fa_enabled,
        }

        if user.email_2fa_enabled:
            now = taiwan_now()  
            otp = str(secrets.randbelow(900000) + 100000)

            _invalidate_old_codes(user.email, "2FA")
            verification = UserVerification(
                user_id=user.user_id,
                type="2FA",
                code_hash=generate_password_hash(otp),
                expires_at=(now + timedelta(minutes=10)).replace(tzinfo=None),
                target_email=user.email,
                is_used=False,
                attempts=0,
            )
            db.session.add(verification)
            db.session.commit()  

            try:
                send_email_via_brevo(
                    user.email,
                    "DataAnalysis 登入驗證碼",
                    f"您好，\n\n您的登入驗證碼是：{otp}\n\n請在 10 分鐘內完成驗證。",
                )
            except Exception as email_error:
                logging.error(f"2FA email send failed during login: {email_error}", exc_info=True)
                verification.is_used = True
                user.email_2fa_enabled = False
                db.session.commit()
                token = build_token(user.user_id, now=now)
                return jsonify({
                    "token": token,
                    **user_info,
                    "warning": "雙因子驗證信寄送失敗，已暫時關閉雙因子驗證。請登入後重新設定。",
                }), 200

            pre_auth_exp = (now + timedelta(minutes=10)).replace(tzinfo=None)
            pre_auth_token = jwt.encode(
                {
                    "email": user.email,
                    "type": "pre_auth",
                    "account_type": "user",
                    "exp": pre_auth_exp,
                },
                get_jwt_secret(),
                algorithm="HS256",
            )
            return jsonify({"require_2fa": True, "pre_auth_token": pre_auth_token, **user_info}), 200

        token = build_token(user.user_id)
        return jsonify({"token": token, **user_info}), 200

    except Exception as e:
        db.session.rollback()
        logging.error(f"Login error: {e}", exc_info=True)
        return jsonify({"error": "登入失敗，請稍後再試"}), 500


def _login_admin(admin: Admin):
    """Admin 密碼驗證通過後直接登入（Admin 不使用雙因子驗證），獨立成函式
    避免跟上面 User 的邏輯糾纏在一起。"""
    token = build_admin_token(admin.admin_id)
    return jsonify({
        "token": token,
        "account_type": "admin",
        "admin_id": admin.admin_id,
        "admin_name": admin.admin_name,
        "email": admin.email,
        "role": "admin",
    }), 200


