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

# ---- 無密碼帳號用忘記密碼流程設定密碼（另一個入口）----
r = reg(cred("g-fp", "forgot.user@example.com"))
fp_id = r.get_json()["user_id"]
with app.app_context():
    db.session.add(m.UserVerification(
        user_id=fp_id, type="PASSWORD_RESET", code_hash=generate_password_hash("123456"),
        expires_at=(taiwan_now() + timedelta(minutes=10)).replace(tzinfo=None),
        target_email="forgot.user@example.com", is_used=False, attempts=0))
    db.session.commit()
r = client.post("/api/auth/reset-password", json={"email": "forgot.user@example.com", "otp": "123456", "new_password": "Brand-new1"})
check("忘記密碼流程也可設定密碼", r.status_code == 200)
clear_rl()
check("設定後可用密碼登入（忘記密碼入口）", client.post("/api/login", json={"email": "forgot.user@example.com", "password": "Brand-new1"}).status_code == 200)
with app.app_context():
    check("password_set 變成 1（忘記密碼入口）", db.session.execute(text("SELECT password_set FROM `User` WHERE user_id=:u"), {"u": fp_id}).scalar() == 1)

# ---- 在個人資料頁用驗證碼設定密碼（/api/auth/google/set-password）----
def add_code(code="654321", minutes=10):
    with app.app_context():
        db.session.add(m.UserVerification(
            user_id=new_id, type="PASSWORD_RESET", code_hash=generate_password_hash(code),
            expires_at=(taiwan_now() + timedelta(minutes=minutes)).replace(tzinfo=None),
            target_email="new.student@example.com", is_used=False, attempts=0))
        db.session.commit()


SP = "/api/auth/google/set-password"
check("未登入不能設定密碼", client.post(SP, json={"otp": "1", "new_password": "Abcdef12"}).status_code == 401)
add_code()
check("缺欄位 → 400", client.post(SP, json={"otp": "654321"}, headers=H).status_code == 400)
check("弱密碼 → 400", client.post(SP, json={"otp": "654321", "new_password": "abc"}, headers=H).status_code == 400)
r = client.post(SP, json={"otp": "000000", "new_password": "Abcdef12"}, headers=H)
check("驗證碼錯誤 → 400 並顯示剩餘次數", r.status_code == 400 and "剩餘" in r.get_json()["error"])
for _ in range(5):
    client.post(SP, json={"otp": "000000", "new_password": "Abcdef12"}, headers=H)
r = client.post(SP, json={"otp": "654321", "new_password": "Abcdef12"}, headers=H)
check("錯太多次後驗證碼作廢（即使輸入正確也不行）", r.status_code in (400, 429))
add_code("111222", minutes=-1)
check("過期的驗證碼 → 400", client.post(SP, json={"otp": "111222", "new_password": "Abcdef12"}, headers=H).status_code == 400)
add_code("777888")
r = client.post(SP, json={"otp": "777888", "new_password": "Abcdef12"}, headers=H)
check("驗證碼正確可設定密碼，回傳新 token", r.status_code == 200 and r.get_json()["token"] and r.get_json()["password_set"] is True)
check("舊 token 失效", client.get("/api/auth/google/status", headers=H).status_code == 401)
H2 = {"Authorization": "Bearer " + r.get_json()["token"]}
check("新 token 可用，且 password_set = True", client.get("/api/auth/google/status", headers=H2).get_json()["password_set"] is True)
clear_rl()
check("設定後可用密碼登入", client.post("/api/login", json={"email": "new.student@example.com", "password": "Abcdef12"}).status_code == 200)
add_code("999000")
check("已經有密碼就不能再用這個入口", client.post(SP, json={"otp": "999000", "new_password": "Another12"}, headers=H2).status_code == 400)

# ---- 頻率限制（與一般註冊共用 register_ip）----
clear_rl()
codes = [reg(cred(f"g-r{i}", f"r{i}@example.com")).status_code for i in range(7)]
check("同一 IP 短時間大量註冊會被擋（429）", 429 in codes and codes[0] == 201)

# ---- 關閉 Google 登入時一併關閉註冊 ----
clear_rl()
with mock.patch.dict("os.environ", {"GOOGLE_LOGIN_ENABLED": "0"}):
    check("GOOGLE_LOGIN_ENABLED=0 時不能註冊", reg(cred("g-off", "off@example.com")).status_code == 403)

finish()
