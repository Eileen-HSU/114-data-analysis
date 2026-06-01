import re
import os
import logging
from datetime import datetime, timedelta

import jwt
from flask import Blueprint, request, jsonify
from werkzeug.security import generate_password_hash

from models import User, UserProfile
from extensions import db

register_bp = Blueprint('register', __name__)

PASSWORD_MIN_LENGTH = 8
EMAIL_REGEX = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')

_JWT_SECRET: str | None = None


def taiwan_now():
    return datetime.utcnow() + timedelta(hours=8)


def get_jwt_secret() -> str:
    global _JWT_SECRET
    if _JWT_SECRET is None:
        _JWT_SECRET = os.getenv("JWT_SECRET_KEY")
        if not _JWT_SECRET:
            raise RuntimeError("JWT_SECRET_KEY 未設定")
    return _JWT_SECRET


def build_token(user_id: int, now=None) -> str:
    if now is None:
        now = taiwan_now()
    exp_time = (now + timedelta(hours=24)).replace(tzinfo=None)
    return jwt.encode(
        {"user_id": user_id, "exp": exp_time},
        get_jwt_secret(),
        algorithm="HS256",
    )


def is_valid_password(password: str) -> bool:
    if len(password) < PASSWORD_MIN_LENGTH:
        return False
    if not re.search(r'[A-Za-z]', password):
        return False
    if not re.search(r'\d', password):
        return False
    return True


@register_bp.route('/api/register', methods=['POST'])
def register():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "未接收到資料"}), 400

    # 1. 必填欄位檢查
    required = ['user_name', 'email', 'phone_number', 'gender', 'password']
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": "請填寫所有必填欄位"}), 400

    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    user_name = data.get('user_name', '').strip()

    # 2. email 格式驗證
    if not EMAIL_REGEX.match(email):
        return jsonify({"error": "電子郵件格式不正確"}), 400

    # 3. email 是否已註冊
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "此電子郵件已被註冊"}), 409

    # 4. 密碼強度驗證
    if not is_valid_password(password):
        return jsonify({"error": "密碼至少需要 8 個字元，並包含英文字母和數字"}), 400

    try:
        now = taiwan_now()  
        new_user = User(
            user_name=user_name,
            email=email,
            password_hash=generate_password_hash(password),
        )
        db.session.add(new_user)
        db.session.flush()

        new_profile = UserProfile(
            user_id=new_user.user_id,
            phone_number=data.get('phone_number', ''),
            gender=data.get('gender', ''),
            language=data.get('language', 'zh-TW'),
            company_name=data.get('company', data.get('company_name', '')),
        )
        db.session.add(new_profile)
        db.session.commit()

        token = build_token(new_user.user_id, now=now)
        return jsonify({
            "message": f"使用者 {new_user.user_name} 註冊成功！",
            "user_id": new_user.user_id,
            "user_name": new_user.user_name,
            "email": new_user.email,
            "token": token,
        }), 201

    except Exception as e:
        db.session.rollback()
        logging.error(f"Registration error: {e}", exc_info=True)
        return jsonify({"error": "註冊失敗，請稍後再試"}), 500