#!/usr/bin/env python
"""
Admin Human Review 狀態機（P0-2 / P1-8）regression tests。

涵蓋：
    1. pending -> start -> 未送訊息直接 quick confirm：classification=confirmed，
       既有 in_progress session 被關閉（closed / quick_confirm），不再殘留 active。
    2. 修正前的斷鏈資料（confirmed + 殘留 in_progress）：reopen 不會被舊 session
       提早 return，classification 正確回到 pending_review，且只有 1 個 active。
    3. reopen 支援 confirmed / modified / excluded，寫入 audit（admin、原狀態、
       原因）並把報告標記 outdated（有具體 outdated_reason）。
    4. failed 不可 start / confirm-original / confirm-candidate / batch confirm。
    5. 重試（重複呼叫）不產生重複紀錄或非法狀態；同一筆永遠最多 1 個 active session。
    6. exclude 關閉自己的 session；別的 Admin 持有 session 時一律 409。
    7. batch confirm：單一 transaction、逐筆 skipped 原因、audit + batch_id、
       同 batch_id 重試冪等。
    8. 所有關鍵動作都有 Admin_Audit_Log（action / entity / admin / before / after）。
    9. API 錯誤回應帶 machine-readable code + message。

執行方式：
    cd backend
    python3 tests/test_admin_review_state_machine.py
"""

from admin_test_support import (
    admin_header, check, create_app, finish, q, seed_classification, seed_people,
    seed_topic, seed_upload_batch,
)
import models as m
from extensions import db

app = create_app()
client = app.test_client()

with app.app_context():
    seed_people()
    version_id = seed_topic()
    answer_ids = seed_upload_batch("batch-sm", [f"回答 {i}" for i in range(12)])

    def mk(i, **kw):
        return seed_classification(answer_ids[i], "batch-sm", f"回答 {i}", "Main A", "A1 Original",
                                   version_id=version_id, **kw)

    c_quick = mk(0)
    c_stale = mk(1, review_status="confirmed")
    c_modified = mk(2)
    c_excluded = mk(3)
    c_failed = mk(4, status="failed")
    c_conflict = mk(5)
    c_batch = [mk(6), mk(7), mk(8, status="failed"), mk(9, review_status="confirmed")]
    c_retry = mk(10)

    # 修正前留下的斷鏈：classification 已 confirmed，但 session 還是 in_progress
    db.session.add(m.Classification_Review(classification_id=c_stale, admin_id=2, status="in_progress"))
    db.session.add(m.Report(
        source_type="user_upload", upload_batch_id="batch-sm", version=1, status="completed",
        is_outdated=False, eligible_count_at_generation=1,
    ))
    db.session.commit()


def active_count(cid):
    with app.app_context():
        return m.Classification_Review.query.filter_by(classification_id=cid, status="in_progress").count()


def row(cid):
    with app.app_context():
        return db.session.get(m.Response_Classification, cid).to_dict()


def audits(cid, action=None):
    with app.app_context():
        query = m.Admin_Audit_Log.query.filter_by(entity_type="classification", entity_id=str(cid))
        if action:
            query = query.filter_by(action=action)
        return [a.to_dict() for a in query.order_by(m.Admin_Audit_Log.audit_id).all()]


def report_state():
    with app.app_context():
        r = m.Report.query.filter_by(upload_batch_id="batch-sm").first()
        return r.is_outdated, r.outdated_reason


print("========== 1. start -> 返回列表 -> quick confirm ==========")
check("start 200", client.post(f"/api/classification/{c_quick}/review/start", headers=admin_header(1)).status_code == 200)
check("start 後有 1 個 active session", active_count(c_quick) == 1)
resp = client.post(f"/api/classification/{c_quick}/review/confirm-original", headers=admin_header(1))
check("quick confirm 200", resp.status_code == 200)
check("classification -> confirmed", row(c_quick)["review_status"] == "confirmed")
check("quick confirm 關閉 active session（0 個 in_progress）", active_count(c_quick) == 0)
with app.app_context():
    closed = m.Classification_Review.query.filter_by(classification_id=c_quick).one()
    check("session status=closed、closed_reason=quick_confirm、有 closed_at",
          closed.status == "closed" and closed.closed_reason == "quick_confirm" and closed.closed_at is not None)
check("reviewed_by_admin_id / reviewed_at / updated_at 已寫入",
      row(c_quick)["reviewed_by_admin_id"] == 1 and row(c_quick)["reviewed_at"] and row(c_quick)["updated_at"])
qa = audits(c_quick, "quick_confirm")
check("quick_confirm audit：admin=1、before=pending_review、after=confirmed",
      len(qa) == 1 and qa[0]["admin_id"] == 1 and qa[0]["before_state"]["review_status"] == "pending_review"
      and qa[0]["after_state"]["review_status"] == "confirmed")
check("報告被標記 outdated（reason=classification_confirmed）", report_state() == (True, "classification_confirmed"))

resp_dup = client.post(f"/api/classification/{c_quick}/review/confirm-original", headers=admin_header(1))
check("重試 confirm-original -> 409 ALREADY_FINALIZED（不重複寫入）",
      resp_dup.status_code == 409 and resp_dup.get_json()["code"] == "ALREADY_FINALIZED")
check("錯誤回應同時有 code 與 message", "message" in resp_dup.get_json() and "error" in resp_dup.get_json())
check("重試沒有新增 audit", len(audits(c_quick, "quick_confirm")) == 1)


print("\n========== 2. reopen 不被殘留的舊 active session 擋住 ==========")
resp = client.post(f"/api/classification/{c_stale}/review/reopen", headers=admin_header(1), json={"reason": "資料有誤"})
check("reopen 200（不是回傳舊 session / 不是 409）", resp.status_code == 200)
check("回傳的是新 session（admin=1）", resp.get_json()["admin_id"] == 1 and resp.get_json()["status"] == "in_progress")
check("classification 回到 pending_review", row(c_stale)["review_status"] == "pending_review")
check("只剩 1 個 active session", active_count(c_stale) == 1)
with app.app_context():
    stale = m.Classification_Review.query.filter_by(classification_id=c_stale, admin_id=2).one()
    check("舊的殘留 session 被關閉（reopen_cleanup）", stale.status == "closed" and stale.closed_reason == "reopen_cleanup")
ra = audits(c_stale, "reopen")
check("reopen audit：原狀態 confirmed、原因、admin",
      len(ra) == 1 and ra[0]["before_state"]["review_status"] == "confirmed"
      and ra[0]["reason"] == "資料有誤" and ra[0]["admin_id"] == 1)
check("報告 outdated_reason=classification_reopened", report_state() == (True, "classification_reopened"))
resp_retry = client.post(f"/api/classification/{c_stale}/review/reopen", headers=admin_header(1))
check("reopen 重試冪等：200 且回傳同一個 session", resp_retry.status_code == 200 and resp_retry.get_json()["review_id"] == resp.get_json()["review_id"])
check("重試後仍只有 1 個 active、1 筆 reopen audit", active_count(c_stale) == 1 and len(audits(c_stale, "reopen")) == 1)
check("其他 Admin reopen 同一筆 -> 409", client.post(f"/api/classification/{c_stale}/review/reopen", headers=admin_header(2)).status_code == 409)


print("\n========== 3. modified -> reopen -> pending ==========")
client.post(f"/api/classification/{c_modified}/review/start", headers=admin_header(1))
q({"reply": "建議改成 B1", "candidate_sub_category": "B1 Candidate", "candidate_secondary_sub_category": None,
   "candidate_reasoning": "人工討論後改為 B1"})
check("message 201", client.post(f"/api/classification/{c_modified}/review/message", headers=admin_header(1),
                                 json={"message": "應該是 B1"}).status_code == 201)
check("有對話後 confirm-original -> 409 CONVERSATION_STARTED",
      client.post(f"/api/classification/{c_modified}/review/confirm-original", headers=admin_header(1)).get_json()["code"] == "CONVERSATION_STARTED")
resp = client.post(f"/api/classification/{c_modified}/review/confirm-candidate", headers=admin_header(1))
check("confirm-candidate 200 -> modified", resp.status_code == 200 and resp.get_json()["review_status"] == "modified")
check("final_* 寫入 B1", resp.get_json()["final_sub_category"] == "B1 Candidate" and resp.get_json()["final_main_category"] == "Main B")
check("modify 後沒有 active session", active_count(c_modified) == 0)
check("modify audit", len(audits(c_modified, "modify")) == 1)
check("報告 outdated_reason=classification_modified", report_state() == (True, "classification_modified"))
resp = client.post(f"/api/classification/{c_modified}/review/reopen", headers=admin_header(1))
check("modified 可以 reopen", resp.status_code == 200 and row(c_modified)["review_status"] == "pending_review")
check("reopen audit 記錄原狀態 modified", audits(c_modified, "reopen")[0]["before_state"]["review_status"] == "modified")


print("\n========== 4. excluded -> reopen -> pending ==========")
client.post(f"/api/classification/{c_excluded}/review/start", headers=admin_header(1))
resp = client.post(f"/api/classification/{c_excluded}/review/exclude", headers=admin_header(1), json={"reason": "無關內容"})
check("exclude 200", resp.status_code == 200 and resp.get_json()["review_status"] == "excluded")
check("exclude 關閉自己的 session", active_count(c_excluded) == 0)
check("exclude audit 帶原因", audits(c_excluded, "exclude")[0]["reason"] == "無關內容")
check("報告 outdated_reason=classification_excluded", report_state() == (True, "classification_excluded"))
resp = client.post(f"/api/classification/{c_excluded}/review/reopen", headers=admin_header(1))
check("excluded 可以 reopen", resp.status_code == 200 and row(c_excluded)["review_status"] == "pending_review")


print("\n========== 5. failed 不走一般流程 ==========")
for path in ("start", "confirm-original", "confirm-candidate"):
    resp = client.post(f"/api/classification/{c_failed}/review/{path}", headers=admin_header(1))
    check(f"failed {path} -> 409 CLASSIFICATION_FAILED", resp.status_code == 409 and resp.get_json()["code"] == "CLASSIFICATION_FAILED")
check("failed 仍是 pending_review", row(c_failed)["review_status"] == "pending_review")
check("failed 的 review state 顯示 failed",
      client.get(f"/api/classification/{c_failed}/review", headers=admin_header(1)).get_json()["review_state"] == "failed")


print("\n========== 6. 其他 Admin 持有 session 時一律 409 ==========")
client.post(f"/api/classification/{c_conflict}/review/start", headers=admin_header(1))
for path in ("start", "confirm-original", "exclude"):
    resp = client.post(f"/api/classification/{c_conflict}/review/{path}", headers=admin_header(2))
    check(f"Bob {path} -> 409 REVIEW_IN_PROGRESS_BY_OTHER",
          resp.status_code == 409 and resp.get_json()["code"] == "REVIEW_IN_PROGRESS_BY_OTHER"
          and resp.get_json()["reviewing_admin_name"] == "Alice")
check("review state 顯示 in_review",
      client.get(f"/api/classification/{c_conflict}/review", headers=admin_header(2)).get_json()["review_state"] == "in_review")
check("Alice 重複 start 冪等（仍 1 個 active）",
      client.post(f"/api/classification/{c_conflict}/review/start", headers=admin_header(1)).status_code == 200
      and active_count(c_conflict) == 1)


print("\n========== 7. batch confirm ==========")
client.post(f"/api/classification/{c_batch[1]}/review/start", headers=admin_header(1))  # 自己的空 session 要被關閉
payload = {"classification_ids": c_batch + [999999], "batch_id": "batch-001"}
resp = client.post("/api/classification/review/batch-confirm", headers=admin_header(1), json=payload)
body = resp.get_json()
check("batch confirm 200", resp.status_code == 200)
check("2 筆 pending 被確認", sorted(body["confirmed_ids"]) == sorted(c_batch[:2]))
skipped = {s["classification_id"]: s["code"] for s in body["skipped"]}
check("failed 被跳過（CLASSIFICATION_FAILED）", skipped.get(c_batch[2]) == "CLASSIFICATION_FAILED")
check("已確認被跳過（ALREADY_FINALIZED）", skipped.get(c_batch[3]) == "ALREADY_FINALIZED")
check("不存在的 ID 被跳過（CLASSIFICATION_NOT_FOUND）", skipped.get(999999) == "CLASSIFICATION_NOT_FOUND")
check("batch confirm 關閉自己的空 session", active_count(c_batch[1]) == 0)
ba = audits(c_batch[0], "batch_confirm")
check("batch audit 帶 batch_id 與 admin", len(ba) == 1 and ba[0]["batch_id"] == "batch-001" and ba[0]["admin_id"] == 1)
check("報告 outdated_reason=bulk_review_action", report_state() == (True, "bulk_review_action"))
resp = client.post("/api/classification/review/batch-confirm", headers=admin_header(1), json=payload)
check("同 batch_id 重試：already_done、沒有新確認", sorted(resp.get_json()["already_done_ids"]) == sorted(c_batch[:2])
      and resp.get_json()["confirmed_ids"] == [])
check("重試不重複寫 audit", len(audits(c_batch[0], "batch_confirm")) == 1)
check("空陣列 -> 400 INVALID_IDS",
      client.post("/api/classification/review/batch-confirm", headers=admin_header(1), json={"classification_ids": []}).get_json()["code"] == "INVALID_IDS")


print("\n========== 8. audit API 與全域不變量 ==========")
resp = client.get(f"/api/classification/{c_modified}/review/audit", headers=admin_header(2))
actions = [a["action"] for a in resp.get_json()["audit"]]
check("audit API 依時間列出 modify -> reopen", actions == ["modify", "reopen"])
with app.app_context():
    from sqlalchemy import func
    dup = (
        db.session.query(m.Classification_Review.classification_id, func.count())
        .filter_by(status="in_progress").group_by(m.Classification_Review.classification_id)
        .having(func.count() > 1).all()
    )
    check("整個 DB 沒有任何 classification 同時有多個 active review", dup == [])
    locked_with_active = (
        db.session.query(m.Response_Classification.classification_id)
        .join(m.Classification_Review, m.Classification_Review.classification_id == m.Response_Classification.classification_id)
        .filter(m.Classification_Review.status == "in_progress",
                m.Response_Classification.review_status.in_(["confirmed", "modified", "excluded"])).all()
    )
    check("沒有任何已定案 classification 殘留 active review", locked_with_active == [])


print("\n========== 9. 重新整理（新的 request / session）後狀態一致 ==========")
with app.app_context():
    db.session.remove()
check("重新讀取 DB：c_quick 仍是 confirmed", row(c_quick)["review_status"] == "confirmed")
check("重新讀取 DB：c_modified 是 pending_review（reopen 後）且 final_* 保留", row(c_modified)["review_status"] == "pending_review"
      and row(c_modified)["final_sub_category"] == "B1 Candidate")

finish()
