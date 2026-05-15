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
    password = data.get("password") or data.get("password_hash")

    if not email or not password:
        return jsonify({"error": "請輸入電子郵件和密碼"}), 400

    try:
        user = User.query.filter_by(email=email).first()
        if not user or not check_password_hash(user.password_hash, password):
            return jsonify({"error": "帳號或密碼錯誤"}), 401

        user_info = {
            "user_id": user.user_id,
            "user_name": user.user_name,
            "email": user.email,
        }

        if user.email_2fa_enabled:
            # 使用密碼學安全的亂數
            otp = str(secrets.randbelow(900000) + 100000)

            # 作廢所有舊的未使用驗證碼
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

            send_password_email_via_resend(
                user.email,
                "DataAnalysis 登入驗證碼",
                f"您好，\n\n您的登入驗證碼是：{otp}\n\n請在 10 分鐘內完成驗證。",
            )

            return jsonify({"require_2fa": True, **user_info}), 200

        token = build_token(user.user_id)
        return jsonify({"token": token, **user_info}), 200

    except Exception as e:
        db.session.rollback()
        import logging
        logging.error(f"Login error: {e}", exc_info=True)
        return jsonify({"error": "登入失敗，請稍後再試"}), 500