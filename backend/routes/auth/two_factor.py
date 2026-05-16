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

MAX_OTP_ATTEMPTS = 5


# 1. 發送 2FA 驗證碼
@two_factor_bp.route('/api/auth/2fa/send', methods=['POST'])
def send_2fa_code():
    data = request.get_json()
    email = data.get('email')
    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"error": "使用者不存在"}), 404

    otp = str(random.randint(100000, 999999))

    # 作廢所有舊的未使用驗證碼
    UserVerification.query.filter_by(
        target_email=email,
        type='2FA',
        is_used=False,
    ).update({"is_used": True})

    new_verify = UserVerification(
        user_id=user.user_id,
        type='2FA',
        code_hash=generate_password_hash(otp),
        expires_at=taiwan_now() + timedelta(minutes=10),
        target_email=email,
        is_used=False,
        attempts=0,
    )

    try:
        db.session.add(new_verify)
        db.session.commit()
        subject = "【DataAnalysis】您的雙因子驗證碼"
        message_body = f"您的驗證碼為：{otp}\n請於 10 分鐘內輸入。若非本人操作請忽略。"
        send_password_email_via_resend(email, subject, message_body)
        return jsonify({"message": "驗證碼已寄出"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# 2. 開啟 2FA 功能 (在 Profile 頁面操作)
@two_factor_bp.route('/api/auth/2fa/two-factor', methods=['POST'])
def enable_2fa():
    data = request.get_json()
    email = data.get('email')
    otp = data.get('otp')

    record = UserVerification.query.filter_by(
        target_email=email,
        type='2FA',
        is_used=False,
    ).order_by(UserVerification.created_at.desc()).first()

    if not record:
        return jsonify({"error": "驗證碼不存在或已使用"}), 400

    if record.expires_at < taiwan_now():
        return jsonify({"error": "驗證碼已過期"}), 400

    if record.attempts >= MAX_OTP_ATTEMPTS:
        record.is_used = True
        db.session.commit()
        return jsonify({"error": "嘗試次數過多，請重新取得驗證碼"}), 429

    if not check_password_hash(record.code_hash, otp):
        record.attempts += 1
        db.session.commit()
        remaining = MAX_OTP_ATTEMPTS - record.attempts
        return jsonify({"error": f"驗證碼錯誤，剩餘 {remaining} 次機會"}), 400

    user = User.query.filter_by(email=email).first()
    user.email_2fa_enabled = True
    record.is_used = True
    db.session.commit()
    return jsonify({"message": "雙因子驗證已開啟"}), 200


# 3. 登入時的 2FA 驗證 (輸入完密碼後的下一步)
@two_factor_bp.route('/api/auth/2fa/login/two-factor', methods=['POST'])
def login_verify_2fa():
    data = request.get_json()
    email = data.get('email')
    otp = data.get('otp')

    record = UserVerification.query.filter_by(
        target_email=email,
        type='2FA',
        is_used=False,
    ).order_by(UserVerification.created_at.desc()).first()

    if not record:
        return jsonify({"error": "驗證碼不存在或已使用"}), 400

    if record.expires_at < taiwan_now():
        return jsonify({"error": "驗證碼已過期"}), 400

    if record.attempts >= MAX_OTP_ATTEMPTS:
        record.is_used = True
        db.session.commit()
        return jsonify({"error": "嘗試次數過多，請重新取得驗證碼"}), 429

    if not check_password_hash(record.code_hash, otp):
        record.attempts += 1
        db.session.commit()
        remaining = MAX_OTP_ATTEMPTS - record.attempts
        return jsonify({"error": f"驗證碼錯誤，剩餘 {remaining} 次機會"}), 400

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
            "user_name": user.user_name,
            "name": user.user_name,
        }
    }), 200


# 4. 關閉 2FA (需輸入密碼確認，最多嘗試 5 次)
# 使用 IP 記錄失敗次數防止暴力破解
_disable_attempts = {}

@two_factor_bp.route('/api/auth/2fa/disable', methods=['POST', 'OPTIONS'])
def disable_2fa():
    if request.method == 'OPTIONS':
        return '', 200

    data = request.get_json(silent=True) or {}
    email = data.get('email')
    password = data.get('password')

    if not email or not password:
        return jsonify({"error": "請提供電子郵件與密碼以進行驗證"}), 400

    # 暴力破解防護（以 email 為 key）
    attempts = _disable_attempts.get(email, 0)
    if attempts >= MAX_OTP_ATTEMPTS:
        return jsonify({"error": "嘗試次數過多，請稍後再試"}), 429

    try:
        user = User.query.filter_by(email=email).first()
        if not user:
            return jsonify({"error": "找不到該使用者"}), 404

        if not check_password_hash(user.password_hash, password):
            _disable_attempts[email] = attempts + 1
            remaining = MAX_OTP_ATTEMPTS - _disable_attempts[email]
            return jsonify({"error": f"密碼錯誤，剩餘 {remaining} 次機會"}), 403

        # 驗證成功，清除計數並關閉 2FA
        _disable_attempts.pop(email, None)
        user.email_2fa_enabled = False
        db.session.commit()
        return jsonify({"message": "雙因子驗證已成功停用"}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"伺服器發生錯誤: {str(e)}"}), 500