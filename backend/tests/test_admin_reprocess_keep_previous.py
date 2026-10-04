#!/usr/bin/env python
"""
Admin 重新處理：新結果不可用時保留舊結果；零片段失敗在 Admin 清單可見並可重試。

涵蓋：
    A. Excel 上傳後拆分失敗（有 Response_Segmentation_Status、零筆
       Response_Classification）：
       - 不在 unrouted 分頁，但出現在 failed 分頁（target=answer、有失敗原因）
       - counts 一致、answer detail 看得到拆分狀態
       - 從 failed 分頁重試：再次失敗 -> 不建立新 attempt、持久化診斷、仍在清單
       - 重試成功 -> 寫入分類、attempt_no +1、離開 failed 分頁
       - 再次重試 -> 409 ALREADY_CLASSIFIED，只有一份 current attempt
    B. 既有有效結果 + 重新分類全部失敗 -> 舊 current classification 不被 superseded，
       自己的審核對話維持進行中，last_attempt_error / audit 記錄失敗
    C. 既有有效結果 + 重新分類零片段（拆分呼叫失敗）-> 同 B
    D. 成功重跑 -> 舊列 superseded、新列 current、attempt_no +1、審核對話關閉
    E. 有人工審核資料（confirmed + final_*）-> 409，資料與 audit 不變；
       有審核歷史（reopen 後 pending）+ 重新處理失敗 -> 審核紀錄完整保留

執行方式：
    cd backend
    python3 tests/test_admin_reprocess_keep_previous.py
"""

import io
import os

import pandas as pd

from admin_test_support import (
    GEMINI_QUEUE, admin_header, check, create_app, finish, q, seed_classification, seed_people, seed_topic,
    seed_failed_retry, seed_upload_batch, user_header,
)
import models as m
from extensions import db
from services.privacy_service import mask_pii

os.environ.pop("OPEN_CLASSIFICATION_ENABLED", None)
app = create_app()
client = app.test_client()

with app.app_context():
    seed_people()
    version_id = seed_topic("custom_topic")


def classify_ok(text, main="Main A", sub="A1 Original"):
    q({"segments": [mask_pii(text)]})
    q({"classifications": [{"index": 0, "main_category": main, "sub_category": sub, "secondary_sub_category": None,
                             "reasoning": "r", "summary": "s", "confidence": 0.93}]})


def classify_all_failed(text):
    # 拆分成功，分類呼叫一直失敗 -> 每個片段 status=failed
    q({"segments": [mask_pii(text)]})
    q(*[RuntimeError("classification boom")] * 6)


def segmentation_failed():
    q(*[RuntimeError("segmentation boom")] * 6)


def failed_items():
    body = client.get("/api/admin/ai/unassigned?kind=failed&page_size=100", headers=admin_header(1)).get_json()
    return body


def status_row(answer_id):
    return m.Response_Segmentation_Status.query.filter_by(uploaded_answer_id=answer_id).one()


def current_rows(answer_id):
    return [r for r in m.Response_Classification.query.filter_by(uploaded_answer_id=answer_id).all()
            if r.status != "superseded"]


print("========== A. Excel 零片段失敗：Admin 看得到、可安全重試 ==========")
GEMINI_QUEUE.clear()
q({"question_type": "custom_topic"})
segmentation_failed()
df = pd.DataFrame({"意見": ["希望多一點教育訓練"]})
buf = io.BytesIO()
df.to_excel(buf, index=False)
buf.seek(0)
resp = client.post("/api/classification/upload", data={"file": (buf, "u.xlsx"), "text_column": "意見"},
                   headers=user_header(1), content_type="multipart/form-data")
upload = resp.get_json()
check("upload 201", resp.status_code == 201)
GEMINI_QUEUE.clear()
with app.app_context():
    answer = m.Uploaded_Answer.query.filter_by(upload_batch_id=upload["upload_batch_id"]).one()
    zero_id = answer.id
    check("前提：有 status 列、沒有任何 Response_Classification",
          status_row(zero_id).segmentation_status == "failed"
          and m.Response_Classification.query.filter_by(uploaded_answer_id=zero_id).count() == 0)
    # 「無法分類」清單只列自動重試仍失敗的資料：補上失敗的重試紀錄（沒有紀錄代表還在排程重試）
    seed_failed_retry(zero_id)

unrouted = client.get("/api/admin/ai/unassigned?kind=unrouted", headers=admin_header(1)).get_json()
check("不在 unrouted 分頁（已經分析過）", zero_id not in {i["id"] for i in unrouted["items"]})
body = failed_items()
item = next((i for i in body["items"] if i.get("target") == "answer" and i["id"] == zero_id), None)
check("出現在 failed 分頁（target=answer）", item is not None)
check("清單項目顯示原始回答與失敗原因",
      item is not None and item["segment"] == "希望多一點教育訓練" and "segmentation boom" in item["reason"]
      and item["failure"] is not None and item["classification_id"] is None)
check("counts.failed 包含零片段失敗", body["counts"]["failed"] == body["total"] == 1)
detail = client.get(f"/api/admin/ai/unassigned/answers/{zero_id}", headers=admin_header(1)).get_json()
check("answer detail 顯示拆分狀態", detail["segmentation"]["segmentation_status"] == "failed")

segmentation_failed()
resp = client.post(f"/api/admin/ai/unassigned/answers/{zero_id}/retry", headers=admin_header(1))
res = resp.get_json()
GEMINI_QUEUE.clear()
check("重試仍失敗：200、succeeded=False", resp.status_code == 200 and res["succeeded"] is False)
with app.app_context():
    st = status_row(zero_id)
    check("仍失敗：不建立新 attempt、沒有分類列", st.attempt_no == 1 and not current_rows(zero_id))
    check("仍失敗：診斷持久化（last_attempt_error / routing_detail）",
          "segmentation boom" in (st.last_attempt_error or "") and st.last_attempt_at is not None
          and db.session.get(m.Uploaded_Answer, zero_id).routing_status == "classification_failed")
check("仍失敗：還在 failed 分頁", any(i.get("target") == "answer" and i["id"] == zero_id for i in failed_items()["items"]))

classify_ok("希望多一點教育訓練")
resp = client.post(f"/api/admin/ai/unassigned/answers/{zero_id}/retry", headers=admin_header(1))
GEMINI_QUEUE.clear()
check("重試成功：200、succeeded", resp.status_code == 200 and resp.get_json()["succeeded"] is True)
with app.app_context():
    st = status_row(zero_id)
    rows = current_rows(zero_id)
    check("重試成功：attempt_no=2、1 筆 current 分類", st.attempt_no == 2 and len(rows) == 1 and rows[0].attempt_no == 2)
    check("重試成功：status completed、清除 last_attempt_error",
          st.segmentation_status == "completed" and st.last_attempt_error is None)
check("重試成功：離開 failed 分頁", not any(i.get("target") == "answer" and i["id"] == zero_id for i in failed_items()["items"]))
resp = client.post(f"/api/admin/ai/unassigned/answers/{zero_id}/retry", headers=admin_header(1))
check("再次重試 -> 409 ALREADY_CLASSIFIED", resp.status_code == 409 and resp.get_json()["code"] == "ALREADY_CLASSIFIED")
with app.app_context():
    check("仍只有一份 current attempt", len(current_rows(zero_id)) == 1 and status_row(zero_id).attempt_no == 2)
resp = client.post("/api/admin/ai/unassigned/answers/999999/retry", headers=admin_header(1))
check("不存在的回答 -> 404", resp.status_code == 404)
check("非 admin 不能重試", client.post(f"/api/admin/ai/unassigned/answers/{zero_id}/retry", headers=user_header(1)).status_code == 403)


def seed_valid(batch, text):
    with app.app_context():
        ids = seed_upload_batch(batch, [text], question_type="custom_topic")
        cid = seed_classification(ids[0], batch, text, "Main A", "A1 Original", version_id=version_id)
        return ids[0], cid


def assert_kept(label, answer_id, cid, res, marker):
    check(f"{label}：回應 succeeded=False、kept_previous", res.get("succeeded") is False and res.get("kept_previous") is True)
    check(f"{label}：回應帶回原本的 current classification",
          [c["classification_id"] for c in res.get("classifications", [])] == [cid])
    with app.app_context():
        old = db.session.get(m.Response_Classification, cid)
        rows = current_rows(answer_id)
        st = status_row(answer_id)
        check(f"{label}：舊列仍是 current（沒有 superseded）", old.status == "completed" and [r.classification_id for r in rows] == [cid])
        check(f"{label}：沒有多寫任何失敗列", m.Response_Classification.query.filter_by(uploaded_answer_id=answer_id).count() == 1)
        check(f"{label}：attempt_no 不變、status 不變", st.attempt_no == 1 and st.segmentation_status == "completed")
        check(f"{label}：last_attempt_error 持久化", marker in (st.last_attempt_error or "") and st.last_attempt_at is not None)
        answer = db.session.get(m.Uploaded_Answer, answer_id)
        check(f"{label}：回答的 routing 狀態不被改成失敗（舊結果仍有效）",
              answer.routing_status == "routed" and answer.question_type == "custom_topic")
        audit = m.Admin_Audit_Log.query.filter_by(entity_id=str(answer_id)).order_by(m.Admin_Audit_Log.audit_id.desc()).first()
        check(f"{label}：audit 記錄 kept_previous", audit is not None and (audit.after_state or {}).get("outcome") == "kept_previous")


print("\n========== B. 有效結果 + 重新分類全部失敗 -> 保留舊結果 ==========")
b_answer, b_cid = seed_valid("batch-b", "主管很願意溝通")
client.post(f"/api/classification/{b_cid}/review/start", headers=admin_header(1))
classify_all_failed("主管很願意溝通")
resp = client.post(f"/api/admin/ai/classifications/{b_cid}/reclassify", headers=admin_header(1), json={"topic_key": "custom_topic"})
GEMINI_QUEUE.clear()
check("B：200", resp.status_code == 200)
assert_kept("B", b_answer, b_cid, resp.get_json(), "classification boom")
with app.app_context():
    review = m.Classification_Review.query.filter_by(classification_id=b_cid).one()
    check("B：自己的審核對話維持進行中（沒有被 superseded 關閉）", review.status == "in_progress" and review.closed_reason is None)


print("\n========== C. 有效結果 + 零片段（拆分失敗）-> 保留舊結果 ==========")
c_answer, c_cid = seed_valid("batch-c", "薪水太低")
segmentation_failed()
resp = client.post(f"/api/admin/ai/classifications/{c_cid}/reclassify", headers=admin_header(1), json={"topic_key": "custom_topic"})
GEMINI_QUEUE.clear()
check("C：200", resp.status_code == 200)
assert_kept("C", c_answer, c_cid, resp.get_json(), "segmentation boom")


print("\n========== D. 成功重跑 -> 取代舊結果 ==========")
classify_ok("主管很願意溝通", sub="B1 Candidate", main="Main B")
resp = client.post(f"/api/admin/ai/classifications/{b_cid}/reclassify", headers=admin_header(1), json={"topic_key": "custom_topic"})
GEMINI_QUEUE.clear()
res = resp.get_json()
check("D：200、succeeded", resp.status_code == 200 and res["succeeded"] is True and not res.get("kept_previous"))
with app.app_context():
    old = db.session.get(m.Response_Classification, b_cid)
    rows = current_rows(b_answer)
    st = status_row(b_answer)
    check("D：舊列 superseded（保留歷史）", old.status == "superseded")
    check("D：新列 current、attempt_no=2", len(rows) == 1 and rows[0].sub_category == "B1 Candidate" and rows[0].attempt_no == 2)
    check("D：status attempt_no=2、清除上一次的失敗診斷", st.attempt_no == 2 and st.last_attempt_error is None)
    review = m.Classification_Review.query.filter_by(classification_id=b_cid).one()
    check("D：成功後審核對話才關閉（closed_reason=superseded）", review.status == "closed" and review.closed_reason == "superseded")


print("\n========== E. 人工審核資料 ==========")
with app.app_context():
    e_ids = seed_upload_batch("batch-e", ["希望彈性上班"], question_type="custom_topic")
    e_cid = seed_classification(e_ids[0], "batch-e", "希望彈性上班", "Main A", "A1 Original", version_id=version_id,
                                review_status="confirmed", final_main_category="Main B", final_sub_category="B1 Candidate")
    audit_before = m.Admin_Audit_Log.query.count()
resp = client.post(f"/api/admin/ai/classifications/{e_cid}/reclassify", headers=admin_header(1), json={"topic_key": "custom_topic"})
check("E：confirmed -> 409 REPROCESS_BLOCKED_BY_REVIEW", resp.status_code == 409 and resp.get_json()["code"] == "REPROCESS_BLOCKED_BY_REVIEW")
with app.app_context():
    row = db.session.get(m.Response_Classification, e_cid)
    check("E：人工審核結果與 final_* 不變",
          row.status == "completed" and row.review_status == "confirmed" and row.final_sub_category == "B1 Candidate")
    check("E：沒有新增 audit、沒有新列", m.Admin_Audit_Log.query.count() == audit_before
          and m.Response_Classification.query.filter_by(uploaded_answer_id=e_ids[0]).count() == 1)

# 有審核歷史（reopen 後回到 pending）+ 重新處理失敗：審核紀錄完整保留
with app.app_context():
    h_ids = seed_upload_batch("batch-h", ["加班太多"], question_type="custom_topic")
    h_cid = seed_classification(h_ids[0], "batch-h", "加班太多", "Main A", "A1 Original", version_id=version_id)
client.post(f"/api/classification/{h_cid}/review/start", headers=admin_header(1))
with app.app_context():
    reviews_before = [(r.review_id, r.status) for r in m.Classification_Review.query.filter_by(classification_id=h_cid).all()]
classify_all_failed("加班太多")
resp = client.post(f"/api/admin/ai/classifications/{h_cid}/reclassify", headers=admin_header(1), json={"topic_key": "custom_topic"})
GEMINI_QUEUE.clear()
check("E：有審核對話 + 失敗 -> kept_previous", resp.status_code == 200 and resp.get_json().get("kept_previous") is True)
with app.app_context():
    reviews_after = [(r.review_id, r.status) for r in m.Classification_Review.query.filter_by(classification_id=h_cid).all()]
    check("E：審核紀錄完整保留", reviews_before == reviews_after and reviews_after)
    check("E：原分類仍是 current", db.session.get(m.Response_Classification, h_cid).status == "completed")

finish()
