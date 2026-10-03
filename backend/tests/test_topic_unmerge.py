#!/usr/bin/env python
"""
解除主題合併：POST /api/admin/ai/topics/<key>/unmerge

語意（刻意收窄）：只清空 merged_into、只影響之後的 routing；不搬回已重新分類到目標主題的回答、
不還原既有分類結果。

涵蓋：
    1. 真實流程（上傳 -> 自動主題 -> merge-into -> unmerge）：
       - merged_into 清空、之後 follow_merge 不再導向目標
       - 已搬到目標的資料完全不被改回（分類列、Uploaded_Answer.question_type、報告狀態都不變）
       - 回傳 answers_staying_on_target（留在原合併目標、不會自動移回的筆數）
       - 被封存的 draft 恢復成 draft、archived_at 清掉
       - 寫 unmerge_topic audit（before / after）
       - 再解除一次 -> 409 TOPIC_NOT_MERGED
    2. 恢復版本的條件：
       - 來源已經有 active（非 archived）版本 -> 不恢復
       - merge audit 沒有封存版本紀錄 -> 不恢復，但仍解除合併
       - 重試併入留下 archived_version_ids=[] 的 audit -> 往前找真正封存過的那一次
    3. 防呆：沒被合併 -> 409、找不到主題 -> 404、非 admin -> 401

執行方式：
    cd backend
    python3 tests/test_topic_unmerge.py
"""

import io
import os

import pandas as pd

from admin_test_support import (
    GEMINI_QUEUE, admin_header, check, create_app, finish, q, seed_classification, seed_people, seed_topic,
    seed_upload_batch, user_header,
)
import models as m
from extensions import db
from services.open_classification import follow_merge
from services.privacy_service import mask_pii

os.environ.pop("OPEN_CLASSIFICATION_ENABLED", None)
app = create_app()
client = app.test_client()

with app.app_context():
    seed_people()
    seed_topic("career", categories=[
        ("職涯發展", "A1 教育訓練", "m1", "c1"),
        ("職涯發展", "A2 升遷制度", "m2", "c2"),
    ])


def classify_q(text, main, sub):
    q({"segments": [mask_pii(text)]})
    q({"classifications": [{"index": 0, "main_category": main, "sub_category": sub,
                            "secondary_sub_category": None, "reasoning": "r", "summary": "s", "confidence": 0.9}]})


def upload(column, texts):
    df = pd.DataFrame({column: texts})
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    buf.seek(0)
    return client.post("/api/classification/upload", data={"file": (buf, "u.xlsx"), "text_column": column},
                       headers=user_header(1), content_type="multipart/form-data").get_json()


def merge(src, target="career"):
    return client.post(f"/api/admin/ai/topics/{src}/merge-into", headers=admin_header(1), json={"target_topic_key": target})


def unmerge(key, headers=None):
    return client.post(f"/api/admin/ai/topics/{key}/unmerge", headers=headers or admin_header(1))


def snapshot(batch_id):
    """已搬資料的完整狀態：分類列、回答所屬主題 / 路由狀態、報告狀態。"""
    rows = sorted(
        (r.classification_id, r.status, r.review_status, r.taxonomy_version_id, r.main_category, r.sub_category,
         r.final_sub_category)
        for r in m.Response_Classification.query.filter_by(upload_batch_id=batch_id).all()
    )
    answers = sorted((a.id, a.question_type, a.routing_status) for a in m.Uploaded_Answer.query.filter_by(upload_batch_id=batch_id).all())
    reports = sorted((r.report_id, r.is_outdated, r.outdated_reason) for r in m.Report.query.filter_by(upload_batch_id=batch_id).all())
    return {"rows": rows, "answers": answers, "reports": reports}


print("========== 1. 真實流程：上傳 -> 合併 -> 解除合併 ==========")
GEMINI_QUEUE.clear()
q({"question_type": None})
q({"categories": [{"main_category": "學習", "sub_category": "課程需求", "definition": "對課程的需求"}]})
classify_q("想上 Excel 課", "學習", "課程需求")
classify_q("希望有英文課", "學習", "課程需求")
data = upload("訓練需求", ["想上 Excel 課", "希望有英文課"])
auto_key = data["columns"][0]["question_type"]
batch = data["upload_batch_id"]
check("前置：建立自動主題並分類 2 筆", (auto_key or "").startswith("auto_") and data["classified_count"] == 2)
with app.app_context():
    draft_id = m.Taxonomy_Version.query.filter_by(topic_key=auto_key).one().version_id
    db.session.add(m.Report(source_type="user_upload", upload_batch_id=batch, version=1, status="completed", is_outdated=False))
    db.session.commit()

GEMINI_QUEUE.clear()
classify_q("想上 Excel 課", "職涯發展", "A1 教育訓練")
classify_q("希望有英文課", "職涯發展", "A1 教育訓練")
body = merge(auto_key).get_json()
check("前置：合併 200、2 筆重新分類", body["moved_count"] == 2 and body["skipped_count"] == 0)
with app.app_context():
    topic = db.session.get(m.Topic, auto_key)
    check("前置：merged_into=career、草稿被封存", topic.merged_into == "career"
          and db.session.get(m.Taxonomy_Version, draft_id).status == "archived")
    moved_state = snapshot(batch)
    check("前置：follow_merge 導向 career", follow_merge(auto_key) == "career")

check("非 admin -> 401", client.post(f"/api/admin/ai/topics/{auto_key}/unmerge").status_code == 401)
resp = unmerge("career")
check("沒被合併的主題 -> 409 TOPIC_NOT_MERGED", resp.status_code == 409 and resp.get_json()["code"] == "TOPIC_NOT_MERGED")
resp = unmerge("no_such_topic")
check("找不到主題 -> 404 TOPIC_NOT_FOUND", resp.status_code == 404 and resp.get_json()["code"] == "TOPIC_NOT_FOUND")

resp = unmerge(auto_key)
body = resp.get_json()
check("解除合併 200", resp.status_code == 200 and body["previous_merged_into"] == "career" and body["merged_into"] is None)
check("回傳：2 筆回答留在原合併目標、不會自動移回", body["answers_staying_on_target"] == 2 and body["answers_left_on_source"] == 0)
check("回傳：恢復了被封存的 draft", body["restored_version_ids"] == [draft_id] and body["restore_skipped_reason"] is None)
check("回傳訊息明講不會自動移回", "不會自動移回" in body["message"])
with app.app_context():
    check("merged_into 已清空", db.session.get(m.Topic, auto_key).merged_into is None)
    check("follow_merge 不再導向 career（之後的 routing 回到這個主題）", follow_merge(auto_key) == auto_key)
    version = db.session.get(m.Taxonomy_Version, draft_id)
    check("封存的版本恢復為 draft、archived_at 清掉", version.status == "draft" and version.archived_at is None)
    after_state = snapshot(batch)
    check("已搬到目標的資料完全不被改回（分類列 / 回答主題 / 報告狀態）", after_state == moved_state)
    check("回答仍在 career、分類列仍綁 career 的版本",
          all(a[1] == "career" for a in after_state["answers"])
          and all(r[3] != draft_id for r in after_state["rows"] if r[1] != "superseded"))
    audit = m.Admin_Audit_Log.query.filter_by(action="unmerge_topic", entity_type="topic", entity_id=auto_key).all()
    check("寫了 unmerge_topic audit（before / after）", len(audit) == 1 and audit[0].before_state == {"merged_into": "career"}
          and audit[0].after_state["merged_into"] is None and audit[0].after_state["restored_version_ids"] == [draft_id]
          and audit[0].after_state["answers_staying_on_target"] == 2)
topics = client.get("/api/admin/ai/taxonomy-topics", headers=admin_header(1)).get_json()["topics"]
mine = next(t for t in topics if t["topic_key"] == auto_key)
check("主題列表：不再顯示已併入、草稿回來了", mine["merged_into"] is None and mine["latest_draft_version"]["version_id"] == draft_id)
resp = unmerge(auto_key)
check("再解除一次 -> 409（不是冪等重做）", resp.status_code == 409 and resp.get_json()["code"] == "TOPIC_NOT_MERGED")

print("\n========== 2. 恢復版本的條件 ==========")
with app.app_context():
    seed_topic("auto_b1", status="draft")
check("2a 前置：合併（沒有回答）", merge("auto_b1").status_code == 200)
with app.app_context():
    b1_v1 = m.Taxonomy_Version.query.filter_by(topic_key="auto_b1", version_number=1).one().version_id
    check("2a 前置：v1 已封存", db.session.get(m.Taxonomy_Version, b1_v1).status == "archived")
    seed_topic("auto_b1", status="draft", version_number=2)  # 解除前，來源又有了一個 active 版本
    b1_v2 = m.Taxonomy_Version.query.filter_by(topic_key="auto_b1", version_number=2).one().version_id
body = unmerge("auto_b1").get_json()
check("來源已有 active 版本 -> 不恢復（ACTIVE_TAXONOMY_EXISTS），仍解除合併",
      body["restored_version_ids"] == [] and body["restore_skipped_reason"] == "ACTIVE_TAXONOMY_EXISTS"
      and body["merged_into"] is None)
with app.app_context():
    check("v1 維持 archived、v2 維持 draft",
          db.session.get(m.Taxonomy_Version, b1_v1).status == "archived" and db.session.get(m.Taxonomy_Version, b1_v2).status == "draft")

with app.app_context():
    seed_topic("plain_merged", status="archived")
    db.session.get(m.Topic, "plain_merged").merged_into = "career"
    db.session.commit()
    pm_v1 = m.Taxonomy_Version.query.filter_by(topic_key="plain_merged").one().version_id
body = unmerge("plain_merged").get_json()
check("merge audit 沒有封存紀錄 -> 不恢復（不憑空猜），仍解除合併",
      body["restored_version_ids"] == [] and body["restore_skipped_reason"] == "NO_ARCHIVED_VERSIONS_IN_MERGE_AUDIT"
      and body["merged_into"] is None)
with app.app_context():
    check("該版本維持 archived", db.session.get(m.Taxonomy_Version, pm_v1).status == "archived")

with app.app_context():
    seed_topic("auto_b3", status="draft")
check("2c 前置：第一次合併（封存 v1）", merge("auto_b3").status_code == 200)
check("2c 前置：重試併入（沒有東西可封存）", merge("auto_b3").status_code == 200)
with app.app_context():
    b3_v1 = m.Taxonomy_Version.query.filter_by(topic_key="auto_b3").one().version_id
    audits = m.Admin_Audit_Log.query.filter_by(action="merge_topic", entity_type="topic", entity_id="auto_b3").order_by(m.Admin_Audit_Log.audit_id).all()
    check("2c 前置：最近一次 merge audit 的 archived_version_ids 是空的",
          len(audits) == 2 and audits[-1].after_state["archived_version_ids"] == [] and audits[0].after_state["archived_version_ids"] == [b3_v1])
body = unmerge("auto_b3").get_json()
check("重試併入留下空 audit -> 往前找真正封存過的那一次，仍能恢復", body["restored_version_ids"] == [b3_v1])
with app.app_context():
    check("恢復為 draft", db.session.get(m.Taxonomy_Version, b3_v1).status == "draft")

print("\n========== 3. 仍留在來源的回答：解除後維持來源主題的資料 ==========")
with app.app_context():
    seed_topic("auto_left", status="draft")
    left_v = m.Taxonomy_Version.query.filter_by(topic_key="auto_left").one().version_id
    ids = seed_upload_batch("b-left", ["搬不走的回答"], question_type="auto_left")
    left_cid = seed_classification(ids[0], "b-left", "搬不走的回答", "Main A", "新類別X", version_id=left_v, status="new_category")
GEMINI_QUEUE.clear()  # 沒有 AI 回應 -> 重新分類失敗，回答留在來源
body = merge("auto_left").get_json()
check("前置：搬失敗的回答被跳過並回報", body["moved_count"] == 0 and body["skipped_count"] == 1)
body = unmerge("auto_left").get_json()
check("留在來源 1 筆、搬到目標 0 筆", body["answers_left_on_source"] == 1 and body["answers_staying_on_target"] == 0)
with app.app_context():
    row = db.session.get(m.Response_Classification, left_cid)
    check("該筆原封不動（仍是待處理的新類別候選）", row.status == "new_category" and row.review_status == "pending_review"
          and row.taxonomy_version_id == left_v)

GEMINI_QUEUE.clear()
finish()
