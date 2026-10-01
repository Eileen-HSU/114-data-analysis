#!/usr/bin/env python
"""
審核流程改版：高信心自動通過 + 新類別一鍵採用。

涵蓋：
    1. 上傳分析：高信心、類別在已發布分類架構內 -> 自動通過（confirmed + auto_confirmed）
       低信心 -> 維持待審；緊急開關 AUTO_CONFIRM_HIGH_CONFIDENCE=0 -> 維持待審
    2. 自動通過不算人工審核：不當回饋範例、is_human_reviewed=False、
       不受重新分析保護；但會進入報告（eligible），readiness 另外回報 auto_confirmed
    3. 可以重新審核：reopen -> 待審；再確認 -> 人工確認（auto_confirmed=False）
    4. Admin 清單：auto_confirmed=true 篩選、auto_confirmed_count
    5. 批次確認：需要人工判斷（needs_human_review）的列跳過
    6. 既有資料補做自動通過：dry_run 預覽、實際寫入 + audit、進過審核的不動、重跑冪等
    7. 一鍵採用：有未發布草稿 -> 409 DRAFT_IN_PROGRESS；主題沒有已發布版本（自動主題）
       -> 只加草稿；發布失敗 -> 刪掉草稿、回答維持待處理

執行方式：
    cd backend
    python3 tests/test_auto_confirm_review.py
"""

import io
import os

import pandas as pd

from admin_test_support import (
    GEMINI_QUEUE, admin_header, check, create_app, finish, q, seed_classification,
    seed_people, seed_topic, seed_upload_batch, user_header,
)
import models as m
from extensions import db
from services.privacy_service import mask_pii

os.environ.pop("AUTO_CONFIRM_HIGH_CONFIDENCE", None)
os.environ.pop("OPEN_CLASSIFICATION_ENABLED", None)

app = create_app()
client = app.test_client()

with app.app_context():
    seed_people()
    version_id = seed_topic("custom_topic")


def upload(column, texts):
    df = pd.DataFrame({column: texts})
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    buf.seek(0)
    resp = client.post("/api/classification/upload", data={"file": (buf, "u.xlsx"), "text_column": column},
                       headers=user_header(1), content_type="multipart/form-data")
    return resp.status_code, resp.get_json()


def classify_q(text, main, sub, confidence):
    q({"segments": [mask_pii(text)]})
    q({"classifications": [{"index": 0, "main_category": main, "sub_category": sub,
                            "secondary_sub_category": None, "reasoning": f"理由：{sub}",
                            "summary": f"摘要：{sub}", "confidence": confidence}]})


def get_row(cid):
    with app.app_context():
        row = db.session.get(m.Response_Classification, cid)
        db.session.expunge(row)
        return row


print("========== 1. 上傳分析時自動通過 ==========")
GEMINI_QUEUE.clear()
q({"question_type": "custom_topic"})
classify_q("教育訓練很有幫助", "Main A", "A1 Original", confidence=0.92)
status, data = upload("意見", ["教育訓練很有幫助"])
check("upload 201", status == 201 and data["classified_count"] == 1)
high = data["classifications"][0]
check("高信心 + 類別在清單內 -> confirmed、auto_confirmed",
      high["review_status"] == "confirmed" and high["auto_confirmed"] is True)
check("自動通過沒有審核人", high["reviewed_by_admin_id"] is None and high["reviewed_at"] is not None)
high_cid = high["classification_id"]
high_batch = get_row(high_cid).upload_batch_id

GEMINI_QUEUE.clear()
q({"question_type": "custom_topic"})
classify_q("不太確定在說什麼", "Main A", "A1 Original", confidence=0.6)
status, data = upload("意見", ["不太確定在說什麼"])
low = data["classifications"][0]
check("低信心 -> 維持待審、不是自動通過",
      low["review_status"] == "pending_review" and low["auto_confirmed"] is False
      and low["needs_human_review"] is True and low["review_flag_reason"] == "low_confidence")
low_cid = low["classification_id"]

os.environ["AUTO_CONFIRM_HIGH_CONFIDENCE"] = "0"
GEMINI_QUEUE.clear()
q({"question_type": "custom_topic"})
classify_q("訓練內容很實用", "Main A", "A1 Original", confidence=0.95)
status, data = upload("意見", ["訓練內容很實用"])
check("緊急開關關閉 -> 高信心也維持待審",
      data["classifications"][0]["review_status"] == "pending_review"
      and data["classifications"][0]["auto_confirmed"] is False)
switch_off_cid = data["classifications"][0]["classification_id"]
os.environ.pop("AUTO_CONFIRM_HIGH_CONFIDENCE", None)

with app.app_context():
    from services.auto_confirm_service import is_eligible
    draft_version = seed_topic("draft_only_topic", status="draft")
    ids = seed_upload_batch("batch-draft", ["草稿主題的回答"], question_type="draft_only_topic")
    draft_cid = seed_classification(ids[0], "batch-draft", "草稿主題的回答", "Main A", "A1 Original",
                                    version_id=draft_version, confidence=0.99)
    check("分類架構還沒發布（AI 自動主題的暫定架構）-> 不符合自動通過",
          is_eligible(db.session.get(m.Response_Classification, draft_cid)) is False)


print("\n========== 2. 自動通過不算人工審核，但會進入報告 ==========")
with app.app_context():
    from services.classification_attempt_service import protected_row_ids
    from services.effective_classification_service import effective_view
    from services.report_service import get_readiness
    from services.review_feedback_service import get_reviewed_examples

    row = db.session.get(m.Response_Classification, high_cid)
    view = effective_view(row)
    check("effective_view：is_human_reviewed=False、auto_confirmed=True",
          view["is_human_reviewed"] is False and view["auto_confirmed"] is True)
    check("不當成回饋給 Gemini 的人工審核範例",
          all(e.get("classification_id") != high_cid for e in get_reviewed_examples(version_id))
          and len(get_reviewed_examples(version_id)) == 0)
    check("不受重新分析保護", high_cid not in protected_row_ids([row]))

    from services.admin_recovery_service import _is_human_finalized
    check("重新處理時不算人工定案", _is_human_finalized(row) is False)

    readiness = get_readiness("user_upload", upload_batch_id=high_batch)
    check("進入報告（eligible=1），並回報其中 1 筆是自動通過",
          readiness["eligible"] == 1 and readiness["confirmed"] == 1 and readiness["auto_confirmed"] == 1)


print("\n========== 3. 可以重新審核 ==========")
resp = client.post(f"/api/classification/{high_cid}/review/reopen", headers=admin_header(1))
check("reopen 自動通過的結果 -> 200", resp.status_code == 200)
row = get_row(high_cid)
check("reopen 後：待審、不再是自動通過", row.review_status == "pending_review" and row.auto_confirmed is False)
resp = client.post(f"/api/classification/{high_cid}/review/confirm-original", headers=admin_header(1))
row = get_row(high_cid)
check("人工再確認：confirmed、auto_confirmed=False、記錄審核人",
      resp.status_code == 200 and row.review_status == "confirmed"
      and row.auto_confirmed is False and row.reviewed_by_admin_id == 1)
with app.app_context():
    check("人工確認後才會成為回饋範例",
          any(e.get("classification_id") == high_cid for e in get_reviewed_examples(version_id))
          or len(get_reviewed_examples(version_id)) == 1)
    check("人工確認後受重新分析保護",
          high_cid in protected_row_ids([db.session.get(m.Response_Classification, high_cid)]))


print("\n========== 3b. 自動通過的結果可以直接做單筆審核 ==========")
with app.app_context():
    ids = seed_upload_batch("batch-direct", ["X", "Y", "Z"], question_type="custom_topic")
    auto_m = seed_classification(ids[0], "batch-direct", "X", "Main A", "A1 Original", version_id=version_id,
                                 review_status="confirmed", auto_confirmed=True)
    auto_x = seed_classification(ids[1], "batch-direct", "Y", "Main A", "A1 Original", version_id=version_id,
                                 review_status="confirmed", auto_confirmed=True)
    auto_s = seed_classification(ids[2], "batch-direct", "Z", "Main A", "A1 Original", version_id=version_id,
                                 review_status="confirmed", auto_confirmed=True)
resp = client.post(f"/api/classification/{auto_m}/review/confirm-manual", headers=admin_header(1),
                   json={"sub_category": "B1 Candidate", "reasoning": "人工改類別"})
row = get_row(auto_m)
check("直接手動改類別 -> modified、不再是自動通過",
      resp.status_code == 200 and row.review_status == "modified" and row.auto_confirmed is False
      and row.final_sub_category == "B1 Candidate")
resp = client.post(f"/api/classification/{auto_x}/review/exclude", headers=admin_header(1), json={"reason": "無關"})
row = get_row(auto_x)
check("直接排除 -> excluded、不再是自動通過",
      resp.status_code == 200 and row.review_status == "excluded" and row.auto_confirmed is False)
resp = client.post(f"/api/classification/{auto_s}/review/start", headers=admin_header(1))
row = get_row(auto_s)
check("開始審核對話 = 重新開啟：回到待審、建立對話",
      resp.status_code in (200, 201) and row.review_status == "pending_review" and row.auto_confirmed is False)
with app.app_context():
    check("開始審核寫入 reopen audit", m.Admin_Audit_Log.query.filter_by(
        action="reopen", entity_id=str(auto_s)).count() == 1)
with app.app_context():
    ids = seed_upload_batch("batch-auto-batch", ["W"], question_type="custom_topic")
    auto_b = seed_classification(ids[0], "batch-auto-batch", "W", "Main A", "A1 Original", version_id=version_id,
                                 review_status="confirmed", auto_confirmed=True)
resp = client.post("/api/classification/review/batch-confirm", headers=admin_header(1),
                   json={"classification_ids": [auto_b], "batch_id": "auto-batch"})
row = get_row(auto_b)
check("批次確認不會把自動通過的一次蓋上人工確認（跳過）",
      resp.get_json()["confirmed_ids"] == [] and row.auto_confirmed is True and row.reviewed_by_admin_id is None)


print("\n========== 4. Admin 清單篩選自動通過 ==========")
with app.app_context():
    ids = seed_upload_batch("batch-list", ["A", "B"], question_type="custom_topic")
    auto1 = seed_classification(ids[0], "batch-list", "A", "Main A", "A1 Original", version_id=version_id,
                                review_status="confirmed", auto_confirmed=True)
    seed_classification(ids[1], "batch-list", "B", "Main A", "A1 Original", version_id=version_id,
                        review_status="confirmed")
body = client.get("/api/admin/ai/classifications?auto_confirmed=true", headers=admin_header(1)).get_json()
with app.app_context():
    expected_auto = {r.classification_id for r in m.Response_Classification.query.filter_by(auto_confirmed=True).all()}
check("auto_confirmed=true 只列出自動通過的",
      auto1 in {r["classification_id"] for r in body["classifications"]}
      and {r["classification_id"] for r in body["classifications"]} == expected_auto
      and all(r["auto_confirmed"] for r in body["classifications"]))
check("回應包含 auto_confirmed_count", body["auto_confirmed_count"] == len(expected_auto))
body = client.get("/api/admin/ai/classifications?auto_confirmed=false", headers=admin_header(1)).get_json()
check("auto_confirmed=false 排除自動通過的", auto1 not in [r["classification_id"] for r in body["classifications"]])


print("\n========== 5. 批次確認跳過需要人工判斷的 ==========")
with app.app_context():
    ids = seed_upload_batch("batch-flag", ["C"], question_type="custom_topic")
    plain = seed_classification(ids[0], "batch-flag", "C", "Main A", "A1 Original", version_id=version_id,
                                confidence=0.7)
resp = client.post("/api/classification/review/batch-confirm", headers=admin_header(1),
                   json={"classification_ids": [low_cid, plain], "batch_id": "flag-batch"})
body = resp.get_json()
check("低信心（needs_human_review）跳過，回報 NEEDS_HUMAN_JUDGEMENT",
      resp.status_code == 200 and [s["code"] for s in body["skipped"]] == ["NEEDS_HUMAN_JUDGEMENT"]
      and body["skipped"][0]["classification_id"] == low_cid)
check("沒有被標記的照常批次確認", body["confirmed_ids"] == [plain])
check("被跳過的仍是待審", get_row(low_cid).review_status == "pending_review")
resp = client.post(f"/api/classification/{low_cid}/review/confirm-original", headers=admin_header(1))
check("低信心可以逐筆確認（人看過了）", resp.status_code == 200 and get_row(low_cid).review_status == "confirmed")


print("\n========== 6. 既有資料補做自動通過 ==========")
with app.app_context():
    ids = seed_upload_batch("batch-backfill", ["D", "E", "F", "G"], question_type="custom_topic")
    old_ok = seed_classification(ids[0], "batch-backfill", "D", "Main A", "A1 Original", version_id=version_id)
    old_low = seed_classification(ids[1], "batch-backfill", "E", "Main A", "A1 Original", version_id=version_id,
                                  confidence=0.5, needs_human_review=True, review_flag_reason="low_confidence")
    old_reviewing = seed_classification(ids[2], "batch-backfill", "F", "Main A", "A1 Original", version_id=version_id)
    db.session.add(m.Classification_Review(classification_id=old_reviewing, admin_id=1, status="in_progress"))
    old_legacy = seed_classification(ids[3], "batch-backfill", "G", "Main A", "A1 Original", version_id=None)
    db.session.commit()
backfill_expected = {old_ok, switch_off_cid}
resp = client.post("/api/admin/ai/classifications/auto-confirm", headers=admin_header(1), json={})
body = resp.get_json()
check("預設 dry_run：只預覽", resp.status_code == 200 and body["dry_run"] is True
      and set(body["classification_ids"]) == backfill_expected)
check("dry_run 不寫入", get_row(old_ok).review_status == "pending_review")
check("非管理員不能呼叫", client.post("/api/admin/ai/classifications/auto-confirm",
                                     headers=user_header(1), json={}).status_code in (401, 403))
resp = client.post("/api/admin/ai/classifications/auto-confirm", headers=admin_header(1), json={"dry_run": False})
body = resp.get_json()
check("實際執行：符合條件的補做自動通過", body["dry_run"] is False and body["eligible_count"] == len(backfill_expected))
row = get_row(old_ok)
check("補做的列：confirmed + auto_confirmed", row.review_status == "confirmed" and row.auto_confirmed is True)
check("低信心不動", get_row(old_low).review_status == "pending_review")
check("有人正在審核的不動", get_row(old_reviewing).review_status == "pending_review")
check("沒有分類架構版本的舊資料不動", get_row(old_legacy).review_status == "pending_review")
with app.app_context():
    check("逐筆寫 audit", m.Admin_Audit_Log.query.filter_by(action="auto_confirm_backfill").count()
          == len(backfill_expected))
body = client.post("/api/admin/ai/classifications/auto-confirm", headers=admin_header(1),
                   json={"dry_run": False}).get_json()
check("重跑冪等（沒有可處理的）", body["eligible_count"] == 0)


print("\n========== 7. 一鍵採用的邊界情況 ==========")
with app.app_context():
    ids = seed_upload_batch("batch-adopt", ["想要彈性上班"], question_type="custom_topic")
    adopt_cid = seed_classification(ids[0], "batch-adopt", "想要彈性上班", "Main C", "彈性工時",
                                    version_id=version_id, status="new_category",
                                    needs_human_review=True, review_flag_reason="new_category_proposed")
    pending_draft = seed_topic("custom_topic", status="draft", version_number=2)

resp = client.post("/api/admin/ai/new-categories/adopt", headers=admin_header(1), json={
    "topic_key": "custom_topic", "main_category": "Main C", "sub_category": "彈性工時",
})
check("有未發布草稿 -> 409 DRAFT_IN_PROGRESS",
      resp.status_code == 409 and resp.get_json()["code"] == "DRAFT_IN_PROGRESS")
check("被拒絕時回答維持待處理", get_row(adopt_cid).review_status == "pending_review")
with app.app_context():
    check("被拒絕時已發布版本不變",
          db.session.get(m.Taxonomy_Version, version_id).status == "published")
    db.session.delete(db.session.get(m.Taxonomy_Version, pending_draft))
    db.session.commit()

import services.taxonomy_service as taxo  # noqa: E402

original_publish = taxo.publish_taxonomy_version_with_validation


def failing_publish(*args, **kwargs):
    raise taxo.TaxonomyPublishValidationError("模擬發布失敗")


taxo.publish_taxonomy_version_with_validation = failing_publish
resp = client.post("/api/admin/ai/new-categories/adopt", headers=admin_header(1), json={
    "topic_key": "custom_topic", "main_category": "Main C", "sub_category": "彈性工時",
})
taxo.publish_taxonomy_version_with_validation = original_publish
check("發布失敗 -> 409 ADOPT_FAILED", resp.status_code == 409 and resp.get_json()["code"] == "ADOPT_FAILED")
with app.app_context():
    check("發布失敗：剛複製的草稿被刪掉，不留半套",
          m.Taxonomy_Version.query.filter_by(topic_key="custom_topic", status="draft").count() == 0)
    check("發布失敗：已發布版本不變", db.session.get(m.Taxonomy_Version, version_id).status == "published")
check("發布失敗：回答維持待處理", get_row(adopt_cid).review_status == "pending_review")

resp = client.post("/api/admin/ai/new-categories/adopt", headers=admin_header(1), json={
    "topic_key": "custom_topic", "main_category": "Main C", "sub_category": "彈性工時",
    "definition": "當回覆主要涉及彈性上下班、遠距工作時，歸入此類別。",
})
body = resp.get_json()
check("正常一鍵採用：發布 + 確認", resp.status_code == 201 and body["published"] is True
      and body["confirmed_ids"] == [adopt_cid])
with app.app_context():
    published = m.Taxonomy_Version.query.filter_by(topic_key="custom_topic", status="published").one()
    category = next(c for c in published.categories if c.sub_category == "彈性工時")
    check("管理員填的定義有寫進分類架構", category.definition == "當回覆主要涉及彈性上下班、遠距工作時，歸入此類別。")

with app.app_context():
    auto_version = seed_topic("auto_topic_x", status="draft")
    ids = seed_upload_batch("batch-auto", ["員工餐廳很好吃"], question_type="auto_topic_x")
    auto_cid = seed_classification(ids[0], "batch-auto", "員工餐廳很好吃", "Main D", "餐飲滿意",
                                   version_id=auto_version, status="new_category")
resp = client.post("/api/admin/ai/new-categories/adopt", headers=admin_header(1), json={
    "topic_key": "auto_topic_x", "main_category": "Main D", "sub_category": "餐飲滿意",
})
body = resp.get_json()
check("自動主題（沒有已發布版本）：只加進草稿、不發布",
      resp.status_code == 201 and body["published"] is False and body["confirmed_count"] == 0)
with app.app_context():
    check("自動主題的草稿沒有被發布",
          m.Taxonomy_Version.query.filter_by(topic_key="auto_topic_x", status="published").count() == 0)
check("自動主題的回答維持待處理", get_row(auto_cid).review_status == "pending_review")
with app.app_context():
    default_def = next(c for c in db.session.get(m.Taxonomy_Version, auto_version).categories
                       if c.sub_category == "餐飲滿意").definition
    check("沒填定義時使用判斷規則句型的預設定義", default_def == "當回覆主要涉及「餐飲滿意」相關內容時，歸入此類別。")

print("\n========== 8. AI 管理首頁彙整（overview）==========")
with app.app_context():
    m.Response_Classification.query.delete()
    m.Uploaded_Answer.query.delete()
    m.Response_Segmentation_Status.query.delete()
    db.session.commit()
    ov_version = m.Taxonomy_Version.query.filter_by(topic_key="custom_topic", status="published").one().version_id
    auto_draft = seed_topic("auto_overview", status="draft")
    ids = seed_upload_batch("batch-ov", [f"t{i}" for i in range(8)], question_type="custom_topic")
    seed_classification(ids[0], "batch-ov", "t0", "Main A", "A1 Original", version_id=ov_version,
                        confidence=0.5, needs_human_review=True, review_flag_reason="low_confidence")
    seed_classification(ids[1], "batch-ov", "t1", "Main C", "新類別甲", version_id=ov_version,
                        status="new_category", needs_human_review=True, review_flag_reason="new_category_proposed")
    seed_classification(ids[2], "batch-ov", "t2", "Main C", "新類別甲", version_id=ov_version,
                        status="new_category", needs_human_review=True, review_flag_reason="new_category_proposed")
    seed_classification(ids[3], "batch-ov", "t3", "Main A", "A1 Original", version_id=ov_version,
                        review_status="confirmed", auto_confirmed=True)
    seed_classification(ids[4], "batch-ov", "t4", "Main A", "A1 Original", version_id=ov_version,
                        review_status="confirmed")
    seed_classification(ids[5], "batch-ov", "t5", "Main X", "X1", version_id=auto_draft)
    seed_classification(ids[6], "batch-ov", "t6", None, None, version_id=ov_version, status="failed")
    # 被取代的舊結果：放在還有有效結果（t3）的回答上，不影響其他計數
    seed_classification(ids[3], "batch-ov", "t3", "Main A", "A1 Original", version_id=ov_version, status="superseded")
    m.Uploaded_Answer.query.filter_by(id=ids[7]).delete()
    db.session.commit()
check("非管理員不能看 overview", client.get("/api/admin/ai/overview", headers=user_header(1)).status_code in (401, 403))
ov = client.get("/api/admin/ai/overview", headers=admin_header(1)).get_json()
check("需要人判斷：低信心 1 + 新類別 2 = 3", ov["needs_person"]["needs_judgement"] == 3
      and ov["needs_person"]["low_confidence"] == 1)
check("新類別以組計算（同一類別 2 筆算 1 組）", ov["needs_person"]["new_category_groups"] == 1)
check("沒被標記的待審（暫定分類）另外計算", ov["needs_person"]["other_pending"] == 1
      and ov["needs_person"]["total"] == 4)
check("自動通過 1 筆（人工確認、失敗、被取代的都不算）", ov["auto_confirmed"]["total"] == 1)
check("分類失敗算在無法分類", ov["cannot_classify"]["failed"] == 1)
check("每個主題的數字",
      ov["topics"]["custom_topic"] == {"needs_judgement": 3, "other_pending": 0, "low_confidence": 1,
                                       "auto_confirmed": 1, "new_category_groups": 1}
      and ov["topics"]["auto_overview"]["other_pending"] == 1)

finish()
