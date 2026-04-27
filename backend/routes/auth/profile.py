from flask import Blueprint, jsonify
from models import User, UserProfile
from extensions import db

profile_bp = Blueprint('profile', __name__)

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
            "phone_number": profile.phone_number if profile else "",
            "company_name": profile.company_name if profile else "",
            "gender":       profile.gender if profile else "",
            "language":     profile.language if profile else "",
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 400