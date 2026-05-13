from datetime import datetime, timedelta
import os
import random
import traceback

import resend
from flask import Blueprint, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db
from models import User, UserVerification

pwd_bp = Blueprint("pwd", __name__)


def taiwan_now():
    return datetime.utcnow() + timedelta(hours=8)


def send_password_email_via_resend(recipient, subject, body_text):
    resend.api_key = os.getenv("RESEND_API_KEY")
    sender = os.getenv("MAIL_DEFAULT_SENDER", "onboarding@resend.dev")
    if "gmail.com" in sender.lower():
        sender = "onboarding@resend.dev"

    response = resend.Emails.send({
        "from": sender,
        "to": recipient,
        "subject": subject,
        "html": f"<p>{body_text.replace(chr(10), '<br>')}</p>",
    })
    print(f"Resend email sent: {response}")
    return response


@pwd_bp.route("/api/auth/send-otp", methods=["POST"])
def send_otp():
    data = request.get_json(silent=True) or {}
    email = data.get("email")
    verify_type = data.get("type", "PASSWORD_RESET")

    if not email:
        return jsonify({"error": "請輸入電子郵件"}), 400

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"error": "找不到此 Email 對應的帳號"}), 404

    otp = str(random.randint(100000, 999999))
    from_param = "change" if verify_type == "PASSWORD_CHANGE" else "forgot"
    frontend_url = os.getenv(
        "FRONTEND_URL",
        "https://one14-data-analysis-frontend.onrender.com",
    ).rstrip("/")
    reset_link = f"{frontend_url}/reset-password?email={email}&from={from_param}"

    verification = UserVerification(
        user_id=user.user_id,
        type=verify_type,
        code_hash=generate_password_hash(otp),
        expires_at=taiwan_now() + timedelta(minutes=10),
        target_email=email,
        is_used=False,
    )

    try:
        db.session.add(verification)
        db.session.commit()

        action_text = "變更密碼" if verify_type == "PASSWORD_CHANGE" else "重設密碼"
        subject = f"DataAnalysis {action_text}驗證碼"
        message_body = (
            f"您好，\n\n"
            f"您正在進行 {action_text}。\n"
            f"您的驗證碼是：{otp}\n\n"
            f"請回到頁面完成操作：\n{reset_link}\n\n"
            f"此驗證碼將在 10 分鐘後失效。"
        )

        send_password_email_via_resend(email, subject, message_body)
        return jsonify({"message": f"{action_text}驗證碼已寄出"}), 200

    except Exception as e:
        db.session.rollback()
        traceback.print_exc()
        return jsonify({"error": "寄送驗證信失敗", "details": str(e)}), 500


@pwd_bp.route("/api/auth/reset-password", methods=["POST"])
def reset_password():
    data = request.get_json(silent=True) or {}
    email = data.get("email")
    otp = data.get("otp")
    new_password = data.get("new_password")

    if not all([email, otp, new_password]):
        return jsonify({"error": "缺少必要欄位"}), 400

    record = UserVerification.query.filter_by(
        target_email=email,
        is_used=False,
    ).order_by(UserVerification.created_at.desc()).first()

    if not record or not check_password_hash(record.code_hash, otp):
        return jsonify({"error": "驗證碼錯誤或不存在"}), 400

    if record.expires_at < taiwan_now():
        return jsonify({"error": "驗證碼已過期"}), 400

    user = User.query.get(record.user_id)
    if not user:
        return jsonify({"error": "找不到使用者"}), 404

    try:
        user.password_hash = generate_password_hash(new_password)
        record.is_used = True
        db.session.commit()
        return jsonify({"message": "密碼已更新"}), 200

    except Exception as e:
        db.session.rollback()
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
