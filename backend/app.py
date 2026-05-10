import os
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
from extensions import db, mail
from routes.auth.register import register_bp
from routes.auth.login import login_bp
from routes.auth.pwd import pwd_bp
from routes.auth.profile import profile_bp
from routes.auth.survey import survey_bp
from models import Survey_Template, User, UserProfile
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
from sqlalchemy import text

# 1. 載入環境變數
load_dotenv()

# 2. 解析並移除不受支援的 ssl_mode 參數
def sanitize_db_uri(uri: str) -> str:
    parsed = urlparse(uri)
    if not parsed.query:
        return uri

    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.pop('ssl_mode', None)
    new_query = urlencode(query)

    return urlunparse(parsed._replace(query=new_query))

app = Flask(__name__)

raw_db_uri = os.getenv('SQLALCHEMY_DATABASE_URI') or \
    "mysql+pymysql://avnadmin:AVNS_VGfMOJaETf2ioJjcFeu@analysis-ntub-analysis.c.aivencloud.com:17020/defaultdb"
app.config['SQLALCHEMY_DATABASE_URI'] = sanitize_db_uri(raw_db_uri)

CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

# 2. 透過 connect_args 傳遞驅動程式能理解的 'ssl' 參數
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    "connect_args": {
        "ssl": {
            "check_hostname": False  # 避免部分環境下主機名稱驗證失敗
        }
    },
    "pool_recycle": 280,  # 預防 Aiven 自動斷開閒置連線
    "pool_pre_ping": True # 每次連線前檢查有效性
}


app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# 3. 郵件伺服器配置
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = '115503project@gmail.com' 
app.config['MAIL_PASSWORD'] = 'zppbngpjpuwjhdzf'
app.config['MAIL_DEFAULT_SENDER'] = '115503project@gmail.com'

# 4. 初始化擴充套件 (只執行一次，避開 RuntimeError)
db.init_app(app)
mail.init_app(app)

# 5. 註冊藍圖
app.register_blueprint(register_bp)
app.register_blueprint(login_bp)
app.register_blueprint(pwd_bp)
app.register_blueprint(profile_bp)
app.register_blueprint(survey_bp)

with app.app_context():
    # 1. 抓出到底是連到哪一個地址
    print(f"📡 目前對標的資料庫地址: {app.config['SQLALCHEMY_DATABASE_URI']}")
    
    # 2. 直接在後端演算一下表內有幾筆
    from models import Survey_Template
    count = Survey_Template.query.count()
    print(f"📊 Aiven 雲端目前的總筆數: {count}")

# ── 路由設定 ────────────────────────────────

@app.route('/')
def index():
    return "後端伺服器運行中！"

@app.route('/api/status', methods=['GET'])
def get_status():
    return jsonify({
        "status": "online",
        "database": "Aiven Cloud Connected"
    })

@app.route('/api/submit_form', methods=['POST'])
def submit_form():
    data = request.json
    try:
        # 1. 產生邀請碼 (對標 Aiven 的 access_code 欄位)
        import random, string
        generated_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

        # 2. 取得第一個可用的 project_id
        workspace = db.session.execute(text("SELECT project_id FROM Workspace LIMIT 1")).fetchone()
        if workspace is None:
            return jsonify({"error": "Workspace 表中沒有可用的 project_id，請先建立 Workspace"}), 400

        project_id = workspace[0]

        # 3. 嚴格對標 Aiven 的欄位名稱
        new_survey = Survey_Template(
            project_id=project_id,
            access_code=generated_code,
            question_json=data  # 前端傳來的完整問卷 JSON
        )
        
        db.session.add(new_survey)
        db.session.commit()
        
        return jsonify({
            "message": "成功存入 Aiven Workspace", 
            "access_code": generated_code
        }), 201
        
    except Exception as e:
        db.session.rollback()
        # 這是最重要的：把錯誤印出來，你才知道為什麼沒存進去！
        print(f"❌ 存入失敗，原因：{e}") 
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True)