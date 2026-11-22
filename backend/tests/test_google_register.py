#!/usr/bin/env python
"""Google 直接註冊：email 未註冊才建立（無密碼帳號）、已註冊 email 拒絕、之後可用忘記密碼設定密碼。"""

import time
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import text
from werkzeug.security import generate_password_hash

from admin_test_support import check, create_app, finish, seed_people
import models as m
from extensions import db
from rate_limit_models import RateLimitCounter
import routes.auth.google_auth as ga
from routes.auth.login import login_bp
from routes.auth.pwd import pwd_bp, taiwan_now
from routes.auth.two_factor import two_factor_bp

app = create_app()
for bp in (login_bp, pwd_bp):
    if bp.name not in app.blueprints:
        app.register_blueprint(bp)
if two_factor_bp.name not in app.blueprints:
    app.register_blueprint(two_factor_bp, url_prefix="/api/auth/2fa")
ga.init_google_auth(app)
client = app.test_client()

with app.app_context():
    seed_people()
    db.metadata.create_all(bind=db.engine, tables=[RateLimitCounter.__table__])

key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
CID = ga.google_client_id()
ga._jwk_client = SimpleNamespace(get_signing_key_from_jwt=lambda t: SimpleNamespace(key=key.public_key()))
sent = []
mock.patch("routes.auth.pwd.send_email_via_brevo", lambda to, subj, body: sent.append(subj)).start()


def cred(sub, email, name="新同學", verified=True):
    now = int(time.time())
    return jwt.encode({"sub": sub, "email": email, "email_verified": verified, "name": name, "aud": CID,
                       "iss": "https://accounts.google.com", "iat": now, "exp": now + 600}, key, algorithm="RS256")


def clear_rl():
    with app.app_context():
        db.session.query(RateLimitCounter).delete(); db.session.commit()


def reg(c):
    return client.post("/api/auth/google/register", json={"credential": c})


# ---- 新帳號 ----
r = reg(cred("g-new", "New.Student@Example.com"))
body = r.get_json()
check("新 email → 201 並回傳 token", r.status_code == 201 and body["token"] and body["login_method"] == "google")
check("email 正規化為小寫、使用 Google 名稱", body["email"] == "new.student@example.com" and body["user_name"] == "新同學")
with app.app_context():
    u = m.User.query.filter_by(email="new.student@example.com").first()
    check("建立 User 與 Profile", u is not None and u.profile is not None and u.email_2fa_enabled in (False, None, 0))
    row = db.session.execute(text("SELECT google_sub, password_set FROM `User` WHERE user_id=:u"), {"u": u.user_id}).first()
    check("已綁定 google_sub 且 password_set = 0", row[0] == "g-new" and row[1] == 0)
    new_id = u.user_id
check("寄出建立帳號通知信", any("使用 Google 建立帳號" in s for s in sent))

H = {"Authorization": f"Bearer {body['token']}"}
check("token 可用於需要登入的 API（狀態）", client.get("/api/auth/google/status", headers=H).get_json() == {
    "bound": True, "email": "new.student@example.com", "password_set": False})

# ---- 這種帳號沒有可用的密碼 ----
for pw in ("", "password1", "Google123", ga.__name__):
    if not pw:
        continue
    r = client.post("/api/login", json={"email": "new.student@example.com", "password": pw})
    check(f"用密碼 {pw!r} 登入 → 401", r.status_code == 401)
clear_rl()

# ---- Google 登入可用 ----
r = client.post("/api/auth/google/login", json={"credential": cred("g-new", "new.student@example.com")})
check("之後可用 Google 登入", r.status_code == 200 and r.get_json()["user_id"] == new_id)
clear_rl()

# ---- 重複註冊 ----
r = reg(cred("g-new", "new.student@example.com"))
check("同一個 Google 帳號再註冊 → 409 GOOGLE_ALREADY_REGISTERED", r.status_code == 409 and r.get_json()["code"] == "GOOGLE_ALREADY_REGISTERED")

# ---- email 已有帳號：不自動合併 ----
r = reg(cred("g-other", "owner@example.com"))
check("email 已有 User 帳號 → 409 EMAIL_EXISTS", r.status_code == 409 and r.get_json()["code"] == "EMAIL_EXISTS")
r = reg(cred("g-admin", "Alice@Example.com"))
check("email 是 Admin → 409 EMAIL_EXISTS（Admin 不能用 Google 註冊）", r.status_code == 409 and r.get_json()["code"] == "EMAIL_EXISTS")
with app.app_context():
    check("沒有因此新增帳號或綁定", m.User.query.count() == 2
          and db.session.execute(text("SELECT google_sub FROM `User` WHERE email='owner@example.com'")).scalar() is None)

# ---- 驗證失敗 ----
check("email 未驗證 → 401", reg(cred("g-x", "x@example.com", verified=False)).status_code == 401)
check("壞 token → 401", reg("not-a-token").status_code == 401)
clear_rl()
check("沒帶 credential → 401", client.post("/api/auth/google/register", json={}).status_code == 401)

# ---- 沒有密碼的帳號不能自己解除綁定／關 2FA 後把自己鎖在外面 ----
r = client.post("/api/auth/google/unbind", json={"password": "anything"}, headers=H)
check("無密碼帳號不能解除 Google 綁定", r.status_code == 400 and "忘記密碼" in r.get_json()["error"])
with app.app_context():
    check("仍然是綁定狀態", db.session.execute(text("SELECT google_sub FROM `User` WHERE user_id=:u"), {"u": new_id}).scalar() == "g-new")
r = client.post("/api/auth/2fa/disable", json={"email": "new.student@example.com", "password": "x"}, headers=H)
check("無密碼帳號關閉 2FA 時提示先設定密碼", r.status_code == 400 and "忘記密碼" in r.get_json()["error"])

# ---- 用忘記密碼設定密碼後，可用密碼登入、password_set = 1 ----
with app.app_context():
    db.session.add(m.UserVerification(
        user_id=new_id, type="PASSWORD_RESET", code_hash=generate_password_hash("123456"),
        expires_at=(taiwan_now() + timedelta(minutes=10)).replace(tzinfo=None),
        target_email="new.student@example.com", is_used=False, attempts=0))
    db.session.commit()
r = client.post("/api/auth/reset-password", json={"email": "new.student@example.com", "otp": "123456", "new_password": "Brand-new1"})
check("忘記密碼流程可設定密碼", r.status_code == 200)
clear_rl()
r = client.post("/api/login", json={"email": "new.student@example.com", "password": "Brand-new1"})
check("設定後可用密碼登入", r.status_code == 200 and r.get_json().get("token"))
with app.app_context():
    check("password_set 變成 1", db.session.execute(text("SELECT password_set FROM `User` WHERE user_id=:u"), {"u": new_id}).scalar() == 1)

# ---- 頻率限制（與一般註冊共用 register_ip）----
clear_rl()
codes = [reg(cred(f"g-r{i}", f"r{i}@example.com")).status_code for i in range(7)]
check("同一 IP 短時間大量註冊會被擋（429）", 429 in codes and codes[0] == 201)

# ---- 關閉 Google 登入時一併關閉註冊 ----
clear_rl()
with mock.patch.dict("os.environ", {"GOOGLE_LOGIN_ENABLED": "0"}):
    check("GOOGLE_LOGIN_ENABLED=0 時不能註冊", reg(cred("g-off", "off@example.com")).status_code == 403)

finish()
