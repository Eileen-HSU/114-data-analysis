#!/usr/bin/env python
"""
AI 第二意見（services/second_opinion_service.py）。

涵蓋：
    1. 一致 -> 自動通過；不一致 -> 維持待審、標記 ai_disagreement、保留第二意見；
       模型認為都不適合 -> 不一致；回傳清單外的類別 -> failed，不會一直重試
    2. 送給模型的內容：個資已遮蔽、沒有告訴它第一次的答案、用較強的模型
    3. 不處理：高信心、新類別、分類架構未發布、有人在審核、已經做過的
    4. AI 額度用完 -> 自動暫停，資料維持可處理
    5. AI 思考期間有人審核了這筆 -> 不覆蓋人工結果
    6. 排程自動處理（用 Admin 的 key）
    7. Admin API：進度、開始、權限

執行方式：
    cd backend
    python3 tests/test_second_opinion.py
"""

import os

from admin_test_support import (
    GEMINI_CALLS, GEMINI_QUEUE, admin_header, check, create_app, finish, q, seed_classification,
    seed_people, seed_topic, seed_upload_batch, user_header,
)
import models as m
import services.gemini_client as gemini_client
from extensions import db
from services import bulk_retry_service as brs
from services import second_opinion_service as sos

brs._sleep = lambda seconds: None
os.environ.pop("SECOND_OPINION_MODEL", None)

app = create_app()
client = app.test_client()

with app.app_context():
    seed_people()
    version_id = seed_topic("so_topic")
    draft_version = seed_topic("so_draft_topic", status="draft")


def seed_low(text, sub="A1 Original", main="Main A", version=None, **extra):
    with app.app_context():
        ids = seed_upload_batch(f"batch-{text}", [text], question_type="so_topic")
        kwargs = dict(version_id=version or version_id, confidence=0.6, needs_human_review=True,
                      review_flag_reason="low_confidence")
        kwargs.update(extra)
        return seed_classification(ids[0], f"batch-{text}", text, main, sub, **kwargs)


def row(cid):
    with app.app_context():
        r = db.session.get(m.Response_Classification, cid)
        db.session.expunge(r)
        return r


def run():
    with app.app_context():
        return brs.start(1, run_inline=True, kind=brs.KIND_SECOND_OPINION)


print("========== 1. 一致／不一致／都不適合／清單外 ==========")
agree = seed_low("教育訓練很有幫助")
disagree = seed_low("主管常常給回饋")
none_fit = seed_low("今天天氣很好")
invalid = seed_low("其他意見")
GEMINI_QUEUE.clear()
GEMINI_CALLS.clear()
q({"sub_category": "A1 Original", "reasoning": "在講訓練"})
q({"sub_category": "B1 Candidate", "reasoning": "在講回饋"})
q({"sub_category": None, "reasoning": "跟工作無關"})
q({"sub_category": "不存在的類別", "reasoning": "x"})
job = run()
check("工作完成：一致 1、其他 3", job["status"] == "completed" and job["succeeded"] == 1 and job["still_failed"] == 3)

r = row(agree)
check("一致 -> 自動通過", r.review_status == "confirmed" and r.auto_confirmed is True
      and r.second_opinion_status == "agreed" and r.reviewed_by_admin_id is None)
r = row(disagree)
check("不一致 -> 維持待審、標記 ai_disagreement",
      r.review_status == "pending_review" and r.second_opinion_status == "disagreed"
      and r.review_flag_reason == "ai_disagreement" and r.needs_human_review is True)
check("不一致時保留第二意見給人工參考",
      r.second_opinion_sub_category == "B1 Candidate" and r.second_opinion_main_category == "Main B"
      and r.second_opinion_reasoning == "在講回饋" and r.sub_category == "A1 Original")
r = row(none_fit)
check("都不適合 -> 不一致、第二意見為空",
      r.second_opinion_status == "disagreed" and r.second_opinion_sub_category is None
      and r.review_status == "pending_review")
r = row(invalid)
check("回傳清單外的類別 -> failed、維持待審", r.second_opinion_status == "failed" and r.review_status == "pending_review")
with app.app_context():
    audits = m.Admin_Audit_Log.query.filter_by(action="second_opinion").all()
    check("一致／不一致都寫 audit，記成系統（沒有管理員）",
          len(audits) == 3 and all(a.admin_id is None for a in audits))
GEMINI_QUEUE.clear()
resp = client.post("/api/admin/ai/second-opinion", headers=admin_header(1))
check("做過的不會再做（沒有可處理的 -> 409 NOTHING_TO_RETRY）",
      resp.status_code == 409 and resp.get_json()["code"] == "NOTHING_TO_RETRY")


print("\n========== 2. 送給模型的內容 ==========")
GEMINI_CALLS.clear()
pii = seed_low("請聯絡我 test.user@example.com 謝謝")
q({"sub_category": "A1 Original", "reasoning": "x"})
captured_models = []
_original_init = gemini_client.GenerativeModel.__init__


def _capture_init(self, *args, **kwargs):
    captured_models.append(kwargs.get("model_name"))
    _original_init(self, *args, **kwargs)


gemini_client.GenerativeModel.__init__ = _capture_init
run()
gemini_client.GenerativeModel.__init__ = _original_init
call = GEMINI_CALLS[-1]
check("個資已遮蔽（email 沒有送出去）", "test.user@example.com" not in str(call["contents"]))
check("沒有告訴模型第一次的答案（使用者訊息只有回覆內容）",
      str(call["contents"]).startswith("問卷回覆內容") and "A1 Original" not in str(call["contents"]))
check("類別清單與定義放在系統指示裡", "A1 Original" in call["system_instruction"]
      and "B1 Candidate" in call["system_instruction"])
check("用較強的模型（預設 gemini-3.5-flash）", captured_models == ["gemini-3.5-flash"])


print("\n========== 3. 不處理的資料 ==========")
high = seed_low("高信心", confidence=0.95, needs_human_review=False, review_flag_reason=None)
newcat = seed_low("新類別", sub="新東西", main="Main C", status="new_category",
                  review_flag_reason="new_category_proposed")
draft_row = seed_low("草稿主題", version=draft_version)
reviewing = seed_low("有人在審")
with app.app_context():
    db.session.add(m.Classification_Review(classification_id=reviewing, admin_id=1, status="in_progress"))
    db.session.commit()
GEMINI_QUEUE.clear()
GEMINI_CALLS.clear()
with app.app_context():
    # 分類架構未發布的暫定分類處理時一定會跳過，所以一開始就不算「等 AI 再確認」
    check("分類架構未發布的不算等 AI 再確認，沒有資料可處理，也沒有呼叫 AI",
          sos.eligible_count() == 0 and len(GEMINI_CALLS) == 0)
check("高信心、新類別、有人在審的都沒被動",
      all(row(c).second_opinion_status is None for c in (high, newcat, reviewing)))
check("分類架構未發布的維持原樣", row(draft_row).second_opinion_status is None
      and row(draft_row).review_status == "pending_review")
with app.app_context():
    db.session.get(m.Response_Classification, draft_row).review_flag_reason = "low_confidence_draft_done"
    db.session.commit()


print("\n========== 4. AI 額度用完 ==========")
quota = seed_low("額度測試")
GEMINI_QUEUE.clear()
for _ in range(5):
    q(RuntimeError("429 RESOURCE_EXHAUSTED quota exceeded"))
job = run()
check("連續額度用完 -> 自動暫停", job["status"] == "paused_quota")
check("資料維持可處理（之後會再試）", row(quota).second_opinion_status is None
      and row(quota).review_status == "pending_review")
GEMINI_QUEUE.clear()
q({"sub_category": "A1 Original", "reasoning": "x"})
job = run()
check("額度恢復後再跑一次就接續完成", job["status"] == "completed" and row(quota).second_opinion_status == "agreed")


print("\n========== 5. AI 思考期間有人審核了 ==========")
race = seed_low("審核競爭")
_original_ask = sos.ask_model


def ask_while_admin_reviews(r, version):
    result = _original_ask(r, version)
    # 模擬：AI 還在處理時，管理員先把這筆改成別的類別
    target = db.session.get(m.Response_Classification, race)
    target.review_status, target.final_sub_category = "modified", "B1 Candidate"
    db.session.commit()
    return result


sos.ask_model = ask_while_admin_reviews
GEMINI_QUEUE.clear()
q({"sub_category": "A1 Original", "reasoning": "x"})
job = run()
sos.ask_model = _original_ask
r = row(race)
check("人工結果沒有被覆蓋", r.review_status == "modified" and r.final_sub_category == "B1 Candidate"
      and r.auto_confirmed is False and r.second_opinion_status is None)
check("這筆記為跳過", job["skipped"] == 1)


print("\n========== 6. 排程自動處理（用 Admin 的 key）==========")
scheduled = seed_low("排程測試")
os.environ["ADMIN_GEMINI_API_KEY"] = "admin-key-SCHED"
keys = []
_original_generate = gemini_client.GenerativeModel.generate_content


def _record_key(self, contents, **kwargs):
    keys.append(gemini_client.current_api_key())
    return _original_generate(self, contents, **kwargs)


gemini_client.GenerativeModel.generate_content = _record_key
GEMINI_QUEUE.clear()
q({"sub_category": "A1 Original", "reasoning": "x"})
brs.scheduled_second_opinion(app)
gemini_client.GenerativeModel.generate_content = _original_generate
os.environ.pop("ADMIN_GEMINI_API_KEY", None)
check("排程自動處理完成", row(scheduled).second_opinion_status == "agreed")
check("排程用 Admin 的 key", keys == ["admin-key-SCHED"])
with app.app_context():
    latest = m.Bulk_Retry_Job.query.filter_by(kind="second_opinion").order_by(m.Bulk_Retry_Job.job_id.desc()).first()
    check("排程開始的工作記成系統（admin 0）", latest.started_by_admin_id == brs.SYSTEM_ADMIN_ID)
GEMINI_QUEUE.clear()
brs.scheduled_second_opinion(app)
check("沒有資料時排程什麼都不做", len(GEMINI_QUEUE) == 0)


print("\n========== 7. Admin API ==========")
body = client.get("/api/admin/ai/second-opinion", headers=admin_header(1)).get_json()
check("進度 API：最近一次工作與剩餘數量", body["job"]["kind"] == "second_opinion" and body["remaining"]["total"] == 0)
check("全部重試的進度不會看到 AI 再確認的工作",
      (client.get("/api/admin/ai/unassigned/retry-all", headers=admin_header(1)).get_json()["job"] or {}).get("kind")
      in (None, "retry"))
check("非管理員不能用", client.get("/api/admin/ai/second-opinion", headers=user_header(1)).status_code in (401, 403)
      and client.post("/api/admin/ai/second-opinion", headers=user_header(1)).status_code in (401, 403))


class InlineThread:
    def __init__(self, target, args, **kwargs):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


api_row = seed_low("API 開始")
original_thread = brs.threading.Thread
brs.threading.Thread = InlineThread
GEMINI_QUEUE.clear()
q({"sub_category": "A1 Original", "reasoning": "x"})
resp = client.post("/api/admin/ai/second-opinion", headers=admin_header(1))
brs.threading.Thread = original_thread
check("API 開始 -> 202，並完成", resp.status_code == 202 and row(api_row).second_opinion_status == "agreed")

finish()
