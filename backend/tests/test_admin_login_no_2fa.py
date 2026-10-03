#!/usr/bin/env python
"""Admin 不使用雙因子驗證：密碼正確直接登入；舊的 Admin 2FA 驗證路徑回 400。"""

import jwt
from werkzeug.security import generate_password_hash

from admin_test_support import check, create_app, finish, seed_people
import models as m
from extensions import db
from routes.auth.admin_guard import get_jwt_secret
from routes.auth.login import login_bp
from routes.auth.two_factor import two_factor_bp

app = create_app()
for bp, prefix in ((login_bp, None), (two_factor_bp, "/api/auth/2fa")):
    if bp.name not in app.blueprints:
        app.register_blueprint(bp, url_prefix=prefix) if prefix else app.register_blueprint(bp)
client = app.test_client()
with app.app_context():
    seed_people()
    db.session.get(m.Admin, 1).password_hash = generate_password_hash("pw-123456")
    db.session.commit()

check("Admin 模型沒有雙因子欄位、驗證碼表已移除",
      not hasattr(m.Admin, "email_2fa_enabled") and not hasattr(m, "AdminVerification"))

resp = client.post("/api/login", json={"email": "alice@example.com", "password": "pw-123456"})
body = resp.get_json() or {}
check("密碼正確 -> 直接拿到 Admin token（不需要驗證碼）",
      resp.status_code == 200 and body.get("account_type") == "admin" and body.get("token")
      and "requires_2fa" not in body and "pre_auth_token" not in body)
check("token 是 Admin token", jwt.decode(body["token"], get_jwt_secret(), algorithms=["HS256"]).get("account_type") == "admin")
check("密碼錯誤仍然擋下", client.post("/api/login", json={"email": "alice@example.com", "password": "wrong"}).status_code in (400, 401))

with app.app_context():
    fake_pre_auth = jwt.encode({"email": "alice@example.com", "type": "pre_auth", "account_type": "admin"},
                               get_jwt_secret(), algorithm="HS256")
resp = client.post("/api/auth/2fa/login/two-factor",
                   json={"email": "alice@example.com", "otp": "123456", "pre_auth_token": fake_pre_auth})
check("舊的 Admin 雙因子驗證路徑 -> 400", resp.status_code == 400)

finish()
