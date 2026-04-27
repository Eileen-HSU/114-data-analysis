from extensions import db
from datetime import datetime, timedelta

# 定義抓取台灣時間的函式 (UTC+8)
def taiwan_now():
    return datetime.utcnow() + timedelta(hours=8)

# T01: User - 使用者帳號基礎資料
class User(db.Model):
    __tablename__ = 'User'
    user_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_name = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(100), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    # 使用台灣時間作為預設值
    created_at = db.Column(db.DateTime, default=taiwan_now)

    # 關聯設定
    profile = db.relationship('UserProfile', backref='user', uselist=False)
    verifications = db.relationship('UserVerification', backref='user')

# T02: User_Profile - 使用者詳細檔案
class UserProfile(db.Model):
    __tablename__ = 'User_Profile'
    profile_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('User.user_id'), nullable=False)
    phone_number = db.Column(db.String(20), nullable=False)
    company_name = db.Column(db.String(100))
    gender = db.Column(db.String(10))
    language = db.Column(db.String(15))

# T03: User_Verification - 驗證碼機制
class UserVerification(db.Model):
    __tablename__ = 'User_Verification'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('User.user_id'), nullable=False)
    type = db.Column(db.String(50), nullable=False) # REGISTER / PASSWORD_RESET
    code_hash = db.Column(db.String(255), nullable=False)
    is_used = db.Column(db.Boolean, default=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    # 使用台灣時間作為預設值
    created_at = db.Column(db.DateTime, default=taiwan_now)
    target_email = db.Column(db.String(255))
    project_id = db.Column(db.Integer)