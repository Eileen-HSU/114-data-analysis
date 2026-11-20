#!/usr/bin/env python
"""頻率限制與登入安全：DB 計數、登入冷卻、驗證碼寄送、帳號列舉、問卷大小限制。"""

import os
from unittest import mock

from werkzeug.security import generate_password_hash

from admin_test_support import check, create_app, finish, seed_people
import models as m
from extensions import db
from rate_limit_models import RateLimitCounter
from services import rate_limit_service as rl
from routes.auth.login import login_bp
from routes.auth.pwd import pwd_bp
from routes.auth.two_factor import two_factor_bp
from routes.auth.register import register_bp
from routes.surveys.survey import survey_bp, response_size_limit

app = create_app()
for bp, prefix in ((login_bp, None), (pwd_bp, None), (two_factor_bp, "/api/auth/2fa"),
                   (register_bp, None), (survey_bp, None)):
    if bp.name not in app.blueprints:
        app.register_blueprint(bp, url_prefix=prefix) if prefix else app.register_blueprint(bp)
client = app.test_client()

with app.app_context():
    seed_people()
    u = db.session.get(m.User, 1)
    u.password_hash = generate_password_hash("pw-123456")
    db.session.commit()
    db.metadata.create_all(bind=db.engine, tables=[RateLimitCounter.__table__])

# ---- 計數核心 ----
with app.app_context():
    results = [rl.hit("t", "x", 3, 60, now=1000)[0] for _ in range(5)]
    check("第 3 次仍通過、第 4 次起拒絕", results == [True, True, True, False, False])
    ok, wait = rl.hit("t", "x", 3, 60, now=1010)
    check("回傳剩餘冷卻秒數（不超過時間窗）", (not ok) and 1 <= wait <= 60)
    check("下一個時間窗自動恢復", rl.hit("t", "x", 3, 60, now=1000 + 120)[0] is True)
    check("不同識別互不影響", rl.hit("t", "other", 3, 60, now=1000)[0] is True)
    row = db.session.query(RateLimitCounter).first()
    check("key 不含明文識別", "x" not in row.counter_key.split(":")[1] or len(row.counter_key.split(":")[1]) == 32)
    n = rl.purge_expired(now=10**10)
    check("過期計數可清除", n >= 1 and db.session.query(RateLimitCounter).count() == 0)

# ---- 登入 ----
def login(pw, email="owner@example.com"):
    return client.post("/api/login", json={"email": email, "password": pw})

r = None
for i in range(5):
    r = login("wrong")
    if i < 4:
        check(f"錯誤密碼 #{i+1} -> 401 且不顯示剩餘次數",
              r.status_code == 401 and "剩餘" not in (r.get_json() or {}).get("error", ""))
check("第 5 次錯誤立刻回 429 冷卻（不用等到第 6 次）", r.status_code == 429)
r = login("pw-123456")
check("達上限後即使密碼正確也冷卻 429", r.status_code == 429 and r.headers.get("Retry-After"))
check("429 訊息不含剩餘次數與重設旗標", "require_password_reset" not in (r.get_json() or {}))

with app.app_context():
    db.session.query(RateLimitCounter).delete(); db.session.commit()
check("冷卻結束（計數清除）後可登入", login("pw-123456").status_code == 200)

for _ in range(3):
    login("wrong")
login("pw-123456")
with app.app_context():
    keys = [r.counter_key for r in db.session.query(RateLimitCounter).all()]
check("登入成功只清帳號計數、保留 IP 計數",
      not any(k.startswith("login_account:") for k in keys) and any(k.startswith("login_ip:") for k in keys))

# 帳號列舉：不存在的帳號與錯密碼回應相同
r1 = login("wrong", "nobody@example.com").get_json()
r2 = login("wrong").get_json()
check("不存在帳號與錯誤密碼訊息相同", r1 == r2)

# ---- IP 上限 ----
with app.app_context():
    db.session.query(RateLimitCounter).delete(); db.session.commit()
with mock.patch.dict(os.environ, {"RL_LOGIN_IP_MAX": "3"}):
    codes = [login("wrong", f"u{i}@example.com").status_code for i in range(5)]
check("同 IP 超過上限後換帳號也被擋", codes[:2] == [401, 401] and codes[2:] == [429, 429, 429])

# ---- 寄送驗證碼 ----
with app.app_context():
    db.session.query(RateLimitCounter).delete(); db.session.commit()
sent = []
with mock.patch("routes.auth.pwd.send_email_via_brevo", lambda *a, **k: sent.append(a)):
    r_known = client.post("/api/auth/send-otp", json={"email": "owner@example.com"})
    r_unknown = client.post("/api/auth/send-otp", json={"email": "ghost@example.com"})
    check("send-otp 已註冊/未註冊回應相同（防列舉）",
          r_known.status_code == 200 and r_unknown.status_code == 200 and r_known.get_json() == r_unknown.get_json())
    check("只對已註冊帳號寄信", len(sent) == 1)
    r_again = client.post("/api/auth/send-otp", json={"email": "owner@example.com"})
    check("同 email 60 秒內再寄 -> 429", r_again.status_code == 429)

with app.app_context():
    db.session.query(RateLimitCounter).delete(); db.session.commit()
with mock.patch("routes.auth.two_factor.send_email_via_brevo", lambda *a, **k: None):
    a = client.post("/api/auth/2fa/send", json={"email": "owner@example.com"})
    b = client.post("/api/auth/2fa/send", json={"email": "owner@example.com"})
    check("2FA 寄送：第二次 60 秒內被擋（改存資料庫）", a.status_code == 200 and b.status_code == 429)

# ---- 註冊 ----
with app.app_context():
    db.session.query(RateLimitCounter).delete(); db.session.commit()
codes = [client.post("/api/register", json={"user_name": "測試者", "email": f"r{i}@example.com", "password": "abc12345", "phone_number": "0900", "gender": "男"}).status_code
         for i in range(7)]
check("註冊同 IP 每小時 5 次，之後 429", codes[:5] == [201] * 5 and codes[5:] == [429, 429])

# ---- 關閉 2FA ----
from routes.auth.login import build_token
with app.app_context():
    db.session.query(RateLimitCounter).delete(); db.session.commit()
    tok = build_token(1)
H = {"Authorization": f"Bearer {tok}"}
last = None
for i in range(6):
    last = client.post("/api/auth/2fa/disable", json={"email": "owner@example.com", "password": "bad"}, headers=H)
    if i == 0:
        check("關閉 2FA 錯誤密碼不顯示剩餘次數", last.status_code == 403 and "剩餘" not in last.get_json()["error"])
check("關閉 2FA 失敗 5 次後冷卻 429", last.status_code == 429)

# ---- 問卷 ----
with app.app_context():
    db.session.query(RateLimitCounter).delete()
    db.session.add(m.Survey_Template(
        title="s", access_code="ABC123", user_id=1, is_anonymous=True,
        question_json={"identity_mode": "anonymous", "items": [
            {"id": "q1", "type": "short", "title": "a"}, {"id": "q2", "type": "long", "title": "b"}]}))
    db.session.commit()

import json as _json

def submit(body_json=None, **kw):
    if body_json is not None:  # 瀏覽器的 JSON.stringify 不會把中文轉成 \\uXXXX，這裡比照
        kw = dict(kw, data=_json.dumps(body_json, ensure_ascii=False).encode("utf-8"), content_type="application/json")
    return client.post("/api/surveys/ABC123/responses", **kw)

check("正常送出 201", submit({"answers": {"q1": "hi", "q2": "ok"}}).status_code == 201)
check("不屬於問卷的欄位 400", submit({"answers": {"q9": "x"}}).status_code == 400)
check("單題超過 10,000 字 400", submit({"answers": {"q1": "字" * 10001}}).status_code == 400)
check("剛好 10,000 字可通過", submit({"answers": {"q1": "a" * 10000}}).status_code == 201)
check("巢狀物件答案 400", submit({"answers": {"q1": {"a": 1}}}).status_code == 400)
check("response_size_limit：2 題 80KB、30 題上限 1MB",
      response_size_limit(2) == 80 * 1024 and response_size_limit(30) == 1024 * 1024)
big = submit(None, data=b"x" * (1024 * 1024 + 10), content_type="application/json")
check("超過 1MB 在解析前就 413", big.status_code == 413)
two_q_big = submit({"answers": {"q1": "a" * 9000, "q2": "b" * 9000, "pad": "x"}})  # 不屬於問卷
check("2 題問卷含未知欄位仍被拒", two_q_big.status_code == 400)
long_ok = [submit({"answers": {"q1": "你" * 9000, "q2": "好" * 9000}}).status_code]
check("2 題各 9000 中文字（UTF-8 約 54KB）< 80KB 可通過", long_ok == [201])
over = submit({"answers": {"q1": "你" * 10000, "q2": "好" * 10000}})
check("2 題各 10000 中文字（約 60KB）仍在 80KB 內", over.status_code == 201)
with app.app_context():
    db.session.query(RateLimitCounter).delete(); db.session.commit()
codes = [submit({"answers": {"q1": "x"}}).status_code for _ in range(62)]
check("問卷 60 次/分鐘：第 61 次起 429", codes[:60].count(201) == 60 and codes[60] == 429)
r = submit({"answers": {"q1": "x"}})
check("429 附 Retry-After", r.status_code == 429 and r.headers.get("Retry-After"))

finish()
