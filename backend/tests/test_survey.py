#!/usr/bin/env python
"""
整合測試：用真正的 app.py（含 runtime migration、所有 blueprint）建立一份問卷。

原本的腳本是在「建立問卷不需要登入、user_id 放在 body」的時代寫的，現在
建立問卷必須帶 JWT（安全修正），所以舊腳本永遠拿到 401；而且失敗時也不會
非 0 結束。這裡改成：
    - 需要 DATABASE_URL（跑真的 app.py）；沒有設定時明確 SKIP
    - 建立測試使用者、用 JWT 呼叫 POST /api/surveys，斷言 201
    - 開放式題目會記錄 routing_status（AI 不可用時為 routing_failed，問卷仍然建立成功）

    cd backend
    DATABASE_URL=mysql+pymysql://user:pass@localhost/testdb JWT_SECRET_KEY=x python3 tests/test_survey.py
"""

import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if not os.environ.get("DATABASE_URL"):
    print("SKIP: 沒有設定 DATABASE_URL，略過需要真實資料庫的建立問卷整合測試")
    sys.exit(0)
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only")

import jwt  # noqa: E402

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from models import Survey_Template, User  # noqa: E402

FAILED = []


def check(label, condition):
    print(f"[{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        FAILED.append(label)


with app.app_context():
    db.create_all()  # 空的測試資料庫：只建立缺少的表，既有表不動
    email = f"survey-test-{uuid.uuid4().hex[:8]}@example.com"
    user = User(user_name="survey-test", email=email, password_hash="x")
    db.session.add(user)
    db.session.commit()
    user_id = user.user_id

token = jwt.encode({"user_id": user_id}, os.environ["JWT_SECRET_KEY"], algorithm="HS256")
payload = {
    "title": "測試問卷標題",
    "description": "這是一個測試問卷",
    "questions": [{"id": "test-1", "type": "short", "title": "您對公司的建議？", "required": True, "options": []}],
}
with app.test_client() as client:
    resp = client.post("/api/surveys", data=json.dumps(payload), content_type="application/json")
    check("未登入不能建立問卷（401）", resp.status_code == 401)
    resp = client.post("/api/surveys", data=json.dumps(payload), content_type="application/json",
                       headers={"Authorization": f"Bearer {token}"})
    check("登入後建立問卷 201", resp.status_code == 201)

with app.app_context():
    tpl = Survey_Template.query.filter_by(user_id=user_id).first()
    item = (tpl.question_json or {}).get("items", [{}])[0] if tpl else {}
    check("問卷已寫入 DB、擁有者正確", tpl is not None and tpl.user_id == user_id)
    check("開放式題目記錄 routing 結果（routing_status）", item.get("routing_status") is not None)

print("\n" + ("全部測試通過！" if not FAILED else f"共 {len(FAILED)} 項失敗"))
os._exit(1 if FAILED else 0)  # APScheduler 背景 thread 會讓 process 不結束
