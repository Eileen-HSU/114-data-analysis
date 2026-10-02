#!/usr/bin/env python
"""
額度分流：Admin 觸發的 AI 呼叫用 ADMIN_GEMINI_API_KEY，使用者的用 GEMINI_API_KEY。

涵蓋：
    1. Admin 管理頁的 API（重新處理）-> Admin key
    2. 使用者上傳分析 -> 一般 key；而且緊接在 Admin 請求之後也不會沾到 Admin key
    3. 審核對話（review）-> Admin key
    4. 「全部重試」的背景 thread（真的開一條 thread）-> Admin key
    5. 沒有設定 ADMIN_GEMINI_API_KEY -> Admin 也沿用一般 key

執行方式：
    cd backend
    python3 tests/test_admin_gemini_key.py
"""

import io
import os
import tempfile
import threading

import pandas as pd

from admin_test_support import (
    GEMINI_QUEUE, admin_header, check, create_app, finish, q, seed_classification, seed_people,
    seed_topic, seed_upload_batch, user_header,
)
import models as m
import services.gemini_client as gemini_client
from extensions import db, taiwan_now
from services import bulk_retry_service as brs
from services.privacy_service import mask_pii

USER_KEY, ADMIN_KEY = "user-key-AAA", "admin-key-BBB"
gemini_client.configure(api_key=USER_KEY)
os.environ["ADMIN_GEMINI_API_KEY"] = ADMIN_KEY
brs._sleep = lambda seconds: None

# 記錄每一次 AI 呼叫當下生效的 key
KEYS = []
_original_generate = gemini_client.GenerativeModel.generate_content


def _recording_generate(self, contents, **kwargs):
    KEYS.append(gemini_client.current_api_key())
    return _original_generate(self, contents, **kwargs)


gemini_client.GenerativeModel.generate_content = _recording_generate

# 背景 thread 會開新的資料庫連線，記憶體資料庫看不到資料，所以用暫存檔
_db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
app = create_app(db_uri=f"sqlite:///{_db_file.name}")
client = app.test_client()

with app.app_context():
    seed_people()
    version_id = seed_topic("key_topic")


def queue_classification(text):
    q({"segments": [mask_pii(text)]})
    q({"classifications": [{"index": 0, "main_category": "Main A", "sub_category": "A1 Original",
                            "secondary_sub_category": None, "reasoning": "r", "summary": "s", "confidence": 0.9}]})


def seed_failed(batch, text):
    with app.app_context():
        ids = seed_upload_batch(batch, [text], question_type="key_topic")
        return seed_classification(ids[0], batch, text, None, None, version_id=version_id, status="failed")


print("========== 1. Admin 管理頁：重新處理 ==========")
failed_cid = seed_failed("batch-admin", "希望增加訓練")
GEMINI_QUEUE.clear()
KEYS.clear()
queue_classification("希望增加訓練")
resp = client.post(f"/api/admin/ai/classifications/{failed_cid}/retry", headers=admin_header(1))
check("重新處理 200", resp.status_code == 200)
check("Admin 的 AI 呼叫全部用 Admin key", KEYS and set(KEYS) == {ADMIN_KEY})


print("\n========== 2. 使用者上傳：一般 key，不沾到 Admin key ==========")
GEMINI_QUEUE.clear()
KEYS.clear()
q({"question_type": "key_topic"})
queue_classification("主管很照顧大家")
df = pd.DataFrame({"意見": ["主管很照顧大家"]})
buf = io.BytesIO()
df.to_excel(buf, index=False)
buf.seek(0)
resp = client.post("/api/classification/upload", data={"file": (buf, "u.xlsx"), "text_column": "意見"},
                   headers=user_header(1), content_type="multipart/form-data")
check("上傳 201", resp.status_code == 201)
check("使用者的 AI 呼叫全部用一般 key（Admin 請求結束後有還原）", KEYS and set(KEYS) == {USER_KEY})
check("請求結束後沒有殘留的切換", gemini_client.current_api_key() == USER_KEY)


print("\n========== 3. 審核對話 ==========")
with app.app_context():
    ids = seed_upload_batch("batch-review", ["想要彈性工時"], question_type="key_topic")
    review_cid = seed_classification(ids[0], "batch-review", "想要彈性工時", "Main A", "A1 Original",
                                     version_id=version_id)
GEMINI_QUEUE.clear()
KEYS.clear()
client.post(f"/api/classification/{review_cid}/review/start", headers=admin_header(1))
q({"reply": "建議改 B", "candidate_sub_category": "B1 Candidate", "candidate_secondary_sub_category": None,
   "candidate_reasoning": "x"})
resp = client.post(f"/api/classification/{review_cid}/review/message", headers=admin_header(1),
                   json={"message": "這筆應該是什麼？"})
check("審核對話 201（AI 有回覆候選類別）", resp.status_code == 201 and resp.get_json()["message"]["candidate_sub_category"] == "B1 Candidate")
check("審核對話的 AI 呼叫用 Admin key", KEYS and set(KEYS) == {ADMIN_KEY})


print("\n========== 4. 全部重試的背景 thread ==========")
seed_failed("batch-bulk", "加班太多")
with app.app_context():
    now = taiwan_now()
    job = m.Bulk_Retry_Job(status="running", started_by_admin_id=1, total_at_start=1, started_at=now, heartbeat_at=now)
    db.session.add(job)
    db.session.commit()
    job_id = job.job_id
GEMINI_QUEUE.clear()
KEYS.clear()
queue_classification("加班太多")
worker = threading.Thread(target=brs._run_in_thread, args=(app, job_id))
worker.start()
worker.join(timeout=60)
with app.app_context():
    finished = db.session.get(m.Bulk_Retry_Job, job_id)
    check("背景工作完成並重跑成功", finished.status == "completed" and finished.succeeded == 1)
check("背景 thread 的 AI 呼叫用 Admin key", KEYS and set(KEYS) == {ADMIN_KEY})
check("背景 thread 結束後主 thread 不受影響", gemini_client.current_api_key() == USER_KEY)


print("\n========== 5. 沒有設定 Admin key：沿用一般 key ==========")
os.environ.pop("ADMIN_GEMINI_API_KEY", None)
failed_cid = seed_failed("batch-nokey", "制度不清楚")
GEMINI_QUEUE.clear()
KEYS.clear()
queue_classification("制度不清楚")
resp = client.post(f"/api/admin/ai/classifications/{failed_cid}/retry", headers=admin_header(1))
check("重新處理 200", resp.status_code == 200)
check("沒有 Admin key 時 Admin 也用一般 key", KEYS and set(KEYS) == {USER_KEY})

os.unlink(_db_file.name)
finish()
