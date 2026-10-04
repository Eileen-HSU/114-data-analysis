#!/usr/bin/env python
"""
新類別候選：殘留／舊候選獨立 bucket，以及「排除」。

殘留條件：legacy classification、topic_key 為空或 Topic 不存在、Topic 已 merged_into。
這些不計入主要「新類別候選」徽章、不出現在預設的正常清單（items），集中在 residual_items。

涵蓋：
    1. bucket：正常候選 / merged 主題殘留 / legacy / 主題不存在 分流，附 residual_reasons
    2. 徽章：overview 的 new_category_groups 只算正常候選；殘留另外回報 residual_new_category_groups
    3. 正常的採用 / 合併 / merge-targets 不會碰到殘留候選
    4. 重試併入（既有 merge-into）：搬走仍留在來源的回答後，殘留候選消失
    5. 排除：
       - 沒有 acknowledged -> 400 ACK_REQUIRED（強提示不能被繞過）
       - 只作用在殘留 bucket：正常候選 -> 404、原狀不動
       - 成功：candidate 消失、review_status=excluded、每筆 audit 帶共用 batch_id、另寫群組層級 audit
       - 別的管理員審核中 -> skipped；非預期錯誤 -> failed（其他筆照常處理）
       - 排除語意不被改變：與直接呼叫 review_service.exclude 的結果完全一致
         （不再計入彙整 / 報告、報告標記過期），reopen 可復原並回到殘留 bucket
    6. 解除合併後，該主題的候選回到正常 bucket

執行方式：
    cd backend
    python3 tests/test_new_category_residual.py
"""

import os
from unittest import mock

from admin_test_support import (
    GEMINI_QUEUE, admin_header, check, create_app, finish, q, seed_classification, seed_people, seed_topic,
    seed_upload_batch,
)
import models as m
from extensions import db
from services import review_service
from services.effective_classification_service import is_countable
from services.privacy_service import mask_pii

os.environ.pop("OPEN_CLASSIFICATION_ENABLED", None)
app = create_app()
client = app.test_client()
BASE = "/api/admin/ai/new-categories"
IMPACT = "排除後，這些回答將不再納入分析、彙整、匯出與報告。此操作可透過 reopen 復原。"


def classify_q(text, main, sub):
    q({"segments": [mask_pii(text)]})
    q({"classifications": [{"index": 0, "main_category": main, "sub_category": sub,
                            "secondary_sub_category": None, "reasoning": "r", "summary": "s", "confidence": 0.9}]})


def candidate(batch, text, main, sub, topic, version_id):
    ids = seed_upload_batch(batch, [text], question_type=topic or "legacy")
    return seed_classification(ids[0], batch, text, main, sub, version_id=version_id, status="new_category")


def listing():
    return client.get(BASE, headers=admin_header(1)).get_json()


def groups(items):
    return {(i["topic_key"], i["sub_category"]): i for i in items}


def exclude(topic, main, sub, ack=True, headers=None, **extra):
    body = {"topic_key": topic, "main_category": main, "sub_category": sub, **extra}
    if ack:
        body["acknowledged"] = True
    return client.post(f"{BASE}/exclude", headers=headers or admin_header(1), json=body)


with app.app_context():
    seed_people()
    norm_v = seed_topic("norm_topic", categories=[("Main A", "A1 Original", "m", "c"), ("Main B", "B1 Candidate", "m", "c")])
    # 正常現行候選：2 筆
    n1 = candidate("b-n1", "加班太多", "Main A", "工時過長", "norm_topic", norm_v)
    n2 = candidate("b-n2", "常常加班", "Main A", "工時過長", "norm_topic", norm_v)
    # merged 主題留下的殘留：搬遷失敗（沒有 AI 回應）留在來源的候選
    seed_topic("auto_left", status="draft")
    left_v = m.Taxonomy_Version.query.filter_by(topic_key="auto_left").one().version_id
    left_cid = candidate("b-left", "搬不走的回答", "Main A", "殘留類別", "auto_left", left_v)
    # legacy：沒有分類架構版本
    legacy_cid = candidate("b-legacy", "舊資料的回答", "Legacy Main", "舊類別", None, None)
    # 主題不存在：版本還在、Topic 不在。只有不強制外鍵的 SQLite 做得到；MySQL 有外鍵（刪主題會連帶刪版本），
    # 這種狀態不可能出現，所以在 MySQL 上略過這個情境。
    GHOST = db.engine.dialect.name == "sqlite"
    ghost_cid = None
    if GHOST:
        ghost_v = m.Taxonomy_Version(topic_key="ghost_topic", version_number=1, status="draft", source="manual")
        db.session.add(ghost_v)
        db.session.commit()
        ghost_cid = candidate("b-ghost", "孤兒主題的回答", "Ghost Main", "孤兒類別", "ghost_topic", ghost_v.version_id)

GEMINI_QUEUE.clear()
resp = client.post("/api/admin/ai/topics/auto_left/merge-into", headers=admin_header(1), json={"target_topic_key": "norm_topic"})
check("前置：auto_left 併入 norm_topic，但搬遷失敗留下候選", resp.status_code == 200 and resp.get_json()["skipped_count"] == 1)

print("========== 1. bucket 分流 ==========")
data = listing()
normal, residual = groups(data["items"]), groups(data["residual_items"])
check("正常清單只有現行候選（norm_topic / 工時過長）", set(normal) == {("norm_topic", "工時過長")} and data["total"] == 1)
expected_residual = {("auto_left", "殘留類別"), (None, "舊類別")} | ({("ghost_topic", "孤兒類別")} if GHOST else set())
check(f"殘留清單有 {len(expected_residual)} 組：merged 主題、legacy" + ("、主題不存在" if GHOST else "（MySQL 不會有主題不存在）"),
      set(residual) == expected_residual and data["residual_total"] == len(expected_residual))
check("merged 主題殘留：原因 topic_merged、帶 merged_into", residual[("auto_left", "殘留類別")]["residual_reasons"] == ["topic_merged"]
      and residual[("auto_left", "殘留類別")]["merged_into"] == "norm_topic")
check("legacy：原因 legacy + no_topic", residual[(None, "舊類別")]["residual_reasons"] == ["legacy", "no_topic"])
if GHOST:
    check("主題不存在：原因 topic_missing", residual[("ghost_topic", "孤兒類別")]["residual_reasons"] == ["topic_missing"])
check("正常候選不帶殘留欄位、既有欄位仍在",
      "residual_reasons" not in normal[("norm_topic", "工時過長")] and normal[("norm_topic", "工時過長")]["count"] == 2
      and normal[("norm_topic", "工時過長")]["classification_ids"] == [n1, n2])
check("殘留也不會出現在正常清單、正常也不會出現在殘留清單",
      not (set(normal) & set(residual)))

print("\n========== 2. 徽章只算正常候選 ==========")
overview = client.get("/api/admin/ai/overview", headers=admin_header(1)).get_json()
check("needs_decision.new_category_groups = 1（只算正常）", overview["needs_decision"]["new_category_groups"] == 1)
check("needs_person.new_category_groups = 1", overview["needs_person"]["new_category_groups"] == 1)
check(f"殘留另外回報 residual_new_category_groups = {len(expected_residual)}", overview["residual_new_category_groups"] == len(expected_residual))
check("每主題的新類別組數：merged 主題不算、legacy 不算",
      overview["topics"].get("norm_topic", {}).get("new_category_groups") == 1
      and overview["topics"].get("auto_left", {}).get("new_category_groups", 0) == 0)

print("\n========== 3. 正常的採用 / 合併不會碰殘留 ==========")
resp = client.post(f"{BASE}/merge", headers=admin_header(1), json={
    "topic_key": "auto_left", "main_category": "Main A", "sub_category": "殘留類別", "target_sub_category": "A1 Original"})
check("對殘留群組做正常「合併到既有類別」-> 404 NOTHING_TO_MERGE", resp.status_code == 404 and resp.get_json()["code"] == "NOTHING_TO_MERGE")
resp = client.post(f"{BASE}/merge", headers=admin_header(1), json={
    "topic_key": None, "main_category": "Legacy Main", "sub_category": "舊類別", "target_sub_category": "A1 Original"})
check("對 legacy 群組做正常合併也不會處理", resp.status_code == 404)
body = client.get(f"{BASE}/merge-targets", query_string={"topic": "auto_left"}, headers=admin_header(1)).get_json()
check("merge-targets 對 merged 主題不算入殘留列（row_total=0）", body["row_total"] == 0)
with app.app_context():
    check("殘留列都原封不動",
          all(db.session.get(m.Response_Classification, c).review_status == "pending_review" for c in (left_cid, legacy_cid, ghost_cid) if c is not None))

print("\n========== 4. 重試併入（既有 merge-into）==========")
classify_q("搬不走的回答", "Main A", "A1 Original")
resp = client.post("/api/admin/ai/topics/auto_left/merge-into", headers=admin_header(1), json={"target_topic_key": "norm_topic"})
check("重試 merge-into：搬走仍留在來源的 1 筆", resp.status_code == 200 and resp.get_json()["moved_count"] == 1)
data = listing()
check("merged 主題的殘留候選消失", ("auto_left", "殘留類別") not in groups(data["residual_items"]))
with app.app_context():
    check("舊列被取代（superseded），保留歷史", db.session.get(m.Response_Classification, left_cid).status == "superseded")

print("\n========== 5. 排除 ==========")
resp = exclude(None, "Legacy Main", "舊類別", ack=False)
check("沒有 acknowledged -> 400 ACK_REQUIRED，訊息就是強提示",
      resp.status_code == 400 and resp.get_json()["code"] == "ACK_REQUIRED" and IMPACT in resp.get_json()["message"])
resp = client.post(f"{BASE}/exclude", headers=admin_header(1), json={
    "topic_key": None, "main_category": "Legacy Main", "sub_category": "舊類別", "acknowledged": "yes"})
check("acknowledged 必須是 true（字串 'yes' 不算）", resp.status_code == 400)
check("非 admin -> 401", client.post(f"{BASE}/exclude", json={"sub_category": "x", "acknowledged": True}).status_code == 401)
resp = exclude(None, "Legacy Main", None)
check("缺子類別 -> 400（不會誤處理整批）", resp.status_code == 400 and resp.get_json()["code"] == "INVALID_CATEGORY")
resp = exclude("norm_topic", "Main A", "工時過長")
check("正常現行候選不能用排除入口 -> 404 NOTHING_TO_EXCLUDE", resp.status_code == 404 and resp.get_json()["code"] == "NOTHING_TO_EXCLUDE")
with app.app_context():
    check("正常候選原狀不動", all(db.session.get(m.Response_Classification, c).review_status == "pending_review" for c in (n1, n2)))

# 報告：排除語意的基準（同時用來比對「endpoint 路徑」與「直接呼叫 review_service.exclude」）
with app.app_context():
    db.session.add(m.Report(source_type="user_upload", upload_batch_id="b-legacy", version=1, status="completed", is_outdated=False))
    db.session.commit()
    check("前置：排除前 legacy 候選計入彙整", is_countable(db.session.get(m.Response_Classification, legacy_cid)))

resp = exclude(None, "Legacy Main", "舊類別", batch_id="batch-legacy-1", reason="舊版留下來、不需要分析")
body = resp.get_json()
check("排除 200：success / skipped / failed", resp.status_code == 200 and body["success_ids"] == [legacy_cid]
      and body["skipped"] == [] and body["failed"] == [] and body["batch_id"] == "batch-legacy-1")
data = listing()
check("排除後該殘留候選消失", (None, "舊類別") not in groups(data["residual_items"]))
with app.app_context():
    row = db.session.get(m.Response_Classification, legacy_cid)
    check("review_status=excluded（軟刪除，資料還在）", row.review_status == "excluded" and row.reviewed_by_admin_id == 1)
    check("排除後不再計入彙整（is_countable=False）", is_countable(row) is False)
    report = m.Report.query.filter_by(upload_batch_id="b-legacy").one()
    check("報告標記過期、原因 classification_excluded", report.is_outdated is True and report.outdated_reason == "classification_excluded")
    entries = m.Admin_Audit_Log.query.filter_by(action="exclude", entity_type="classification", entity_id=str(legacy_cid)).all()
    check("逐筆 exclude audit 保留、帶共用 batch_id、帶 reason",
          len(entries) == 1 and entries[0].batch_id == "batch-legacy-1" and entries[0].reason == "舊版留下來、不需要分析"
          and entries[0].before_state["review_status"] == "pending_review" and entries[0].after_state["review_status"] == "excluded")
    summary = m.Admin_Audit_Log.query.filter_by(action="exclude_new_category", batch_id="batch-legacy-1").all()
    check("另有群組層級 audit（成功 / 略過 / 失敗的 id）",
          len(summary) == 1 and summary[0].after_state == {"success_ids": [legacy_cid], "skipped_ids": [], "failed_ids": []})
resp = exclude(None, "Legacy Main", "舊類別")
check("重複排除同一組 -> 404（已經不是候選）", resp.status_code == 404)

print("\n   --- 排除語意不被改變：endpoint 與直接呼叫 review_service.exclude 結果一致 ---")
with app.app_context():
    twin_a = candidate("b-twin-a", "對照組A", "Twin Main", "對照類別A", None, None)
    twin_b = candidate("b-twin-b", "對照組B", "Twin Main", "對照類別B", None, None)
    for batch in ("b-twin-a", "b-twin-b"):
        db.session.add(m.Report(source_type="user_upload", upload_batch_id=batch, version=1, status="completed", is_outdated=False))
    db.session.commit()
    review_service.exclude(twin_b, 1, reason="直接呼叫")          # 基準：不經過 endpoint
resp = exclude(None, "Twin Main", "對照類別A", reason="直接呼叫")  # 經過 endpoint
check("對照組 endpoint 處理成功", resp.get_json()["success_ids"] == [twin_a])
with app.app_context():
    a, b = (db.session.get(m.Response_Classification, c) for c in (twin_a, twin_b))
    check("兩條路徑：review_status / 審核者 / 是否計入彙整完全一致",
          (a.review_status, a.reviewed_by_admin_id, is_countable(a)) == (b.review_status, b.reviewed_by_admin_id, is_countable(b))
          == ("excluded", 1, False))
    ra, rb = (m.Report.query.filter_by(upload_batch_id=x).one() for x in ("b-twin-a", "b-twin-b"))
    check("兩條路徑：報告都標記過期、原因相同", (ra.is_outdated, ra.outdated_reason) == (rb.is_outdated, rb.outdated_reason) == (True, "classification_excluded"))
    aa = m.Admin_Audit_Log.query.filter_by(action="exclude", entity_id=str(twin_a)).one()
    ab = m.Admin_Audit_Log.query.filter_by(action="exclude", entity_id=str(twin_b)).one()
    check("兩條路徑：audit 的 before / after / reason 相同（endpoint 只多補 batch_id）",
          aa.before_state["review_status"] == ab.before_state["review_status"] == "pending_review"
          and aa.after_state["review_status"] == ab.after_state["review_status"] == "excluded"
          and aa.reason == ab.reason and aa.batch_id is not None and ab.batch_id is None)

print("\n   --- reopen 可復原，且回到殘留 bucket ---")
resp = client.post(f"/api/classification/{legacy_cid}/review/reopen", headers=admin_header(1))
check("reopen 200", resp.status_code == 200)
with app.app_context():
    row = db.session.get(m.Response_Classification, legacy_cid)
    check("復原後回到 pending_review、重新計入彙整", row.review_status == "pending_review" and is_countable(row))
check("復原後再次出現在殘留 bucket", (None, "舊類別") in groups(listing()["residual_items"]))

print("\n   --- skipped / failed：逐筆處理，不互相影響 ---")
with app.app_context():
    s1 = candidate("b-s1", "審核中的", "Mix Main", "混合類別", None, None)
    s2 = candidate("b-s2", "正常的", "Mix Main", "混合類別", None, None)
    s3 = candidate("b-s3", "會出錯的", "Mix Main", "混合類別", None, None)
check("前置：Bob 開始審核 s1", client.post(f"/api/classification/{s1}/review/start", headers=admin_header(2)).status_code == 200)
original_exclude = review_service.exclude


def flaky_exclude(classification_id, admin_id, reason=None):
    if classification_id == s3:
        raise RuntimeError("模擬非預期錯誤")
    return original_exclude(classification_id, admin_id, reason=reason)


with mock.patch.object(review_service, "exclude", side_effect=flaky_exclude):
    body = exclude(None, "Mix Main", "混合類別").get_json()
check("success = 正常那筆", body["success_ids"] == [s2] and body["success_count"] == 1)
check("skipped = 別的管理員審核中（沿用既有規則的 code）", [x["classification_id"] for x in body["skipped"]] == [s1]
      and body["skipped"][0]["code"] == "REVIEW_IN_PROGRESS_BY_OTHER")
check("failed = 非預期錯誤，帶訊息", [x["classification_id"] for x in body["failed"]] == [s3] and "模擬非預期錯誤" in body["failed"][0]["message"])
with app.app_context():
    check("只有 success 那筆被排除，skipped / failed 維持待處理",
          [db.session.get(m.Response_Classification, c).review_status for c in (s1, s2, s3)] == ["pending_review", "excluded", "pending_review"])
    summary = m.Admin_Audit_Log.query.filter_by(action="exclude_new_category", batch_id=body["batch_id"]).one()
    check("群組 audit 記下三種結果", summary.after_state == {"success_ids": [s2], "skipped_ids": [s1], "failed_ids": [s3]})
    check("批次 audit 只標在成功的那筆", [a.entity_id for a in m.Admin_Audit_Log.query.filter_by(action="exclude", batch_id=body["batch_id"]).all()] == [str(s2)])
body = exclude(None, "Mix Main", "混合類別").get_json()
check("剩下的（審核中 + 出錯那筆）仍在殘留清單、可以重試",
      body["success_ids"] == [s3] and [x["classification_id"] for x in body["skipped"]] == [s1])

print("\n========== 6. 解除合併後候選回到正常 bucket ==========")
with app.app_context():
    seed_topic("auto_left2", status="draft")
    left2_v = m.Taxonomy_Version.query.filter_by(topic_key="auto_left2").one().version_id
    left2_cid = candidate("b-left2", "另一筆搬不走的", "Main A", "回得來的類別", "auto_left2", left2_v)
GEMINI_QUEUE.clear()
client.post("/api/admin/ai/topics/auto_left2/merge-into", headers=admin_header(1), json={"target_topic_key": "norm_topic"})
check("前置：auto_left2 的候選在殘留 bucket", ("auto_left2", "回得來的類別") in groups(listing()["residual_items"]))
overview = client.get("/api/admin/ai/overview", headers=admin_header(1)).get_json()
check("前置：它不計入徽章", overview["needs_decision"]["new_category_groups"] == 1)
resp = client.post("/api/admin/ai/topics/auto_left2/unmerge", headers=admin_header(1))
check("解除合併 200", resp.status_code == 200)
data = listing()
check("解除後候選回到正常清單、離開殘留清單",
      ("auto_left2", "回得來的類別") in groups(data["items"]) and ("auto_left2", "回得來的類別") not in groups(data["residual_items"]))
overview = client.get("/api/admin/ai/overview", headers=admin_header(1)).get_json()
check("解除後計入徽章（1 -> 2）", overview["needs_decision"]["new_category_groups"] == 2)

GEMINI_QUEUE.clear()
finish()
