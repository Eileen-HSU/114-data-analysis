from flask import Blueprint, request, jsonify
from werkzeug.security import check_password_hash
from models import User
from extensions import db
from datetime import datetime, timedelta

login_bp = Blueprint('login', __name__)

def taiwan_now():
    return datetime.utcnow() + timedelta(hours=8)

@login_bp.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    if not data:
        return jsonify({"error": "未接收到資料"}), 400

    required = ['email']
    missing = [f for f in required if not data.get(f)]
    password = data.get('password') or data.get('password_hash')
    if not password:
        missing.append('password')
    if missing:
        return jsonify({"error": f"缺少必填欄位: {missing}"}), 400

    try:
        user = User.query.filter_by(email=data.get('email')).first()
        if not user:
            return jsonify({"error": "帳號或密碼錯誤"}), 401

        # 用 check_password_hash 比對加密密碼
        if not check_password_hash(user.password_hash, password):
            return jsonify({"error": "帳號或密碼錯誤"}), 401

        return jsonify({
            "message":   "登入成功",
            "user_id":   user.user_id,
            "user_name": user.user_name,
            "email":     user.email
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 400
