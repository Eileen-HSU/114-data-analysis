import secrets
import os
from datetime import timedelta

import jwt
from flask import Blueprint, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

from extensions import db
from models import User, UserVerification
from routes.auth.pwd import send_password_email_via_resend, taiwan_now

two_factor_bp = Blueprint('two_factor', __name__)

MAX_OTP_ATTEMPTS = 5
OTP_SEND_COOLDOWN_SECONDS = 60  # 同一 email 發送間隔限制

# 記錄上次發送時間（以 email 為 key）
_last_otp_sent = {}
# 關閉 2FA 失敗次數
_disable_attempts = {}


def get_jwt_secret():
    secret = os.getenv("JWT_SECRET_KEY")
    if not secret:
        raise RuntimeError("JWT_SECRET_KEY 環境變數未設定")
    return secret


def verify_token(req):
    """驗證 JWT token 並回傳 user_id"""
    auth_header = req.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None, "Unauthorized"
    token = auth_header.split(" ")[1]
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=["HS256"])
        return payload.get("user_id"), None
    except jwt.ExpiredSignatureError:
        return None, "Token expired"
    except jwt.InvalidTokenError:
        return None, "Invalid token"


# 1. 發送 2FA 驗證碼
@two_factor_bp.route('/send', methods=['POST'])
def send_2fa_code():
    data = request.get_json(silent=True) or {}
    email = data.get('email')

    if not email:
        return jsonify({"error": "請提供電子郵件"}), 400

    # 發送頻率限制（60 秒內不能重複發送）
    import time
    last_sent = _last_otp_sent.get(email, 0)
    if time.time() - last_sent < OTP_SEND_COOLDOWN_SECONDS:
        remaining = int(OTP_SEND_COOLDOWN_SECONDS - (time.time() - last_sent))
        return jsonify({"error": f"請等待 {remaining} 秒後再重新發送"}), 429

    user = User.query.filter_by(email=email).first()

    # 模糊回應，不洩漏 email 是否存在
    if not user:
        return jsonify({"message": "若此信箱已註冊，驗證碼將會寄出"}), 200

    otp = str(secrets.randbelow(900000) + 100000)

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
        _last_otp_sent[email] = time.time()
        subject = "【DataAnalysis】您的雙因子驗證碼"
        message_body = f"您的驗證碼為：{otp}\n請於 10 分鐘內輸入。若非本人操作請忽略。"
        send_password_email_via_resend(email, subject, message_body)
        return jsonify({"message": "若此信箱已註冊，驗證碼將會寄出"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "發送失敗，請稍後再試"}), 500


# 2. 開啟 2FA 功能 (在 Profile 頁面操作)
@two_factor_bp.route('/two-factor', methods=['POST'])
def enable_2fa():
    data = request.get_json(silent=True) or {}
    email = data.get('email')
    otp = data.get('otp')

    if not email or not otp:
        return jsonify({"error": "請提供電子郵件與驗證碼"}), 400

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


# 3. 登入時的 2FA 驗證
# 使用 pre_auth_token 確保第一步密碼驗證已完成
@two_factor_bp.route('/login/two-factor', methods=['POST'])
def login_verify_2fa():
    data = request.get_json(silent=True) or {}
    email = data.get('email')
    otp = data.get('otp')
    pre_auth_token = data.get('pre_auth_token')

    if not email or not otp:
        return jsonify({"error": "請提供電子郵件與驗證碼"}), 400

    # 驗證 pre_auth_token，確認第一步密碼登入已完成
    if not pre_auth_token:
        return jsonify({"error": "Unauthorized"}), 401

    try:
        payload = jwt.decode(pre_auth_token, get_jwt_secret(), algorithms=["HS256"])
        if payload.get("email") != email or payload.get("type") != "pre_auth":
            return jsonify({"error": "Unauthorized"}), 401
    except jwt.ExpiredSignatureError:
        return jsonify({"error": "驗證已過期，請重新登入"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"error": "Unauthorized"}), 401

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
    }, get_jwt_secret(), algorithm="HS256")

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


# 4. 關閉 2FA（需 JWT 登入狀態 + 密碼確認）
@two_factor_bp.route('/disable', methods=['POST', 'OPTIONS'])
def disable_2fa():
    if request.method == 'OPTIONS':
        return '', 200

    # 驗證 JWT，確認已登入
    auth_user_id, error = verify_token(request)
    if error:
        return jsonify({"error": "請先登入"}), 401

    data = request.get_json(silent=True) or {}
    email = data.get('email')
    password = data.get('password')

    if not email or not password:
        return jsonify({"error": "請提供電子郵件與密碼以進行驗證"}), 400

    attempts = _disable_attempts.get(email, 0)
    if attempts >= MAX_OTP_ATTEMPTS:
        return jsonify({"error": "嘗試次數過多，請稍後再試"}), 429

    try:
        user = User.query.filter_by(email=email).first()
        if not user:
            return jsonify({"error": "找不到該使用者"}), 404

        # 確認 JWT 對應的 user 跟要關閉 2FA 的 user 一致
        if auth_user_id != user.user_id:
            return jsonify({"error": "Forbidden"}), 403

        if not check_password_hash(user.password_hash, password):
            _disable_attempts[email] = attempts + 1
            remaining = MAX_OTP_ATTEMPTS - _disable_attempts[email]
            return jsonify({"error": f"密碼錯誤，剩餘 {remaining} 次機會"}), 403

        _disable_attempts.pop(email, None)
        user.email_2fa_enabled = False
        db.session.commit()
        return jsonify({"message": "雙因子驗證已成功停用"}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "伺服器發生錯誤，請稍後再試"}), 500