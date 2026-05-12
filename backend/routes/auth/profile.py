from flask import Blueprint, jsonify, request
from models import User, UserProfile
from extensions import db
from datetime import datetime, timedelta
import traceback

profile_bp = Blueprint('profile', __name__)

def taiwan_now():
    return datetime.utcnow() + timedelta(hours=8)

@profile_bp.route('/api/profile/<int:user_id>', methods=['GET'])
def get_profile(user_id):
    try:
        user = User.query.get(user_id)
        if not user:
            return jsonify({"error": "使用者不存在"}), 404

        profile = UserProfile.query.filter_by(user_id=user_id).first()
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
            "updated_at":   profile.updated_at.isoformat() if profile and profile.updated_at else ""
        }), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 400


@profile_bp.route('/api/profile/<int:user_id>', methods=['PUT'])
def update_profile(user_id):
    try:
        data = request.get_json(silent=True) or {}
        user = User.query.get(user_id)
        if not user:
            return jsonify({"error": "使用者不存在"}), 404

        user_name = (data.get('user_name') or '').strip()
        if user_name:
            user.user_name = user_name

        profile = UserProfile.query.filter_by(user_id=user_id).first()
        if not profile:
            profile = UserProfile(user_id=user_id, phone_number='')
            db.session.add(profile)

        profile.phone_number = data.get('phone_number') or ''
        profile.company_name = data.get('company_name') or ''
        profile.gender       = data.get('gender')       or ''
        profile.bio          = data.get('bio')          or ''
        profile.location     = data.get('location')     or ''
        profile.updated_at    = taiwan_now()

        db.session.commit()
        return jsonify({"message": "更新成功"}), 200

    except Exception as e:
        db.session.rollback()
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
