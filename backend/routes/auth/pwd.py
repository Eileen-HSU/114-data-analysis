from flask import Blueprint, current_app, request, jsonify
from extensions import db
from models import User, UserVerification
from werkzeug.security import generate_password_hash, check_password_hash
import random
from datetime import datetime, timedelta
import traceback
import os
import resend 

pwd_bp = Blueprint('pwd', __name__)

# 沒辦法改 Render 環境變數，所以直接寫死 API KEY
RESEND_API_KEY = "re_8iZoHx8F_6trPstNJyCsis55zZbvGpDNQ"
resend.api_key = RESEND_API_KEY

def taiwan_now():
    return datetime.utcnow() + timedelta(hours=8)

# ── 1. Resend 發信函數 ───────────────────────
def send_password_email_resend(recipient, subject, body_text):
    try:
        # 轉換換行符號為 HTML 格式
        html_body = body_text.replace("\n", "<br>")
        
        params = {
            "from": "onboarding@resend.dev",  # 測試期固定
            "to": recipient,
            "subject": subject,
            "html": f"<div>{html_body}</div>"
        }
        
        r = resend.Emails.send(params)
        return True
    except Exception as e:
        print(f"Resend Error: {str(e)}")
        raise e

@pwd_bp.route('/api/auth/send-otp', methods=['POST'])
def send_otp():
    data = request.get_json()
    email = data.get('email')
    verify_type = data.get('type', 'PASSWORD_RESET')

    if not email:
        return jsonify({"error": "請提供電子郵件"}), 400

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"error": "此 Email 尚未註冊"}), 404

    otp = str(random.randint(100000, 999999))
    from_param = "change" if verify_type == "PASSWORD_CHANGE" else "forgot"
    
    # 寫死前端網址，避免抓不到環境變數
    frontend_url = "https://one14-data-analysis-frontend.onrender.com"
    reset_link = f"{frontend_url}/reset-password?email={email}&from={from_param}"

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

        action_text = "修改" if verify_type == "PASSWORD_CHANGE" else "重設"
        subject = f"【DataAnalysis】{action_text}您的密碼驗證"

        message_body = f"""您好：
        
我們收到了您{action_text}密碼的請求。
您的驗證碼為：{otp}

您可以直接點擊下方連結進行{action_text}：
{reset_link}

(此連結與驗證碼將於 10 分鐘後失效。如果這不是您本人的操作，請忽略此信。)
"""
        send_password_email_resend(email, subject, message_body)
        return jsonify({"message": f"{action_text}驗證碼已寄出"}), 200

    except Exception as e:
        db.session.rollback()
        traceback.print_exc()
        # 顯示詳細錯誤，方便你用 F12 Network 查看真相
        return jsonify({"error": "發信系統故障", "details": str(e)}), 500

# ── 2. 驗證並更新 (保持原有邏輯) ────────────────────────
@pwd_bp.route('/api/auth/reset-password', methods=['POST'])
def reset_password():
    # ... 原有邏輯 ...
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