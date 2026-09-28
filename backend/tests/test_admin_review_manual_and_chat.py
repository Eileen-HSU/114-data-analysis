#!/usr/bin/env python
"""
審核對話：直接選擇分類 + 跟 AI 溝通的修正。

涵蓋：
    1. GET review 回傳 taxonomy_options（動態 taxonomy：該版 categories）
    2. legacy 分類（taxonomy_version_id IS NULL）也有選項（legacy 表），
       AI 對話可以提出合法候選（原本清單是空的，建議全被拒絕）
    3. 問卷題目沒有存 question_type，但分類有 taxonomy version：仍可跟 AI 對話
    4. confirm-manual：不需對話即可指定分類 -> modified、main_category 由清單決定、
       次要子類別、判斷原因、關閉 session、audit、報告 outdated
    5. confirm-manual 拒絕清單外的分類 / failed / 已定案 / 別人審核中
    6. AI 服務失敗（503 / 額度不足）：對話不中斷，回應帶中文 ai_error
    7. 完全沒有分類清單時，送訊息回 422 NO_TAXONOMY_OPTIONS（中文說明）

執行方式：
    cd backend
    python3 tests/test_admin_review_manual_and_chat.py
"""

from admin_test_support import (
    GEMINI_QUEUE, admin_header, check, create_app, finish, q, seed_classification, seed_people,
    seed_topic, seed_upload_batch,
)
import models as m
from extensions import db

app = create_app()
client = app.test_client()

with app.app_context():
    seed_people()
    version_id = seed_topic()
    ids = seed_upload_batch("batch-manual", [f"回答{i}" for i in range(8)])

    def mk(i, **kw):
        return seed_classification(ids[i], "batch-manual", f"回答{i}", "Main A", "A1 Original", version_id=version_id, **kw)

    c_manual = mk(0)
    c_failed = mk(1, status="failed")
    c_done = mk(2, review_status="confirmed")
    c_other = mk(3)
    c_busy = mk(4)
    # legacy：問卷來源、taxonomy_version_id NULL、question_type=career_and_feedback
    template = m.Survey_Template(user_id=1, title="t", access_code="LEGAC", question_json={"items": [
        {"id": "q1", "type": "short", "title": "t", "question_type": "career_and_feedback"},
        {"id": "q2", "type": "short", "title": "no routing", "question_type": None},
    ]})
    db.session.add(template)
    db.session.flush()
    resp_row = m.Survey_Response(template_id=template.template_id, answer_json={"answers": {}})
    db.session.add(resp_row)
    db.session.flush()
    legacy = m.Response_Classification(
        response_id=resp_row.response_id, source_type="survey", question_id="q1", answer_text="希望多一點教育訓練",
        segment_start=0, segment_end=9, main_category="工作表現的回饋及職涯發展", sub_category="A5 教育訓練",
        reasoning="r", status="completed",
    )
    no_qtype = m.Response_Classification(
        response_id=resp_row.response_id, source_type="survey", question_id="q2", answer_text="主管溝通不錯",
        segment_start=0, segment_end=6, main_category="Main A", sub_category="A1 Original",
        reasoning="r", status="completed", taxonomy_version_id=version_id,
    )
    no_options = m.Response_Classification(
        response_id=resp_row.response_id, source_type="survey", question_id="q2", answer_text="完全沒有清單",
        segment_start=0, segment_end=6, main_category="X", sub_category="Y", reasoning="r", status="completed",
    )
    db.session.add_all([legacy, no_qtype, no_options])
    db.session.add(m.Report(source_type="user_upload", upload_batch_id="batch-manual", version=1, status="completed", is_outdated=False))
    db.session.commit()
    c_legacy, c_no_qtype, c_no_options = legacy.classification_id, no_qtype.classification_id, no_options.classification_id


def state(cid, admin=1):
    return client.get(f"/api/classification/{cid}/review", headers=admin_header(admin)).get_json()


print("========== 1/2. taxonomy_options ==========")
opts = state(c_manual)["taxonomy_options"]
check("動態 taxonomy 的選項", {o["sub_category"] for o in opts} == {"A1 Original", "B1 Candidate"})
legacy_opts = state(c_legacy)["taxonomy_options"]
check("legacy 分類也有選項（legacy 表）", any(o["sub_category"] == "A5 教育訓練" for o in legacy_opts) and len(legacy_opts) > 3)

client.post(f"/api/classification/{c_legacy}/review/start", headers=admin_header(1))
q({"reply": "比較像職涯規劃", "candidate_sub_category": legacy_opts[0]["sub_category"],
   "candidate_secondary_sub_category": None, "candidate_reasoning": "legacy 候選"})
resp = client.post(f"/api/classification/{c_legacy}/review/message", headers=admin_header(1), json={"message": "改一下"})
check("legacy 對話 201", resp.status_code == 201)
check("legacy 對話可以提出合法候選（不再全部被拒絕）",
      resp.get_json()["message"]["candidate_sub_category"] == legacy_opts[0]["sub_category"]
      and resp.get_json()["taxonomy_rejected"] is False)


print("\n========== 3. 題目沒有 question_type 仍可對話 ==========")
client.post(f"/api/classification/{c_no_qtype}/review/start", headers=admin_header(1))
q({"reply": "好", "candidate_sub_category": "B1 Candidate", "candidate_secondary_sub_category": None, "candidate_reasoning": "x"})
resp = client.post(f"/api/classification/{c_no_qtype}/review/message", headers=admin_header(1), json={"message": "改 B1"})
check("用 taxonomy version 的 topic 對話 -> 201", resp.status_code == 201 and resp.get_json()["message"]["candidate_sub_category"] == "B1 Candidate")


print("\n========== 4. confirm-manual ==========")
client.post(f"/api/classification/{c_manual}/review/start", headers=admin_header(1))
resp = client.post(f"/api/classification/{c_manual}/review/confirm-manual", headers=admin_header(1), json={
    "sub_category": "B1 Candidate", "secondary_sub_category": "A1 Original", "reasoning": "其實在講支援",
})
body = resp.get_json()
check("confirm-manual 200 -> modified", resp.status_code == 200 and body["review_status"] == "modified")
check("final_main_category 由清單決定（Main B）", body["final_main_category"] == "Main B" and body["final_sub_category"] == "B1 Candidate")
check("次要子類別與原因寫入", body["final_secondary_sub_category"] == "A1 Original" and body["final_reasoning"] == "其實在講支援")
with app.app_context():
    check("session 已結束（沒有 in_progress）",
          m.Classification_Review.query.filter_by(classification_id=c_manual, status="in_progress").count() == 0)
    audit = m.Admin_Audit_Log.query.filter_by(entity_id=str(c_manual), action="modify").one()
    check("audit：manual_selection + 原因 + admin", audit.admin_id == 1 and audit.reason.startswith("manual_selection"))
    check("報告 outdated", m.Report.query.filter_by(upload_batch_id="batch-manual").first().outdated_reason == "classification_modified")
resp = client.post(f"/api/classification/{c_other}/review/confirm-manual", headers=admin_header(1), json={"sub_category": "A1 Original"})
check("沒開過 session 也可以直接指定", resp.status_code == 200 and resp.get_json()["final_reasoning"] == "管理員直接指定分類")


print("\n========== 5. confirm-manual 拒絕情況 ==========")
def manual(cid, admin=1, **payload):
    return client.post(f"/api/classification/{cid}/review/confirm-manual", headers=admin_header(admin), json=payload)

check("清單外的子類別 -> 400 INVALID_CATEGORY", manual(c_busy, sub_category="自創類別").get_json()["code"] == "INVALID_CATEGORY")
check("沒選 -> 400 INVALID_CATEGORY", manual(c_busy).get_json()["code"] == "INVALID_CATEGORY")
check("failed -> 409 CLASSIFICATION_FAILED", manual(c_failed, sub_category="A1 Original").get_json()["code"] == "CLASSIFICATION_FAILED")
check("已定案 -> 409 ALREADY_FINALIZED", manual(c_done, sub_category="A1 Original").get_json()["code"] == "ALREADY_FINALIZED")
client.post(f"/api/classification/{c_busy}/review/start", headers=admin_header(2))
check("別人審核中 -> 409 REVIEW_IN_PROGRESS_BY_OTHER",
      manual(c_busy, sub_category="A1 Original").get_json()["code"] == "REVIEW_IN_PROGRESS_BY_OTHER")


print("\n========== 6. AI 服務失敗：對話不中斷、中文說明 ==========")
GEMINI_QUEUE.clear()
q(RuntimeError("503 UNAVAILABLE high demand"), RuntimeError("503 UNAVAILABLE high demand"), RuntimeError("503 UNAVAILABLE high demand"))
resp = client.post(f"/api/classification/{c_busy}/review/message", headers=admin_header(2), json={"message": "請說明"})
body = resp.get_json()
check("仍然 201（對話保存）", resp.status_code == 201)
check("ai_error：AI_SERVICE_BUSY 中文說明", body["ai_error"]["code"] == "AI_SERVICE_BUSY" and "使用量過高" in body["ai_error"]["message"])
check("AI 回覆文字是中文說明", body["message"]["content"].startswith("AI 暫時無法回覆"))
GEMINI_QUEUE.clear()


print("\n========== 7. 沒有分類清單 ==========")
client.post(f"/api/classification/{c_no_options}/review/start", headers=admin_header(1))
resp = client.post(f"/api/classification/{c_no_options}/review/message", headers=admin_header(1), json={"message": "hi"})
check("422 NO_TAXONOMY_OPTIONS 且訊息為中文", resp.status_code == 422 and resp.get_json()["code"] == "NO_TAXONOMY_OPTIONS"
      and "直接選擇分類" in resp.get_json()["message"])
check("taxonomy_options 為空陣列", state(c_no_options)["taxonomy_options"] == [])

finish()
