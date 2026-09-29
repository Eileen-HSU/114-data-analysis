#!/usr/bin/env python
"""
問卷 <-> 工作區關聯：PATCH /api/surveys/<code>/bind 不可以假成功。

資料模型：問卷與工作區的關聯是 Chat_History.template_id（由
POST /api/chat/history 寫入）。/bind 以前不驗證工作區擁有權、不寫任何
資料就回「綁定成功」；現在只回報真實狀態。

涵蓋：
    1. 還沒有關聯 -> 409 SURVEY_NOT_LINKED（bound=false），不是假的成功
    2. 別人的工作區 / 已刪除工作區 / 不存在 / 別人的問卷 / 缺 project_id / 未登入
    3. POST /api/chat/history 帶 template_id：只能關聯自己的問卷（403 / 404 / 400）
    4. 帶自己的 template_id 存對話後，重新讀取（新 session）仍查得到關聯：
       /bind 200 bound=true、GET /api/chat/history 帶 template_id

執行方式：
    cd backend
    python3 tests/test_survey_workspace_bind.py
"""

from admin_test_support import check, create_app, finish, seed_people, user_header
import models as m
from extensions import db
from routes.surveys.survey import survey_bp

app = create_app()
app.register_blueprint(survey_bp)
client = app.test_client()

with app.app_context():
    seed_people()
    db.session.add(m.User(user_id=2, user_name="other", email="other@example.com", password_hash="x"))
    db.session.add_all([
        m.Workspace(project_id=11, user_id=1, project_name="我的工作區"),
        m.Workspace(project_id=12, user_id=1, project_name="已刪除", is_deleted=True),
        m.Workspace(project_id=21, user_id=2, project_name="別人的工作區"),
        m.Survey_Template(template_id=5, user_id=1, title="我的問卷", access_code="MINE1", question_json={"items": []}),
        m.Survey_Template(template_id=6, user_id=2, title="別人的問卷", access_code="OTHR1", question_json={"items": []}),
    ])
    db.session.commit()


def bind(code, project_id, user=1):
    return client.patch(f"/api/surveys/{code}/bind", json={"project_id": project_id}, headers=user_header(user))


print("========== 1. 沒有關聯時不能回報成功 ==========")
resp = bind("MINE1", 11)
body = resp.get_json()
check("409 SURVEY_NOT_LINKED、bound=false", resp.status_code == 409 and body["code"] == "SURVEY_NOT_LINKED" and body["bound"] is False)
with app.app_context():
    check("沒有寫入任何資料", m.Chat_History.query.count() == 0)

print("\n========== 2. 擁有權 / 參數驗證 ==========")
check("別人的工作區 -> 403", bind("MINE1", 21).status_code == 403)
check("已刪除工作區 -> 404", bind("MINE1", 12).status_code == 404)
check("不存在的工作區 -> 404", bind("MINE1", 999).status_code == 404)
check("別人的問卷 -> 403", bind("OTHR1", 11).status_code == 403)
check("不存在的問卷 -> 404", bind("NOPE1", 11).status_code == 404)
check("缺 project_id -> 400", client.patch("/api/surveys/MINE1/bind", json={}, headers=user_header(1)).status_code == 400)
check("project_id 格式錯誤 -> 400", bind("MINE1", "abc").status_code == 400)
check("未登入 -> 401", client.patch("/api/surveys/MINE1/bind", json={"project_id": 11}).status_code == 401)


def save_chat(template_id, project_id=11, user=1):
    return client.post("/api/chat/history", headers=user_header(user), json={
        "project_id": project_id, "sender_type": "user", "message_content": "[問卷] 觸發自動分析",
        "template_id": template_id,
    })


print("\n========== 3. 對話紀錄只能關聯自己的問卷 ==========")
check("別人的問卷 template_id -> 403", save_chat(6).status_code == 403)
check("不存在的 template_id -> 404", save_chat(999).status_code == 404)
check("template_id 格式錯誤 -> 400", save_chat("abc").status_code == 400)
with app.app_context():
    check("被拒絕時沒有寫入", m.Chat_History.query.count() == 0)
check("不帶 template_id 的一般對話照常 201", save_chat(None).status_code == 201)

print("\n========== 4. 真正的關聯：存對話後重新讀取仍在 ==========")
resp = save_chat(5)
check("帶自己的 template_id 存對話 201", resp.status_code == 201 and resp.get_json()["chat_history"]["template_id"] == 5)
with app.app_context():
    db.session.remove()  # 模擬重新整理：新的 session 重新讀取
    check("DB 裡 Chat_History 關聯存在", m.Chat_History.query.filter_by(project_id=11, template_id=5).count() == 1)
resp = bind("MINE1", 11)
body = resp.get_json()
check("/bind 200、bound=true、回傳 template_id", resp.status_code == 200 and body["bound"] is True and body["template_id"] == 5)
history = client.get("/api/chat/history/11", headers=user_header(1)).get_json()
items = history.get("chat_history") or []
check("重新讀取對話紀錄仍帶 template_id", any(i.get("template_id") == 5 for i in items))
check("別人查不到這個工作區的關聯", bind("MINE1", 11, user=2).status_code == 403)

finish()
