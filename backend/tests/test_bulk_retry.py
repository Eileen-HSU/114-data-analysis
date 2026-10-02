#!/usr/bin/env python
"""
全部重試（services/bulk_retry_service.py）。

涵蓋：
    1. 真的重跑：分類失敗的資料重新分類成功；同一則回答的多個失敗片段只重試一次
    2. 進度 API、沒有資料時 NOTHING_TO_RETRY、非管理員不能用
    3. AI 額度用完：放慢、等待，連續 5 次自動暫停（paused_quota），資料維持原樣
    4. 真的失敗的每筆只試一次，不會無限重跑；跳過的另外計數
    5. 同時只能有一個；停止；執行它的 worker 中斷後可以重新開始
    6. API 開始（背景 thread）回 202

執行方式：
    cd backend
    python3 tests/test_bulk_retry.py
"""

from admin_test_support import (
    GEMINI_QUEUE, admin_header, check, create_app, finish, q, seed_classification, seed_people,
    seed_topic, seed_upload_batch, user_header,
)
import models as m
from extensions import db, taiwan_now
from services import bulk_retry_service as brs
from services.privacy_service import mask_pii

app = create_app()
client = app.test_client()
brs._sleep = lambda seconds: None  # 測試不真的等待

with app.app_context():
    seed_people()
    version_id = seed_topic("retry_topic")


def queue_success(text):
    q({"segments": [mask_pii(text)]})
    q({"classifications": [{"index": 0, "main_category": "Main A", "sub_category": "A1 Original",
                            "secondary_sub_category": None, "reasoning": "r", "summary": "s", "confidence": 0.9}]})


def failed_count():
    with app.app_context():
        return brs.remaining_counts()["failed"]


def clear_failed():
    """把前一段測試留下的失敗資料改成有結果，避免影響下一段。
    （不能改成 superseded：回答會變成「沒有任何結果」，又被算進無法分類。）"""
    with app.app_context():
        for row in m.Response_Classification.query.filter_by(status="failed").all():
            row.status, row.main_category, row.sub_category = "completed", "Main A", "A1 Original"
        db.session.commit()


print("========== 1. 真的重跑 ==========")
with app.app_context():
    ids = seed_upload_batch("batch-retry", ["回答甲", "回答乙"], question_type="retry_topic")
    seed_classification(ids[0], "batch-retry", "回答甲", None, None, version_id=version_id, status="failed")
    seed_classification(ids[0], "batch-retry", "回答甲", None, None, version_id=version_id, status="failed")
    seed_classification(ids[1], "batch-retry", "回答乙", None, None, version_id=version_id, status="failed")
check("開始前有 3 筆失敗片段", failed_count() == 3)

GEMINI_QUEUE.clear()
queue_success("回答甲")
queue_success("回答乙")
with app.app_context():
    job = brs.start(1, run_inline=True)
check("工作完成", job["status"] == "completed")
check("同一則回答的兩個失敗片段只重試一次：處理 2 則、成功 2 則",
      job["processed"] == 2 and job["succeeded"] == 2 and job["still_failed"] == 0)
check("Gemini 呼叫剛好用完（沒有多打）", len(GEMINI_QUEUE) == 0)
check("重跑後沒有失敗的資料了", failed_count() == 0)
with app.app_context():
    check("每次重試都寫 audit、原因是全部重試",
          m.Admin_Audit_Log.query.filter_by(reason="全部重試（背景）").count() == 2)


print("\n========== 2. 進度 API 與權限 ==========")
body = client.get("/api/admin/ai/unassigned/retry-all", headers=admin_header(1)).get_json()
check("進度 API 回傳最近一次工作與剩餘數量",
      body["job"]["job_id"] == job["job_id"] and body["job"]["status"] == "completed"
      and body["remaining"]["failed"] == 0)
check("非管理員不能看進度", client.get("/api/admin/ai/unassigned/retry-all",
                                    headers=user_header(1)).status_code in (401, 403))
check("非管理員不能開始", client.post("/api/admin/ai/unassigned/retry-all",
                                   headers=user_header(1)).status_code in (401, 403))
with app.app_context():
    ids_unrouted_before = brs.remaining_counts()["unrouted"]
if ids_unrouted_before == 0:
    resp = client.post("/api/admin/ai/unassigned/retry-all", headers=admin_header(1))
    check("沒有資料 -> 409 NOTHING_TO_RETRY", resp.status_code == 409 and resp.get_json()["code"] == "NOTHING_TO_RETRY")


print("\n========== 3. AI 額度用完：自動暫停 ==========")
with app.app_context():
    ids = seed_upload_batch("batch-quota", ["額度"], question_type="retry_topic")
    seed_classification(ids[0], "batch-quota", "額度", None, None, version_id=version_id, status="failed")

original_process = brs._process
sleeps = []
brs._sleep = sleeps.append
brs._process = lambda kind, item_id, admin_id: ("transient", "AI_QUOTA_EXCEEDED", "429")
with app.app_context():
    job = brs.start(1, run_inline=True)
brs._process = original_process
brs._sleep = lambda seconds: None
check("連續 5 次額度用完 -> paused_quota", job["status"] == "paused_quota" and job["quota_waits"] == 5)
check("暫停時沒有把這筆算成失敗或成功", job["processed"] == 0 and job["succeeded"] == 0)
check("前 4 次額度用完各等待 60 秒，第 5 次直接暫停不再等", sleeps.count(60) == 4)
check("暫停的說明告訴管理員之後再按一次", "再按一次" in (job["last_error"] or ""))
check("資料維持原樣、還在失敗清單", failed_count() == 1)
clear_failed()


print("\n========== 4. 真的失敗只試一次；跳過另外計數 ==========")
with app.app_context():
    ids = seed_upload_batch("batch-bad", ["壞一", "壞二"], question_type="retry_topic")
    seed_classification(ids[0], "batch-bad", "壞一", None, None, version_id=version_id, status="failed")
    seed_classification(ids[1], "batch-bad", "壞二", None, None, version_id=version_id, status="failed")
calls = []


def fake_process(kind, item_id, admin_id):
    calls.append(item_id)
    if len(calls) == 1:
        return "skipped", "TOPIC_REQUIRED", "無法判斷 Topic"
    return "failed", "AI_RESPONSE_INVALID", "格式錯誤"


brs._process = fake_process
with app.app_context():
    job = brs.start(1, run_inline=True)
brs._process = original_process
check("每筆只試一次（2 則回答、2 次呼叫），然後結束", len(calls) == 2 and job["status"] == "completed")
check("跳過 1、失敗 1", job["skipped"] == 1 and job["still_failed"] == 1 and job["processed"] == 2)
check("失敗原因記在 last_error", job["last_error"] == "格式錯誤")
clear_failed()


print("\n========== 5. 同時只能一個、停止、中斷後可重來 ==========")
with app.app_context():
    ids = seed_upload_batch("batch-lock", ["鎖"], question_type="retry_topic")
    seed_classification(ids[0], "batch-lock", "鎖", None, None, version_id=version_id, status="failed")
    now = taiwan_now()
    running = m.Bulk_Retry_Job(status="running", started_by_admin_id=1, total_at_start=1,
                               started_at=now, heartbeat_at=now)
    db.session.add(running)
    db.session.commit()
    running_id = running.job_id
resp = client.post("/api/admin/ai/unassigned/retry-all", headers=admin_header(1))
check("已經有執行中的 -> 409 BULK_RETRY_RUNNING（附上那個工作）",
      resp.status_code == 409 and resp.get_json()["code"] == "BULK_RETRY_RUNNING"
      and resp.get_json()["job"]["job_id"] == running_id)
resp = client.post("/api/admin/ai/unassigned/retry-all/cancel", headers=admin_header(1))
check("停止 -> 標記 cancel_requested", resp.status_code == 200 and resp.get_json()["job"]["cancel_requested"] is True)
with app.app_context():
    brs.run_job(running_id)
    check("工作看到停止要求就結束（cancelled），沒有處理任何資料",
          db.session.get(m.Bulk_Retry_Job, running_id).status == "cancelled"
          and db.session.get(m.Bulk_Retry_Job, running_id).processed == 0)
check("沒有執行中的工作時停止 -> 409 NOT_RUNNING",
      client.post("/api/admin/ai/unassigned/retry-all/cancel", headers=admin_header(1)).get_json()["code"] == "NOT_RUNNING")

with app.app_context():
    stale_time = taiwan_now() - brs.STALE_AFTER * 2
    stale = m.Bulk_Retry_Job(status="running", started_by_admin_id=1, total_at_start=1,
                             started_at=stale_time, heartbeat_at=stale_time)
    db.session.add(stale)
    db.session.commit()
    stale_id = stale.job_id
body = client.get("/api/admin/ai/unassigned/retry-all", headers=admin_header(1)).get_json()
check("worker 中斷（heartbeat 太舊）-> 進度顯示 interrupted", body["job"]["interrupted"] is True)


print("\n========== 6. API 開始（背景 thread）==========")


class InlineThread:
    def __init__(self, target, args, **kwargs):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


original_thread = brs.threading.Thread
brs.threading.Thread = InlineThread
GEMINI_QUEUE.clear()
queue_success("鎖")
resp = client.post("/api/admin/ai/unassigned/retry-all", headers=admin_header(1))
brs.threading.Thread = original_thread
check("中斷的舊工作不擋新的：202", resp.status_code == 202)
with app.app_context():
    check("中斷的舊工作被標成 failed（說明 worker 重啟）",
          db.session.get(m.Bulk_Retry_Job, stale_id).status == "failed"
          and "中斷" in db.session.get(m.Bulk_Retry_Job, stale_id).last_error)
body = client.get("/api/admin/ai/unassigned/retry-all", headers=admin_header(1)).get_json()
check("背景工作完成、資料重跑成功", body["job"]["status"] == "completed" and body["job"]["succeeded"] == 1
      and body["remaining"]["failed"] == 0)

print("\n========== 7. 判斷不出主題的回答：重新判斷的結果怎麼算 ==========")
import services.admin_recovery_service as recovery  # noqa: E402

original_reroute = recovery.reroute_answer
cases = [
    ({"routed": True, "succeeded": True}, "success"),
    ({"routed": False, "routing_error": "rate_limited"}, "transient"),
    ({"routed": False, "routing_error": "service_unavailable"}, "transient"),
    ({"routed": False, "routing_error": None, "routing_reason": "兩個主題都不適合"}, "failed"),
    ({"routed": True, "succeeded": False, "failure": {"code": "AI_QUOTA_EXCEEDED", "message": "429"}}, "transient"),
]
with app.app_context():
    for result, expected in cases:
        recovery.reroute_answer = lambda answer_id, admin_id, _r=result: _r
        outcome = brs._process("unrouted_answer", 1, 1)[0]
        check(f"重新判斷 {result} -> {expected}", outcome == expected)
recovery.reroute_answer = original_reroute

finish()
