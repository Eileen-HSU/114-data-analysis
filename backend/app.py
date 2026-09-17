import os
from dotenv import load_dotenv
load_dotenv()
from urllib.parse import urlsplit, parse_qsl, urlunsplit, urlencode

from dotenv import load_dotenv
from flask import Flask, jsonify, request, make_response
from flask_cors import CORS
from sqlalchemy import text

from extensions import db, mail
from routes.auth.two_factor import two_factor_bp
from routes.auth.login import login_bp
from routes.users.profile import profile_bp
from routes.auth.pwd import pwd_bp
from routes.auth.register import register_bp
from routes.workspaces.workspace import workspace_bp
from routes.surveys.survey import survey_bp
from routes.chats.chat import chat_bp
from routes.workspaces.trash import trash_bp, start_scheduler
from routes.classifications.classification import classification_bp
from routes.classifications.review import review_bp
from routes.classifications.report import report_bp
from routes.exports.export import exports_bp
from routes.ai.ppt_survey import ppt_survey_ai_bp
from routes.admin.ai_admin import ai_admin_bp

load_dotenv()

# 如果開發環境沒有設定 JWT_SECRET_KEY，提供一個安全性較低的預設值以利本地開發
# 在生產環境請務必透過環境變數設定強密鑰
if not os.environ.get('JWT_SECRET_KEY'):
    os.environ['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY', 'dev-secret')
    print('[WARN] JWT_SECRET_KEY 未設定，已使用本機開發預設值（請勿用於生產環境）')

app = Flask(__name__)
ALLOWED_CORS_ORIGINS = {
    "https://site--frontend--d6tvmpswrhlp.code.run",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
}

CORS(app,
    resources={r"/api/*": {"origins": list(ALLOWED_CORS_ORIGINS)}},
    supports_credentials=False,
    allow_headers=["Content-Type", "Authorization"],
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    automatic_options=False
)


@app.after_request
def add_cors_headers(response):
    origin = request.headers.get("Origin")
    if origin in ALLOWED_CORS_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
    return response

basedir = os.path.abspath(os.path.dirname(__file__))

db_url = os.getenv("DATABASE_URL")
if db_url:
    parsed_url = urlsplit(db_url)
    query_params = []
    for key, value in parse_qsl(parsed_url.query, keep_blank_values=True):
        normalized_key = key.lower().replace("_", "-")
        if normalized_key == "ssl-mode":
            continue
        if key == "ssl_ca" and value == "ca.pem":
            value = os.path.join(basedir, "ca.pem")
        query_params.append((key, value))

    db_url = urlunsplit((
        parsed_url.scheme,
        parsed_url.netloc,
        parsed_url.path,
        urlencode(query_params),
        parsed_url.fragment,
    ))

# 優先使用你算出或定義好的 db_url，如果沒有，才去讀取環境變數
db_url = db_url or os.environ.get('SQLALCHEMY_DATABASE_URI')

# 將最終決定的網址塞給 Flask
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY')
app.config['MAX_CONTENT_LENGTH'] = int(
    os.environ.get("MAX_CONTENT_LENGTH", 25 * 1024 * 1024)
)

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    "pool_pre_ping": True,
    "pool_recycle": 280,
    "pool_timeout": 10,
    "connect_args": {
        "connect_timeout": 10,
        "read_timeout": 15,
        "write_timeout": 15,
    },
}

# 最後再初始化資料庫
db.init_app(app)
mail.init_app(app)

def ensure_column(table_name, column_name, column_definition):
    exists = db.session.execute(
        text("""
            SELECT COUNT(*)
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = :table_name
              AND COLUMN_NAME = :column_name
        """),
        {"table_name": table_name, "column_name": column_name},
    ).scalar()

    if not exists:
        db.session.execute(
            text(f"ALTER TABLE `{table_name}` ADD COLUMN {column_definition}")
        )


def ensure_column_length(table_name, column_name, column_definition, min_length):
    """
    確保某個 VARCHAR 欄位的長度至少是 min_length，長度已經足夠就完全
    不執行任何 DDL（用 information_schema 查目前的
    CHARACTER_MAXIMUM_LENGTH，只在小於 min_length 時才下
    ALTER TABLE ... MODIFY COLUMN）。

    只會「放寬」長度，不會縮短、不會改變欄位型別以外的其他屬性
    以外的東西（nullable / default 由呼叫端在 column_definition 裡
    自己完整寫清楚，這裡不額外推斷），也不會動到既有資料列本身。

    這個專案目前沒有用 Alembic / Flask-Migrate，schema 變更一律走
    這種「app 啟動時檢查、需要才補」的 runtime migration 風格
    （比照上面的 ensure_column()），這裡沿用同一套風格，不另外引入
    新的 migration 機制。
    """
    current_length = db.session.execute(
        text("""
            SELECT CHARACTER_MAXIMUM_LENGTH
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = :table_name
              AND COLUMN_NAME = :column_name
        """),
        {"table_name": table_name, "column_name": column_name},
    ).scalar()

    if current_length is not None and current_length < min_length:
        db.session.execute(
            text(f"ALTER TABLE `{table_name}` MODIFY COLUMN {column_definition}")
        )


def ensure_table(model):
    """
    只有這張表在資料庫裡完全不存在時才會建立，已存在的表（不論是
    舊資料庫沿用下來的，還是上次啟動時已經建立過的）完全不會被
    觸碰，不會有 DROP/RECREATE 這種破壞性動作。

    用 db.metadata.create_all(tables=[...]) 只鎖定單一 model 的
    __table__，不會意外把其他還沒建立的表一起建出來、也不會用
    整份 metadata 覆蓋既有表的定義。
    """
    exists = db.session.execute(
        text("""
            SELECT COUNT(*)
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = :table_name
        """),
        {"table_name": model.__tablename__},
    ).scalar()

    if not exists:
        db.metadata.create_all(bind=db.session.get_bind(), tables=[model.__table__])


def ensure_unique_index(table_name, column_name, index_name):
    """確保某欄位有 UNIQUE 索引，只在完全沒有時才補一個新的 UNIQUE
    INDEX，不會動到既有資料、也不會刪除/取代任何既有索引。用在
    Admin.email 這種「表可能是舊資料庫留下來、schema 跟現在的
    model 不完全一樣」的情況（對應需求 #8：不確定現況前不做
    destructive 動作，schema 不同時用最小、可疊加的方式補齊）。
    """
    exists = db.session.execute(
        text(
            """
            SELECT COUNT(*)
            FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = :table_name
              AND COLUMN_NAME = :column_name
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    ).scalar()

    if not exists:
        db.session.execute(
            text(f"ALTER TABLE `{table_name}` ADD UNIQUE INDEX `{index_name}` (`{column_name}`)")
        )


def ensure_runtime_schema():
    with app.app_context():
        try:
            ensure_column("User", "email_2fa_enabled", "`email_2fa_enabled` TINYINT(1) DEFAULT 0")
            ensure_column("User_Verification", "attempts", "`attempts` INT NOT NULL DEFAULT 0")
            ensure_column("Workspace", "is_deleted", "`is_deleted` TINYINT(1) DEFAULT 0")
            ensure_column("Workspace", "deleted_at", "`deleted_at` DATETIME NULL")
            ensure_column("Chat_History", "template_id", "`template_id` INT NULL")
            ensure_column("Survey_Template", "user_id", "`user_id` INT NULL")
            ensure_column("Survey_Template", "due_date", "`due_date` TIMESTAMP NULL")
            ensure_column("Survey_Template", "is_anonymous", "`is_anonymous` TINYINT(1) DEFAULT 0")

            # ── Human Review / Aggregation / Report 支援（新增，additive-only）──
            ensure_column(
                "Response_Classification", "secondary_main_category",
                "`secondary_main_category` VARCHAR(100) NULL",
            )
            ensure_column(
                "Response_Classification", "final_main_category",
                "`final_main_category` VARCHAR(100) NULL",
            )
            ensure_column(
                "Response_Classification", "final_sub_category",
                "`final_sub_category` VARCHAR(100) NULL",
            )
            ensure_column(
                "Response_Classification", "final_secondary_main_category",
                "`final_secondary_main_category` VARCHAR(100) NULL",
            )
            ensure_column(
                "Response_Classification", "final_secondary_sub_category",
                "`final_secondary_sub_category` VARCHAR(100) NULL",
            )
            ensure_column(
                "Response_Classification", "final_reasoning",
                "`final_reasoning` TEXT NULL",
            )
            ensure_column(
                "Uploaded_Answer", "user_id",
                "`user_id` INT NULL",
            )
            db.session.commit()

            ensure_column_length(
                "Response_Classification", "status",
                "`status` VARCHAR(50) NOT NULL",
                min_length=50,
            )

            ensure_column_length(
                "Chat_History", "message_content",
                "`message_content` MEDIUMTEXT NOT NULL",
                min_length=16_777_215,
            )
            db.session.commit()

            db.session.execute(
                text(
                    "UPDATE `Response_Classification` "
                    "SET `review_status` = 'excluded' "
                    "WHERE `review_status` = 'removed'"
                )
            )
            db.session.commit()

            from models import (
                Classification_Review,
                Classification_Review_Message,
                Report,
                Report_Aggregation,
                Report_Aggregation_Item,
            )
            ensure_table(Classification_Review)
            ensure_table(Classification_Review_Message)
            ensure_table(Report)
            ensure_table(Report_Aggregation)
            ensure_table(Report_Aggregation_Item)
            ensure_column("Export_File", "content", "`content` MEDIUMTEXT NULL")
            ensure_column("Export_File", "row_count", "`row_count` INT NULL")
            ensure_column("Workspace", "share_code", "`share_code` VARCHAR(10) NULL UNIQUE")

            from models import Admin, AdminVerification

            ensure_table(Admin)
            ensure_column("Admin", "admin_name", "`admin_name` VARCHAR(50) NOT NULL DEFAULT ''")
            ensure_column("Admin", "email", "`email` VARCHAR(100) NULL")
            ensure_column("Admin", "password_hash", "`password_hash` VARCHAR(255) NULL")
            ensure_column("Admin", "email_2fa_enabled", "`email_2fa_enabled` TINYINT(1) DEFAULT 0")
            ensure_column("Admin", "created_at", "`created_at` DATETIME NULL")
            ensure_column("Admin", "updated_at", "`updated_at` DATETIME NULL")
            db.session.commit()
            ensure_unique_index("Admin", "email", "uq_admin_email")

            ensure_table(AdminVerification)
            db.session.commit()

            # ── Taxonomy 核心資料層（Phase A，additive-only）──────────
            from models import Topic, Taxonomy_Version, Taxonomy_Category

            ensure_table(Topic)
            ensure_table(Taxonomy_Version)
            ensure_table(Taxonomy_Category)
            db.session.commit()

            # ── Response_Classification taxonomy version 追溯（Phase B）──
            ensure_column(
                "Response_Classification", "taxonomy_version_id",
                "`taxonomy_version_id` INT NULL",
            )
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            app.logger.exception("Runtime schema check failed: %s", exc)


ensure_runtime_schema()

app.register_blueprint(register_bp)
app.register_blueprint(login_bp)
app.register_blueprint(pwd_bp)
app.register_blueprint(profile_bp)
app.register_blueprint(two_factor_bp, url_prefix='/api/auth/2fa')
app.register_blueprint(survey_bp)
app.register_blueprint(workspace_bp)
app.register_blueprint(chat_bp)
app.register_blueprint(trash_bp)
app.register_blueprint(classification_bp)
app.register_blueprint(review_bp)
app.register_blueprint(report_bp)
app.register_blueprint(exports_bp)
app.register_blueprint(ppt_survey_ai_bp)
app.register_blueprint(ai_admin_bp)

start_scheduler(app)

@app.route("/api/2fa/disable", methods=["OPTIONS"])
def options_2fa_disable():

    
    res = make_response()
    res.headers["Access-Control-Allow-Origin"] = "*"
    res.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    res.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return res, 200

@app.route("/api/status", methods=["GET"])
def get_status():
    return jsonify({
        "status": "online",
        "database": "Connected",
        "environment": "Production",
    })

# 健康檢查端點，供 Northflank health check / uptime robot 定期呼叫
@app.route("/health", methods=["GET", "HEAD"])
def health():
    return jsonify({"status": "ok"}), 200


@app.errorhandler(Exception)
def handle_exception(e):
    from werkzeug.exceptions import HTTPException
    
    if isinstance(e, HTTPException):
        response = jsonify({
            "error": e.description,
            "type": str(type(e)),
            "message": e.name,
        })
        return response, e.code   # ← 保留原始 status code

    # 非預期的 500
    response = jsonify({
        "error": str(e),
        "type": str(type(e)),
        "message": "伺服器發生錯誤，請稍後再試",
    })
    return response, 500

@app.before_request
def handle_options():
    if request.method == "OPTIONS":
        from flask import make_response
        res = make_response()
        res.headers["Access-Control-Allow-Origin"] = "*"
        res.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
        res.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        return res
    

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port)
