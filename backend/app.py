import os
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
from models import db, User, UserProfile

load_dotenv()

app = Flask(__name__)
CORS(app)

basedir = os.path.abspath(os.path.dirname(__file__))
db_url = os.getenv('DATABASE_URL')
if db_url and "ssl_ca=ca.pem" in db_url:
    db_url = db_url.replace("ssl_ca=ca.pem", f"ssl_ca={os.path.join(basedir, 'ca.pem')}")

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)


# ── 狀態檢查 ──────────────────────────────────────────────────
@app.route('/api/status', methods=['GET'])
def get_status():
    return jsonify({
        "status": "online",
        "database": "Aiven Cloud Connected",
        "models": ["User", "User_Profile", "User_Verification"]
    })


# ── 註冊 ──────────────────────────────────────────────────────
@app.route('/api/register', methods=['POST'])
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


# ── 登入 ──────────────────────────────────────────────────────
@app.route('/api/login', methods=['POST'])
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


# ── 個人檔案 ──────────────────────────────────────────────────
@app.route('/api/profile/<int:user_id>', methods=['GET'])
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


if __name__ == '__main__':
    app.run(debug=True, port=5000)