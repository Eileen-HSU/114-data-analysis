from datetime import timedelta
import os
import random

import jwt
from flask import Blueprint, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db
from models import User, UserVerification
from routes.auth.pwd import send_password_email_via_resend, taiwan_now

two_factor_bp = Blueprint("two_factor", __name__)


def get_jwt_secret():
    return os.getenv("JWT_SECRET_KEY") or os.getenv("VERIFY") or "JWT_SECRET_KEY"


def issue_token(user_id):
    return jwt.encode(
        {"user_id": user_id, "exp": taiwan_now() + timedelta(hours=24)},
        get_jwt_secret(),
        algorithm="HS256",
    )


@two_factor_bp.route("/api/auth/2fa/send", methods=["POST"])
def send_2fa_code():
    data = request.get_json(silent=True) or {}
    email = data.get("email")
    if not email:
        return jsonify({"error": "請輸入電子郵件"}), 400

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"error": "找不到使用者"}), 404

    otp = str(random.randint(100000, 999999))
    verification = UserVerification(
        user_id=user.user_id,
        type="2FA",
        code_hash=generate_password_hash(otp),
        expires_at=taiwan_now() + timedelta(minutes=10),
        target_email=email,
        is_used=False,
    )

    try:
        db.session.add(verification)
        db.session.commit()

        send_password_email_via_resend(
            email,
            "DataAnalysis 兩步驟驗證碼",
            f"您好，\n\n您的驗證碼是：{otp}\n\n請在 10 分鐘內完成驗證。",
        )
        return jsonify({"message": "驗證碼已寄出"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@two_factor_bp.route("/api/auth/2fa/two-factor", methods=["POST"])
def enable_2fa():
    data = request.get_json(silent=True) or {}
    email = data.get("email")
    otp = data.get("otp")

    record = UserVerification.query.filter_by(
        target_email=email,
        type="2FA",
        is_used=False,
    ).order_by(UserVerification.created_at.desc()).first()

    if not record or not check_password_hash(record.code_hash, otp or ""):
        return jsonify({"error": "驗證碼錯誤"}), 400

    if record.expires_at < taiwan_now():
        return jsonify({"error": "驗證碼已過期"}), 400

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"error": "找不到使用者"}), 404

    user.email_2fa_enabled = True
    record.is_used = True
    db.session.commit()

    return jsonify({"message": "兩步驟驗證已啟用"}), 200


@two_factor_bp.route("/api/auth/2fa/login/two-factor", methods=["POST"])
def login_verify_2fa():
    data = request.get_json(silent=True) or {}
    email = data.get("email")
    otp = data.get("otp")

    record = UserVerification.query.filter_by(
        target_email=email,
        type="2FA",
        is_used=False,
    ).order_by(UserVerification.created_at.desc()).first()

    if not record or not check_password_hash(record.code_hash, otp or ""):
        return jsonify({"error": "驗證碼錯誤"}), 400

    if record.expires_at < taiwan_now():
        return jsonify({"error": "驗證碼已過期"}), 400

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"error": "找不到使用者"}), 404

    record.is_used = True
    db.session.commit()

    return jsonify({
        "token": issue_token(user.user_id),
        "user": {
            "user_id": user.user_id,
            "email": user.email,
            "user_name": user.user_name,
            "name": user.user_name,
        },
    }), 200


@two_factor_bp.route("/api/auth/2fa/disable", methods=["POST"])
def disable_2fa():
    data = request.get_json(silent=True) or {}
    email = data.get("email")

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"error": "找不到使用者"}), 404

    try:
        user.email_2fa_enabled = False
        db.session.commit()
        return jsonify({"message": "兩步驟驗證已停用"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500
