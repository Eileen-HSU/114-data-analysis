#!/usr/bin/env python
"""
測試腳本：Human Review（Phase 3）端到端測試。

涵蓋需求文件第二十七節「Human Review」測試項目 1~10：
    1. direct confirm → confirmed
    2. start conversation → candidate 不修改 final
    3. multiple revisions
    4. confirm reviewed candidate → modified
    5. conversation 後回到 original → 仍 modified
    6. excluded
    7. unauthorized user 不可 review
    8. invalid classification_id
    9. AI 回傳不存在 taxonomy → reject / retry-safe
    10. Primary == Secondary → Secondary null

以及 Report Outdated 集中 helper 的觸發驗證（呼應 Phase 1 修正三）。

執行方式：
    cd backend
    export JWT_SECRET_KEY=test-secret
    python3 test_review_service.py
"""

import sys
import os
import types
import json

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only")
sys.path.insert(0, os.path.dirname(__file__))

FAILED = []


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    if status == "FAIL":
        FAILED.append(label)
    print(f"[{status}] {label}")


# ── 假的 google.generativeai：依序從佇列吐出回應（比照既有測試風格）──
_queue = []


class _FakeResp:
    def __init__(self, text):
        self.text = text


class _FakeModel:
    def __init__(self, system_instruction=None, **kwargs):
        self.system_instruction = system_instruction

    def generate_content(self, prompt, **kwargs):
        return _FakeResp(_queue.pop(0))


_fake_genai = types.ModuleType("google.generativeai")
_fake_genai.GenerativeModel = _FakeModel
_fake_genai.configure = lambda **kwargs: None
_fake_google = types.ModuleType("google")
_fake_google.generativeai = _fake_genai
sys.modules["google"] = _fake_google
sys.modules["google.generativeai"] = _fake_genai


def q(obj_or_text):
    _queue.append(obj_or_text if isinstance(obj_or_text, str) else json.dumps(obj_or_text, ensure_ascii=False))


import jwt
from flask import Flask
from extensions import db
import models as m
from routes.classifications.review import review_bp
from services.review_ai_service import build_review_reply

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
app.config["TESTING"] = True
app.register_blueprint(review_bp)
db.init_app(app)

with app.app_context():
    tables = [
        m.User.__table__,
        m.Survey_Template.__table__,
        m.Survey_Response.__table__,
        m.Response_Classification.__table__,
        m.Uploaded_Answer.__table__,
        m.Classification_Review.__table__,
        m.Classification_Review_Message.__table__,
        m.Report.__table__,
    ]
    db.metadata.create_all(bind=db.engine, tables=tables)

    db.session.add(m.User(user_id=1, user_name="owner", email="owner@example.com", password_hash="x"))
    db.session.add(m.User(user_id=2, user_name="stranger", email="stranger@example.com", password_hash="x"))
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


def auth_header(user_id):
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

resp = client.post(f"/api/classification/{cid1}/review/confirm-original", headers=auth_header(1))
check("HTTP 200", resp.status_code == 200)
check("review_status 變成 confirmed", resp.get_json().get("review_status") == "confirmed")
with app.app_context():
    rc = m.Response_Classification.query.get(cid1)
    check("final_sub_category 仍為 None（confirmed 不寫 final_*）", rc.final_sub_category is None)

# Report v1 應該被標記 outdated
with app.app_context():
    check("confirm-original 觸發 Report v1 標記為 outdated", m.Report.query.get(report_v1_id).is_outdated is True)

# 已確認過的不能再確認
resp_dup = client.post(f"/api/classification/{cid1}/review/confirm-original", headers=auth_header(1))
check("重複 confirm-original 回 409", resp_dup.status_code == 409)


# ═══════════════════════════════════════════════════════════════
# 測試 2：start conversation → candidate 不修改 final
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 2：start conversation → candidate 不修改 final ==========")
cid2 = make_classification("希望主管可以多給一些回饋，也希望增加人力", "部門合作", "B2 支援協作")

resp_start = client.post(f"/api/classification/{cid2}/review/start", headers=auth_header(1))
check("start HTTP 200", resp_start.status_code == 200)
check("start 回傳 status=in_progress", resp_start.get_json().get("status") == "in_progress")

q({
    "reply": "根據你的說明，我重新判斷...",
    "candidate_sub_category": "A2 回饋與溝通",
    "candidate_secondary_sub_category": None,
    "candidate_reasoning": "candidate reasoning 1",
})
resp_msg = client.post(
    f"/api/classification/{cid2}/review/message", headers=auth_header(1),
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
    f"/api/classification/{cid2}/review/message", headers=auth_header(1),
    json={"message": "其實比較像是分工不清楚的問題"},
)
check("第二輪 message HTTP 201", resp_msg2.status_code == 201)
check("第二輪 candidate 正確更新", resp_msg2.get_json()["message"]["candidate_sub_category"] == "B3 權責界定與規範落實")

resp_confirm = client.post(f"/api/classification/{cid2}/review/confirm-candidate", headers=auth_header(1))
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
client.post(f"/api/classification/{cid5}/review/start", headers=auth_header(1))

q({
    "reply": "我覺得可能更像支援協作的問題",
    "candidate_sub_category": "B2 支援協作",
    "candidate_secondary_sub_category": None,
    "candidate_reasoning": "候選 1",
})
client.post(f"/api/classification/{cid5}/review/message", headers=auth_header(1), json={"message": "會不會其實是支援不足？"})

q({
    "reply": "重新考慮後，我覺得原本的判斷比較準確",
    "candidate_sub_category": "B1 溝通與協調機制",
    "candidate_secondary_sub_category": None,
    "candidate_reasoning": "討論後仍確認原判斷",
})
client.post(f"/api/classification/{cid5}/review/message", headers=auth_header(1), json={"message": "想想還是原本的比較對"})

resp5 = client.post(f"/api/classification/{cid5}/review/confirm-candidate", headers=auth_header(1))
data5 = resp5.get_json()
check("即使最終候選跟 AI original 相同，review_status 仍是 modified", data5["review_status"] == "modified")
check("final_sub_category 等於 AI original（B1）", data5["final_sub_category"] == "B1 溝通與協調機制")
check("final_reasoning 有值（曾經討論過的紀錄）", bool(data5["final_reasoning"]))


# ═══════════════════════════════════════════════════════════════
# 測試 6：excluded
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 6：excluded ==========")
cid6 = make_classification("這題沒有意見", "其他與建議", "C2 無具體建議")
resp6 = client.post(f"/api/classification/{cid6}/review/exclude", headers=auth_header(1))
check("exclude HTTP 200", resp6.status_code == 200)
check("review_status 變成 excluded", resp6.get_json()["review_status"] == "excluded")


# ═══════════════════════════════════════════════════════════════
# 測試 7：unauthorized user 不可 review
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 7：unauthorized user 不可 review ==========")
resp7 = client.get(f"/api/classification/{cid1}/review", headers=auth_header(2))
check("非 owner 存取回 403", resp7.status_code == 403)

resp7b = client.post(f"/api/classification/{cid1}/review/exclude", headers=auth_header(2))
check("非 owner 呼叫 exclude 也回 403", resp7b.status_code == 403)

resp7c = client.get(f"/api/classification/{cid1}/review")
check("完全沒帶 token 回 401", resp7c.status_code == 401)


# ═══════════════════════════════════════════════════════════════
# 測試 8：invalid classification_id
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 8：invalid classification_id ==========")
resp8 = client.get("/api/classification/999999/review", headers=auth_header(1))
check("不存在的 classification_id 回 404", resp8.status_code == 404)


# ═══════════════════════════════════════════════════════════════
# 測試 9：AI 回傳不存在 taxonomy → reject / retry-safe
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 9：AI 回傳不存在 taxonomy → reject ==========")
cid9 = make_classification("希望公司多辦活動", "部門合作", "B2 支援協作")
client.post(f"/api/classification/{cid9}/review/start", headers=auth_header(1))

q({
    "reply": "這聽起來比較像是「員工福利」類別",
    "candidate_sub_category": "員工福利（不存在的類別）",
    "candidate_secondary_sub_category": None,
    "candidate_reasoning": "不應該被採用",
})
resp9 = client.post(
    f"/api/classification/{cid9}/review/message", headers=auth_header(1),
    json={"message": "這應該算員工福利吧？"},
)
check("HTTP 201（不會因為 taxonomy 不合法就整個失敗）", resp9.status_code == 201)
data9 = resp9.get_json()
check("taxonomy_rejected 為 True", data9["taxonomy_rejected"] is True)
check("candidate_sub_category 沒有被採用（None）", data9["message"]["candidate_sub_category"] is None)
check("candidate_main_category 也沒有被採用（None）", data9["message"]["candidate_main_category"] is None)
check("自然語言回覆仍保留（對話可以繼續）", "員工福利" in data9["message"]["content"])

with app.app_context():
    rc9 = m.Response_Classification.query.get(cid9)
    check("不合法 taxonomy 不影響 AI original", rc9.sub_category == "B2 支援協作")

# 不合法 candidate 之後，confirm-candidate 應該 fallback 回 AI original（因為從未有合法 candidate）
resp9_confirm = client.post(f"/api/classification/{cid9}/review/confirm-candidate", headers=auth_header(1))
data9_confirm = resp9_confirm.get_json()
check("從未有合法 candidate 時，confirm-candidate fallback 回 AI original", data9_confirm["final_sub_category"] == "B2 支援協作")
check("review_status 仍是 modified（因為確實進入過對話）", data9_confirm["review_status"] == "modified")


# ═══════════════════════════════════════════════════════════════
# 測試 10：Primary == Secondary → Secondary null（review_ai_service 單元測試）
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 10：Primary == Secondary → Secondary null ==========")
q({
    "reply": "這則同時符合兩個描述，但其實是同一個類別",
    "candidate_sub_category": "B2 支援協作",
    "candidate_secondary_sub_category": "B2 支援協作",
    "candidate_reasoning": "重複",
})
result10 = build_review_reply(
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
check("Primary == Secondary 時，secondary_sub_category 被正規化為 None", result10["candidate_secondary_sub_category"] is None)
check("Primary == Secondary 時，secondary_main_category 也被正規化為 None", result10["candidate_secondary_main_category"] is None)
check("Primary 本身仍正確保留", result10["candidate_sub_category"] == "B2 支援協作")


# ═══════════════════════════════════════════════════════════════
# 額外：user_upload 來源的 ownership 檢查（Uploaded_Answer.user_id）
# ═══════════════════════════════════════════════════════════════
print("\n========== 額外：user_upload 來源 ownership ==========")
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

resp_owner = client.get(f"/api/classification/{cid_upload}/review", headers=auth_header(1))
check("user_upload 來源，owner 可以存取", resp_owner.status_code == 200)

resp_stranger = client.get(f"/api/classification/{cid_upload}/review", headers=auth_header(2))
check("user_upload 來源，非 owner 回 403", resp_stranger.status_code == 403)

with app.app_context():
    ua_legacy = m.Uploaded_Answer(
        upload_batch_id="batch-legacy", user_id=None, source_column="意見", row_index=0,
        answer_text="舊資料沒有owner", question_type="career_and_feedback",
    )
    db.session.add(ua_legacy)
    db.session.commit()
    ua_legacy_id = ua_legacy.id

    rc_legacy = m.Response_Classification(
        upload_batch_id="batch-legacy", uploaded_answer_id=ua_legacy_id,
        source_type="user_upload", question_id="意見_row0",
        answer_text="舊資料沒有owner", segment_start=0, segment_end=5,
        main_category="工作表現的回饋及職涯發展", sub_category="A5 教育訓練",
        status="completed",
    )
    db.session.add(rc_legacy)
    db.session.commit()
    cid_legacy = rc_legacy.classification_id

resp_legacy = client.get(f"/api/classification/{cid_legacy}/review", headers=auth_header(1))
check("舊資料 user_id=None 時，任何人都無法通過 ownership 檢查（回 403，不是意外放行）", resp_legacy.status_code == 403)


print("\n" + "=" * 50)
if FAILED:
    print(f"共 {len(FAILED)} 項測試失敗：")
    for f in FAILED:
        print("  -", f)
    sys.exit(1)
else:
    print("全部測試通過！")
