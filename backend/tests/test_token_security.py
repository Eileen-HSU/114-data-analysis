#!/usr/bin/env python
"""Token 效期（10 小時）、版本號失效（改密碼／登出）、CSP 回報、安全標頭。"""

import json
import os
import time
from datetime import datetime
from unittest import mock

import jwt
from werkzeug.security import generate_password_hash

from admin_test_support import admin_header, check, create_app, finish, seed_people
import models as m
from extensions import db
from security_models import CspViolation
from routes.auth.login import login_bp, build_token
from routes.auth.pwd import pwd_bp
from routes.users.profile import profile_bp
from routes.security import init_security, _normalize, _host_path
import routes.security as sec

app = create_app()
for bp in (login_bp, pwd_bp, profile_bp):
    if bp.name not in app.blueprints:
        app.register_blueprint(bp)
init_security(app)
client = app.test_client()
with app.app_context():
    seed_people()
    db.session.get(m.User, 1).password_hash = generate_password_hash("pw-123456")
    db.session.commit()
    db.metadata.create_all(bind=db.engine, tables=[CspViolation.__table__])

SECRET = os.environ["JWT_SECRET_KEY"]

# ---- 效期 ----
r = client.post("/api/login", json={"email": "owner@example.com", "password": "pw-123456"})
tok = r.get_json()["token"]
p = jwt.decode(tok, SECRET, algorithms=["HS256"])
remain = p["exp"] - time.time()
check("預設效期 10 小時（以 UTC 計，不再多 8 小時）", 10 * 3600 - 120 < remain <= 10 * 3600 + 5)
check("token 帶版本號 tv=0", p.get("tv") == 0)
with mock.patch.dict(os.environ, {"AUTH_TOKEN_TTL_HOURS": "2"}):
    with app.app_context():
        t2 = jwt.decode(build_token(1), SECRET, algorithms=["HS256"])
check("效期可用環境變數調整", 2 * 3600 - 120 < t2["exp"] - time.time() <= 2 * 3600 + 5)
with mock.patch.dict(os.environ, {"AUTH_TOKEN_TTL_HOURS": "abc"}):
    with app.app_context():
        t3 = jwt.decode(build_token(1), SECRET, algorithms=["HS256"])
check("環境變數無效時退回 10 小時", t3["exp"] - time.time() > 9 * 3600)

H = {"Authorization": f"Bearer {tok}"}
check("新 token 可呼叫需登入 API", client.get("/api/profile/1", headers=H).status_code == 200)

old_style = jwt.encode({"user_id": 1, "exp": time.time() + 3600}, SECRET, algorithm="HS256")
check("沒有 tv 的舊 token 在版本 0 時仍可用",
      client.get("/api/profile/1", headers={"Authorization": f"Bearer {old_style}"}).status_code == 200)

# ---- 登出使 token 失效 ----
r = client.post("/api/auth/logout", headers=H)
check("登出 200", r.status_code == 200)
check("登出後舊 token 立即 401", client.get("/api/profile/1", headers=H).status_code == 401)
check("登出後舊（無 tv）token 也失效",
      client.get("/api/profile/1", headers={"Authorization": f"Bearer {old_style}"}).status_code == 401)
tok2 = client.post("/api/login", json={"email": "owner@example.com", "password": "pw-123456"}).get_json()["token"]
check("重新登入後新 token 可用", client.get("/api/profile/1", headers={"Authorization": f"Bearer {tok2}"}).status_code == 200)
check("登出不帶 token -> 401", client.post("/api/auth/logout").status_code == 401)
check("登出帶無效 token 不報錯", client.post("/api/auth/logout", headers={"Authorization": "Bearer xxx"}).status_code == 200)

# ---- 改密碼使 token 失效 ----
H2 = {"Authorization": f"Bearer {tok2}"}
with app.app_context():
    from routes.auth.pwd import _invalidate_old_codes  # noqa
    db.session.add(m.UserVerification(
        user_id=1, type="PASSWORD_RESET", code_hash=generate_password_hash("123456"),
        expires_at=datetime(2099, 1, 1), target_email="owner@example.com", is_used=False, attempts=0))
    db.session.commit()
r = client.post("/api/auth/reset-password", json={"email": "owner@example.com", "otp": "123456", "new_password": "newpass999"})
check("重設密碼成功", r.status_code == 200)
check("改密碼後舊 token 立即 401", client.get("/api/profile/1", headers=H2).status_code == 401)

# ---- Admin token 效期 ----
adm = admin_header(1)["Authorization"].split()[1]
pa = jwt.decode(adm, SECRET, algorithms=["HS256"])
check("Admin token 效期也是 10 小時（UTC）", 9 * 3600 < pa["exp"] - time.time() <= 10 * 3600 + 5)

# ---- 安全標頭 ----
r = client.get("/api/auth/email-config")
check("API 回應有 X-Content-Type-Options: nosniff", r.headers.get("X-Content-Type-Options") == "nosniff")
check("http 請求不送 HSTS", "Strict-Transport-Security" not in r.headers)
r = client.get("/api/auth/email-config", headers={"X-Forwarded-Proto": "https"})
check("https 請求送 HSTS", "max-age=" in r.headers.get("Strict-Transport-Security", ""))

# ---- CSP 回報 ----
legacy = {"csp-report": {"document-uri": "https://app.example/profile?token=SECRET", "violated-directive": "img-src 'self'",
                          "effective-directive": "img-src", "blocked-uri": "https://evil.example/a.png?x=1#f"}}
check("舊式回報 204", client.post("/api/csp-report", data=json.dumps(legacy), content_type="application/csp-report").status_code == 204)
client.post("/api/csp-report", data=json.dumps(legacy), content_type="application/csp-report")
modern = [{"type": "csp-violation", "body": {"effectiveDirective": "script-src-elem", "blockedURL": "inline",
                                              "documentURL": "https://app.example/x?y=1"}}]
client.post("/api/csp-report", data=json.dumps(modern), content_type="application/reports+json")
with app.app_context():
    rows = {r.directive: r for r in db.session.query(CspViolation).all()}
check("相同違規合併計數", rows["img-src"].hit_count == 2)
check("網址只存網域與路徑（去掉查詢參數與 fragment）",
      rows["img-src"].blocked == "evil.example/a.png" and rows["img-src"].document_path == "/profile")
check("inline 等特殊值照存", rows["script-src-elem"].blocked == "inline")
check("垃圾內容不報錯", client.post("/api/csp-report", data="not json").status_code == 204)
check("超過 10KB 拒絕 413", client.post("/api/csp-report", data=b"x" * (10 * 1024 + 1)).status_code == 413)
sec._hits.clear()
codes = [client.post("/api/csp-report", data="{}").status_code for _ in range(32)]
check("回報端點有頻率限制", codes[:30].count(204) == 30 and codes[30] == 429)
sec._hits.clear()
with mock.patch.object(sec, "MAX_DISTINCT_VIOLATIONS", 3):
    for i in range(6):
        client.post("/api/csp-report", data=json.dumps({"csp-report": {"effective-directive": f"d{i}", "blocked-uri": "x"}}))
with app.app_context():
    check("不同違規種類有上限", db.session.query(CspViolation).count() <= 3)

# ---- Admin 彙總 ----
check("彙總需要 Admin", client.get("/api/admin/security/csp").status_code == 401)
check("一般使用者 token 不可看", client.get("/api/admin/security/csp", headers={"Authorization": f"Bearer {tok2}"}).status_code in (401, 403))
body = client.get("/api/admin/security/csp", headers=admin_header(1)).get_json()
check("彙總回傳模式與明細", body["mode"] == "report-only" and body["items"] and body["total_reports"] >= 3)
with mock.patch.dict(os.environ, {"CSP_MODE": "enforce"}):
    check("CSP_MODE=enforce 反映在彙總", client.get("/api/admin/security/csp", headers=admin_header(1)).get_json()["mode"] == "enforce")

finish()
