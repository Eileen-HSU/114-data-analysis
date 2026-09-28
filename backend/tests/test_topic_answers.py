#!/usr/bin/env python
"""
Admin 看得到主題底下的原始回答（判斷分類 / 主題對不對的依據）。

涵蓋：
    1. 來源欄位名稱與回答數、每個類別的筆數與原始回答範例
    2. 人工修改過的回答歸在修改後的類別；excluded / failed 另外計數；superseded 不列入
    3. per_category 限制範例數；main_category + sub_category 只看某一類
    4. 審核畫面顯示這則回答來自哪個欄位
    5. 權限與找不到主題

執行方式：
    cd backend
    python3 tests/test_topic_answers.py
"""

from admin_test_support import (
    admin_header, check, create_app, finish, seed_classification, seed_people, seed_topic, seed_upload_batch,
)
import models as m
from extensions import db

app = create_app()
client = app.test_client()

with app.app_context():
    seed_people()
    vid = seed_topic("auto_demo", status="draft", categories=[
        ("組織現況感知", "B1 模糊的負面感受", "m", "c"),
        ("組織現況感知", "B2 具體問題", "m", "c"),
    ])
    texts = ["不知道，怪怪的", "說不上來", "薪水太低", "主管不溝通", "沒意見", "改完的", "舊的", "壞掉的"]
    ids = seed_upload_batch("b1", texts, question_type="auto_demo", column="你對公司的感覺")
    seed_classification(ids[0], "b1", texts[0], "組織現況感知", "B1 模糊的負面感受", version_id=vid)
    seed_classification(ids[1], "b1", texts[1], "組織現況感知", "B1 模糊的負面感受", version_id=vid, review_status="confirmed")
    seed_classification(ids[2], "b1", texts[2], "組織現況感知", "B2 具體問題", version_id=vid)
    seed_classification(ids[3], "b1", texts[3], "組織現況感知", "B2 具體問題", version_id=vid)
    seed_classification(ids[4], "b1", texts[4], "組織現況感知", "B1 模糊的負面感受", version_id=vid, review_status="excluded")
    modified_id = seed_classification(
        ids[5], "b1", texts[5], "組織現況感知", "B1 模糊的負面感受", version_id=vid, review_status="modified",
        final_main_category="組織現況感知", final_sub_category="B2 具體問題")
    seed_classification(ids[6], "b1", texts[6], "組織現況感知", "B1 模糊的負面感受", version_id=vid, status="superseded")
    seed_classification(ids[7], "b1", texts[7], None, None, version_id=vid, status="failed")
    other_vid = seed_topic("career")
    other = seed_upload_batch("b2", ["別的主題"], question_type="career")
    seed_classification(other[0], "b2", "別的主題", "Main A", "A1 Original", version_id=other_vid)


print("========== 1. 來源與類別 ==========")
resp = client.get("/api/admin/ai/topics/auto_demo/answers", headers=admin_header(1))
body = resp.get_json()
check("200", resp.status_code == 200)
check("來源欄位名稱與回答數（不含 superseded）", body["sources"] == [{"label": "你對公司的感覺", "answer_count": 7}])
check("總回答數 7（只算這個主題）", body["total_answers"] == 7)
groups = {g["sub_category"]: g for g in body["groups"]}
check("B1 兩則（含已確認，不含 excluded / superseded）", groups["B1 模糊的負面感受"]["count"] == 2)
check("B2 三則（含人工修改過來的）", groups["B2 具體問題"]["count"] == 3)
check("範例是原始回答文字", {i["segment_text"] for i in groups["B1 模糊的負面感受"]["items"]} == {"不知道，怪怪的", "說不上來"})
check("範例帶審核狀態", any(i["review_status"] == "confirmed" for i in groups["B1 模糊的負面感受"]["items"]))
check("excluded / failed 另外計數", body["excluded_count"] == 1 and body["failed_count"] == 1
      and body["failed_items"][0]["segment_text"] == "壞掉的")
check("已確認 / 修改 2 則", body["reviewed_count"] == 2)

print("\n========== 2. 範例數與單一類別 ==========")
body = client.get("/api/admin/ai/topics/auto_demo/answers?per_category=1", headers=admin_header(1)).get_json()
check("per_category=1 每類只給 1 則，count 不變",
      all(len(g["items"]) == 1 for g in body["groups"]) and sum(g["count"] for g in body["groups"]) == 5)
body = client.get("/api/admin/ai/topics/auto_demo/answers",
                  query_string={"main_category": "組織現況感知", "sub_category": "B2 具體問題", "per_category": 200},
                  headers=admin_header(1)).get_json()
check("只看 B2：三則全部列出", len(body["groups"]) == 1 and len(body["groups"][0]["items"]) == 3)

print("\n========== 3. 審核畫面顯示來源欄位 ==========")
state = client.get(f"/api/classification/{modified_id}/review", headers=admin_header(1)).get_json()
check("source_question = 欄位名稱", state["source_question"] == "你對公司的感覺")

print("\n========== 4. 權限 / 錯誤 ==========")
check("非 admin 401", client.get("/api/admin/ai/topics/auto_demo/answers").status_code == 401)
resp = client.get("/api/admin/ai/topics/nope/answers", headers=admin_header(1))
check("找不到主題 404", resp.status_code == 404 and resp.get_json()["code"] == "TOPIC_NOT_FOUND")

finish()
