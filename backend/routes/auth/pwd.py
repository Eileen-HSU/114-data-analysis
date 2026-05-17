from datetime import datetime, timedelta
import os
import secrets
import resend

import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException
from flask import Blueprint, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db
from models import User, UserVerification

pwd_bp = Blueprint("pwd", __name__)
DEFAULT_RESEND_SENDER = "DataAnalysis <onboarding@resend.dev>"



def taiwan_now():
    return datetime.utcnow() + timedelta(hours=8)


def send_password_email_via_resend(recipient, subject, body_text):
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("RESEND_API_KEY is not configured")

    sender = os.getenv("RESEND_FROM_EMAIL") or os.getenv("MAIL_DEFAULT_SENDER") or DEFAULT_RESEND_SENDER
    sender = sender.strip()
    if not sender:
        sender = DEFAULT_RESEND_SENDER
    if "gmail.com" in sender.lower():
        raise RuntimeError("Resend sender cannot be a Gmail address. Use onboarding@resend.dev or a verified domain sender.")

    resend.api_key = api_key
    html_body = "<p>" + body_text.replace("\n", "<br>") + "</p>"
    response = resend.Emails.send({
        "from": sender,
        "to": [recipient],
        "subject": subject,
        "html": html_body,
        "text": body_text,
    })
    return response

'''
def send_password_email_via_resend(recipient, subject, body_text):
    api_key = os.getenv("BREVO_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("BREVO_API_KEY is not configured")

    sender_email = os.getenv("BREVO_FROM_EMAIL", "").strip()
    sender_name = os.getenv("BREVO_FROM_NAME", "DataAnalysis").strip()

    if not sender_email:
        raise RuntimeError("BREVO_FROM_EMAIL is not configured")

    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key["api-key"] = api_key

    api_instance = sib_api_v3_sdk.TransactionalEmailsApi(
        sib_api_v3_sdk.ApiClient(configuration)
    )

    html_body = "<p>" + body_text.replace("\n", "<br>") + "</p>"

    send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
        to=[{"email": recipient}],
        sender={"email": sender_email, "name": sender_name},
        subject=subject,
        text_content=body_text,
        html_content=html_body,
    )

    try:
        api_instance.send_transac_email(send_smtp_email)
    except ApiException as e:
        raise RuntimeError(f"Brevo 寄信失敗: {e}")
'''

def _invalidate_old_codes(email: str, otp_type: str):
    """將同一 email 所有未使用的舊驗證碼標記為已使用"""
    UserVerification.query.filter_by(
        target_email=email,
        type=otp_type,
        is_used=False,
    ).update({"is_used": True})


@pwd_bp.route("/api/auth/email-config", methods=["GET"])
def email_config():
    return jsonify({"status": "ok"}), 200


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

    otp = str(secrets.randbelow(900000) + 100000)

    from_param = "change" if verify_type == "PASSWORD_CHANGE" else "forgot"
    frontend_url = os.getenv(
        "FRONTEND_URL",
        "https://one14-data-analysis-frontend.onrender.com",
    ).rstrip("/")
    reset_link = f"{frontend_url}/reset-password?email={email}&from={from_param}"

    try:
        _invalidate_old_codes(email, verify_type)

        verification = UserVerification(
            user_id=user.user_id,
            type=verify_type,
            code_hash=generate_password_hash(otp),
            expires_at=taiwan_now() + timedelta(minutes=10),
            target_email=email,
            is_used=False,
            attempts=0,
        )
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
        import logging
        logging.error(f"OTP send failed: {e}", exc_info=True)
        return jsonify({"error": "寄送驗證信失敗，請稍後再試"}), 500


@pwd_bp.route("/api/auth/reset-password", methods=["POST"])
def reset_password():
    data = request.get_json(silent=True) or {}
    email = data.get("email")
    otp = data.get("otp")
    new_password = data.get("new_password")
    verify_type = data.get("type", "PASSWORD_RESET")

    if not all([email, otp, new_password]):
        return jsonify({"error": "缺少必要欄位"}), 400

    record = UserVerification.query.filter_by(
        target_email=email,
        type=verify_type,
        is_used=False,
    ).order_by(UserVerification.created_at.desc()).first()

    if not record:
        return jsonify({"error": "驗證碼不存在或已使用"}), 400

    if record.expires_at < taiwan_now():
        return jsonify({"error": "驗證碼已過期"}), 400

    if not check_password_hash(record.code_hash, otp):
        return jsonify({"error": "驗證碼錯誤"}), 400

    user = User.query.get(record.user_id)
    if not user:
        return jsonify({"error": "找不到使用者"}), 404

    # 對比新密碼與舊密碼是否相同，如果相同則拒絕更新
    if check_password_hash(user.password_hash, new_password):
        return jsonify({"error": "新密碼不能與原本密碼相同"}), 400

    try:
        user.password_hash = generate_password_hash(new_password)
        record.is_used = True
        db.session.commit()
        return jsonify({"message": "密碼已更新"}), 200

    except Exception as e:
        db.session.rollback()
        import logging
        logging.error(f"Password reset failed: {e}", exc_info=True)
        return jsonify({"error": "密碼更新失敗，請稍後再試"}), 500
