import secrets
import os
from datetime import timedelta

import jwt
from flask import Blueprint, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

from extensions import db
from models import User, UserVerification
from routes.auth.pwd import send_email_via_brevo, taiwan_now
from services import rate_limit_service as rl

two_factor_bp = Blueprint('two_factor', __name__)

MAX_OTP_ATTEMPTS = 5


_JWT_SECRET: str | None = None

def get_jwt_secret() -> str:
    global _JWT_SECRET
    if _JWT_SECRET is None:
        _JWT_SECRET = os.getenv("JWT_SECRET_KEY")
        if not _JWT_SECRET:
            raise RuntimeError("JWT_SECRET_KEY 環境變數未設定")
    return _JWT_SECRET


def verify_token(req):
    """驗證 JWT token 並回傳 user_id"""
    auth_header = req.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None, "Unauthorized"
    token = auth_header.split(" ")[1]
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=["HS256"])
        from routes.auth.token_service import token_is_current
        if not token_is_current(payload):
            return None, "Token revoked"
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

    # 發送頻率限制：同 email 每 60 秒 1 次、每小時 5 次；同 IP 每小時 20 次（存資料庫）
    ok, wait = rl.check_otp_send(str(email).strip().lower())
    if not ok:
        resp = jsonify({"error": "寄送太頻繁，請稍後再試"})
        resp.status_code = 429
        resp.headers["Retry-After"] = str(wait)
        return resp

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
        subject = "【DataAnalysis】您的雙因子驗證碼"
        message_body = f"您的驗證碼為：{otp}\n請於 10 分鐘內輸入。若非本人操作請忽略。"
        send_email_via_brevo(email, subject, message_body)
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

    user = db.session.get(User, record.user_id)

    user.email_2fa_enabled = True
    record.is_used = True
    db.session.commit()
    return jsonify({"message": "雙因子驗證已開啟"}), 200

# 3. 查詢 2FA 狀態
@two_factor_bp.route('/status', methods=['GET'])
def get_2fa_status():
    auth_user_id, error = verify_token(request)
    if error:
        return jsonify({"error": "請先登入"}), 401
    
    user = db.session.get(User, auth_user_id)
    if not user:
        return jsonify({"error": "找不到使用者"}), 404
    
    return jsonify({"enabled": bool(user.email_2fa_enabled)}), 200


# 4. 登入時的 2FA 驗證
# 使用 pre_auth_token 確保第一步密碼驗證已完成
# pre_auth_token 裡的 account_type 決定要走 Admin 分支還是原本的 User
# 分支；沒有 account_type（舊 token / 走完整流程前發出的 token）一律
# 視為 User，保持原本行為不被破壞。
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

    if payload.get("account_type") == "admin":
        return jsonify({"error": "管理員帳號不使用雙因子驗證，請重新登入"}), 400
    return _verify_user_2fa(email, otp)


def _verify_user_2fa(email, otp):
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

    user = db.session.get(User, record.user_id)

    from routes.auth.token_service import issue_user_token
    token = issue_user_token(user.user_id, get_jwt_secret(), taiwan_now())

    record.is_used = True
    db.session.commit()

    return jsonify({
        "token": token,
        "user": {
            "account_type": "user",
            "user_id": user.user_id,
            "email": user.email,
            "user_name": user.user_name,
            "name": user.user_name,
        }
    }), 200


# 5. 關閉 2FA（需 JWT 登入狀態 + 密碼確認）
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

    ip = rl.client_ip()
    account_key = f"user:{auth_user_id}"
    blocked_acct, wait_a = rl.blocked("disable2fa_account", account_key)
    blocked_ip, wait_i = rl.blocked("disable2fa_ip", ip)
    if blocked_acct or blocked_ip:
        wait = max(wait_a, wait_i)
        resp = jsonify({"error": f"嘗試次數過多，請約 {max(1, (wait + 59) // 60)} 分鐘後再試"})
        resp.status_code = 429
        resp.headers["Retry-After"] = str(wait)
        return resp

    try:
        user = User.query.filter_by(email=email).first()
        if not user:
            return jsonify({"error": "找不到該使用者"}), 404

        # 確認 JWT 對應的 user 跟要關閉 2FA 的 user 一致
        if auth_user_id != user.user_id:
            return jsonify({"error": "Forbidden"}), 403

        from routes.auth.google_auth import _password_set
        if not _password_set(user.user_id):
            return jsonify({"error": "這個帳號還沒有設定密碼，請先用「忘記密碼」設定密碼"}), 400

        if not check_password_hash(user.password_hash, password):
            rl.record_failure("disable2fa_account", account_key)
            rl.record_failure("disable2fa_ip", ip)
            return jsonify({"error": "密碼錯誤"}), 403

        rl.reset("disable2fa_account", account_key)
        user.email_2fa_enabled = False
        db.session.commit()
        return jsonify({"message": "雙因子驗證已成功停用"}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "伺服器發生錯誤，請稍後再試"}), 500
