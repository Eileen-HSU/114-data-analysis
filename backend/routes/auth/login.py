from flask import Blueprint, request, jsonify
from models import User
from extensions import db

login_bp = Blueprint('login', __name__)

@login_bp.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    if not data:
        return jsonify({"error": "未接收到資料"}), 400

    required = ['email', 'password_hash']
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": f"缺少必填欄位: {missing}"}), 400

    try:
        user = User.query.filter_by(email=data.get('email')).first()

        if not user:
            return jsonify({"error": "帳號或密碼錯誤"}), 401

        if user.password_hash != data.get('password_hash'):
            return jsonify({"error": "帳號或密碼錯誤"}), 401

        return jsonify({
            "message": "登入成功",
            "user_id": user.user_id,
            "user_name": user.user_name,
            "email": user.email
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 400