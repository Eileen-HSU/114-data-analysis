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

load_dotenv()

# 如果開發環境沒有設定 JWT_SECRET_KEY，提供一個安全性較低的預設值以利本地開發
# 在生產環境請務必透過環境變數設定強密鑰
if not os.environ.get('JWT_SECRET_KEY'):
    os.environ['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY', 'dev-secret')
    print('[WARN] JWT_SECRET_KEY 未設定，已使用本機開發預設值（請勿用於生產環境）')

app = Flask(__name__)
ALLOWED_CORS_ORIGINS = {
    "https://site--frontend--d6tvmpswrhlp.code.run",
    "https://one14-data-analysis-frontend.onrender.com",
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

            # 【修正｜status 欄位長度不足】services/classify_v2.py 會寫入
            # "methodology_not_found"（22 字元），超過原本 VARCHAR(20)，
            # 造成 INSERT 直接丟出 "Data too long for column 'status'"、
            # 整筆分類結果都存不進去。這裡放寬成 VARCHAR(50)，只在資料庫
            # 現有長度不足時才會真的執行 ALTER TABLE，不會每次啟動都下
            # 不必要的 DDL，也不影響既有資料。
            ensure_column_length(
                "Response_Classification", "status",
                "`status` VARCHAR(50) NOT NULL",
                min_length=50,
            )
            # 【修正｜分析追問撈到舊批次】Chat_History.message_content 原本
            # 是 TEXT（上限 65,535 bytes），分類結果訊息（含所有大類別/
            # 子類別底下受試者原文與彙整摘要）數量一多就會超過，STRICT
            # 模式下 INSERT 直接失敗、訊息沒存進 DB，導致
            # services/chat_ask_service.py 依 project_id 回頭找「目前
            # 分析結果」時，看不到最新一批、改抓到更舊的 upload_batch_id
            # /template_id。放寬成 MEDIUMTEXT（16MB），不影響既有資料。
            ensure_column_length(
                "Chat_History", "message_content",
                "`message_content` MEDIUMTEXT NOT NULL",
                min_length=16_777_215,
            )
            db.session.commit()

            # review_status 舊值 migration："removed" -> "excluded"。
            # 目前 repo 內沒有任何寫入路徑會產生 "removed"（review_status
            # 尚未被任何 route 實際使用過），資料庫裡如果本來就沒有這個
            # 值，這條 UPDATE 是 no-op，不會動到任何既有資料列。
            db.session.execute(
                text(
                    "UPDATE `Response_Classification` "
                    "SET `review_status` = 'excluded' "
                    "WHERE `review_status` = 'removed'"
                )
            )
            db.session.commit()

            # 新表：只在完全不存在時建立，不影響任何既有資料。
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
            # 【新增｜Export_File 補欄位】原本 Export_File 是為了「產生檔案存到
            # 某個路徑」設計的（export_path），但目前沒有真正的檔案儲存服務，
            # 分類結果的 CSV 匯出改成直接把內容存進資料庫，所以補一個 content
            # 欄位。用 ensure_column 而不是動 export_path 的意義，避免混淆
            # 「路徑」跟「內容」這兩種不同語意。
            ensure_column("Export_File", "content", "`content` MEDIUMTEXT NULL")
            ensure_column("Export_File", "row_count", "`row_count` INT NULL")
            # 【新增｜邀請瀏覽】Workspace 補上 share_code 欄位，用來產生
            # 免登入的唯讀邀請連結。
            ensure_column("Workspace", "share_code", "`share_code` VARCHAR(10) NULL UNIQUE")
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

# 防止render冷啟動,使用uptime robot每5分鐘呼叫一次
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