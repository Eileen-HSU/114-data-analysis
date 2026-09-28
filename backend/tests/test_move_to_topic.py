#!/usr/bin/env python
"""
主題分錯了：移到其他主題。

涵蓋：
    1. 單筆：審核畫面顯示目前主題；reclassify 到指定主題 -> 用目標主題的分類架構重新分類，
       舊結果 superseded、Uploaded_Answer.question_type 改成目標主題、audit、報告過期
    2. 整個主題併入：自動主題 -> 既有主題
       - 來源主題 merged_into、草稿 archived、不再是 routing 候選
       - 來源主題底下的資料全部用目標主題重新分類
       - 之後同名欄位的資料直接用目標主題，不會再自動歸納
    3. 防呆：不能併入自己、不能併入已被合併的主題、已發布主題不能整個搬走、
       目標主題沒有分類架構 -> 422；已人工定案的回答跳過並回報

執行方式：
    cd backend
    python3 tests/test_move_to_topic.py
"""

import io
import os

import pandas as pd

from admin_test_support import (
    GEMINI_CALLS, GEMINI_QUEUE, admin_header, check, create_app, finish, q, seed_classification,
    seed_people, seed_topic, seed_upload_batch, user_header,
)
import models as m
from extensions import db
from services.privacy_service import mask_pii

os.environ.pop("OPEN_CLASSIFICATION_ENABLED", None)
app = create_app()
client = app.test_client()

with app.app_context():
    seed_people()
    target_version = seed_topic("career", categories=[
        ("職涯發展", "A1 教育訓練", "m1", "c1"),
        ("職涯發展", "A2 升遷制度", "m2", "c2"),
    ])
    seed_topic("leadership", categories=[("主管領導", "B1 溝通", "m", "c")])


def classify_q(text, main, sub):
    q({"segments": [mask_pii(text)]})
    q({"classifications": [{"index": 0, "main_category": main, "sub_category": sub,
                            "secondary_sub_category": None, "reasoning": "r", "summary": "s", "confidence": 0.9}]})


def upload(column, texts):
    df = pd.DataFrame({column: texts})
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    buf.seek(0)
    resp = client.post("/api/classification/upload", data={"file": (buf, "u.xlsx"), "text_column": column},
                       headers=user_header(1), content_type="multipart/form-data")
    return resp.get_json()


print("========== 1. 單筆移到其他主題 ==========")
with app.app_context():
    ids = seed_upload_batch("batch-one", ["希望多一點教育訓練"], question_type="leadership")
    leader_version = m.Taxonomy_Version.query.filter_by(topic_key="leadership").one().version_id
    cid = seed_classification(ids[0], "batch-one", "希望多一點教育訓練", "主管領導", "B1 溝通", version_id=leader_version)
    db.session.add(m.Report(source_type="user_upload", upload_batch_id="batch-one", version=1, status="completed", is_outdated=False))
    db.session.commit()
state = client.get(f"/api/classification/{cid}/review", headers=admin_header(1)).get_json()
check("審核畫面顯示目前主題", state["topic"]["topic_key"] == "leadership")
client.post(f"/api/classification/{cid}/review/start", headers=admin_header(2))
GEMINI_QUEUE.clear()
resp = client.post(f"/api/admin/ai/classifications/{cid}/reclassify", headers=admin_header(1), json={"topic_key": "career"})
check("別人審核中 -> 409，不呼叫 AI", resp.status_code == 409 and resp.get_json()["code"] == "REVIEW_IN_PROGRESS_BY_OTHER")
classify_q("希望多一點教育訓練", "職涯發展", "A1 教育訓練")
resp = client.post(f"/api/admin/ai/classifications/{cid}/reclassify", headers=admin_header(2), json={"topic_key": "career"})
body = resp.get_json()
check("移動 200，用目標主題重新分類", resp.status_code == 200 and body["topic_key"] == "career"
      and body["classifications"][0]["sub_category"] == "A1 教育訓練")
with app.app_context():
    check("舊結果 superseded（保留歷史）", db.session.get(m.Response_Classification, cid).status == "superseded")
    rv = m.Classification_Review.query.filter_by(classification_id=cid).one()
    check("自己的審核對話自動關閉", rv.status == "closed" and rv.closed_reason == "superseded")
    check("Uploaded_Answer 改到目標主題", db.session.get(m.Uploaded_Answer, ids[0]).question_type == "career")
    check("報告標記過期", m.Report.query.filter_by(upload_batch_id="batch-one").one().outdated_reason == "classification_rerun")
    check("audit 記錄", m.Admin_Audit_Log.query.filter_by(action="reclassify", entity_id=str(ids[0])).count() == 1)


print("\n========== 2. 整個自動主題併入既有主題 ==========")
GEMINI_QUEUE.clear()
q({"question_type": None})
q({"categories": [{"main_category": "學習", "sub_category": "課程需求", "definition": "對課程的需求"}]})
classify_q("想上 Excel 課", "學習", "課程需求")
classify_q("希望有英文課", "學習", "課程需求")
data = upload("訓練需求", ["想上 Excel 課", "希望有英文課"])
auto_key = data["columns"][0]["question_type"]  # 自動主題 key 含範圍與內容特徵，由回應取得
check("前置：建立自動主題並分類", (auto_key or "").startswith("auto_") and data["classified_count"] == 2)

GEMINI_QUEUE.clear()
classify_q("想上 Excel 課", "職涯發展", "A1 教育訓練")
classify_q("希望有英文課", "職涯發展", "A1 教育訓練")
resp = client.post(f"/api/admin/ai/topics/{auto_key}/merge-into", headers=admin_header(1), json={"target_topic_key": "career"})
body = resp.get_json()
check("併入 200、2 筆重新分類", resp.status_code == 200 and body["moved_count"] == 2 and body["skipped_count"] == 0)
with app.app_context():
    topic = db.session.get(m.Topic, auto_key)
    check("來源主題 merged_into=career", topic.merged_into == "career")
    check("來源草稿 archived（保留）", all(v.status == "archived" for v in topic.taxonomy_versions))
    rows = [r for r in m.Response_Classification.query.filter_by(upload_batch_id=data["upload_batch_id"]).all()
            if r.status != "superseded"]
    check("資料改用目標主題的分類", len(rows) == 2 and all(r.taxonomy_version_id == target_version and r.sub_category == "A1 教育訓練" for r in rows))
    check("Uploaded_Answer 全部改到 career", all(a.question_type == "career" for a in
                                                 m.Uploaded_Answer.query.filter_by(upload_batch_id=data["upload_batch_id"]).all()))
topics = client.get("/api/admin/ai/taxonomy-topics", headers=admin_header(1)).get_json()["topics"]
check("主題列表顯示已併入", next(t for t in topics if t["topic_key"] == auto_key)["merged_into"] == "career")

GEMINI_QUEUE.clear()
GEMINI_CALLS.clear()
q({"question_type": None})
classify_q("希望有 Python 課", "職涯發展", "A1 教育訓練")
data = upload("訓練需求", ["希望有 Python 課"])
check("之後同名欄位直接用 career，不再自動歸納", data["columns"][0]["question_type"] == "career" and data["classified_count"] == 1)
check("routing 候選不再包含已合併的自動主題", not any(auto_key in (c["system_instruction"] or "") for c in GEMINI_CALLS))
with app.app_context():
    check("沒有為已合併主題產生新版本", len(db.session.get(m.Topic, auto_key).taxonomy_versions) == 1)


print("\n========== 3. 防呆 ==========")
def merge(src, target):
    return client.post(f"/api/admin/ai/topics/{src}/merge-into", headers=admin_header(1), json={"target_topic_key": target})

check("併入自己 -> 400", merge("career", "career").get_json()["code"] == "INVALID_TARGET_TOPIC")
check("已發布主題不能整個搬 -> 409", merge("leadership", "career").get_json()["code"] == "SOURCE_HAS_PUBLISHED_TAXONOMY")
check("目標已被合併 -> 409", merge("career", auto_key).get_json()["code"] == "TARGET_ALREADY_MERGED")
with app.app_context():
    db.session.add(m.Topic(topic_key="empty_target", title="沒有分類架構"))
    db.session.add(m.Topic(topic_key="auto_other", title="另一個自動主題"))
    db.session.commit()
    seed_topic("auto_other2", status="draft")
    ids = seed_upload_batch("batch-reviewed", ["已確認的回答"], question_type="auto_other2")
    v = m.Taxonomy_Version.query.filter_by(topic_key="auto_other2").one().version_id
    seed_classification(ids[0], "batch-reviewed", "已確認的回答", "Main A", "A1 Original", version_id=v, review_status="confirmed")
check("目標沒有分類架構 -> 422", merge("auto_other", "empty_target").get_json()["code"] == "TAXONOMY_UNAVAILABLE")
body = merge("auto_other2", "career").get_json()
check("已人工定案的回答跳過並回報", body["moved_count"] == 0 and body["skipped"][0]["code"] == "REPROCESS_BLOCKED_BY_REVIEW")
check("非 admin 不能合併", client.post(f"/api/admin/ai/topics/{auto_key}/merge-into", json={"target_topic_key": "career"}).status_code == 401)

GEMINI_QUEUE.clear()
finish()
