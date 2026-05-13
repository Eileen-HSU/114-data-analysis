from flask import Blueprint, request, jsonify
from extensions import db
from models import User, UserVerification
from routes.auth.pwd import send_password_email_via_resend, taiwan_now
from werkzeug.security import generate_password_hash, check_password_hash
import random
from datetime import timedelta
import jwt
import os

two_factor_bp = Blueprint('two_factor', __name__)

# ── 1. 發送 2FA 驗證碼 (開啟功能或登入時共用) ──
@two_factor_bp.route('/api/auth/2fa/send', methods=['POST'])
def send_2fa_code():
    data = request.get_json()
    email = data.get('email')
    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"error": "使用者不存在"}), 404

    otp = str(random.randint(100000, 999999))
    new_verify = UserVerification(
        user_id=user.user_id,
        type='2FA',
        code_hash=generate_password_hash(otp),
        expires_at=taiwan_now() + timedelta(minutes=10),
        target_email=email,
        is_used=False
    )
    
    try:
        db.session.add(new_verify)
        db.session.commit()
        
        subject = "【DataAnalysis】您的雙因子驗證碼"
        message_body = f"您好：\n\n您的驗證碼為：{otp}\n\n請於 10 分鐘內輸入完成驗證。若非本人操作請忽略此信。"
        
        send_password_email_via_resend(email, subject, message_body)
        return jsonify({"message": "驗證碼已寄出"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

# ── 2. 驗證並開啟 2FA 功能 ──
@two_factor_bp.route('/api/auth/2fa/two-factor', methods=['POST'])
def enable_2fa():
    data = request.get_json()
    email = data.get('email')
    otp = data.get('otp')

    record = UserVerification.query.filter_by(
        target_email=email, 
        type='2FA', 
        is_used=False
    ).order_by(UserVerification.created_at.desc()).first()

    if not record or not check_password_hash(record.code_hash, otp):
        return jsonify({"error": "驗證碼錯誤"}), 400
    
    if record.expires_at < taiwan_now():
        return jsonify({"error": "驗證碼已過期"}), 400

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"error": "找不到使用者"}), 404

    # 寫入資料庫
    user.email_2fa_enabled = True 
    record.is_used = True
    db.session.commit() 

    return jsonify({"message": "雙因子驗證已正式開啟"}), 200

# ── 3. 登入時的 2FA 驗證 (對應 /login/two-factor 頁面) ──
@two_factor_bp.route('/api/auth/2fa/login/two-factor', methods=['POST'])
def login_verify_2fa():
    data = request.get_json()
    email = data.get('email')
    otp = data.get('otp')

    record = UserVerification.query.filter_by(
        target_email=email, 
        type='2FA', 
        is_used=False
    ).order_by(UserVerification.created_at.desc()).first()

    if not record or not check_password_hash(record.code_hash, otp):
        return jsonify({"error": "驗證碼錯誤"}), 400

    user = User.query.filter_by(email=email).first()
    token = jwt.encode({
        'user_id': user.user_id,
        'exp': taiwan_now() + timedelta(hours=24)
    }, os.getenv("JWT_SECRET_KEY", "your-secret-key"), algorithm="HS256")

    record.is_used = True
    db.session.commit()

    return jsonify({
        "token": token,
        "user": {
            "user_id": user.user_id,
            "email": user.email,
            "user_name": user.user_name
        }
    }), 200

# ── 4. 關閉 2FA 功能 (Profile 頁面直接關閉) ──
@two_factor_bp.route('/api/auth/2fa/disable', methods=['POST'])
def disable_2fa():
    data = request.get_json()
    email = data.get('email')
    
    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"error": "使用者不存在"}), 404

    try:
        user.email_2fa_enabled = False 
        db.session.commit() 
        return jsonify({"message": "雙因子驗證已關閉"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500