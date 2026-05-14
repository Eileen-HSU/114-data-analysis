import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from dotenv import load_dotenv
from flask import Flask, jsonify
from flask_cors import CORS

from extensions import db, mail
from routes.auth.TwoFactor import two_factor_bp
from routes.auth.login import login_bp
from routes.auth.profile import profile_bp
from routes.auth.pwd import pwd_bp
from routes.auth.register import register_bp
from routes.workspace import workspace_bp, start_scheduler
from routes.auth.survey import survey_bp

load_dotenv()

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)

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

db.init_app(app)
mail.init_app(app)

start_scheduler()


app.register_blueprint(register_bp)
app.register_blueprint(login_bp)
app.register_blueprint(pwd_bp)
app.register_blueprint(profile_bp)
app.register_blueprint(two_factor_bp)
app.register_blueprint(survey_bp)
app.register_blueprint(workspace_bp)


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
