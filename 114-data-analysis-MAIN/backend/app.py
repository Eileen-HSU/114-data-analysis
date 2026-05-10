import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from flask import Flask, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from extensions import db, mail
from sqlalchemy import text
from routes.auth.register import register_bp
from routes.auth.login import login_bp
from routes.auth.pwd import pwd_bp
from routes.auth.profile import profile_bp

load_dotenv()

app = Flask(__name__)

# ── 1. 強化 CORS 設定 ──────────────────────────────────────────
CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)

# ── 2. 資料庫與 SSL 配置 ────────────────────────────────────────
basedir = os.path.abspath(os.path.dirname(__file__))
db_url = os.getenv('DATABASE_URL')

if db_url:
    # 針對 Render 的 PostgreSQL SSL 連線優化
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
        
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

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# 郵件配置
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', '587'))
app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS', 'True').lower() == 'true'
app.config['MAIL_USE_SSL'] = os.getenv('MAIL_USE_SSL', 'False').lower() == 'true'
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME', '115503project@gmail.com')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD', 'zppbngpjpuwjhdzf')
app.config['MAIL_TIMEOUT'] = int(os.getenv('MAIL_TIMEOUT', '20'))
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER', app.config['MAIL_USERNAME'])

# ── 3. 初始化 ──────────────────────────────────────────────────
db.init_app(app)
mail.init_app(app)

# ── 4. 註冊藍圖 ────────────────────────────────────────────────
app.register_blueprint(register_bp)
app.register_blueprint(login_bp)
app.register_blueprint(pwd_bp)
app.register_blueprint(profile_bp)

# ── 5. 定義路由 (解決 Not Found 問題) ──────────────────────────

# 根目錄：解決直接點開網址看到 Not Found 的問題
@app.route('/')
def home():
    return jsonify({
        "status": "success",
        "message": "114 數據分析後端伺服器已成功啟動",
        "available_endpoints": {
            "status": "/api/status",
            "workspace": "/api/workspace",
            "auth": ["/login", "/register", "/profile"]
        }
    })

# 狀態檢查 API
@app.route('/api/status', methods=['GET'])
def get_status():
    return jsonify({
        "status": "online",
        "database": "Connected",
        "environment": "Production"
    })

# Workspace 資料查詢 API (供前端串接使用)
@app.route('/api/workspace', methods=['GET'])
def get_workspace():
    try:
        # 使用原生 SQL 查詢 Workspace 表
        result = db.session.execute(text("SELECT * FROM Workspace"))
        # 將結果轉換為字典清單
        workspaces = [dict(row._mapping) for row in result]
        return jsonify({
            "status": "success",
            "count": len(workspaces),
            "data": workspaces
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"資料庫查詢失敗: {str(e)}"
        }), 500

# ── 6. 錯誤處理與啟動 ──────────────────────────────────────────
@app.errorhandler(Exception)
def handle_exception(e):
    response = jsonify({
        "error": str(e),
        "type": str(type(e)),
        "message": "後端發生未預期的錯誤"
    })
    response.headers.add("Access-Control-Allow-Origin", "*")
    return response, 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)