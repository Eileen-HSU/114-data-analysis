#!/usr/bin/env python
"""
總覽「待決策的 AI 自動主題」（needs_decision.provisional_topics）只算真正還沒決定去向的主題。

規則：主題存在、沒有被併入其他主題、也沒有 published 版本，而且還有待處理回答。
已被併入、或已經是正式主題（待處理回答仍綁在採用 / 合併後被封存的舊版）不算。

執行方式：
    cd backend
    python3 tests/test_overview_provisional_topics.py
"""

import os

from admin_test_support import (
    admin_header, check, create_app, finish, seed_classification, seed_people, seed_topic, seed_upload_batch,
)
import models as m
from extensions import db

os.environ.pop("OPEN_CLASSIFICATION_ENABLED", None)
app = create_app()
client = app.test_client()


def provisional():
    body = client.get("/api/admin/ai/overview", headers=admin_header(1)).get_json()
    return body["needs_decision"]["provisional_topics"], body["needs_decision"]["total"]


def pending(batch, topic, version_id):
    ids = seed_upload_batch(batch, ["一筆待處理的回答"], question_type=topic)
    return seed_classification(ids[0], batch, "一筆待處理的回答", "Main A", "A1", version_id=version_id, status="completed")


with app.app_context():
    seed_people()
    seed_topic("career", categories=[("Main A", "A1", "m", "c")])  # 正式主題（目標）
check("沒有任何待處理資料 -> 0", provisional()[0] == 0)

print("========== 1. 未發布的 AI 主題：要算 ==========")
with app.app_context():
    seed_topic("auto_a", status="draft")
    pending("b-a", "auto_a", m.Taxonomy_Version.query.filter_by(topic_key="auto_a").one().version_id)
count, total = provisional()
check("未發布 + 有待處理回答 -> 算 1", count == 1)
check("needs_decision.total 也跟著算進去", total >= 1)

print("\n========== 2. 已被併入其他主題：不算 ==========")
with app.app_context():
    seed_topic("auto_b", status="draft")
    pending("b-b", "auto_b", m.Taxonomy_Version.query.filter_by(topic_key="auto_b").one().version_id)
check("未併入前：2 個待決策", provisional()[0] == 2)
with app.app_context():
    db.session.get(m.Topic, "auto_b").merged_into = "career"
    db.session.commit()
check("併入 career 後（仍有 1 筆待處理）-> 不再算，只剩 auto_a", provisional()[0] == 1)

print("\n========== 3. 已有 published 版本：不算 ==========")
with app.app_context():
    seed_topic("auto_c", status="archived")
    seed_topic("auto_c", status="published", version_number=2)
    pending("b-c", "auto_c", m.Taxonomy_Version.query.filter_by(topic_key="auto_c", version_number=1).one().version_id)
check("已發布的正式主題，待處理回答綁在已封存的舊版 -> 不算", provisional()[0] == 1)

print("\n========== 4. 找不到主題：不算（沒有主題可以決策）==========")
with app.app_context():
    if db.engine.dialect.name == "sqlite":   # MySQL 有外鍵：刪主題會連帶刪版本，這種狀態不可能出現
        ghost = m.Taxonomy_Version(topic_key="ghost_topic", version_number=1, status="draft", source="manual")
        db.session.add(ghost)
        db.session.commit()
        pending("b-g", "ghost_topic", ghost.version_id)
        check("主題不存在 -> 不算", provisional()[0] == 1)
    else:
        print("（MySQL 略過：外鍵讓「主題不存在」不可能發生）")

print("\n========== 5. 再有一個真的未決定主題：照常累計 ==========")
with app.app_context():
    seed_topic("auto_d", status="draft")
    pending("b-d", "auto_d", m.Taxonomy_Version.query.filter_by(topic_key="auto_d").one().version_id)
check("auto_a + auto_d -> 2", provisional()[0] == 2)

finish()
