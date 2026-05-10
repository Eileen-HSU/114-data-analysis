import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from flask import Flask, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from extensions import db, mail
from routes.auth.register import register_bp
from routes.auth.login import login_bp
from routes.auth.pwd import pwd_bp
from routes.auth.profile import profile_bp

load_dotenv()

app = Flask(__name__)

# ── 1. 強化 CORS 設定 ──────────────────────────────────────────
# 允許你的前端 Render 網址存取
CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)

# ── 2. 配置 ──────────────────────────────────────────────────────
basedir = os.path.abspath(os.path.dirname(__file__))

# 修正資料庫 SSL 憑證路徑 (Render 環境專用)
db_url = os.getenv('DATABASE_URL')
if db_url:
    # 確保在 Render 上能正確找到 ca.pem 的絕對路徑
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
app.config['MAIL_DEFAULT_SENDER'] = os.getenv(
    'MAIL_DEFAULT_SENDER',
    app.config['MAIL_USERNAME']
)

# ── 初始化 ────────────────────────────────────────────────────
db.init_app(app)
mail.init_app(app)

# ── 註冊藍圖  ────────────────────────────────
app.register_blueprint(register_bp)
app.register_blueprint(login_bp)
app.register_blueprint(pwd_bp)
app.register_blueprint(profile_bp)

@app.route('/api/status', methods=['GET'])
def get_status():
    return jsonify({
        "status": "online",
        "database": "Connected",
        "environment": "Production"
    })

if __name__ == '__main__':
    # 這裡要注意：Render 部署時通常會由 Gunicorn 啟動，
    # 只有在本地執行 python app.py 時才會用到下面這行
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

@app.errorhandler(Exception)
def handle_exception(e):
    # 這會把後端的報錯直接轉成 JSON 傳給前端，不會被 CORS 擋住
    response = jsonify({
        "error": str(e),
        "type": str(type(e)),
        "message": "後端邏輯崩潰，請檢查此報錯"
    })
    response.headers.add("Access-Control-Allow-Origin", "*")
    return response, 500
