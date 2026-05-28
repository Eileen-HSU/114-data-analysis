from flask import Blueprint, jsonify, request
from models import User, UserProfile
from extensions import db
from datetime import datetime, timedelta
from sqlalchemy.orm import joinedload
from sqlalchemy import select
import traceback
import logging
import os
import jwt

profile_bp = Blueprint('profile', __name__)

logger = logging.getLogger(__name__)


def taiwan_now():
    return datetime.utcnow() + timedelta(hours=8)


def get_jwt_secret():
    secret = os.getenv("JWT_SECRET_KEY")
    if not secret:
        raise RuntimeError("JWT_SECRET_KEY 環境變數未設定")
    return secret


def verify_token(request):
    """驗證 JWT token 並回傳 user_id"""
    auth_header = request.headers.get("Authorization", "")
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


@profile_bp.route('/api/profile/<int:user_id>', methods=['GET', 'PUT', 'OPTIONS'])
def profile_handler(user_id):
    # OPTIONS 預檢請求直接返回成功
    if request.method == "OPTIONS":
        return "", 200

    # 驗證用戶身份—只能查看/更新自己的資料
    auth_user_id, error = verify_token(request)
    if error:
        return jsonify({"error": "Unauthorized"}), 401

    if auth_user_id != user_id:
        return jsonify({"error": "Forbidden"}), 403

    try:
        if request.method == "GET":
            # 單次 JOIN 查詢，避免兩次獨立 round-trip
            stmt = (
                select(
                    User.user_id,
                    User.user_name,
                    User.email,
                    User.created_at,
                    UserProfile.phone_number,
                    UserProfile.company_name,
                    UserProfile.gender,
                    UserProfile.language,
                    UserProfile.bio,
                    UserProfile.location,
                    UserProfile.avatar_url,
                    UserProfile.updated_at,
                )
                .outerjoin(UserProfile, User.user_id == UserProfile.user_id)
                .where(User.user_id == user_id)
            )
            row = db.session.execute(stmt).first()

            if not row:
                return jsonify({"error": "User not found"}), 404

            return jsonify({
                "user_id":      row.user_id,
                "user_name":    row.user_name,
                "email":        row.email,
                "created_at":   row.created_at.isoformat() if row.created_at else "",
                "phone_number": row.phone_number or "",
                "company_name": row.company_name or "",
                "gender":       row.gender       or "",
                "language":     row.language     or "",
                "bio":          row.bio          or "",
                "location":     row.location     or "",
                "avatar_url":   row.avatar_url   or "",
                "updated_at":   row.updated_at.isoformat() if row.updated_at else "",
            }), 200

        elif request.method == "PUT":
            # PUT 仍需要 ORM 物件才能做 upsert，用 joinedload 一次撈完
            user = db.session.get(
                User, user_id,
                options=[joinedload(User.profile)]
            )
            if not user:
                return jsonify({"error": "User not found"}), 404

            data = request.get_json(silent=True) or {}

            user_name = (data.get('user_name') or '').strip()
            if user_name:
                user.user_name = user_name

            profile = user.profile
            if not profile:
                profile = UserProfile(user_id=user_id, phone_number='')
                db.session.add(profile)

            # 只更新有傳的欄位，沒傳的保留原值
            updatable_fields = (
                'phone_number', 'company_name', 'gender',
                'bio', 'location', 'avatar_url',
            )
            for field in updatable_fields:
                if field in data:
                    setattr(profile, field, data[field] or '')

            profile.updated_at = taiwan_now()
            db.session.commit()

            return jsonify({"message": "Profile updated successfully"}), 200

    except Exception as e:
        db.session.rollback()
        logger.error("Profile handler error: %s", e, exc_info=True)
        return jsonify({"error": "Failed to process profile request"}), 500