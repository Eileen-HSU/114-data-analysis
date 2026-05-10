import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from flask import Flask, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from sqlalchemy import text
from extensions import db, mail
from routes.auth.register import register_bp
from routes.auth.login import login_bp
from routes.auth.pwd import pwd_bp
from routes.auth.profile import profile_bp

load_dotenv()

app = Flask(__name__)

# ── 1. 強化 CORS 設定 ──────────────────────────────────────────
CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)

# ── 2. 配置資料庫 (加入防崩潰邏輯) ──────────────────────────────
basedir = os.path.abspath(os.path.dirname(__file__))
db_url = os.getenv('DATABASE_URL')

if not db_url:
    # 💡 關鍵：如果環境變數被清空，先用這行頂住，避免啟動失敗碼 1
    print("\n[!!! ERROR !!!] DATABASE_URL IS MISSING! Please check Render Environment Settings.\n")
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'fallback.db')
else:
    # 修正 Render PostgreSQL 的連線協議頭
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

# ── 3. 郵件與初始化 ────────────────────────────────────────────
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', '587'))
app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS', 'True').lower() == 'true'
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME', '115503project@gmail.com')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD', 'zppbngpjpuwjhdzf')

db.init_app(app)
mail.init_app(app)

# ── 4. 註冊藍圖 ────────────────────────────────────────────────
app.register_blueprint(register_bp)
app.register_blueprint(login_bp)
app.register_blueprint(pwd_bp)
app.register_blueprint(profile_bp)

# ── 5. 定義路由 (解決 Not Found 問題) ──────────────────────────

@app.route('/')
def home():
    # 檢查資料庫狀態
    db_status = "Connected" if os.getenv('DATABASE_URL') else "Missing DATABASE_URL (Using Fallback)"
    return jsonify({
        "status": "success",
        "message": "後端伺服器已啟動",
        "database_info": db_status,
        "endpoints": ["/api/status", "/api/workspace"]
    })

@app.route('/api/status', methods=['GET'])
def get_status():
    return jsonify({"status": "online", "env": "Production"})

@app.route('/api/workspace', methods=['GET'])
def get_workspace():
    try:
        result = db.session.execute(text("SELECT * FROM Workspace"))
        workspaces = [dict(row._mapping) for row in result]
        return jsonify({"status": "success", "data": workspaces})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# ── 6. 錯誤處理與啟動 ──────────────────────────────────────────
@app.errorhandler(Exception)
def handle_exception(e):
    return jsonify({"error": str(e), "message": "後端崩潰，請檢查日誌"}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)