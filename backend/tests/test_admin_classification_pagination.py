#!/usr/bin/env python
"""
P1-6：Admin 分類審查清單 server-side pagination / counts / filtering。

涵蓋：
    1. total / status_counts 是「全部資料」的數字，不是目前頁面（> 200 筆也正確）
    2. page / page_size 穩定排序（created_at DESC, classification_id DESC），
       跨頁不重複、不遺漏
    3. state 篩選：pending_review（含 in_review）/ in_review / failed /
       confirmed / modified / excluded，failed 跟 pending 不混用
    4. topic + needs_human_review + state AND 疊加，status_counts 反映 topic 篩選
    5. 每列回傳 review_state、active_review（審核中的 Admin）、effective_result
       （excluded / failed 為 null）
    6. superseded 列不出現；不合法參數 400 + code

執行方式：
    cd backend
    python3 tests/test_admin_classification_pagination.py
"""

from admin_test_support import (
    admin_header, check, create_app, finish, seed_classification, seed_people, seed_topic,
    seed_upload_batch,
)
import models as m
from extensions import db

app = create_app()
client = app.test_client()

with app.app_context():
    seed_people()
    v1 = seed_topic("topic_a")
    v2 = seed_topic("topic_b")
    ids = seed_upload_batch("batch-page", [f"t{i}" for i in range(260)])
    expected = {"pending_review": 0, "failed": 0, "confirmed": 0, "modified": 0, "excluded": 0}
    for i, answer_id in enumerate(ids):
        kind = ["pending_review", "confirmed", "modified", "excluded", "failed"][i % 5]
        kw = {"review_status": kind if kind != "failed" else "pending_review"}
        if kind == "failed":
            kw["status"] = "failed"
        if kind == "modified":
            kw.update(final_main_category="Main B", final_sub_category="B1 Candidate")
        seed_classification(answer_id, "batch-page", f"t{i}", "Main A", "A1 Original",
                            version_id=v1 if i < 250 else v2, needs_human_review=(i % 2 == 0), **kw)
        if i < 250:
            expected[kind] += 1
    # 一筆 in_review
    in_review_cid = m.Response_Classification.query.filter_by(review_status="pending_review", status="completed").first().classification_id
    db.session.add(m.Classification_Review(classification_id=in_review_cid, admin_id=2, status="in_progress"))
    # 一筆 superseded（不該出現）
    superseded_cid = seed_classification(seed_upload_batch("batch-page", ["old"])[0], "batch-page", "old", "Main A", "A1 Original",
                                         version_id=v1, status="superseded")
    db.session.commit()


def get(params):
    return client.get(f"/api/admin/ai/classifications?{params}", headers=admin_header(1))


print("========== 1. counts 與 total 是全部資料 ==========")
body = get("topic=topic_a&page_size=50").get_json()
check("topic_a total=250（不是 200 上限、也不是頁面筆數）", body["total"] == 250)
check("這一頁 50 筆", len(body["classifications"]) == 50)
counts = body["status_counts"]
check("status_counts 各狀態正確", all(counts[k] == v for k, v in expected.items()))
check("in_review=1（pending_review 的子集合）", counts["in_review"] == 1)
check("failed 不算進 pending_review", counts["pending_review"] == expected["pending_review"])
check("total_pages=5", body["total_pages"] == 5)


print("\n========== 2. 穩定排序、跨頁不重複不遺漏 ==========")
seen = []
for page in range(1, 6):
    seen += [r["classification_id"] for r in get(f"topic=topic_a&page={page}&page_size=50").get_json()["classifications"]]
check("5 頁共 250 筆、沒有重複", len(seen) == 250 and len(set(seen)) == 250)
check("superseded 不出現", superseded_cid not in seen)
check("第 6 頁為空", get("topic=topic_a&page=6&page_size=50").get_json()["classifications"] == [])
check("page_size 上限 200", get("page_size=1000").get_json()["page_size"] == 200)


print("\n========== 3. state 篩選 ==========")
for state, n in expected.items():
    body = get(f"topic=topic_a&state={state}&page_size=200").get_json()
    check(f"state={state} total={n}", body["total"] == n)
failed_rows = get("topic=topic_a&state=failed&page_size=200").get_json()["classifications"]
check("failed 列 review_state=failed、effective_result=null",
      all(r["review_state"] == "failed" and r["effective_result"] is None for r in failed_rows))
excluded_rows = get("topic=topic_a&state=excluded&page_size=5").get_json()["classifications"]
check("excluded 列 effective_result=null", all(r["effective_result"] is None for r in excluded_rows))
modified_rows = get("topic=topic_a&state=modified&page_size=5").get_json()["classifications"]
check("modified 列 effective_result 使用 final_*", all(r["effective_result"]["sub_category"] == "B1 Candidate" for r in modified_rows))
in_review = get("topic=topic_a&state=in_review").get_json()["classifications"]
check("in_review 列帶 active_review（Bob）",
      len(in_review) == 1 and in_review[0]["review_state"] == "in_review" and in_review[0]["active_review"]["admin_name"] == "Bob")


print("\n========== 4. AND 疊加 ==========")
body = get("topic=topic_b&page_size=200").get_json()
check("topic_b 只有 10 筆，counts 也只算 topic_b", body["total"] == 10 and sum(
    body["status_counts"][k] for k in ("pending_review", "failed", "confirmed", "modified", "excluded")) == 10)
body = get("topic=topic_a&state=confirmed&needs_human_review=true&page_size=200").get_json()
check("topic + state + needs_human_review", body["total"] > 0 and all(
    r["needs_human_review"] and r["review_status"] == "confirmed" for r in body["classifications"]))
check("舊參數 review_status 仍可用", get("topic=topic_a&review_status=excluded&page_size=200").get_json()["total"] == expected["excluded"])


print("\n========== 5. 不合法參數 ==========")
check("state 不合法 -> 400 INVALID_STATE", get("state=nope").get_json()["code"] == "INVALID_STATE")
check("review_status 不合法 -> 400 INVALID_REVIEW_STATUS", get("review_status=nope").get_json()["code"] == "INVALID_REVIEW_STATUS")

finish()
