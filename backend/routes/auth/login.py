from datetime import timedelta
import os
import random

import jwt
from flask import Blueprint, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db
from models import User, UserVerification
from routes.auth.pwd import send_password_email_via_resend, taiwan_now

login_bp = Blueprint("login", __name__)


def get_jwt_secret():
    return os.getenv("JWT_SECRET_KEY") or os.getenv("VERIFY") or "JWT_SECRET_KEY"


def build_token(user_id):
    return jwt.encode(
        {"user_id": user_id, "exp": taiwan_now() + timedelta(hours=24)},
        get_jwt_secret(),
        algorithm="HS256",
    )


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
            otp = str(random.randint(100000, 999999))
            verification = UserVerification(
                user_id=user.user_id,
                type="2FA",
                code_hash=generate_password_hash(otp),
                expires_at=taiwan_now() + timedelta(minutes=10),
                target_email=user.email,
                is_used=False,
            )
            db.session.add(verification)
            db.session.commit()

            try:
                send_password_email_via_resend(
                    user.email,
                    "DataAnalysis login verification code",
                    f"Your login verification code is: {otp}\n\nThis code expires in 10 minutes.",
                )
            except Exception as email_error:
                print(f"2FA email failed: {email_error}")
                token = build_token(user.user_id)
                return jsonify({
                    "token": token,
                    "two_factor_email_failed": True,
                    **user_info,
                }), 200

            return jsonify({"require_2fa": True, **user_info}), 200

        token = build_token(user.user_id)
        return jsonify({"token": token, **user_info}), 200

    except Exception as e:
        db.session.rollback()
        print(f"Login Error: {e}")
        return jsonify({"error": "登入失敗，請稍後再試"}), 500
