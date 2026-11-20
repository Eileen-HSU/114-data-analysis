#!/usr/bin/env python
"""Google 帳號綁定與登入：簽章／aud／iss 驗證、email 必須相同、需密碼（+2FA 驗證碼）、未綁定拒絕、Admin 不適用。"""

import time
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest import mock

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from werkzeug.security import generate_password_hash

from admin_test_support import check, create_app, finish, seed_people
import models as m
from extensions import db
from rate_limit_models import RateLimitCounter
import routes.auth.google_auth as ga
from routes.auth.login import login_bp, build_token

app = create_app()
if login_bp.name not in app.blueprints:
    app.register_blueprint(login_bp)
ga.init_google_auth(app)
client = app.test_client()

with app.app_context():
    seed_people()
    u = db.session.get(m.User, 1)
    u.password_hash = generate_password_hash("pw-123456")
    owner_email = u.email
    db.session.commit()
    db.metadata.create_all(bind=db.engine, tables=[RateLimitCounter.__table__])
    tok = build_token(1)
H = {"Authorization": f"Bearer {tok}"}

key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
CID = ga.google_client_id()


def cred(sub="g-1", email=None, verified=True, aud=CID, iss="https://accounts.google.com", exp_in=600, signer=key):
    now = int(time.time())
    return jwt.encode({"sub": sub, "email": email or owner_email, "email_verified": verified, "aud": aud,
                       "iss": iss, "iat": now, "exp": now + exp_in}, signer, algorithm="RS256")


fake_jwk = SimpleNamespace(get_signing_key_from_jwt=lambda t: SimpleNamespace(key=key.public_key()))
ga._jwk_client = fake_jwk
sent = []
mock.patch("routes.auth.pwd.send_email_via_brevo", lambda to, subj, body: sent.append(subj)).start()


def clear_rl():
    with app.app_context():
        db.session.query(RateLimitCounter).delete(); db.session.commit()


# ---- token 驗證 ----
with app.app_context():
    p = ga.verify_google_credential(cred())
check("合法 ID token 驗證通過", p["sub"] == "g-1")
for name, c in [("aud 不是自己的 Client ID", cred(aud="someone-else")),
                ("iss 不是 Google", cred(iss="https://evil.example")),
                ("已過期", cred(exp_in=-3600)),
                ("簽章不符", cred(signer=other_key)),
                ("不是 JWT", "not-a-token")]:
    try:
        ga.verify_google_credential(c); ok = False
    except ga.GoogleTokenError:
        ok = True
    check(f"拒絕：{name}", ok)
try:
    ga._identity(ga.verify_google_credential(cred(verified=False))); ok = False
except ga.GoogleTokenError:
    ok = True
check("拒絕：email_verified 不是 true", ok)

check("config 回傳 Client ID", client.get("/api/auth/google/config").get_json()["client_id"] == CID)

# ---- 未綁定不能 Google 登入 ----
r = client.post("/api/auth/google/login", json={"credential": cred()})
check("未綁定 Google 登入 -> 403 並提示先綁定", r.status_code == 403 and r.get_json()["code"] == "GOOGLE_NOT_BOUND")
clear_rl()

# ---- 綁定 ----
check("未登入不能綁定", client.post("/api/auth/google/bind", json={"credential": cred(), "password": "pw-123456"}).status_code == 401)
r = client.post("/api/auth/google/bind", json={"credential": cred(), "password": "bad"}, headers=H)
check("密碼錯誤不能綁定", r.status_code == 403)
r = client.post("/api/auth/google/bind", json={"credential": cred(email="other@example.com"), "password": "pw-123456"}, headers=H)
check("email 不同不能綁定", r.status_code == 400 and "完全相同" in r.get_json()["error"])
r = client.post("/api/auth/google/bind", json={"credential": cred(email=owner_email.upper() + " "), "password": "pw-123456"}, headers=H)
check("email 大小寫／空白不同視為相同，可綁定", r.status_code == 200)
check("綁定寄通知信", any("已綁定" in s for s in sent))
check("狀態顯示已綁定", client.get("/api/auth/google/status", headers=H).get_json()["bound"] is True)

# ---- Google 登入 ----
sent.clear()
r = client.post("/api/auth/google/login", json={"credential": cred()})
body = r.get_json()
check("已綁定可 Google 登入，不需驗證碼", r.status_code == 200 and body["token"] and body["user_id"] == 1 and "require_2fa" not in body)
check("Google 登入寄通知信", any("Google 登入" in s for s in sent))
r = client.post("/api/auth/google/login", json={"credential": cred(sub="g-unknown")})
check("其他 Google 帳號（未綁定）仍被拒", r.status_code == 403)
clear_rl()

# ---- 同一 Google 帳號不能綁兩個系統帳號 ----
with app.app_context():
    db.session.add(m.User(user_id=2, user_name="second", email="second@example.com", password_hash=generate_password_hash("pw-2")))
    db.session.commit()
    email2 = "second@example.com"
    tok2 = build_token(2)
r = client.post("/api/auth/google/bind", json={"credential": cred(sub="g-1", email=email2), "password": "pw-2"},
                headers={"Authorization": f"Bearer {tok2}"})
check("已綁定他人的 Google 帳號不能再綁", r.status_code == 409)

# ---- 2FA 使用者綁定需驗證碼 ----
with app.app_context():
    u2 = db.session.get(m.User, 2); u2.email_2fa_enabled = True
    db.session.add(m.UserVerification(user_id=2, type="2FA", code_hash=generate_password_hash("654321"),
                                      expires_at=datetime(2099, 1, 1), target_email=email2, is_used=False, attempts=0))
    db.session.commit()
H2 = {"Authorization": f"Bearer {tok2}"}
r = client.post("/api/auth/google/bind", json={"credential": cred(sub="g-2", email=email2), "password": "pw-2"}, headers=H2)
check("開啟 2FA 未給驗證碼 -> 要求驗證碼", r.status_code == 400 and r.get_json().get("require_otp"))
r = client.post("/api/auth/google/bind", json={"credential": cred(sub="g-2", email=email2), "password": "pw-2", "otp": "000000"}, headers=H2)
check("驗證碼錯誤不能綁定", r.status_code == 400)
r = client.post("/api/auth/google/bind", json={"credential": cred(sub="g-2", email=email2), "password": "pw-2", "otp": "654321"}, headers=H2)
check("驗證碼正確可綁定", r.status_code == 200)
clear_rl()

# ---- 解除綁定 ----
check("解除綁定密碼錯誤 403", client.post("/api/auth/google/unbind", json={"password": "x"}, headers=H).status_code == 403)
sent.clear()
r = client.post("/api/auth/google/unbind", json={"password": "pw-123456"}, headers=H)
check("解除綁定成功並寄信", r.status_code == 200 and any("解除" in s for s in sent))
check("解除後不能 Google 登入", client.post("/api/auth/google/login", json={"credential": cred()}).status_code == 403)
clear_rl()

# ---- email 變更自動解除 ----
client.post("/api/auth/google/bind", json={"credential": cred(sub="g-1"), "password": "pw-123456"}, headers=H)
with app.app_context():
    db.session.get(m.User, 1).email = "changed@example.com"; db.session.commit()
r = client.post("/api/auth/google/login", json={"credential": cred(sub="g-1")})
check("帳號 email 變更後 Google 登入被拒並自動解除", r.status_code == 403)
with app.app_context():
    check("google_sub 已清除", ga._get_sub(1) is None)
clear_rl()

# ---- Admin 不適用：Google 登入只查 User 表 ----
with app.app_context():
    admin = db.session.query(m.Admin).first()
    admin_email = admin.email if admin else "admin@example.com"
r = client.post("/api/auth/google/login", json={"credential": cred(sub="g-admin", email=admin_email)})
check("Admin email 的 Google 帳號不能登入", r.status_code == 403)
clear_rl()

# ---- 頻率限制 ----
codes = [client.post("/api/auth/google/login", json={"credential": "bad"}).status_code for _ in range(22)]
check("Google 登入失敗計入同 IP 限制", 429 in codes)
clear_rl()
codes = [client.post("/api/auth/google/bind", json={"credential": cred(), "password": "bad"}, headers=H).status_code for _ in range(6)]
check("綁定輸錯密碼多次後冷卻", codes[-1] == 429)

finish()
