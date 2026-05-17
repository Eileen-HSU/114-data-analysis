from datetime import timedelta
import os
import secrets
import jwt
from flask import Blueprint, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash
from extensions import db
from models import User, UserVerification
from routes.auth.pwd import send_password_email_via_resend, taiwan_now

login_bp = Blueprint("login", __name__)

# 登入失敗次數記錄（以 email 為 key）
_login_attempts = {}
MAX_LOGIN_ATTEMPTS = 5


def get_jwt_secret():
    secret = os.getenv("JWT_SECRET_KEY")
    if not secret:
        raise RuntimeError("JWT_SECRET_KEY 環境變數未設定")
    return secret


def build_token(user_id):
    return jwt.encode(
        {"user_id": user_id, "exp": taiwan_now() + timedelta(hours=24)},
        get_jwt_secret(),
        algorithm="HS256",
    )


def _invalidate_old_codes(email: str, otp_type: str):
    """將同一 email 所有未使用的舊驗證碼標記為已使用"""
    UserVerification.query.filter_by(
        target_email=email,
        type=otp_type,
        is_used=False,
    ).update({"is_used": True})


@login_bp.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    email = data.get("email")
    password = data.get("password")  # 移除 password_hash

    if not email or not password:
        return jsonify({"error": "請輸入電子郵件和密碼"}), 400

    # 暴力破解防護
    attempts = _login_attempts.get(email, 0)
    if attempts >= MAX_LOGIN_ATTEMPTS:
        return jsonify({"error": "登入失敗次數過多，請稍後再試"}), 429

    try:
        user = User.query.filter_by(email=email).first()

        if not user or not check_password_hash(user.password_hash, password):
            _login_attempts[email] = attempts + 1
            remaining = MAX_LOGIN_ATTEMPTS - _login_attempts[email]
            if remaining > 0:
                return jsonify({"error": f"帳號或密碼錯誤，剩餘 {remaining} 次機會"}), 401
            else:
                return jsonify({"error": "登入失敗次數過多，請稍後再試"}), 429

        # 登入成功，清除失敗計數
        _login_attempts.pop(email, None)

        user_info = {
            "user_id": user.user_id,
            "user_name": user.user_name,
            "email": user.email,
        }

        if user.email_2fa_enabled:
            otp = str(secrets.randbelow(900000) + 100000)
            _invalidate_old_codes(user.email, "2FA")
            verification = UserVerification(
                user_id=user.user_id,
                type="2FA",
                code_hash=generate_password_hash(otp),
                expires_at=taiwan_now() + timedelta(minutes=10),
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
                import logging
                logging.error(f"2FA email send failed during login: {email_error}", exc_info=True)
                verification.is_used = True
                user.email_2fa_enabled = False
                db.session.commit()
                token = build_token(user.user_id)
                return jsonify({
                    "token": token,
                    **user_info,
                    "warning": "雙因子驗證信寄送失敗，已暫時關閉雙因子驗證。請登入後重新設定。",
                }), 200

            pre_auth_token = jwt.encode({
                'email': user.email,
                'type': 'pre_auth',
                'exp': taiwan_now() + timedelta(minutes=10)
            }, get_jwt_secret(), algorithm="HS256")

            return jsonify({"require_2fa": True, "pre_auth_token": pre_auth_token, **user_info}), 200

        token = build_token(user.user_id)
        return jsonify({"token": token, **user_info}), 200

    except Exception as e:
        db.session.rollback()
        import logging
        logging.error(f"Login error: {e}", exc_info=True)
        return jsonify({"error": "登入失敗，請稍後再試"}), 500
