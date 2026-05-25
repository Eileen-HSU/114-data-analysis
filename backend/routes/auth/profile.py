from flask import Blueprint, jsonify, request
from models import User, UserProfile
from extensions import db
from datetime import datetime, timedelta
import traceback
import os
import jwt

profile_bp = Blueprint('profile', __name__)

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
        user = User.query.get(user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404

        profile = UserProfile.query.filter_by(user_id=user_id).first()
        
        if request.method == "GET":
            return jsonify({
                "user_id":      user.user_id,
                "user_name":    user.user_name,
                "email":        user.email,
                "created_at":   user.created_at.isoformat() if user.created_at else "",
                "phone_number": profile.phone_number if profile else "",
                "company_name": profile.company_name if profile else "",
                "gender":       profile.gender       if profile else "",
                "language":     profile.language     if profile else "",
                "bio":          profile.bio          if profile else "",
                "location":     profile.location     if profile else "",
                "avatar_url":   profile.avatar_url   if profile else "",
                "updated_at":   profile.updated_at.isoformat() if profile and profile.updated_at else ""
            }), 200
        
        elif request.method == "PUT":
            data = request.get_json(silent=True) or {}
            user_name = (data.get('user_name') or '').strip()
            if user_name:
                user.user_name = user_name

            if not profile:
                profile = UserProfile(user_id=user_id, phone_number='')
                db.session.add(profile)

            # 只更新有傳的欄位，沒傳的保留原值
            if 'phone_number' in data:
                profile.phone_number = data['phone_number'] or ''
            if 'company_name' in data:
                profile.company_name = data['company_name'] or ''
            if 'gender' in data:
                profile.gender = data['gender'] or ''
            if 'bio' in data:
                profile.bio = data['bio'] or ''
            if 'location' in data:
                profile.location = data['location'] or ''
            if 'avatar_url' in data:
                profile.avatar_url = data['avatar_url'] or ''

            profile.updated_at = taiwan_now()
            db.session.commit()
            return jsonify({"message": "Profile updated successfully"}), 200

    except Exception as e:
        db.session.rollback()
        import logging
        logging.error(f"Profile handler error: {e}", exc_info=True)
        return jsonify({"error": "Failed to process profile request"}), 500
