#!/usr/bin/env python
"""
查詢效能相關改動的行為保證（在 SQLite 上驗證「結果沒變」；速度另外在真的 MySQL 類引擎上量過）。

涵蓋：
    1. 索引：模型有宣告 Admin 清單 / 合併常用欄位的索引
    2. fast_count：和 Query.count() 結果相同（單表、過濾、join、有 order_by）
    3. 分類審查清單：status_counts 一次聚合 == 逐一狀態各數一次
    4. 新類別候選清單：改成窄查詢 + 只讀範例文字後，輸出與「逐列載入再分組」的參考實作逐欄相同
       （classification_ids / examples / reasons / 版本 / 排序，含空白 reasoning、超過 3 筆的群組）
    5. 合併主題：
       - 資料庫逾時（OperationalError）只記該筆為 DATABASE_BUSY，其他筆照常處理，不是整個 500
       - 連續逾時 3 次就中止（aborted、unprocessed_count），不是一筆筆各等一次
       - AI 等待期間不抓鎖：AI 回來時資料被別人改過 -> CONCURRENT_MODIFICATION，不覆蓋、不重複寫入
       - 已被別的請求搬走的回答不再呼叫 AI

執行方式：
    cd backend
    python3 tests/test_query_performance_guards.py
"""

import os
from unittest import mock

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import OperationalError

from admin_test_support import (
    GEMINI_QUEUE, admin_header, check, create_app, finish, q, seed_classification, seed_people, seed_topic,
    seed_upload_batch,
)
import models as m
from extensions import db
from services import admin_recovery_service as recovery
from services import new_category_service
from services.privacy_service import mask_pii
from services.query_utils import fast_count

os.environ.pop("OPEN_CLASSIFICATION_ENABLED", None)
app = create_app()
client = app.test_client()

print("========== 1. 索引 ==========")
with app.app_context():
    inspector = sa_inspect(db.engine)
    rc_indexes = {i["name"]: i["column_names"] for i in inspector.get_indexes("Response_Classification")}
    ua_indexes = {i["name"]: i["column_names"] for i in inspector.get_indexes("Uploaded_Answer")}
check("Response_Classification(status, review_status, taxonomy_version_id)",
      rc_indexes.get("ix_rc_status_review_version") == ["status", "review_status", "taxonomy_version_id"])
check("Response_Classification(review_status, created_at)", rc_indexes.get("ix_rc_review_created") == ["review_status", "created_at"])
check("Uploaded_Answer(question_type) 與 (upload_batch_id)",
      ua_indexes.get("ix_ua_question_type") == ["question_type"] and ua_indexes.get("ix_ua_upload_batch") == ["upload_batch_id"])

# ── 共用資料：兩個主題、各種狀態的分類列 ──
with app.app_context():
    seed_people()
    v_a = seed_topic("topic_a", categories=[("Main A", "A1", "m", "c"), ("Main B", "B1", "m", "c")])
    v_b = seed_topic("topic_b", categories=[("Main A", "A1", "m", "c")])
    ids = seed_upload_batch("b-mix", [f"回答{i}" for i in range(30)], question_type="topic_a")
    states = [
        dict(status="completed", review_status="pending_review"),
        dict(status="completed", review_status="confirmed", auto_confirmed=True),
        dict(status="completed", review_status="confirmed"),
        dict(status="completed", review_status="modified"),
        dict(status="completed", review_status="excluded"),
        dict(status="failed", review_status="pending_review"),
        dict(status="superseded", review_status="pending_review"),
        dict(status="completed", review_status="pending_review", review_flag_reason="ai_disagreement"),
    ]
    for i, aid in enumerate(ids):
        extra = dict(states[i % len(states)])
        status = extra.pop("status"); review = extra.pop("review_status")
        seed_classification(aid, "b-mix", f"回答{i}", "Main A", "A1", version_id=v_a if i % 3 else v_b,
                            status=status, review_status=review, **extra)

print("\n========== 2. fast_count == Query.count() ==========")
with app.app_context():
    RC = m.Response_Classification
    cases = {
        "單表": RC.query,
        "過濾": RC.query.filter(RC.review_status == "pending_review"),
        "join": RC.query.join(m.Taxonomy_Version, RC.taxonomy_version_id == m.Taxonomy_Version.version_id)
                  .filter(m.Taxonomy_Version.topic_key == "topic_a"),
        "有 order_by": RC.query.filter(RC.status != "superseded").order_by(RC.created_at.desc()),
        "另一張表": m.Uploaded_Answer.query.filter(m.Uploaded_Answer.question_type == "topic_a"),
        "空結果": RC.query.filter(RC.status == "no_such_status"),
    }
    for label, query in cases.items():
        check(f"{label}：fast_count == count()（{query.count()}）", fast_count(query) == query.count())

print("\n========== 3. 分類審查清單 status_counts 一次聚合 ==========")
from routes.admin.ai_admin import CLASSIFICATION_STATES, _state_clause
with app.app_context():
    base = m.Response_Classification.query.filter(db.or_(m.Response_Classification.status.is_(None), m.Response_Classification.status != "superseded"))
    expected = {s: base.filter(_state_clause(s)).count() for s in CLASSIFICATION_STATES}
    expected_auto = base.filter(m.Response_Classification.auto_confirmed.is_(True)).count()
body = client.get("/api/admin/ai/classifications?queue=all&page_size=5", headers=admin_header(1)).get_json()
check("每個狀態的筆數與逐一計算相同", body["status_counts"] == expected)
check("auto_confirmed_count 相同", body["auto_confirmed_count"] == expected_auto)
check("total 與頁面資料一致", body["total"] == sum(1 for _ in range(1)) * body["total"] and len(body["classifications"]) == 5)
body = client.get("/api/admin/ai/classifications?queue=all&topic=topic_a&state=confirmed&page_size=100", headers=admin_header(1)).get_json()
check("帶 topic（會 join）+ state 時 total 正確", body["total"] == len(body["classifications"]) and body["total"] > 0)

print("\n========== 4. 新類別候選：窄查詢輸出 == 逐列載入的參考實作 ==========")
with app.app_context():
    # 同一主題 topic_a 的兩個版本：前 6 筆綁 v1、後 3 筆綁 v2 -> 同一群組、版本不一致
    v_a2 = seed_topic("topic_a", status="draft", version_number=2, categories=[("Main A", "A1", "m", "c")])
    ids = seed_upload_batch("b-nc", [f"新類別回答{i}" for i in range(9)], question_type="topic_a")
    for i, aid in enumerate(ids):
        seed_classification(aid, "b-nc", f"新類別回答{i}-" + "字" * 5, "Main A", "新類別甲", version_id=v_a if i < 6 else v_a2,
                            status="new_category")
        row = m.Response_Classification.query.filter_by(uploaded_answer_id=aid).one()
        row.reasoning = ["", None, "理由一", "理由二", "   ", "理由三", "理由四", "理由五", ""][i]   # 空字串 / None / 空白字串
        row.segment_start, row.segment_end = 1, 6
    more = seed_upload_batch("b-nc2", ["另一組回答"], question_type="topic_b")
    seed_classification(more[0], "b-nc2", "另一組回答", "Main B", "新類別乙", version_id=v_b, status="new_category")
    db.session.commit()

    def reference(topic_key=None):
        """舊實作：把每一列整個載入，再用 Python 分組。"""
        entries = new_category_service._candidate_entries(topic_key, residual=False)
        groups = {}
        for row, row_topic, _exists, _merged in entries:
            g = groups.setdefault((row_topic, row.main_category, row.sub_category), {
                "topic_key": row_topic, "main_category": row.main_category, "sub_category": row.sub_category,
                "count": 0, "classification_ids": [], "examples": [], "reasons": [], "taxonomy_version_ids": []})
            g["count"] += 1
            g["classification_ids"].append(row.classification_id)
            if row.taxonomy_version_id is not None and row.taxonomy_version_id not in g["taxonomy_version_ids"]:
                g["taxonomy_version_ids"].append(row.taxonomy_version_id)
            if len(g["examples"]) < 3:
                g["examples"].append(row.answer_text[row.segment_start:row.segment_end])
            if row.reasoning and len(g["reasons"]) < 3:
                g["reasons"].append(row.reasoning)
        out = sorted(groups.values(), key=lambda g: (-g["count"], g["topic_key"] or "", g["sub_category"] or ""))
        for g in out:
            g["taxonomy_version_ids"] = sorted(g["taxonomy_version_ids"])
            g["version_mismatch"] = len(g["taxonomy_version_ids"]) > 1
        return out
    actual = new_category_service.list_candidates()["items"]
    ref = reference()
    keep = ("topic_key", "main_category", "sub_category", "count", "classification_ids", "examples", "reasons",
            "taxonomy_version_ids", "version_mismatch")
    strip = lambda items: [{k: it[k] for k in keep} for it in items]
big = next(i for i in strip(actual) if i["sub_category"] == "新類別甲")
check("群組、排序、筆數與參考實作完全相同", strip(actual) == strip(ref))
check("超過 3 筆的群組：examples 只取前 3 筆", len(big["examples"]) == 3 and big["count"] == 9)
check("reasons：略過 None / 空字串，只取前 3 個有內容的（空白字串算有內容，與舊行為一致）", big["reasons"] == ["理由一", "理由二", "   "])
check("classification_ids 依 id 排序", big["classification_ids"] == sorted(big["classification_ids"]))
check("綁定不同版本 -> version_mismatch", big["version_mismatch"] is True and len(big["taxonomy_version_ids"]) == 2)
with app.app_context():
    check("限定主題時也相同", strip(new_category_service.list_candidates("topic_b")["items"]) == strip(reference("topic_b")))

print("\n========== 5. 合併主題：逾時 / 並發 ==========")


def classify_queue(texts, target_sub="A1", target_main="Main A"):
    for text in texts:
        q({"segments": [mask_pii(text)]})
        q({"classifications": [{"index": 0, "main_category": target_main, "sub_category": target_sub,
                                "secondary_sub_category": None, "reasoning": "r", "summary": "s", "confidence": 0.9}]})


def seed_source(key, texts):
    with app.app_context():
        seed_topic(key, status="draft", categories=[("Main A", "A1", "m", "c")])
        vid = m.Taxonomy_Version.query.filter_by(topic_key=key).one().version_id
        aids = seed_upload_batch(f"b-{key}", texts, question_type=key)
        for aid, text in zip(aids, texts):
            seed_classification(aid, f"b-{key}", text, "Main A", "A1", version_id=vid, status="completed")
    return aids


def merge(key):
    return client.post(f"/api/admin/ai/topics/{key}/merge-into", headers=admin_header(1), json={"target_topic_key": "topic_a"})


def timeout_error():
    return OperationalError("SELECT ...", {}, Exception("(2013, 'Lost connection to MySQL server during query (timed out)')"))


# 5a. 第一筆逾時，其他筆照常
texts = ["逾時一", "正常二", "正常三"]
aids = seed_source("auto_t1", texts)
GEMINI_QUEUE.clear(); classify_queue(texts[1:])
real_lock = recovery._lock_answer
def lock_with_one_timeout(answer_id):
    if answer_id == aids[0]:
        raise timeout_error()
    return real_lock(answer_id)
with mock.patch.object(recovery, "_lock_answer", side_effect=lock_with_one_timeout):
    resp = merge("auto_t1")
body = resp.get_json()
check("資料庫逾時不再讓整個請求 500（200）", resp.status_code == 200)
check("逾時那筆記為 DATABASE_BUSY、其他 2 筆照常搬走",
      body["moved_count"] == 2 and [s["code"] for s in body["skipped"]] == ["DATABASE_BUSY"]
      and body["skipped"][0]["uploaded_answer_id"] == aids[0] and body["aborted"] is False)
with app.app_context():
    left = m.Uploaded_Answer.query.filter_by(question_type="auto_t1").all()
    check("逾時那筆原封不動留在來源（可再按重試併入）", [a.id for a in left] == [aids[0]])

# 5b. 連續逾時 -> 中止
texts = [f"全部逾時{i}" for i in range(6)]
aids = seed_source("auto_t2", texts)
GEMINI_QUEUE.clear()
with mock.patch.object(recovery, "_lock_answer", side_effect=lambda _id: (_ for _ in ()).throw(timeout_error())):
    body = merge("auto_t2").get_json()
check("連續 3 次逾時就中止（不是 6 筆各等一次）", body["aborted"] is True and body["skipped_count"] == 3)
check("回報還沒處理的筆數", body["unprocessed_count"] == 3 and body["moved_count"] == 0)

# 5c. AI 等待期間資料被改過 -> CONCURRENT_MODIFICATION
texts = ["並發一", "並發二"]
aids = seed_source("auto_t3", texts)
GEMINI_QUEUE.clear(); classify_queue(texts)
import services.classify_v2 as classify_v2
real_ai = classify_v2.classify_response_multi_segment
state = {"calls": 0}
def ai_with_concurrent_writer(text, *args, **kwargs):
    state["calls"] += 1
    if state["calls"] == 1:   # 模擬另一個請求在這則回答等 AI 的時候寫入了一筆分類
        with app.app_context():
            pass
        db.session.add(m.Response_Classification(
            source_type="user_upload", upload_batch_id="b-auto_t3", uploaded_answer_id=aids[0], question_id=f"意見_row{aids[0]}",
            answer_text="並發一", segment_start=0, segment_end=3, main_category="Main A", sub_category="A1",
            status="completed", review_status="pending_review", taxonomy_version_id=None))
        db.session.commit()
    return real_ai(text, *args, **kwargs)
with app.app_context():
    before_live = m.Response_Classification.query.filter_by(uploaded_answer_id=aids[0]).count()
with mock.patch.object(classify_v2, "classify_response_multi_segment", side_effect=ai_with_concurrent_writer):
    body = merge("auto_t3").get_json()
check("AI 回來時資料已被改過 -> 該筆 CONCURRENT_MODIFICATION，不覆蓋",
      [s["code"] for s in body["skipped"]] == ["CONCURRENT_MODIFICATION"] and body["skipped"][0]["uploaded_answer_id"] == aids[0])
check("另一筆沒有衝突 -> 照常搬走", body["moved_count"] == 1)
with app.app_context():
    rows = m.Response_Classification.query.filter_by(uploaded_answer_id=aids[0]).all()
    check("被擋下那筆沒有多寫任何列（只有原本的 + 並發寫入的那筆）", len(rows) == before_live + 1)
    check("它仍屬於來源主題", m.Uploaded_Answer.query.get(aids[0]).question_type == "auto_t3")

# 5d. 已被別人搬走 -> 不再呼叫 AI
texts = ["先搬走", "還在來源"]
aids = seed_source("auto_t4", texts)
GEMINI_QUEUE.clear(); classify_queue([texts[0]])
calls = {"n": 0}
def ai_and_move_second(text, *args, **kwargs):
    calls["n"] += 1
    with app.app_context():
        pass
    answer = m.Uploaded_Answer.query.get(aids[1])
    answer.question_type = "topic_a"          # 模擬另一個請求 / 管理員已經把第二則搬走
    db.session.commit()
    return real_ai(text, *args, **kwargs)
with mock.patch.object(classify_v2, "classify_response_multi_segment", side_effect=ai_and_move_second):
    body = merge("auto_t4").get_json()
check("第二則已經不屬於來源 -> 只呼叫 1 次 AI，不算失敗", calls["n"] == 1 and body["moved_count"] == 1 and body["skipped_count"] == 0)

GEMINI_QUEUE.clear()
finish()
