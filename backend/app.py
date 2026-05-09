import os
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
from extensions import db, mail
from routes.auth.register import register_bp
from routes.auth.login import login_bp
from routes.auth.pwd import pwd_bp
from routes.auth.profile import profile_bp
from models import Survey, User, UserProfile

# 1. 載入環境變數
load_dotenv()

app = Flask(__name__)
CORS(app)

# 1. 完全移除 URI 中的查詢參數，不給 PyMySQL 誤判的機會
# 1. 將連線網址後面所有的參數（?ssl_mode...）通通刪掉，只留下純淨的網址
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('SQLALCHEMY_DATABASE_URI') or \
    "mysql+pymysql://avnadmin:AVNS_VGfMOJaETf2ioJjcFeu@analysis-ntub-analysis.c.aivencloud.com:17020/defaultdb"

# 2. 改用 connect_args 傳遞 SSL 設定。
# 在 PyMySQL 中，SSL 參數的 Key 叫做 'ssl'，且裡面不支援 'ssl_mode' 這個字眼。
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    "connect_args": {
        "ssl": {
            "ca": None  # 讓 PyMySQL 自動處理 SSL 握手，避開參數名稱衝突
        }
    }
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
        new_survey = Survey(content=str(data))
        db.session.add(new_survey)
        db.session.commit()
        return jsonify({"message": "成功存入 Aiven Workspace"}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@app.route('/api/get_surveys', methods=['GET'])
def get_surveys():
    return jsonify({"data": "從資料庫抓到的內容"})

if __name__ == '__main__':
    app.run(debug=True, port=5000)