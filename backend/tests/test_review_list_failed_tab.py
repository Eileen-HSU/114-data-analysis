#!/usr/bin/env python
"""
分類審查清單 GET /api/admin/ai/classifications：預設篩選（queue=human）不能把「失敗」的列藏起來。

前端只有待審分頁會帶 queue；失敗等其他分頁不帶，後端預設 queue=human。失敗的列有自己的分頁
（state=failed），不屬於待審佇列，不能因為預設篩選讓 failed 分頁與 status_counts.failed 永遠是 0。

執行方式：
    cd backend
    python3 tests/test_review_list_failed_tab.py
"""

import os

from admin_test_support import (
    admin_header, check, create_app, finish, seed_classification, seed_people, seed_topic, seed_upload_batch,
)

os.environ.pop("OPEN_CLASSIFICATION_ENABLED", None)
app = create_app()
client = app.test_client()

with app.app_context():
    seed_people()
    v = seed_topic("t1", categories=[("Main A", "A1", "m", "c")])
    ids = seed_upload_batch("b1", ["失敗的回答", "待人工的回答", "系統處理中的回答"], question_type="t1")
    failed_cid = seed_classification(ids[0], "b1", "失敗的回答", None, None, version_id=v, status="failed")
    human_cid = seed_classification(ids[1], "b1", "待人工的回答", "Main A", "A1", version_id=v, status="completed",
                                    review_flag_reason="ai_disagreement")
    auto_cid = seed_classification(ids[2], "b1", "系統處理中的回答", "Main A", "A1", version_id=v, status="completed")


def get(qs):
    return client.get("/api/admin/ai/classifications?" + qs, headers=admin_header(1)).get_json()


def cids(body):
    return {r["classification_id"] for r in body["classifications"]}


print("========== 前端 failed 分頁實際送出的請求：state=failed（沒有 queue）==========")
body = get("state=failed&topic=t1")
check("failed 分頁看得到失敗的列", cids(body) == {failed_cid} and body["total"] == 1)
check("status_counts.failed = 1（不是 0）", body["status_counts"]["failed"] == 1)

print("\n========== 待審分頁：預設只留需要人工處理的 ==========")
body = get("state=pending_review&topic=t1&queue=human")
check("待審分頁只有需要人工的那筆（失敗的不在待審、系統處理中的被隱藏）", cids(body) == {human_cid})
check("待審 status_counts.pending_review = 1", body["status_counts"]["pending_review"] == 1)
body = get("state=pending_review&topic=t1")
check("沒帶 queue 時預設也是 human，待審清單不變", cids(body) == {human_cid})
body = get("state=pending_review&topic=t1&queue=ai_disagreement")
check("指定單一人工桶（ai_disagreement）時，待審清單也不變、失敗的列不混進來", cids(body) == {human_cid})

print("\n========== queue=all 看全部（API 使用者）==========")
body = get("topic=t1&queue=all")
check("queue=all 不篩選：3 筆都在", cids(body) == {failed_cid, human_cid, auto_cid})

finish()
