from datetime import datetime, timedelta
import logging
import os
import secrets

import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException
from flask import Blueprint, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db
from models import User, UserVerification

pwd_bp = Blueprint("pwd", __name__)

_brevo_client: sib_api_v3_sdk.TransactionalEmailsApi | None = None
_brevo_sender: dict | None = None


def taiwan_now():
    return datetime.utcnow() + timedelta(hours=8)


def _get_brevo_client() -> tuple[sib_api_v3_sdk.TransactionalEmailsApi, dict]:
    global _brevo_client, _brevo_sender
    if _brevo_client is None:
        api_key = os.getenv("BREVO_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("BREVO_API_KEY is not configured")
        sender_email = os.getenv("BREVO_FROM_EMAIL", "").strip()
        if not sender_email:
            raise RuntimeError("BREVO_FROM_EMAIL is not configured")
        sender_name = os.getenv("BREVO_FROM_NAME", "DataAnalysis").strip()

        configuration = sib_api_v3_sdk.Configuration()
        configuration.api_key["api-key"] = api_key
        _brevo_client = sib_api_v3_sdk.TransactionalEmailsApi(
            sib_api_v3_sdk.ApiClient(configuration)
        )
        _brevo_sender = {"email": sender_email, "name": sender_name}

    return _brevo_client, _brevo_sender


def send_password_email_via_resend(recipient: str, subject: str, body_text: str):
    api_instance, sender = _get_brevo_client()
    html_body = "<p>" + body_text.replace("\n", "<br>") + "</p>"
    send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
        to=[{"email": recipient}],
        sender=sender,
        subject=subject,
        text_content=body_text,
        html_content=html_body,
    )
    try:
        api_instance.send_transac_email(send_smtp_email)
    except ApiException as e:
        raise RuntimeError(f"Brevo 寄信失敗: {e}")


def _invalidate_old_codes(email: str, otp_type: str):
    UserVerification.query.filter_by(
        target_email=email,
        type=otp_type,
        is_used=False,
    ).update({"is_used": True}, synchronize_session=False)  # 跳過 ORM session sync


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

    try:
        now = taiwan_now()  # 只取一次時間
        _invalidate_old_codes(email, verify_type)
        verification = UserVerification(
            user_id=user.user_id,
            type=verify_type,
            code_hash=generate_password_hash(otp),
            expires_at=(now + timedelta(minutes=10)).replace(tzinfo=None),
            target_email=email,
            is_used=False,
            attempts=0,
        )
        db.session.add(verification)
        db.session.commit()  # invalidate + add 合併一次 commit

        action_text = "變更密碼" if verify_type == "PASSWORD_CHANGE" else "重設密碼"
        subject = f"DataAnalysis {action_text}驗證碼"
        message_body = (
            f"您好，\n\n"
            f"您正在進行 {action_text}。\n"
            f"您的驗證碼是：{otp}\n\n"
            f"此驗證碼將在 10 分鐘後失效。"
        )
        send_password_email_via_resend(email, subject, message_body)
        return jsonify({"message": f"{action_text}驗證碼已寄出"}), 200

    except Exception as e:
        db.session.rollback()
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
        return jsonify({"error": "驗證碼不存在或已使用，請重新取得"}), 400

    now = taiwan_now()  # 只取一次，後續不再重複呼叫

    if record.expires_at < now:
        return jsonify({"error": "驗證碼已過期，請重新取得"}), 400

    if record.attempts >= 5:
        record.is_used = True
        db.session.commit()
        return jsonify({"error": "嘗試次數過多，請重新取得驗證碼"}), 429

    if not check_password_hash(record.code_hash, otp):
        record.attempts += 1
        db.session.commit()
        remaining = 5 - record.attempts
        return jsonify({"error": f"驗證碼錯誤，剩餘 {remaining} 次機會"}), 400

    user = User.query.get(record.user_id)
    if not user:
        return jsonify({"error": "找不到使用者"}), 404

    if check_password_hash(user.password_hash, new_password):
        return jsonify({"error": "新密碼不可與原本密碼相同，請設定不同的密碼"}), 400

    try:
        user.password_hash = generate_password_hash(new_password)
        record.is_used = True
        db.session.commit()
        return jsonify({"message": "密碼已更新"}), 200

    except Exception as e:
        db.session.rollback()
        logging.error(f"Password reset failed: {e}", exc_info=True)
        return jsonify({"error": "密碼更新失敗，請稍後再試"}), 500