from extensions import db
from datetime import datetime
from zoneinfo import ZoneInfo
import uuid

# 定義抓取台灣時間的函式 (UTC+8)
def taiwan_now():
    return datetime.now(ZoneInfo("Asia/Taipei"))

# T01: User - 使用者帳號基礎資料
class User(db.Model):
    __tablename__ = 'User'
    user_id           = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_name         = db.Column(db.String(50), nullable=False)
    email             = db.Column(db.String(100), nullable=False, unique=True)
    password_hash     = db.Column(db.String(255), nullable=False)
    role              = db.Column(db.String(10), default='user') # user / admin
    created_at        = db.Column(db.DateTime(timezone=True), default=taiwan_now)
    email_2fa_enabled = db.Column(db.Boolean, default=False)

    # 關聯設定
    profile       = db.relationship('UserProfile', backref='user', uselist=False, cascade="all, delete-orphan")
    verifications = db.relationship('UserVerification', backref='user', cascade="all, delete-orphan")
    workspaces    = db.relationship('Workspace', backref='user', cascade="all, delete-orphan")


# T02: User_Profile - 使用者詳細檔案
class UserProfile(db.Model):
    __tablename__ = 'User_Profile'
    profile_id   = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('User.user_id'), nullable=False)
    phone_number = db.Column(db.String(20), nullable=False)
    company_name = db.Column(db.String(100))
    gender       = db.Column(db.String(20))
    language     = db.Column(db.String(36))
    bio          = db.Column(db.String(500))
    location     = db.Column(db.String(100))
    avatar_url   = db.Column(db.String(255))
    updated_at   = db.Column(db.DateTime(timezone=True), default=taiwan_now, onupdate=taiwan_now)


# T03: User_Verification - 驗證碼機制
class UserVerification(db.Model):
    __tablename__ = 'User_Verification'
    verification_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id         = db.Column(db.Integer, db.ForeignKey('User.user_id'), nullable=False)
    type            = db.Column(db.String(50), nullable=False) # REGISTER / PASSWORD_RESET / 2FA / SHARE_CHAT
    code_hash       = db.Column(db.String(255), nullable=False)
    is_used         = db.Column(db.Boolean, default=False)
    expires_at      = db.Column(db.DateTime(timezone=True), nullable=False)
    created_at      = db.Column(db.DateTime(timezone=True), default=taiwan_now)
    target_email    = db.Column(db.String(255))

    # 分享對話功能使用：安全補回外鍵約束，綁定驗證碼對應的 Workspace，其餘驗證類型為 None
    project_id      = db.Column(db.Integer, db.ForeignKey('Workspace.project_id', ondelete='CASCADE'), nullable=True)
    attempts        = db.Column(db.Integer, default=0, nullable=False)

# T04: Workspace - 專案紀錄
class Workspace(db.Model):
    __tablename__ = 'Workspace'
    
    project_id   = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('User.user_id'), nullable=False)
    project_name = db.Column(db.String(100), nullable=False) 
    
    # 當為 Null 時，前端畫面就會自動歸類在「未分類檔案」；有值時則是使用者自訂的資料夾名稱
    folder_name  = db.Column(db.String(100), nullable=True) 
    search_tag   = db.Column(db.String(50))
    status       = db.Column(db.String(20), default='Pending')
    created_at   = db.Column(db.DateTime(timezone=True), default=taiwan_now)
    is_deleted   = db.Column(db.Boolean, default=False)
    deleted_at   = db.Column(db.DateTime(timezone=True))

    # ── 子資料表關聯 ─────────────────────────────────────────
    chats     = db.relationship('Chat_History',    backref='workspace', cascade="all, delete-orphan")
    templates = db.relationship('Survey_Template', backref='workspace', passive_deletes=True)
    
"""
# T05: AI_Analysis - AI分析結果 
class AI_Analysis(db.Model):
    __tablename__ = 'AI_Analysis'
    analysis_id        = db.Column(db.Integer, primary_key=True, autoincrement=True)
    project_id         = db.Column(db.Integer, db.ForeignKey('Workspace.project_id'), nullable=False)
    raw_content        = db.Column(db.Text, nullable=False)
    ai_category        = db.Column(db.String(100))
    ai_summary         = db.Column(db.Text)
    ai_suggestion      = db.Column(db.Text)
    corrected_category = db.Column(db.String(100))
    chart_data         = db.Column(db.JSON)
    export_status      = db.Column(db.String(20), default='Not Exported') 
    created_at         = db.Column(db.DateTime(timezone=True), default=taiwan_now)


# T06: Chat_History - 儲存對話紀錄
class Chat_History(db.Model):
    __tablename__ = 'Chat_History'
    chat_id         = db.Column(db.Integer, primary_key=True, autoincrement=True)
    project_id      = db.Column(db.Integer, db.ForeignKey('Workspace.project_id'), nullable=False)
    chat_name       = db.Column(db.String(20), nullable=False)
    sender_type     = db.Column(db.String(10), nullable=False) # user / ai
    message_content = db.Column(db.Text, nullable=False)
    created_at      = db.Column(db.DateTime(timezone=True), default=taiwan_now)
    uploaded_files  = db.relationship('UploadedFile', backref='chat', cascade="all, delete-orphan")


# T07: Uploaded_File - 儲存聊天室內上傳的檔案資訊
class UploadedFile(db.Model):
    __tablename__ = 'Uploaded_File'
    file_id     = db.Column(db.Integer, primary_key=True, autoincrement=True)
    chat_id     = db.Column(db.Integer, db.ForeignKey('Chat_History.chat_id'), nullable=False)
    file_name   = db.Column(db.String(255), nullable=False)
    file_path   = db.Column(db.String(1000), nullable=False)     
    file_type   = db.Column(db.String(10), nullable=False)  # csv / xlsx / json / txt
    is_survey   = db.Column(db.Boolean, default=False)      # True: 問卷數據 / False: 一般分析檔案
    uploaded_at = db.Column(db.DateTime(timezone=True), default=taiwan_now)
"""

# T08: Survey_Template - 問卷模板
class Survey_Template(db.Model):
    __tablename__ = 'Survey_Template'
    template_id   = db.Column(db.Integer, primary_key=True, autoincrement=True)
    title         = db.Column(db.String(100), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('Workspace.project_id', ondelete="SET NULL"), nullable=True)
    share_uuid    = db.Column(db.String(36), default=lambda: str(uuid.uuid4()), unique=True)
    access_code   = db.Column(db.String(5), nullable=True)     
    question_json = db.Column(db.JSON, nullable=False)
    is_active     = db.Column(db.Boolean, default=True)
    created_at    = db.Column(db.DateTime(timezone=True), default=taiwan_now)

    # 關聯設定
    responses = db.relationship('Survey_Response', backref='template', cascade="all, delete-orphan")

# T09: Survey_Response - 儲存問卷回覆資料
class Survey_Response(db.Model):
    __tablename__ = 'Survey_Response'
    response_id    = db.Column(db.Integer, primary_key=True, autoincrement=True)
    template_id    = db.Column(db.Integer, db.ForeignKey('Survey_Template.template_id'), nullable=False)
    answer_json    = db.Column(db.JSON, nullable=False)
    response_token = db.Column(db.String(255), nullable=False, default=lambda: str(uuid.uuid4()))
    submitted_at   = db.Column(db.DateTime(timezone=True), default=taiwan_now)
    updated_at     = db.Column(db.DateTime(timezone=True), default=taiwan_now, onupdate=taiwan_now)

"""
# T10: Admin - 系統設定（金鑰與 AI 提示語）
class Admin(db.Model):
    __tablename__ = 'Admin'
    config_id       = db.Column(db.Integer, primary_key=True, autoincrement=True)
    admin_entry_key = db.Column(db.String(50), nullable=False) # 管理員金鑰
    prompt_template = db.Column(db.Text)                       # AI分析提示語模板
    system_error_log = db.Column(db.Text)                      # 系統錯誤日誌
    updated_at      = db.Column(db.DateTime(timezone=True), default=taiwan_now, onupdate=taiwan_now)
"""