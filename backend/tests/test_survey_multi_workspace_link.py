#!/usr/bin/env python
"""
一份問卷可以被匯入多個 workspace（多對多）：全程走 HTTP API 的整合測試。

關聯語意（見 routes/surveys/survey.py bind_survey_to_workspace）：
    問卷與 workspace 的關聯不是獨立的一對一欄位，而是「這個 workspace 裡
    有沒有任何一則 Chat_History 帶這份問卷的 template_id」。每則訊息各自帶
    template_id，同一份問卷可以出現在任意多個 workspace，彼此不會覆蓋。

流程（全部透過 Flask test client 呼叫真實路由，不直接寫 DB）：
    1. POST /api/surveys 建立問卷；POST /api/workspace 建立兩個 workspace
    2. 兩個 workspace 各自 POST /api/chat/history 儲存帶同一 template_id 的
       使用者訊息與 AI 訊息（模擬前端「匯入問卷後建立新 chat」）
    3. GET /api/chat/history/<project_id> 重新讀取兩邊：都保有 template_id，
       訊息數、內容互不影響；再匯入第三次也不會影響前兩個
    4. PATCH /api/surveys/<code>/bind 對兩個 workspace 都回 200 bound=true
    5. 聊天訊息儲存失敗（DB commit 失敗 / 參數錯誤 / 問卷不是自己的）時，
       /bind 對那個 workspace 回 409 SURVEY_NOT_LINKED，不會宣稱已關聯
    6. 刪除（移到垃圾桶）其中一個 workspace 不影響另一個的關聯

執行方式：
    cd backend
    python3 tests/test_survey_multi_workspace_link.py
"""

import os

os.environ.pop("OPEN_CLASSIFICATION_ENABLED", None)

from admin_test_support import GEMINI_QUEUE, check, create_app, finish, seed_people, user_header  # noqa: E402
from extensions import db  # noqa: E402
import models as m  # noqa: E402
from routes.surveys.survey import survey_bp  # noqa: E402
from routes.workspaces.workspace import workspace_bp  # noqa: E402

app = create_app()
app.register_blueprint(survey_bp)
app.register_blueprint(workspace_bp)
client = app.test_client()
H = user_header(1)

with app.app_context():
    seed_people()
    db.session.add(m.User(user_id=2, user_name="other", email="other@example.com", password_hash="x"))
    db.session.commit()

print("========== 1. 建立問卷與兩個 workspace（HTTP）==========")
GEMINI_QUEUE.clear()  # 建立問卷時的 routing 呼叫會失敗 -> routing_failed，不影響建立
resp = client.post("/api/surveys", headers=H, json={
    "title": "員工滿意度", "questions": [
        {"id": "q1", "type": "short", "title": "其他建議"},
        {"id": "r1", "type": "rating", "title": "整體滿意度"},
    ],
})
survey = resp.get_json()
check("建立問卷 201", resp.status_code == 201 and survey.get("template_id"))
TEMPLATE_ID, CODE = survey["template_id"], survey["access_code"]
detail = client.get(f"/api/surveys/{CODE}", headers=H).get_json()
check("問卷詳情回傳 template_id（前端匯入時用的就是這個值）", detail["template_id"] == TEMPLATE_ID)


def create_workspace(name):
    resp = client.post("/api/workspace", headers=H, json={"project_name": name})
    return resp.status_code, (resp.get_json() or {}).get("project_id")


status_a, WS_A = create_workspace("問卷分析：員工滿意度")
status_b, WS_B = create_workspace("問卷分析：員工滿意度")
check("兩個 workspace 201、project_id 不同", status_a == status_b == 201 and WS_A and WS_B and WS_A != WS_B)


def save(project_id, sender, content, template_id=TEMPLATE_ID, headers=H):
    return client.post("/api/chat/history", headers=headers, json={
        "project_id": project_id, "sender_type": sender, "message_content": content, "template_id": template_id,
    })


def history(project_id):
    resp = client.get(f"/api/chat/history/{project_id}", headers=H)
    return resp.status_code, [i for i in resp.get_json()["chat_history"] if i["type"] == "message"]


def bind(project_id, headers=H):
    resp = client.patch(f"/api/surveys/{CODE}/bind", headers=headers, json={"project_id": project_id})
    return resp.status_code, resp.get_json()


print("\n========== 2. 兩個 workspace 各自儲存帶同一 template_id 的訊息 ==========")
check("A：使用者訊息 201", save(WS_A, "user", "[問卷：員工滿意度] 觸發自動分析").status_code == 201)
check("A：AI 分析結果 201", save(WS_A, "ai", "A 的分析結果").status_code == 201)
check("B：使用者訊息 201", save(WS_B, "user", "[問卷：員工滿意度] 觸發自動分析").status_code == 201)
check("B：AI 分析結果 201", save(WS_B, "ai", "B 的分析結果").status_code == 201)

print("\n========== 3. 重新讀取兩邊的 chat history ==========")
with app.app_context():
    db.session.remove()  # 新 session 重新讀取，不靠 identity map
sa, msgs_a = history(WS_A)
sb, msgs_b = history(WS_B)
check("兩邊 GET 200", sa == sb == 200)
check("A 兩則訊息都帶 template_id", len(msgs_a) == 2 and all(i["template_id"] == TEMPLATE_ID for i in msgs_a))
check("B 兩則訊息都帶 template_id", len(msgs_b) == 2 and all(i["template_id"] == TEMPLATE_ID for i in msgs_b))
check("A / B 內容互不覆蓋", {i["content"] for i in msgs_a} >= {"A 的分析結果"} and "A 的分析結果" not in {i["content"] for i in msgs_b}
      and {i["content"] for i in msgs_b} >= {"B 的分析結果"})
check("每則訊息屬於自己的 workspace", all(i["project_id"] == WS_A for i in msgs_a) and all(i["project_id"] == WS_B for i in msgs_b))

print("\n========== 4. /bind 對兩個 workspace 都正確 ==========")
code_a, body_a = bind(WS_A)
code_b, body_b = bind(WS_B)
check("A：200 bound=true", code_a == 200 and body_a["bound"] is True and body_a["project_id"] == WS_A)
check("B：200 bound=true", code_b == 200 and body_b["bound"] is True and body_b["project_id"] == WS_B)
check("兩邊回傳同一個 template_id", body_a["template_id"] == body_b["template_id"] == TEMPLATE_ID)
check("/bind 本身不寫資料（查詢前後訊息數不變）", len(history(WS_A)[1]) == 2 and len(history(WS_B)[1]) == 2)

# 第三次匯入同一份問卷：不影響前兩個
_, WS_C = create_workspace("問卷分析：員工滿意度")
check("C：儲存 201", save(WS_C, "user", "[問卷：員工滿意度] 觸發自動分析").status_code == 201)
check("第三次匯入後 A / B 仍是 bound", bind(WS_A)[1]["bound"] is True and bind(WS_B)[1]["bound"] is True
      and bind(WS_C)[1]["bound"] is True)

print("\n========== 5. 訊息儲存失敗時 /bind 不可宣稱已關聯 ==========")
_, WS_FAIL = create_workspace("問卷分析：儲存失敗")
check("剛建立、還沒有任何訊息：409", bind(WS_FAIL)[0] == 409)

# 5-1 DB commit 失敗（例如連線中斷）：API 回 500，rollback 後沒有任何關聯
with app.app_context():
    original_commit = db.session.commit

    def failing_commit():
        raise RuntimeError("simulated DB failure")

    db.session.commit = failing_commit
    try:
        resp = save(WS_FAIL, "user", "[問卷：員工滿意度] 觸發自動分析")
    finally:
        db.session.commit = original_commit
check("DB commit 失敗：儲存 API 回 500", resp.status_code == 500)
code, body = bind(WS_FAIL)
check("DB commit 失敗後 /bind 409 SURVEY_NOT_LINKED、bound=false",
      code == 409 and body["code"] == "SURVEY_NOT_LINKED" and body["bound"] is False)

# 5-2 參數錯誤 / 別人的問卷 / 別人的 workspace：一樣不會建立關聯
check("sender_type 不合法 -> 400", save(WS_FAIL, "robot", "x").status_code == 400)
check("template_id 格式錯誤 -> 400", save(WS_FAIL, "user", "x", template_id="abc").status_code == 400)
with app.app_context():
    other_tpl = m.Survey_Template(user_id=2, title="別人的", access_code="OTH99", question_json={"items": []})
    db.session.add(other_tpl)
    db.session.commit()
    OTHER_TEMPLATE = other_tpl.template_id
check("別人的問卷 -> 403", save(WS_FAIL, "user", "x", template_id=OTHER_TEMPLATE).status_code == 403)
check("存到別人的 workspace（user 2 存 A）-> 404", save(WS_A, "user", "x", headers=user_header(2)).status_code == 404)
check("以上失敗後 /bind 仍是 409", bind(WS_FAIL)[0] == 409)
check("沒有帶 template_id 的一般訊息不算關聯", save(WS_FAIL, "user", "一般聊天", template_id=None).status_code == 201
      and bind(WS_FAIL)[0] == 409)
check("A 的訊息數沒有被失敗請求影響", len(history(WS_A)[1]) == 2)

print("\n========== 6. 刪除其中一個 workspace 不影響其他 ==========")
check("刪除 B 200", client.delete(f"/api/workspace/{WS_B}", headers=H).status_code == 200)
check("B 已刪除：/bind 404", bind(WS_B)[0] == 404)
check("A 仍然 bound", bind(WS_A)[1]["bound"] is True)

finish()
