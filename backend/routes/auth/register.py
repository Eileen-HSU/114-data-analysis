from flask import Blueprint, request, jsonify
from models import User, UserProfile
from extensions import db

register_bp = Blueprint('register', __name__)

@register_bp.route('/api/register', methods=['POST'])
def register():
    data = request.get_json()
    print("收到的資料:", data)
    if not data:
        return jsonify({"error": "未接收到資料"}), 400

    required = ['user_name', 'email', 'password_hash', 'phone_number', 'gender']
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": f"缺少必填欄位: {missing}"}), 400

    try:
        new_user = User(
            user_name=data.get('user_name'),
            email=data.get('email'),
            password_hash=data.get('password_hash')
        )
        db.session.add(new_user)
        db.session.flush()

        new_profile = UserProfile(
            user_id=new_user.user_id,
            phone_number=data.get('phone_number'),
            gender=data.get('gender'),
            language=data.get('language', 'zh-TW')
        )
        db.session.add(new_profile)
        db.session.commit()

        return jsonify({
            "message": f"使用者 {new_user.user_name} 註冊成功！",
            "user_id": new_user.user_id
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400