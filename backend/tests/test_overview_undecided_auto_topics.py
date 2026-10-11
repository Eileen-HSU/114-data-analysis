#!/usr/bin/env python
"""
總覽「待決策 AI 暫時主題」（needs_decision.undecided_auto_topics）與分類架構頁「AI 暫時主題」篩選同一個定義：
auto_ 開頭、未併入其他主題、沒有 published 版本、不是舊資料主題。不看有沒有回答、草稿或新類別候選。

另外確認：原本的 provisional_topics 與 needs_decision.total 語意不變（新欄位不計入 total）。

執行方式：
    cd backend
    python3 tests/test_overview_undecided_auto_topics.py
"""

import os

from admin_test_support import (
    admin_header, check, create_app, finish, seed_classification, seed_people, seed_topic, seed_upload_batch,
)
import models as m
from extensions import db
from services import taxonomy_service as taxo
from services.admin_overview_service import is_legacy_technical_topic, undecided_auto_topic_keys

os.environ.pop("OPEN_CLASSIFICATION_ENABLED", None)
app = create_app()
client = app.test_client()


def overview():
    return client.get("/api/admin/ai/overview", headers=admin_header(1)).get_json()["needs_decision"]


def hub_filter_keys():
    """分類架構頁「AI 暫時主題」篩選（前端 isUndecidedAuto + 排除舊資料）用同一份主題清單算出來的結果。"""
    topics = taxo.list_topics_with_status()
    return {t["topic_key"] for t in topics
            if not t["merged_into"] and t["is_auto_topic"] and not t["published_version"]
            and not is_legacy_technical_topic(t["topic_key"], t["title"])}


def draft_id(key):
    return m.Taxonomy_Version.query.filter_by(topic_key=key).order_by(m.Taxonomy_Version.version_number).first().version_id


with app.app_context():
    seed_people()
    seed_topic("career", categories=[("Main A", "A1", "m", "c")])
    base = overview()
check("沒有任何 AI 主題 -> 0", base["undecided_auto_topics"] == 0 and base["provisional_topics"] == 0)

print("========== 1. 無回答、僅有草稿、有新類別候選、有暫定回答：都要算 ==========")
with app.app_context():
    # 無任何版本 / 回答
    db.session.add(m.Topic(topic_key="auto_empty", title="Topic auto_empty"))
    db.session.commit()
    seed_topic("auto_draft", status="draft")                       # 只有草稿，沒有回答
    seed_topic("auto_cand", status="draft")                        # 有新類別候選的回答
    ids = seed_upload_batch("b-cand", ["候選回答"], question_type="auto_cand")
    seed_classification(ids[0], "b-cand", "候選回答", "Main A", "A1", version_id=draft_id("auto_cand"), status="new_category")
    seed_topic("auto_prov", status="draft")                        # 有暫定回答
    ids = seed_upload_batch("b-prov", ["暫定回答"], question_type="auto_prov")
    seed_classification(ids[0], "b-prov", "暫定回答", "Main A", "A1", version_id=draft_id("auto_prov"), status="completed")
    d = overview()
check("無回答 / 僅草稿 / 新類別候選 / 暫定回答 共 4 個", d["undecided_auto_topics"] == 4)
check("原本的 provisional_topics 仍只算有暫定回答的 1 個", d["provisional_topics"] == 1)

print("\n========== 2. 已發布、已合併、舊資料、非 auto_ 主題：不算 ==========")
with app.app_context():
    seed_topic("auto_pub", status="published")
    seed_topic("auto_merged", status="draft")
    db.session.get(m.Topic, "auto_merged").merged_into = "career"
    db.session.add(m.Topic(topic_key="auto_legacy", title="unknown_legacy_column"))
    # 系統為舊資料欄位建立的自動主題：標題是「自動歸納：unknown_legacy_column」，key 是雜湊
    db.session.add(m.Topic(topic_key="auto_0123456789ab", title="自動歸納：unknown_legacy_column",
                           auto_label="unknown_legacy_column", auto_scope="global"))
    # 一般的自動主題，標題帶「自動歸納：」前綴：要算
    db.session.add(m.Topic(topic_key="auto_normal", title="自動歸納：意見", auto_label="意見"))
    seed_topic("manual_unpublished", status="draft")               # 不是 auto_ 開頭
    db.session.commit()
    d2 = overview()
check("加入已發布 / 已合併 / 舊資料（2 種寫法）/ 非 auto_ 主題後，只多一個一般自動主題 -> 5", d2["undecided_auto_topics"] == 5)

print("\n========== 3. 與分類架構頁篩選完全一致（用同一份主題清單驗證）==========")
with app.app_context():
    backend_keys = undecided_auto_topic_keys()
    hub_keys = hub_filter_keys()
check("後端集合 == 分類架構頁篩選集合", backend_keys == hub_keys)
check("集合內容正確", backend_keys == {"auto_empty", "auto_draft", "auto_cand", "auto_prov", "auto_normal"})
check("數字 == 集合大小（不硬編碼）", d2["undecided_auto_topics"] == len(hub_keys))

print("\n========== 3b. 舊資料技術性主題只被排除、沒有被刪除 ==========")
with app.app_context():
    check("兩筆舊資料主題仍在資料庫", all(db.session.get(m.Topic, k) is not None for k in ("auto_legacy", "auto_0123456789ab")))
    check("判斷規則：各種寫法都認得，一般標題不誤判",
          is_legacy_technical_topic("x", "自動歸納：unknown_legacy_column") and is_legacy_technical_topic("x", "自動歸納: unknown_legacy_column")
          and not is_legacy_technical_topic("x", "自動歸納：意見")
          and not is_legacy_technical_topic("x", "unknown_legacy_column 的說明"))

print("\n========== 4. 其他統計與 total 不受新欄位影響 ==========")
check("provisional_topics 沒變", d2["provisional_topics"] == d["provisional_topics"] == 1)
check("needs_decision.total 沒有把新欄位加進去", d2["total"] == d["total"])
same = {k: v for k, v in d2.items() if k != "undecided_auto_topics"} == {k: v for k, v in d.items() if k != "undecided_auto_topics"}
check("加入已發布 / 已合併 / 舊資料 / 非 auto_ 主題後，needs_decision 其餘欄位完全沒變", same)

print("\n========== 5. 發布 / 併入後數字跟著變 ==========")
with app.app_context():
    v = m.Taxonomy_Version.query.filter_by(topic_key="auto_draft").one()
    v.status = "published"
    db.session.get(m.Topic, "auto_empty").merged_into = "career"
    db.session.commit()
    d3 = overview()
check("發布 auto_draft、併入 auto_empty 後 -> 3", d3["undecided_auto_topics"] == 3)

finish()
