import os
from flask import Flask, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from extensions import db, mail
from routes.auth.register import register_bp
from routes.auth.login import login_bp
from routes.auth.pwd import pwd_bp
from routes.profile import profile_bp

load_dotenv()

app = Flask(__name__)
CORS(app)

# ── 配置 ──────────────────────────────────────────────────────
basedir = os.path.abspath(os.path.dirname(__file__))
db_url = os.getenv('DATABASE_URL')
if db_url and "ssl_ca=ca.pem" in db_url:
    db_url = db_url.replace("ssl_ca=ca.pem", f"ssl_ca={os.path.join(basedir, 'ca.pem')}")

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = '15503project@gmail.com' 
app.config['MAIL_PASSWORD'] = 'cwymtbotttwbuxom'
app.config['MAIL_DEFAULT_SENDER'] = '15503project@gmail.com'

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
        "database": "Aiven Cloud Connected"
    })

if __name__ == '__main__':
    app.run(debug=True, port=5000)