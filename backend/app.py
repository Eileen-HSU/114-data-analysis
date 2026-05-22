import os
from dotenv import load_dotenv
load_dotenv()
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from dotenv import load_dotenv
from flask import Flask, jsonify, request, make_response
from flask_cors import CORS
from sqlalchemy import text

from extensions import db, mail
from routes.auth.two_factor import two_factor_bp
from routes.auth.login import login_bp
from routes.auth.profile import profile_bp
from routes.auth.pwd import pwd_bp
from routes.auth.register import register_bp
from routes.auth.workspace import workspace_bp, start_scheduler
from routes.auth.survey import survey_bp

load_dotenv()

# 如果開發環境沒有設定 JWT_SECRET_KEY，提供一個安全性較低的預設值以利本地開發
# 在生產環境請務必透過環境變數設定強密鑰
if not os.environ.get('JWT_SECRET_KEY'):
    os.environ['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY', 'dev-secret')
    print('[WARN] JWT_SECRET_KEY 未設定，已使用本機開發預設值（請勿用於生產環境）')

app = Flask(__name__)
CORS(app,
    resources={r"/api/*": {"origins": "*"}},
    supports_credentials=False,
    allow_headers=["Content-Type", "Authorization"],
    methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    automatic_options=False
)

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

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
import os

# 強制讓 Flask 去讀取環境變數中的資料庫網址與金鑰
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('SQLALCHEMY_DATABASE_URI')
app.config['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY')
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


def ensure_runtime_schema():
    with app.app_context():
        try:
            ensure_column("User", "email_2fa_enabled", "`email_2fa_enabled` TINYINT(1) DEFAULT 0")
            ensure_column("User_Verification", "attempts", "`attempts` INT NOT NULL DEFAULT 0")
            ensure_column("Workspace", "is_deleted", "`is_deleted` TINYINT(1) DEFAULT 0")
            ensure_column("Workspace", "deleted_at", "`deleted_at` DATETIME NULL")
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


@app.errorhandler(Exception)
def handle_exception(e):
    response = jsonify({
        "error": str(e),
        "type": str(type(e)),
        "message": "伺服器發生錯誤，請稍後再試",
    })
    response.headers.add("Access-Control-Allow-Origin", "*")
    return response, 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)


@app.before_request
def handle_options():
    if request.method == "OPTIONS":
        from flask import make_response
        res = make_response()
        res.headers["Access-Control-Allow-Origin"] = "*"
        res.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        res.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        return res