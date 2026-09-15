from datetime import timedelta
import logging
import os
import secrets

import jwt
from flask import Blueprint, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db
from models import Admin, AdminVerification, User, UserVerification
from routes.auth.admin_guard import build_admin_pre_auth_token, build_admin_token
from routes.auth.pwd import send_password_email_via_resend, taiwan_now

login_bp = Blueprint("login", __name__)

_login_attempts = {}
MAX_LOGIN_ATTEMPTS = 5

_JWT_SECRET: str | None = None


def get_jwt_secret() -> str:
    global _JWT_SECRET
    if _JWT_SECRET is None:
        _JWT_SECRET = os.getenv("JWT_SECRET_KEY")
        if not _JWT_SECRET:
            raise RuntimeError("JWT_SECRET_KEY 環境變數未設定")
    return _JWT_SECRET


def build_token(user_id: int, role: str = "user", now=None) -> str:
    """User 專用 token。role 只是沿用資料庫裡的 User.role 值原樣帶出去
    （给前端顯示/相容舊程式碼用），實際的權限判斷一律看
    account_type=="admin"，不會因為某個 User.role 剛好是 "admin"
    字串就被當成管理員（對應需求 #7）。
    """
    if now is None:
        now = taiwan_now()
    exp_time = (now + timedelta(hours=24)).replace(tzinfo=None)
    return jwt.encode(
        {
            "account_type": "user",
            "user_id": user_id,
            "role": role,
            "exp": exp_time,
        },
        get_jwt_secret(),
        algorithm="HS256",
    )


def _invalidate_old_codes(email: str, otp_type: str):
    """將同一 email 所有未使用的舊驗證碼標記為已使用（不單獨 commit，由呼叫端統一 commit）"""
    UserVerification.query.filter_by(
        target_email=email,
        type=otp_type,
        is_used=False,
    ).update({"is_used": True}, synchronize_session=False)


def _invalidate_old_admin_codes(email: str, otp_type: str):
    AdminVerification.query.filter_by(
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

    attempts = _login_attempts.get(email, 0)
    if attempts >= MAX_LOGIN_ATTEMPTS:
        return jsonify({
            "error": "登入失敗次數過多，請重設密碼後再試",
            "require_password_reset": True,
            "email": email,
        }), 429

    try:
        # ── 先查 Admin，找到就不 fallback 查 User（需求 #2）──
        admin = Admin.query.filter_by(email=email).first()
        if admin:
            if not check_password_hash(admin.password_hash, password):
                _login_attempts[email] = attempts + 1
                remaining = MAX_LOGIN_ATTEMPTS - _login_attempts[email]
                if remaining > 0:
                    return jsonify({"error": f"帳號或密碼錯誤，剩餘 {remaining} 次機會"}), 401
                else:
                    return jsonify({"error": "登入失敗次數過多，請稍後再試"}), 429

            _login_attempts.pop(email, None)
            return _login_admin(admin)

        # ── Admin 找不到，才查 User，走原本 User 登入 ──
        user = User.query.filter_by(email=email).first()

        if not user or not check_password_hash(user.password_hash, password):
            _login_attempts[email] = attempts + 1
            remaining = MAX_LOGIN_ATTEMPTS - _login_attempts[email]
            if remaining > 0:
                return jsonify({"error": f"帳號或密碼錯誤，剩餘 {remaining} 次機會"}), 401
            else:
                return jsonify({"error": "登入失敗次數過多，請稍後再試"}), 429

        _login_attempts.pop(email, None)

        user_info = {
            "account_type": "user",
            "user_id": user.user_id,
            "user_name": user.user_name,
            "email": user.email,
            "role": user.role,
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
                send_password_email_via_resend(
                    user.email,
                    "DataAnalysis 登入驗證碼",
                    f"您好，\n\n您的登入驗證碼是：{otp}\n\n請在 10 分鐘內完成驗證。",
                )
            except Exception as email_error:
                logging.error(f"2FA email send failed during login: {email_error}", exc_info=True)
                verification.is_used = True
                user.email_2fa_enabled = False
                db.session.commit()
                token = build_token(user.user_id, role=user.role, now=now)
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

        token = build_token(user.user_id, role=user.role)
        return jsonify({"token": token, **user_info}), 200

    except Exception as e:
        db.session.rollback()
        logging.error(f"Login error: {e}", exc_info=True)
        return jsonify({"error": "登入失敗，請稍後再試"}), 500


def _login_admin(admin: Admin):
    """Admin 密碼驗證通過後的登入邏輯（含 2FA 分支），獨立成函式避免
    跟上面 User 的邏輯糾纏在一起，降低誤改到 User 流程的風險。
    """
    admin_info = {
        "account_type": "admin",
        "admin_id": admin.admin_id,
        "admin_name": admin.admin_name,
        "email": admin.email,
        "role": "admin",
        "email_2fa_enabled": admin.email_2fa_enabled,
    }

    if admin.email_2fa_enabled:
        now = taiwan_now()
        otp = str(secrets.randbelow(900000) + 100000)

        _invalidate_old_admin_codes(admin.email, "2FA")
        verification = AdminVerification(
            admin_id=admin.admin_id,
            type="2FA",
            code_hash=generate_password_hash(otp),
            expires_at=(now + timedelta(minutes=10)).replace(tzinfo=None),
            target_email=admin.email,
            is_used=False,
            attempts=0,
        )
        db.session.add(verification)
        db.session.commit()

        try:
            send_password_email_via_resend(
                admin.email,
                "DataAnalysis 管理員登入驗證碼",
                f"您好，\n\n您的管理員登入驗證碼是：{otp}\n\n請在 10 分鐘內完成驗證。",
            )
        except Exception as email_error:
            logging.error(f"Admin 2FA email send failed during login: {email_error}", exc_info=True)
            verification.is_used = True
            admin.email_2fa_enabled = False
            db.session.commit()
            token = build_admin_token(admin.admin_id, now=now)
            return jsonify({
                "token": token,
                **admin_info,
                "warning": "雙因子驗證信寄送失敗，已暫時關閉雙因子驗證。請登入後重新設定。",
            }), 200

        pre_auth_token = build_admin_pre_auth_token(admin.email, now=now)
        return jsonify({"require_2fa": True, "pre_auth_token": pre_auth_token, **admin_info}), 200

    token = build_admin_token(admin.admin_id)
    return jsonify({"token": token, **admin_info}), 200
