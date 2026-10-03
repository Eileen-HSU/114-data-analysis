#!/usr/bin/env python
"""
P0-3 integration：routing failure 的上傳回答能被 Admin 看見並恢復。

    upload -> unrouted -> Admin 指派 Topic -> classification -> Workspace / Report

另外涵蓋：
    - Uploaded_Answer.question_type 在 routing 失敗時存 NULL（不再寫入 "other"），
      routing_status 精準記錄原因（unrouted / routing_failed / taxonomy_unavailable）
    - 未分類頁三個分頁（unrouted / failed / legacy_other）分開計數，server-side 分頁
    - 指派 Topic 防止重複建立 classification（ALREADY_CLASSIFIED）
    - fail-closed：draft taxonomy 不可用、沒有 published taxonomy 的 Topic 不分類
    - failed retry：舊列 superseded（保留 attempt history）、不重複計數
    - 已有人工定案的回答不可重新處理（REPROCESS_BLOCKED_BY_REVIEW）
    - legacy question_id="other" 分類可指派 Topic 重新分類
    - reroute
    - 所有動作 audit + report outdated（classification_rerun）
    - 重新整理（新 session）後狀態一致

執行方式：
    cd backend
    python3 tests/test_admin_unrouted_recovery.py
"""

import io

import pandas as pd

from admin_test_support import (
    GEMINI_QUEUE, admin_header, check, create_app, finish, q, seed_classification, seed_people,
    seed_topic, seed_upload_batch, seed_workspace_chat, user_header,
)
import models as m
from extensions import db
from services.privacy_service import mask_pii

app = create_app()
client = app.test_client()

with app.app_context():
    seed_people()
    version_id = seed_topic("custom_topic")
    draft_id = seed_topic("custom_topic", status="draft", version_number=2)
    db.session.add(m.Topic(topic_key="empty_topic", title="沒有 taxonomy 的 Topic"))
    db.session.commit()


def classify_responses(text, sub="A1 Original", main="Main A", status_ok=True):
    masked = mask_pii(text)
    q({"segments": [masked]})
    q({"classifications": [{
        "index": 0, "main_category": main, "sub_category": sub, "secondary_sub_category": None,
        "reasoning": f"r-{sub}", "summary": f"s-{sub}", "confidence": 0.93,
    }]})


print("========== 1. 上傳：routing 判斷不出 Topic ==========")
df = pd.DataFrame({"雜項欄位": ["希望公司增加教育訓練", "希望主管多給回饋"]})
buf = io.BytesIO()
df.to_excel(buf, index=False)
buf.seek(0)
GEMINI_QUEUE.clear()
q({"question_type": None})  # routing：Gemini 成功回應但判斷不出來
resp = client.post("/api/classification/upload", data={"file": (buf, "u.xlsx"), "text_column": "雜項欄位"},
                   headers=user_header(1), content_type="multipart/form-data")
data = resp.get_json()
check("upload 201", resp.status_code == 201)
check("classified_count=0、question_type=None", data["classified_count"] == 0 and data["question_type"] is None)
check("columns 帶 routing_status=unrouted", data["columns"][0]["routing_status"] == "unrouted")
batch_id = data["upload_batch_id"]
with app.app_context():
    answers = m.Uploaded_Answer.query.filter_by(upload_batch_id=batch_id).order_by(m.Uploaded_Answer.id).all()
    answer_ids = [a.id for a in answers]
    check("Uploaded_Answer.question_type 存 NULL（不是 'other'）", all(a.question_type is None for a in answers))
    check("routing_status=unrouted、routing_detail 有原因", all(a.routing_status == "unrouted" and "undetermined" in a.routing_detail for a in answers))
    chat_id = seed_workspace_chat(batch_id, rows=[], meta_extra={"review_revision": data["review_revision"]})


print("\n========== 2. Admin 未分類頁看得到 ==========")
resp = client.get("/api/admin/ai/unassigned?kind=unrouted", headers=admin_header(1))
body = resp.get_json()
check("unassigned 200", resp.status_code == 200)
listed = {i["id"]: i for i in body["items"]}
check("尚未自動重試的 routing failure 不逐筆列給人工", not listed)
check("自動重試進度只聚合顯示", body["retry_progress"]["pending_by_kind"]["unrouted"] == 2
      and body["counts"]["unrouted"] == 0)
check("非 admin 不能存取", client.get("/api/admin/ai/unassigned", headers=user_header(1)).status_code == 403)
check("不合法 kind -> 400 INVALID_KIND",
      client.get("/api/admin/ai/unassigned?kind=nope", headers=admin_header(1)).get_json()["code"] == "INVALID_KIND")
resp = client.get("/api/admin/ai/unassigned?kind=unrouted&page=2&page_size=1", headers=admin_header(1))
check("人工清單沒有 still_failed 時不回傳自動重試中的資料",
      len(resp.get_json()["items"]) == 0 and resp.get_json()["total"] == 0)


print("\n========== 3. fail-closed：draft / 無 taxonomy ==========")
resp = client.post(f"/api/admin/ai/unassigned/answers/{answer_ids[0]}/assign", headers=admin_header(1),
                   json={"topic_key": "custom_topic", "taxonomy_version_id": draft_id})
check("draft version -> 422 TAXONOMY_VERSION_NOT_USABLE", resp.status_code == 422 and resp.get_json()["code"] == "TAXONOMY_VERSION_NOT_USABLE")
resp = client.post(f"/api/admin/ai/unassigned/answers/{answer_ids[0]}/assign", headers=admin_header(1),
                   json={"topic_key": "empty_topic"})
check("沒有 published taxonomy -> 422 TAXONOMY_UNAVAILABLE", resp.status_code == 422 and resp.get_json()["code"] == "TAXONOMY_UNAVAILABLE")
resp = client.post(f"/api/admin/ai/unassigned/answers/{answer_ids[0]}/assign", headers=admin_header(1),
                   json={"topic_key": "nope"})
check("不存在的 Topic -> 404 TOPIC_NOT_FOUND", resp.status_code == 404 and resp.get_json()["code"] == "TOPIC_NOT_FOUND")
with app.app_context():
    check("失敗的指派不寫入任何 classification", m.Response_Classification.query.filter_by(upload_batch_id=batch_id).count() == 0)


print("\n========== 4. 指派 Topic -> classification ==========")
classify_responses("希望公司增加教育訓練")
resp = client.post(f"/api/admin/ai/unassigned/answers/{answer_ids[0]}/assign", headers=admin_header(1),
                   json={"topic_key": "custom_topic", "reason": "人工判斷為 custom_topic"})
result = resp.get_json()
check("assign 200、succeeded", resp.status_code == 200 and result["succeeded"] is True)
check("使用 published version", result["taxonomy_version_id"] == version_id)
check("產生 1 筆 A1 classification", len(result["classifications"]) == 1 and result["classifications"][0]["sub_category"] == "A1 Original")
new_cid = result["classifications"][0]["classification_id"]
with app.app_context():
    db.session.remove()
    a0 = db.session.get(m.Uploaded_Answer, answer_ids[0])
    check("Uploaded_Answer persistence：question_type / routing_status / assigned_by",
          a0.question_type == "custom_topic" and a0.routing_status == "assigned" and a0.assigned_by_admin_id == 1)
    audit = m.Admin_Audit_Log.query.filter_by(action="assign_topic", entity_id=str(answer_ids[0])).all()
    check("assign_topic audit（admin / before / after / reason）",
          len(audit) == 1 and audit[0].admin_id == 1 and audit[0].before_state["question_type"] is None
          and audit[0].after_state["topic_key"] == "custom_topic" and audit[0].reason == "人工判斷為 custom_topic")
resp = client.post(f"/api/admin/ai/unassigned/answers/{answer_ids[0]}/assign", headers=admin_header(1),
                   json={"topic_key": "custom_topic"})
check("重複指派 -> 409 ALREADY_CLASSIFIED（不重複建立）", resp.status_code == 409 and resp.get_json()["code"] == "ALREADY_CLASSIFIED")
with app.app_context():
    check("仍然只有 1 筆 classification", m.Response_Classification.query.filter_by(uploaded_answer_id=answer_ids[0]).count() == 1)
body = client.get("/api/admin/ai/unassigned?kind=unrouted", headers=admin_header(1)).get_json()
check("已處理的回答離開 unrouted 分頁", answer_ids[0] not in {i["id"] for i in body["items"]} and body["counts"]["unrouted"] == 1)
detail = client.get(f"/api/admin/ai/unassigned/answers/{answer_ids[0]}", headers=admin_header(1)).get_json()
check("answer detail 顯示處理狀態與 audit", detail["routing_status"] == "assigned" and len(detail["audit"]) == 1)


print("\n========== 5. Workspace / Report 看得到 ==========")
freshness = client.get(f"/api/chat/{chat_id}/classification-result/freshness", headers=user_header(1)).get_json()
check("Workspace 快照被判定需要更新", freshness["stale"] is True)
rows = client.post(f"/api/chat/{chat_id}/classification-result/refresh", headers=user_header(1)).get_json()["rows"]
check("Workspace 顯示新分類 A1", any(r["main_category"] == "Main A" and "教育訓練" in r["respondent_text"] for r in rows))
client.post(f"/api/classification/{new_cid}/review/confirm-original", headers=admin_header(1))
q({"summary": "報告摘要"})
resp = client.post(f"/api/admin/ai/reports/user_upload/{batch_id}/generate", headers=admin_header(1))
check("Report 產生成功", resp.status_code == 201)
detail = client.get(f"/api/admin/ai/reports/detail/{resp.get_json()['report']['report_id']}", headers=admin_header(1)).get_json()
check("Report 含指派後的分類", any(a["sub_category"] == "A1 Original" for a in detail["aggregations"]))


print("\n========== 6. reroute ==========")
q({"question_type": "custom_topic"})
classify_responses("希望主管多給回饋", sub="B1 Candidate", main="Main B")
resp = client.post(f"/api/admin/ai/unassigned/answers/{answer_ids[1]}/reroute", headers=admin_header(1))
check("reroute 200、routed", resp.status_code == 200 and resp.get_json()["routed"] is True)
with app.app_context():
    a1 = db.session.get(m.Uploaded_Answer, answer_ids[1])
    check("reroute 後 routing_status=routed", a1.routing_status == "routed" and a1.question_type == "custom_topic")
    check("report 被標記 outdated（classification_rerun）",
          m.Report.query.filter_by(upload_batch_id=batch_id).first().outdated_reason == "classification_rerun")


print("\n========== 7. failed retry（attempt history、不重複計數）==========")
with app.app_context():
    ids = seed_upload_batch("batch-failed", ["這一則分類失敗"])
    failed_cid = seed_classification(ids[0], "batch-failed", "這一則分類失敗", None, None,
                                     version_id=version_id, status="failed")
check("尚未自動重試的 failed 分類不逐筆列給人工", failed_cid not in {i["classification_id"] for i in client.get(
    "/api/admin/ai/unassigned?kind=failed", headers=admin_header(1)).get_json()["items"]})
from services import bulk_retry_service
original_retry_process = bulk_retry_service._process
bulk_retry_service._process = lambda *_args: ("failed", "AI_RESPONSE_INVALID", "格式錯誤")
with app.app_context():
    bulk_retry_service.start(0, run_inline=True)
bulk_retry_service._process = original_retry_process
check("逐筆重試紀錄確認 still_failed 後出現在人工清單", failed_cid in {i["classification_id"] for i in client.get(
    "/api/admin/ai/unassigned?kind=failed", headers=admin_header(1)).get_json()["items"]})
classify_responses("這一則分類失敗")
resp = client.post(f"/api/admin/ai/classifications/{failed_cid}/retry", headers=admin_header(1))
check("retry 200、succeeded", resp.status_code == 200 and resp.get_json()["succeeded"] is True)
check("舊列列為 superseded", resp.get_json()["superseded_ids"] == [failed_cid])
with app.app_context():
    old = db.session.get(m.Response_Classification, failed_cid)
    check("舊 failed 列保留（status=superseded）", old is not None and old.status == "superseded")
    live = [r for r in m.Response_Classification.query.filter_by(uploaded_answer_id=ids[0]).all() if r.status != "superseded"]
    check("有效列只有 1 筆（不重複計數）", len(live) == 1 and live[0].status == "completed")
    from services.report_service import get_readiness
    readiness = get_readiness("user_upload", upload_batch_id="batch-failed")
    # 重試後的新結果信心 0.93、類別在已發布架構內 -> 自動通過；舊的 failed 列 superseded 不計入
    check("readiness：failed=0、只算 1 筆（superseded 不計）、新結果自動通過",
          readiness["failed"] == 0 and readiness["pending_review"] == 0
          and readiness["confirmed"] == 1 and readiness["auto_confirmed"] == 1)
attempts = client.get(f"/api/admin/ai/classifications/{failed_cid}/attempts", headers=admin_header(1)).get_json()
check("attempt history 2 筆 + retry audit", len(attempts["attempts"]) == 2 and attempts["audit"][-1]["action"] == "retry_failed")
check("failed 分頁不再出現", failed_cid not in {i["classification_id"] for i in client.get(
    "/api/admin/ai/unassigned?kind=failed", headers=admin_header(1)).get_json()["items"]})
check("superseded 不出現在審查清單", failed_cid not in {r["classification_id"] for r in client.get(
    "/api/admin/ai/classifications?page_size=200", headers=admin_header(1)).get_json()["classifications"]})
check("非 failed 不能 retry -> 409 NOT_FAILED",
      client.post(f"/api/admin/ai/classifications/{new_cid}/retry", headers=admin_header(1)).get_json()["code"] == "NOT_FAILED")


print("\n========== 8. 已人工定案不可重新處理 ==========")
resp = client.post(f"/api/admin/ai/classifications/{new_cid}/reclassify", headers=admin_header(1), json={"topic_key": "custom_topic"})
check("confirmed 的回答 reclassify -> 409 REPROCESS_BLOCKED_BY_REVIEW",
      resp.status_code == 409 and resp.get_json()["code"] == "REPROCESS_BLOCKED_BY_REVIEW")


print("\n========== 9. legacy question_id='other' ==========")
with app.app_context():
    ids = seed_upload_batch("batch-legacy", ["舊流程的其他類資料"], question_type="other")
    legacy_cid = seed_classification(ids[0], "batch-legacy", "舊流程的其他類資料", "動態", "動態子類",
                                     version_id=None, question_id="other", confidence=None)
check("legacy_other 分頁出現", legacy_cid in {i["classification_id"] for i in client.get(
    "/api/admin/ai/unassigned?kind=legacy_other", headers=admin_header(1)).get_json()["items"]})
check("legacy 沒指定 topic -> 422 TOPIC_REQUIRED",
      client.post(f"/api/admin/ai/classifications/{legacy_cid}/reclassify", headers=admin_header(1), json={}).get_json()["code"] == "TOPIC_REQUIRED")
classify_responses("舊流程的其他類資料")
resp = client.post(f"/api/admin/ai/classifications/{legacy_cid}/reclassify", headers=admin_header(1), json={"topic_key": "custom_topic"})
check("legacy 指派 Topic 重新分類 200", resp.status_code == 200 and resp.get_json()["classifications"][0]["taxonomy_version_id"] == version_id)
check("legacy_other 分頁不再出現", legacy_cid not in {i["classification_id"] for i in client.get(
    "/api/admin/ai/unassigned?kind=legacy_other", headers=admin_header(1)).get_json()["items"]})


print("\n========== 10. AI 服務失敗：原因持久化，不留半套資料 ==========")
with app.app_context():
    ids = seed_upload_batch("batch-err", ["AI 會失敗的回答"], question_type=None)
GEMINI_QUEUE.clear()
q(RuntimeError("segmentation boom"), RuntimeError("segmentation boom"), RuntimeError("segmentation boom"))
resp = client.post(f"/api/admin/ai/unassigned/answers/{ids[0]}/assign", headers=admin_header(1), json={"topic_key": "custom_topic"})
check("回應是具體錯誤（200 失敗結果或 502）", resp.status_code in (200, 502))
with app.app_context():
    a = db.session.get(m.Uploaded_Answer, ids[0])
    check("routing_status=classification_failed 且有失敗原因", a.routing_status == "classification_failed" and bool(a.routing_detail))
    live = m.Response_Classification.query.filter_by(uploaded_answer_id=ids[0]).all()
    check("沒有任何成功計數的 classification", all(r.status == "failed" for r in live))
GEMINI_QUEUE.clear()

finish()
