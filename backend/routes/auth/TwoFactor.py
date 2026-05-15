from datetime import timedelta
import os
import secrets

import jwt
from flask import Blueprint, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db
from models import User, UserVerification
from routes.auth.pwd import send_password_email_via_resend, taiwan_now

two_factor_bp = Blueprint("two_factor", __name__)

# 暴力破解防護：OTP 最多嘗試次數
MAX_OTP_ATTEMPTS = 5


def get_jwt_secret():
    secret = os.getenv("JWT_SECRET_KEY")
    if not secret:
        raise RuntimeError("JWT_SECRET_KEY 環境變數未設定")
    return secret


def issue_token(user_id):
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


def _verify_otp(email: str, otp: str, otp_type: str):
    """
    驗證 OTP，回傳 (record, error_message, status_code)。
    成功時 error_message 為 None。
    """
    record = UserVerification.query.filter_by(
        target_email=email,
        type=otp_type,
        is_used=False,
    ).order_by(UserVerification.created_at.desc()).first()

    if not record:
        return None, "驗證碼不存在或已使用", 400

    # 先檢查過期，避免繼續計算 hash
    if record.expires_at < taiwan_now():
        return None, "驗證碼已過期", 400

    # 暴力破解防護
    if record.attempts >= MAX_OTP_ATTEMPTS:
        record.is_used = True
        db.session.commit()
        return None, "嘗試次數過多，請重新取得驗證碼", 429

    if not check_password_hash(record.code_hash, otp or ""):
        record.attempts += 1
        db.session.commit()
        remaining = MAX_OTP_ATTEMPTS - record.attempts
        return None, f"驗證碼錯誤，剩餘 {remaining} 次機會", 400

    return record, None, 200


@two_factor_bp.route("/api/auth/2fa/send", methods=["POST"])
def send_2fa_code():
    data = request.get_json(silent=True) or {}
    email = data.get("email")
    if not email:
        return jsonify({"error": "請輸入電子郵件"}), 400

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"error": "找不到使用者"}), 404

    # 使用密碼學安全的亂數
    otp = str(secrets.randbelow(900000) + 100000)

    try:
        # 作廢所有舊的未使用驗證碼，防止舊碼仍可登入
        _invalidate_old_codes(email, "2FA")

        verification = UserVerification(
            user_id=user.user_id,
            type="2FA",
            code_hash=generate_password_hash(otp),
            expires_at=taiwan_now() + timedelta(minutes=10),
            target_email=email,
            is_used=False,
            attempts=0,  # 需確認 model 有此欄位
        )
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
    """啟用 2FA：需先通過 OTP 驗證"""
    data = request.get_json(silent=True) or {}
    email = data.get("email")
    otp = data.get("otp")

    if not email or not otp:
        return jsonify({"error": "請提供電子郵件與驗證碼"}), 400

    record, error, status = _verify_otp(email, otp, "2FA")
    if error:
        return jsonify({"error": error}), status

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"error": "找不到使用者"}), 404

    try:
        user.email_2fa_enabled = True
        record.is_used = True
        db.session.commit()
        return jsonify({"message": "兩步驟驗證已啟用"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@two_factor_bp.route("/api/auth/2fa/login/two-factor", methods=["POST"])
def login_verify_2fa():
    """
    登入第二步：驗證 OTP。
    前端必須先完成密碼驗證（第一步），再呼叫此路由。
    建議第一步回傳短效 pre_auth_token，此路由應驗證該 token。
    目前以 email + otp 為最低驗證，正式環境請加上 pre_auth_token 驗證。
    """
    data = request.get_json(silent=True) or {}
    email = data.get("email")
    otp = data.get("otp")

    if not email or not otp:
        return jsonify({"error": "請提供電子郵件與驗證碼"}), 400

    record, error, status = _verify_otp(email, otp, "2FA")
    if error:
        return jsonify({"error": error}), status

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"error": "找不到使用者"}), 404

    try:
        record.is_used = True
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

    return jsonify({
        "token": issue_token(user.user_id),
        "user": {
            "user_id": user.user_id,
            "email": user.email,
            "user_name": user.user_name,
            "name": user.user_name,
        },
    }), 200


@two_factor_bp.route("/disable", methods=["POST"])
def disable_2fa():
    # 驗證 JWT token
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return jsonify({"error": "未授權"}), 401

    token = auth_header.split(" ")[1]
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=["HS256"])
        user_id = payload.get("user_id")
    except jwt.ExpiredSignatureError:
        return jsonify({"error": "登入已過期，請重新登入"}), 401
    except jwt.InvalidTokenError as e:
        print("JWT ERROR:", str(e))
        return jsonify({"error": f"Token 無效: {str(e)}"}), 400

    user = User.query.filter_by(user_id=user_id).first()
    if not user:
        return jsonify({"error": "找不到使用者"}), 404

    try:
        user.email_2fa_enabled = False
        db.session.commit()
        return jsonify({"message": "兩步驟驗證已停用"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500