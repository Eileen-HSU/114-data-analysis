from flask import Blueprint, request, jsonify
from werkzeug.security import check_password_hash
from models import User
from extensions import db
from datetime import datetime, timedelta
from routes.auth.pwd import send_password_email_via_resend, taiwan_now
from models import UserVerification
import random
import jwt 
import os

login_bp = Blueprint('login', __name__)

def taiwan_now():
    return datetime.utcnow() + timedelta(hours=8)

@login_bp.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    if not data:
        return jsonify({"error": "未接收到資料"}), 400

    email = data.get('email')
    password = data.get('password') or data.get('password_hash')

    if not email or not password:
        return jsonify({"error": "請提供電子郵件與密碼"}), 400

    try:
        user = User.query.filter_by(email=email).first()
        
        # 1. 基本帳密驗證
        if not user or not check_password_hash(user.password_hash, password):
            return jsonify({"error": "帳號或密碼錯誤"}), 401

        # 2. 準備回傳給前端的基礎資料 (用於 sessionStorage)
        user_info = {
            "user_id":   user.user_id,
            "user_name": user.user_name,
            "email":     user.email
        }

        # 3. 檢查是否開啟雙因子驗證 (2FA)
        if user.email_2fa_enabled:
            # 💡 關鍵修改：在攔截登入的同時，直接產生並寄出驗證碼
            otp = str(random.randint(100000, 999999))
            new_verify = UserVerification(
                user_id=user.user_id,
                type='2FA',
                code_hash=generate_password_hash(otp),
                expires_at=taiwan_now() + timedelta(minutes=10),
                target_email=user.email
            )
            db.session.add(new_verify)
            db.session.commit()

            # 寄出 Resend 信件
            subject = "【DataAnalysis】您的雙因子驗證碼"
            message_body = f"您的登入驗證碼為：{otp}\n請於 10 分鐘內輸入。"
            send_password_email_via_resend(user.email, subject, message_body)

            return jsonify({
                "require_2fa": True,
                "user_id":   user.user_id,
                "user_name": user.user_name,
                "email":     user.email
            }), 200

    except Exception as e:
        print(f"Login Error: {str(e)}") # 終端機偵錯用
        return jsonify({"error": "伺服器內部錯誤"}), 500