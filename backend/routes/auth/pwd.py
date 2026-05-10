from flask import Blueprint, current_app, request, jsonify
from extensions import db
from models import User, UserVerification
from werkzeug.security import generate_password_hash, check_password_hash
import random
from datetime import datetime, timedelta
import traceback
import os
import smtplib
from email.mime.text import MIMEText

pwd_bp = Blueprint('pwd', __name__)

def taiwan_now():
    return datetime.utcnow() + timedelta(hours=8)

# ── 1. 發送驗證碼 (支援修改與重設) ───────────────────────
def send_password_email(recipient, subject, body):
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = current_app.config["MAIL_DEFAULT_SENDER"]
    msg["To"] = recipient

    smtp_class = smtplib.SMTP_SSL if current_app.config.get("MAIL_USE_SSL") else smtplib.SMTP
    with smtp_class(
        current_app.config["MAIL_SERVER"],
        current_app.config["MAIL_PORT"],
        timeout=current_app.config.get("MAIL_TIMEOUT", 20),
    ) as smtp:
        smtp.ehlo()
        if current_app.config.get("MAIL_USE_TLS"):
            smtp.starttls()
            smtp.ehlo()
        if current_app.config.get("MAIL_USERNAME") and current_app.config.get("MAIL_PASSWORD"):
            smtp.login(
                current_app.config["MAIL_USERNAME"],
                current_app.config["MAIL_PASSWORD"],
            )
        smtp.send_message(msg)

@pwd_bp.route('/api/auth/send-otp', methods=['POST'])
def send_otp():
    data = request.get_json()
    email = data.get('email')
    # 接收前端傳入的 type: 'PASSWORD_CHANGE' 或 'PASSWORD_RESET'
    verify_type = data.get('type', 'PASSWORD_RESET')

    if not email:
        return jsonify({"error": "請提供電子郵件"}), 400

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"error": "此 Email 尚未註冊"}), 404

    # 產生 6 位數隨機碼
    otp = str(random.randint(100000, 999999))

    # 如果是從個人資料發起的修改，from=change；如果是登入頁發起的忘記密碼，from=forgot
    from_param = "change" if verify_type == "PASSWORD_CHANGE" else "forgot"
    
    frontend_url = os.getenv(
        "FRONTEND_URL",
        "https://one14-data-analysis-frontend.onrender.com",
    ).rstrip("/")
    reset_link = f"{frontend_url}/reset-password?email={email}&from={from_param}"

    print(f"DEBUG: 目前生成的連結是 -> {reset_link}")  

    # 寫入驗證紀錄
    new_verify = UserVerification(
        user_id=user.user_id,
        type=verify_type,
        code_hash=generate_password_hash(otp),  
        expires_at=taiwan_now() + timedelta(minutes=10),
        target_email=email,
        is_used=False
    )

    try:
        db.session.add(new_verify)
        db.session.commit()

        # 動態調整郵件內容
        action_text = "修改" if verify_type == "PASSWORD_CHANGE" else "重設"
        subject = f"【DataAnalysis】{action_text}您的密碼驗證"

        message_body = f"""您好：
        
我們收到了您{action_text}密碼的請求。
您的驗證碼為：{otp}

您也可以直接點擊下方連結進行{action_text}：
{reset_link}

(此連結與驗證碼將於 10 分鐘後失效。如果這不是您本人的操作，請忽略此信。)
"""
        send_password_email(email, subject, message_body)
        return jsonify({"message": f"{action_text}驗證碼已寄出"}), 200

    except Exception as e:
        db.session.rollback()
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

# ── 2. 驗證並執行密碼更新 ───────────────────────────────
@pwd_bp.route('/api/auth/reset-password', methods=['POST'])
def reset_password():
    data = request.get_json()
    email = data.get('email')
    otp = data.get('otp')
    new_password = data.get('new_password')

    if not all([email, otp, new_password]):
        return jsonify({"error": "缺少必要欄位"}), 400

    record = UserVerification.query.filter_by(
        target_email=email,
        is_used=False
    ).order_by(UserVerification.created_at.desc()).first()

    if not record or not check_password_hash(record.code_hash, otp):
        return jsonify({"error": "驗證碼錯誤或無效"}), 400

    if record.expires_at < taiwan_now():
        return jsonify({"error": "驗證碼已過期"}), 400

    user = User.query.get(record.user_id)
    if not user:
        return jsonify({"error": "使用者不存在"}), 404

    try:
        user.password_hash = generate_password_hash(new_password)  
        record.is_used = True 
        db.session.commit()
        return jsonify({"message": "密碼更新成功！"}), 200

    except Exception as e:
        db.session.rollback()
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
