#!/usr/bin/env python
"""
測試腳本：「排除舊版資料」bulk exclude（P1-9 收窄後的規則）。

舊規則只看 confidence IS NULL + pending_review，範圍過寬，會誤排除
taxonomy-versioned / failed / 審核中 / 已有人工動作的資料。新規則
（services/review_service._bulk_exclude_scan）：

    review_status = pending_review AND confidence IS NULL
    AND taxonomy_version_id IS NULL
    AND status NOT IN (failed, superseded)
    AND 沒有 in_progress review session
    AND 從未有人工動作（沒有任何 review session / audit）

涵蓋：
    1. preview：eligible / skipped 數量、逐筆 skipped 原因、affected IDs
    2. 執行：只排除 eligible，其他欄位不變；寫入 admin identity + audit
       （batch_id）；報告標記 outdated（bulk_review_action）
    3. 同一個 batch_id 重試冪等（不重複寫入、回傳上一次結果）
    4. expected_ids：只處理預覽時確認過、而且執行當下仍合格的列
    5. 向後相容：service 舊入口 / endpoint 仍回傳 affected_count
    6. Admin-only（401）

執行方式：
    cd backend
    python3 tests/test_review_bulk_exclude_legacy.py
"""

from admin_test_support import (
    admin_header, check, create_app, finish, seed_classification, seed_people, seed_topic,
    seed_upload_batch,
)
import models as m
from extensions import db
from services import review_service

app = create_app()
client = app.test_client()
BATCH = "batch-legacy-bulk"

with app.app_context():
    seed_people()
    version_id = seed_topic()
    ids = seed_upload_batch(BATCH, [f"legacy {i}" for i in range(10)])

    def mk(i, **kw):
        kw.setdefault("confidence", None)
        return seed_classification(ids[i], BATCH, f"legacy {i}", f"MAIN{i}", f"SUB{i}", **kw)

    c_legacy_1 = mk(0)
    c_legacy_2 = mk(1)
    c_has_version = mk(2, version_id=version_id)
    c_failed = mk(3, status="failed")
    c_active = mk(4)
    c_history = mk(5)
    c_confirmed = mk(6, review_status="confirmed")
    c_has_confidence = mk(7, confidence=0.4)
    c_later = mk(8)

    db.session.add(m.Classification_Review(classification_id=c_active, admin_id=2, status="in_progress"))
    db.session.add(m.Classification_Review(classification_id=c_history, admin_id=2, status="closed"))
    db.session.add(m.Report(source_type="user_upload", upload_batch_id=BATCH, version=1, status="completed", is_outdated=False))
    db.session.commit()

    snapshot_fields = ("main_category", "sub_category", "reasoning", "confidence", "taxonomy_version_id",
                       "answer_text", "segment_start", "segment_end", "status")

    def snap(cid):
        row = db.session.get(m.Response_Classification, cid)
        return {f: getattr(row, f) for f in snapshot_fields}

    before = {cid: snap(cid) for cid in (c_legacy_1, c_legacy_2, c_has_version, c_failed, c_active, c_history)}


def review_status(cid):
    with app.app_context():
        return db.session.get(m.Response_Classification, cid).review_status


print("========== 1. preview ==========")
check("未帶 token -> 401", client.get("/api/classification/review/exclude-legacy/preview").status_code == 401)
resp = client.get("/api/classification/review/exclude-legacy/preview", headers=admin_header(1))
preview = resp.get_json()
check("preview 200", resp.status_code == 200)
check("eligible 只有真正的 legacy pending（含 c_later）",
      sorted(preview["eligible_ids"]) == sorted([c_legacy_1, c_legacy_2, c_later]))
skipped = {s["classification_id"]: s["code"] for s in preview["skipped"]}
check("taxonomy-versioned 被跳過（HAS_TAXONOMY_VERSION）", skipped.get(c_has_version) == "HAS_TAXONOMY_VERSION")
check("failed 被跳過（CLASSIFICATION_FAILED）", skipped.get(c_failed) == "CLASSIFICATION_FAILED")
check("審核中被跳過（REVIEW_IN_PROGRESS）", skipped.get(c_active) == "REVIEW_IN_PROGRESS")
check("已有人工紀錄被跳過（HAS_HUMAN_ACTION）", skipped.get(c_history) == "HAS_HUMAN_ACTION")
check("confirmed / 有 confidence 的列根本不是候選", c_confirmed not in skipped and c_has_confidence not in skipped)
check("skipped_reasons 彙總數量", {r["code"]: r["count"] for r in preview["skipped_reasons"]} == {
    "CLASSIFICATION_FAILED": 1, "HAS_HUMAN_ACTION": 1, "HAS_TAXONOMY_VERSION": 1, "REVIEW_IN_PROGRESS": 1})
check("preview 不修改任何資料", review_status(c_legacy_1) == "pending_review")


print("\n========== 2. 執行（expected_ids 限定範圍）==========")
with app.app_context():
    # 預覽之後才出現的新 legacy 資料，不在 expected_ids 裡，不能被順手排除
    late_ids = seed_upload_batch(BATCH, ["late"])
    c_after_preview = seed_classification(late_ids[0], BATCH, "late", "M", "S", confidence=None)
resp = client.post("/api/classification/review/exclude-legacy", headers=admin_header(1), json={
    "batch_id": "bulk-001", "expected_ids": [c_legacy_1, c_legacy_2],
})
result = resp.get_json()
check("執行 200", resp.status_code == 200)
check("affected_count=2（只處理 expected_ids 裡仍合格的列）", result["affected_count"] == 2 and sorted(result["affected_ids"]) == sorted([c_legacy_1, c_legacy_2]))
check("回傳 batch_id 可追蹤", result["batch_id"] == "bulk-001")
check("legacy 兩筆 -> excluded", review_status(c_legacy_1) == "excluded" and review_status(c_legacy_2) == "excluded")
check("預覽後新增的資料沒被排除", review_status(c_after_preview) == "pending_review")
for cid in (c_has_version, c_failed, c_active, c_history, c_confirmed, c_has_confidence, c_later):
    check(f"classification_id={cid} review_status 不變", review_status(cid) != "excluded")
with app.app_context():
    for cid in (c_legacy_1, c_legacy_2, c_has_version, c_failed, c_active, c_history):
        after = snap(cid)
        check(f"classification_id={cid} 除 review_status 外欄位不變", after == before[cid])
    row = db.session.get(m.Response_Classification, c_legacy_1)
    check("寫入 admin identity（reviewed_by_admin_id=1）", row.reviewed_by_admin_id == 1 and row.reviewed_at is not None)
    audit = m.Admin_Audit_Log.query.filter_by(action="bulk_exclude", batch_id="bulk-001").all()
    check("每筆一個 audit、admin=1、batch_id", len(audit) == 2 and all(a.admin_id == 1 for a in audit))
    report = m.Report.query.filter_by(upload_batch_id=BATCH).first()
    check("報告 outdated（bulk_review_action）", report.is_outdated and report.outdated_reason == "bulk_review_action")


print("\n========== 3. 同 batch_id 重試冪等 ==========")
resp = client.post("/api/classification/review/exclude-legacy", headers=admin_header(1), json={"batch_id": "bulk-001"})
check("重試回傳上一次結果（idempotent_replay）", resp.get_json()["idempotent_replay"] is True and resp.get_json()["affected_count"] == 2)
check("重試沒有順手排除其他 eligible（c_later 仍 pending）", review_status(c_later) == "pending_review")
with app.app_context():
    check("重試沒有新增 audit", m.Admin_Audit_Log.query.filter_by(batch_id="bulk-001").count() == 2)


print("\n========== 4. 向後相容入口 ==========")
with app.app_context():
    affected = review_service.exclude_legacy_pending_classifications(admin_id=1)
check("舊 service 入口套用新規則（c_later + c_after_preview = 2）", affected == 2)
check("第二次呼叫 affected_count=0", client.post("/api/classification/review/exclude-legacy", headers=admin_header(1)).get_json()["affected_count"] == 0)
check("expected_ids 型別錯誤 -> 400 INVALID_IDS",
      client.post("/api/classification/review/exclude-legacy", headers=admin_header(1), json={"expected_ids": "x"}).get_json()["code"] == "INVALID_IDS")

finish()
