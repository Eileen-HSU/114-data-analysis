#!/usr/bin/env python
"""
測試腳本：Human Review（Admin-only 定案後）端到端測試。

涵蓋原本需求文件第二十七節「Human Review」測試項目裡跟業務規則本身
有關、Admin-only 化之後仍然成立的部分：
    1. direct confirm → confirmed
    2. start conversation → candidate 不修改 final
    3. multiple revisions
    4. confirm reviewed candidate → modified
    5. conversation 後回到 original → 仍 modified
    6. excluded
    7. invalid classification_id
    8. AI 回傳不存在 taxonomy → reject / retry-safe
    9. Primary == Secondary → Secondary null

以及這次 Admin-only 改版新增的測試（對應本次需求文件第八節 1~12）：
    10. Admin 可以 start review 任一 classification（不分來源、不看
        Survey_Template.user_id / Uploaded_Answer.user_id）
    11. User token 無法使用 Admin Human Review API（401/403）
    12. 同一 Admin 重複 start → 回同一 session（冪等）
    13. Admin A start 後，Admin B start 同一筆 → 409，帶
        reviewing_admin_id / reviewing_admin_name
    14. 不會建立兩筆 in_progress（DB 實際查詢驗證，不只看 API 回應）
    15. message 正常（Admin-only 版本）
    16. confirm-original 正常（Admin-only 版本）
    17. confirm-candidate 正常（Admin-only 版本）
    18. exclude 正常（Admin-only 版本）
    19. history 可看到不同 Admin 的全部歷史（不因為登入者不同而過濾）
    20. Classification_Review.admin_id 正確寫入
    21. 不再依賴 User.user_id（Classification_Review 已無 user_id 欄位）
    22. 被其他 Admin 持有 session 時，message/confirm-candidate/exclude
        也一律 409（不能繞過 start 的併發檢查直接操作）

執行方式：
    cd backend
    python3 tests/test_review_service.py
"""

import sys
import os
import json

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

FAILED = []


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    if status == "FAIL":
        FAILED.append(label)
    print(f"[{status}] {label}")


# ── 假的 Gemini：monkeypatch services.gemini_client.GenerativeModel ──
# review_ai_service.py 是透過 `from services import gemini_client as genai`
# 再呼叫 `genai.GenerativeModel(...)`，正式呼叫路徑統一收斂在
# services/gemini_client.py 這一層薄封裝，所以只要在這一層換掉
# GenerativeModel 類別本身，就能讓 review 對話流程吃到假回應，不需要
# 去動 sys.modules["google"]，也不影響真正的 google-genai SDK。
import services.gemini_client as gemini_client

_queue = []


def q(obj_or_text):
    _queue.append(obj_or_text if isinstance(obj_or_text, str) else json.dumps(obj_or_text, ensure_ascii=False))


class _FakeResp:
    def __init__(self, text):
        self.text = text


class _FakeGenerativeModel:
    def __init__(self, model_name=None, system_instruction=None, **kwargs):
        pass

    def generate_content(self, contents, **kwargs):
        return _FakeResp(_queue.pop(0))


gemini_client.GenerativeModel = _FakeGenerativeModel


import jwt
from flask import Flask
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.ext.compiler import compiles

from extensions import db
import models as m
from routes.auth.admin_guard import build_admin_token
from routes.classifications.review import review_bp
from services.review_ai_service import build_review_reply


# ── SQLite 相容性 shim：MEDIUMTEXT 是 MySQL 專屬型別，這個環境的
# SQLAlchemy 版本在 SQLite 上編譯 CREATE TABLE 時不會自動 fallback 成
# TEXT。只在 sqlite 方言下生效，不影響正式環境（MySQL）。
@compiles(MEDIUMTEXT, "sqlite")
def _compile_mediumtext_sqlite(element, compiler, **kw):
    return "TEXT"


app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
app.config["TESTING"] = True
app.register_blueprint(review_bp)
db.init_app(app)

with app.app_context():
    tables = [
        m.User.__table__,
        m.Admin.__table__,
        m.Survey_Template.__table__,
        m.Survey_Response.__table__,
        m.Response_Classification.__table__,
        m.Uploaded_Answer.__table__,
        m.Classification_Review.__table__,
        m.Classification_Review_Message.__table__,
        m.Report.__table__,
    ]
    db.metadata.create_all(bind=db.engine, tables=tables)

    # User 只是 Survey_Template.user_id 的 FK 需要，Admin-only 模型下
    # 不再代表任何 review 權限。
    db.session.add(m.User(user_id=1, user_name="survey_owner", email="owner@example.com", password_hash="x"))

    db.session.add(m.Admin(admin_id=1, admin_name="審核員 Alice", email="alice@example.com", password_hash="x"))
    db.session.add(m.Admin(admin_id=2, admin_name="審核員 Bob", email="bob@example.com", password_hash="x"))
    db.session.commit()

    template = m.Survey_Template(
        title="測試問卷", access_code="RVIEW", user_id=1,
        question_json={"items": [
            {"id": "q1", "type": "short", "title": "對主管的建議", "question_type": "leadership_and_dept"},
        ]},
    )
    db.session.add(template)
    db.session.commit()
    template_id = template.template_id

    survey_response = m.Survey_Response(template_id=template_id, answer_json={"answers": {"q1": "測試回答"}})
    db.session.add(survey_response)
    db.session.commit()
    response_id = survey_response.response_id

    report_v1 = m.Report(
        source_type="survey", template_id=template_id, version=1,
        generated_by=1, status="completed", is_outdated=False,
        eligible_count_at_generation=1, pending_count_at_generation=0, excluded_count_at_generation=0,
    )
    db.session.add(report_v1)
    db.session.commit()
    report_v1_id = report_v1.report_id


client = app.test_client()


def admin_header(admin_id):
    """真正的 Admin JWT，用既有 build_admin_token()，不是自己亂拼
    payload——這樣才能同時驗證 verify_admin_token() 這一側的行為。"""
    token = build_admin_token(admin_id)
    return {"Authorization": f"Bearer {token}"}


def user_header(user_id):
    """一般 User JWT（跟 routes/surveys/survey.py 的 verify_token() 格式
    一致），用來驗證「User token 不能打 Admin Human Review API」。"""
    token = jwt.encode({"user_id": user_id}, os.environ["JWT_SECRET_KEY"], algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def make_classification(answer_text, main_category, sub_category, secondary_sub_category=None):
    with app.app_context():
        rc = m.Response_Classification(
            response_id=response_id,
            source_type="survey",
            question_id="q1",
            answer_text=answer_text,
            segment_start=0,
            segment_end=len(answer_text),
            main_category=main_category,
            sub_category=sub_category,
            secondary_sub_category=secondary_sub_category,
            reasoning="ai reasoning",
            summary="ai summary",
            methodology="互惠與責任承擔分析",
            citation="cite",
            status="completed",
        )
        db.session.add(rc)
        db.session.commit()
        return rc.classification_id


# ═══════════════════════════════════════════════════════════════
# 測試 1：direct confirm → confirmed
# ═══════════════════════════════════════════════════════════════
print("========== 測試 1：direct confirm → confirmed ==========")
cid1 = make_classification("主管很願意聽取意見", "部門合作", "B2 支援協作")

resp = client.post(f"/api/classification/{cid1}/review/confirm-original", headers=admin_header(1))
check("HTTP 200", resp.status_code == 200)
check("review_status 變成 confirmed", resp.get_json().get("review_status") == "confirmed")
with app.app_context():
    rc = m.Response_Classification.query.get(cid1)
    check("final_sub_category 仍為 None（confirmed 不寫 final_*）", rc.final_sub_category is None)

with app.app_context():
    check("confirm-original 觸發 Report v1 標記為 outdated", m.Report.query.get(report_v1_id).is_outdated is True)

resp_dup = client.post(f"/api/classification/{cid1}/review/confirm-original", headers=admin_header(1))
check("重複 confirm-original 回 409", resp_dup.status_code == 409)


# ═══════════════════════════════════════════════════════════════
# 測試 2：start conversation → candidate 不修改 final
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 2：start conversation → candidate 不修改 final ==========")
cid2 = make_classification("希望主管可以多給一些回饋，也希望增加人力", "部門合作", "B2 支援協作")

resp_start = client.post(f"/api/classification/{cid2}/review/start", headers=admin_header(1))
check("start HTTP 200", resp_start.status_code == 200)
check("start 回傳 status=in_progress", resp_start.get_json().get("status") == "in_progress")
check("start 回傳的 review 帶 admin_id=1", resp_start.get_json().get("admin_id") == 1)

q({
    "reply": "根據你的說明，我重新判斷...",
    "candidate_sub_category": "A2 回饋與溝通",
    "candidate_secondary_sub_category": None,
    "candidate_reasoning": "candidate reasoning 1",
})
resp_msg = client.post(
    f"/api/classification/{cid2}/review/message", headers=admin_header(1),
    json={"message": "我覺得這比較偏向主管的回饋與溝通方式"},
)
check("message HTTP 201", resp_msg.status_code == 201)
msg_data = resp_msg.get_json()
check("assistant 訊息帶有 candidate_main_category（查表結果）", msg_data["message"]["candidate_main_category"] == "主管領導")
check("assistant 訊息帶有 candidate_sub_category", msg_data["message"]["candidate_sub_category"] == "A2 回饋與溝通")

with app.app_context():
    rc2 = m.Response_Classification.query.get(cid2)
    check("candidate 出現後，final_sub_category 仍為 None（尚未 confirm）", rc2.final_sub_category is None)
    check("candidate 出現後，AI original main/sub 完全沒變", rc2.main_category == "部門合作" and rc2.sub_category == "B2 支援協作")
    check("review_status 仍是 pending_review（訊息本身不會改變 review_status）", rc2.review_status == "pending_review")


# ═══════════════════════════════════════════════════════════════
# 測試 3 + 4：multiple revisions → confirm reviewed candidate → modified
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 3+4：multiple revisions → confirm-candidate → modified ==========")
q({
    "reply": "了解，那我改成這個類別",
    "candidate_sub_category": "B3 權責界定與規範落實",
    "candidate_secondary_sub_category": None,
    "candidate_reasoning": "candidate reasoning 2",
})
resp_msg2 = client.post(
    f"/api/classification/{cid2}/review/message", headers=admin_header(1),
    json={"message": "其實比較像是分工不清楚的問題"},
)
check("第二輪 message HTTP 201", resp_msg2.status_code == 201)
check("第二輪 candidate 正確更新", resp_msg2.get_json()["message"]["candidate_sub_category"] == "B3 權責界定與規範落實")

resp_confirm = client.post(f"/api/classification/{cid2}/review/confirm-candidate", headers=admin_header(1))
check("confirm-candidate HTTP 200", resp_confirm.status_code == 200)
confirmed_data = resp_confirm.get_json()
check("review_status 變成 modified", confirmed_data["review_status"] == "modified")
check("final_sub_category 是最新一輪 candidate（B3，不是 A2）", confirmed_data["final_sub_category"] == "B3 權責界定與規範落實")
check("final_main_category 正確（查表結果，不是 Gemini 輸出）", confirmed_data["final_main_category"] == "部門合作")
check("AI original 完全沒被覆寫", confirmed_data["main_category"] == "部門合作" and confirmed_data["sub_category"] == "B2 支援協作")


# ═══════════════════════════════════════════════════════════════
# 測試 5：conversation 後回到 original → 仍 modified
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 5：conversation 後回到 original → 仍 modified ==========")
cid5 = make_classification("跨部門溝通不太順暢", "部門合作", "B1 溝通與協調機制")
client.post(f"/api/classification/{cid5}/review/start", headers=admin_header(1))

q({
    "reply": "我覺得可能更像支援協作的問題",
    "candidate_sub_category": "B2 支援協作",
    "candidate_secondary_sub_category": None,
    "candidate_reasoning": "候選 1",
})
client.post(f"/api/classification/{cid5}/review/message", headers=admin_header(1), json={"message": "會不會其實是支援不足？"})

q({
    "reply": "重新考慮後，我覺得原本的判斷比較準確",
    "candidate_sub_category": "B1 溝通與協調機制",
    "candidate_secondary_sub_category": None,
    "candidate_reasoning": "討論後仍確認原判斷",
})
client.post(f"/api/classification/{cid5}/review/message", headers=admin_header(1), json={"message": "想想還是原本的比較對"})

resp5 = client.post(f"/api/classification/{cid5}/review/confirm-candidate", headers=admin_header(1))
data5 = resp5.get_json()
check("即使最終候選跟 AI original 相同，review_status 仍是 modified", data5["review_status"] == "modified")
check("final_sub_category 等於 AI original（B1）", data5["final_sub_category"] == "B1 溝通與協調機制")
check("final_reasoning 有值（曾經討論過的紀錄）", bool(data5["final_reasoning"]))


# ═══════════════════════════════════════════════════════════════
# 測試 6：excluded
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 6：excluded ==========")
cid6 = make_classification("這題沒有意見", "其他與建議", "C2 無具體建議")
resp6 = client.post(f"/api/classification/{cid6}/review/exclude", headers=admin_header(1))
check("exclude HTTP 200", resp6.status_code == 200)
check("review_status 變成 excluded", resp6.get_json()["review_status"] == "excluded")


# ═══════════════════════════════════════════════════════════════
# 測試 7：invalid classification_id
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 7：invalid classification_id ==========")
resp7 = client.get("/api/classification/999999/review", headers=admin_header(1))
check("不存在的 classification_id 回 404", resp7.status_code == 404)


# ═══════════════════════════════════════════════════════════════
# 測試 8：AI 回傳不存在 taxonomy → reject / retry-safe
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 8：AI 回傳不存在 taxonomy → reject ==========")
cid8 = make_classification("希望公司多辦活動", "部門合作", "B2 支援協作")
client.post(f"/api/classification/{cid8}/review/start", headers=admin_header(1))

q({
    "reply": "這聽起來比較像是「員工福利」類別",
    "candidate_sub_category": "員工福利（不存在的類別）",
    "candidate_secondary_sub_category": None,
    "candidate_reasoning": "不應該被採用",
})
resp8b = client.post(
    f"/api/classification/{cid8}/review/message", headers=admin_header(1),
    json={"message": "這應該算員工福利吧？"},
)
check("HTTP 201（不會因為 taxonomy 不合法就整個失敗）", resp8b.status_code == 201)
data8b = resp8b.get_json()
check("taxonomy_rejected 為 True", data8b["taxonomy_rejected"] is True)
check("candidate_sub_category 沒有被採用（None）", data8b["message"]["candidate_sub_category"] is None)
check("candidate_main_category 也沒有被採用（None）", data8b["message"]["candidate_main_category"] is None)
check("自然語言回覆仍保留（對話可以繼續）", "員工福利" in data8b["message"]["content"])

with app.app_context():
    rc8 = m.Response_Classification.query.get(cid8)
    check("不合法 taxonomy 不影響 AI original", rc8.sub_category == "B2 支援協作")

resp8_confirm = client.post(f"/api/classification/{cid8}/review/confirm-candidate", headers=admin_header(1))
data8_confirm = resp8_confirm.get_json()
check("從未有合法 candidate 時，confirm-candidate fallback 回 AI original", data8_confirm["final_sub_category"] == "B2 支援協作")
check("review_status 仍是 modified（因為確實進入過對話）", data8_confirm["review_status"] == "modified")


# ═══════════════════════════════════════════════════════════════
# 測試 9：Primary == Secondary → Secondary null（review_ai_service 單元測試）
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 9：Primary == Secondary → Secondary null ==========")
q({
    "reply": "這則同時符合兩個描述，但其實是同一個類別",
    "candidate_sub_category": "B2 支援協作",
    "candidate_secondary_sub_category": "B2 支援協作",
    "candidate_reasoning": "重複",
})
result9 = build_review_reply(
    question_type="leadership_and_dept",
    segment_text="測試文字",
    ai_main_category="部門合作",
    ai_sub_category="B2 支援協作",
    ai_secondary_sub_category=None,
    ai_reasoning="r",
    candidate_sub_category="B2 支援協作",
    candidate_secondary_sub_category=None,
    conversation_history=[],
    user_message="test",
)
check("Primary == Secondary 時，secondary_sub_category 被正規化為 None", result9["candidate_secondary_sub_category"] is None)
check("Primary == Secondary 時，secondary_main_category 也被正規化為 None", result9["candidate_secondary_main_category"] is None)
check("Primary 本身仍正確保留", result9["candidate_sub_category"] == "B2 支援協作")


# ═══════════════════════════════════════════════════════════════
# 測試 10：Admin 可以 review 任一 classification（不分來源、不看 owner）
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 10：Admin 可以 review 任一 classification（不分來源）==========")
with app.app_context():
    ua = m.Uploaded_Answer(
        upload_batch_id="batch-1", user_id=1, source_column="意見", row_index=0,
        answer_text="上傳的意見內容", question_type="career_and_feedback",
    )
    db.session.add(ua)
    db.session.commit()
    ua_id = ua.id

    rc_upload = m.Response_Classification(
        upload_batch_id="batch-1", uploaded_answer_id=ua_id,
        source_type="user_upload", question_id="意見_row0",
        answer_text="上傳的意見內容", segment_start=0, segment_end=6,
        main_category="工作表現的回饋及職涯發展", sub_category="A5 教育訓練",
        reasoning="ai reasoning", summary="ai summary",
        methodology="知識賦能與趨勢接軌分析", citation="cite", status="completed",
    )
    db.session.add(rc_upload)
    db.session.commit()
    cid_upload = rc_upload.classification_id

# 這筆的 owner（Uploaded_Answer.user_id）是 1，但用 admin_id=2（跟這個
# owner 完全無關的 Admin）呼叫，Admin-only 模型下應該一樣可以存取。
resp10 = client.get(f"/api/classification/{cid_upload}/review", headers=admin_header(2))
check("Admin（跟這筆的 owner user_id 無關）仍可正常查看 review state", resp10.status_code == 200)

resp10b = client.post(f"/api/classification/{cid_upload}/review/start", headers=admin_header(2))
check("Admin（跟這筆的 owner 無關）仍可正常 start review", resp10b.status_code == 200)


# ═══════════════════════════════════════════════════════════════
# 測試 11：User token 無法使用 Admin Human Review API
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 11：User token 無法使用 Admin Human Review API ==========")
cid11 = make_classification("測試 User token 被拒絕", "部門合作", "B2 支援協作")

resp11a = client.get(f"/api/classification/{cid11}/review", headers=user_header(1))
check("User token 呼叫 GET review 被拒絕（403：token 有效但不是 admin）", resp11a.status_code == 403)

resp11b = client.post(f"/api/classification/{cid11}/review/start", headers=user_header(1))
check("User token 呼叫 start 被拒絕", resp11b.status_code == 403)

resp11c = client.post(f"/api/classification/{cid11}/review/exclude", headers=user_header(1))
check("User token 呼叫 exclude 被拒絕", resp11c.status_code == 403)

resp11d = client.get(f"/api/classification/{cid11}/review")
check("完全沒帶 token 回 401", resp11d.status_code == 401)


# ═══════════════════════════════════════════════════════════════
# 測試 12~14：Concurrent review（同一 Admin 冪等 / 不同 Admin 409 / 不會建立兩筆 in_progress）
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 12~14：Concurrent review ==========")
cid_concurrent = make_classification("測試併發控制", "部門合作", "B2 支援協作")

resp_a1 = client.post(f"/api/classification/{cid_concurrent}/review/start", headers=admin_header(1))
check("Admin A 第一次 start -> 200", resp_a1.status_code == 200)
review_id_a1 = resp_a1.get_json()["review_id"]

resp_a2 = client.post(f"/api/classification/{cid_concurrent}/review/start", headers=admin_header(1))
check("同一個 Admin A 重複 start -> 200（冪等）", resp_a2.status_code == 200)
check("同一個 Admin A 重複 start -> 回同一筆 review_id", resp_a2.get_json()["review_id"] == review_id_a1)

resp_b1 = client.post(f"/api/classification/{cid_concurrent}/review/start", headers=admin_header(2))
check("Admin B 在 Admin A 進行中時 start -> 409", resp_b1.status_code == 409)
resp_b1_data = resp_b1.get_json()
check("409 回應帶 reviewing_admin_id=1", resp_b1_data.get("reviewing_admin_id") == 1)
check("409 回應帶 reviewing_admin_name（依 Admin.admin_name 查到的值）", resp_b1_data.get("reviewing_admin_name") == "審核員 Alice")

with app.app_context():
    in_progress_count = m.Classification_Review.query.filter_by(
        classification_id=cid_concurrent, status="in_progress",
    ).count()
    check("DB 裡實際只有 1 筆 in_progress（不會因為併發 start 而建立第二筆）", in_progress_count == 1)

resp_b_message = client.post(
    f"/api/classification/{cid_concurrent}/review/message", headers=admin_header(2),
    json={"message": "Admin B 想插話"},
)
check("Admin B 被擋在 start 之後，直接呼叫 message 也一樣 409（不能繞過併發檢查）", resp_b_message.status_code == 409)

resp_b_confirm_original = client.post(
    f"/api/classification/{cid_concurrent}/review/confirm-original", headers=admin_header(2),
)
check("Admin B 呼叫 confirm-original 也被 409 擋下", resp_b_confirm_original.status_code == 409)

resp_b_exclude = client.post(f"/api/classification/{cid_concurrent}/review/exclude", headers=admin_header(2))
check("Admin B 呼叫 exclude 也被 409 擋下", resp_b_exclude.status_code == 409)

# Admin A 結束（confirm-original 不行，因為已經進入過 conversation？這裡還沒對話，
# 用 exclude 收尾，驗證 Admin A 自己可以正常操作。
resp_a_exclude = client.post(f"/api/classification/{cid_concurrent}/review/exclude", headers=admin_header(1))
check("Admin A（持有 session 的人）自己呼叫 exclude 正常 200", resp_a_exclude.status_code == 200)


# ═══════════════════════════════════════════════════════════════
# 測試 15：history 可看到不同 Admin 的全部歷史
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 15：history 顯示全部 Admin 的歷史 ==========")
cid_history = make_classification("測試歷史紀錄跨 Admin", "部門合作", "B1 溝通與協調機制")

client.post(f"/api/classification/{cid_history}/review/start", headers=admin_header(1))
client.post(f"/api/classification/{cid_history}/review/exclude", headers=admin_header(1))

# Admin A 排除後 review_status 已鎖定，改直接在 DB 塞一筆第二輪歷史
# （模擬「這筆之前曾經被排除又復原、Admin B 後來又審過一次」的情境，
# 不因為 review_status 鎖定就無法測試 history 的跨 Admin 顯示）。
with app.app_context():
    second_review = m.Classification_Review(
        classification_id=cid_history, admin_id=2, status="confirmed",
    )
    db.session.add(second_review)
    db.session.commit()

resp_history = client.get(f"/api/classification/{cid_history}/review/history", headers=admin_header(1))
check("history HTTP 200", resp_history.status_code == 200)
history_reviews = resp_history.get_json()["reviews"]
history_admin_ids = {r["admin_id"] for r in history_reviews}
check("history 包含 Admin A（admin_id=1）跟 Admin B（admin_id=2）兩筆，不因登入者是 Admin A 就過濾掉 B 的", history_admin_ids == {1, 2})
check(
    "每筆 history 都帶 admin_name",
    all(r.get("admin_name") in ("審核員 Alice", "審核員 Bob") for r in history_reviews),
)

# 用 Admin B 的身分查同一筆 history，結果應該完全一樣（不因登入者不同而變）
resp_history_b = client.get(f"/api/classification/{cid_history}/review/history", headers=admin_header(2))
check("Admin B 查同一筆 history，結果跟 Admin A 查到的一樣（不依登入者過濾）", resp_history_b.get_json() == resp_history.get_json())


# ═══════════════════════════════════════════════════════════════
# 測試 16：Classification_Review.admin_id 正確寫入、不再依賴 User.user_id
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 16：schema 層驗證 ==========")
check(
    "Classification_Review model 已經沒有 user_id 欄位",
    not hasattr(m.Classification_Review, "user_id"),
)
check(
    "Classification_Review model 有 admin_id 欄位",
    hasattr(m.Classification_Review, "admin_id"),
)
with app.app_context():
    review_row = m.Classification_Review.query.filter_by(classification_id=cid2).first()
    check("實際寫入 DB 的 review row，admin_id 正確等於呼叫時傳入的 Admin", review_row.admin_id == 1)
    check("to_dict() 回傳 admin_id、不回傳 user_id", "admin_id" in review_row.to_dict() and "user_id" not in review_row.to_dict())


print("\n" + "=" * 50)
if FAILED:
    print(f"共 {len(FAILED)} 項測試失敗：")
    for f in FAILED:
        print("  -", f)
    sys.exit(1)
else:
    print("全部測試通過！")
