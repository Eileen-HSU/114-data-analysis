from flask import Blueprint, request, jsonify
from werkzeug.security import generate_password_hash
from models import User, UserProfile
from extensions import db
import traceback

register_bp = Blueprint('register', __name__)

def taiwan_now():
    return datetime.utcnow() + timedelta(hours=8)

@register_bp.route('/api/register', methods=['POST'])
def register():
    data = request.get_json()
    if not data:
        return jsonify({"error": "未接收到資料"}), 400

    required = ['user_name', 'email', 'phone_number', 'gender']
    missing = [f for f in required if not data.get(f)]
    password = data.get('password') or data.get('password_hash')
    if not password:
        missing.append('password')
    if missing:
        return jsonify({"error": f"缺少必填欄位: {missing}"}), 400

    try:
        new_user = User(
            user_name=data.get('user_name'),
            email=data.get('email'),
            password_hash=generate_password_hash(password)
        )
        db.session.add(new_user)
        db.session.flush()

        new_profile = UserProfile(
            user_id=new_user.user_id,
            phone_number=data.get('phone_number'),
            gender=data.get('gender'),
            language=data.get('language', 'zh-TW'),
            company_name=data.get('company_name', '')
        )
        db.session.add(new_profile)
        db.session.commit()

        return jsonify({
            "message": f"使用者 {new_user.user_name} 註冊成功！",
            "user_id": new_user.user_id
        }), 201

    except Exception as e:
        db.session.rollback()
        import logging
        logging.error(f"Registration error: {e}", exc_info=True)
        return jsonify({"error": "註冊失敗，請稍後再試"}), 400
