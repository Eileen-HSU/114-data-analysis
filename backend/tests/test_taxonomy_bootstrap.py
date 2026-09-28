#!/usr/bin/env python
"""
P0-5：legacy taxonomy bootstrap（services/taxonomy_bootstrap_service.py）。

涵蓋：
    1. empty DB bootstrap：建立兩個 legacy Topic 的 v1 published，內容跟
       migrate_taxonomy_from_legacy 解析結果一致（共用同一套 seed）
    2. repeated startup idempotency：再跑一次 skipped_existing，不重複建立版本
    3. existing taxonomy preservation：只要 DB 已有任何版本（即使是別的 Topic、
       即使只是 draft），完全不動
    4. concurrent initialization：兩個 worker（兩個 thread、檔案型 SQLite、
       各自的 DB session）同時通過「空表」檢查，只會有一個成功寫入，另一個
       rollback 並回報 concurrent_bootstrap / skipped_existing；最後只有一份資料
    5. bootstrap 後 production 分類入口（resolve_published_taxonomy_prompt）
       可以正常取得 published taxonomy；bootstrap 前維持 fail-closed
    6. published 唯一索引：DB 層拒絕同一 Topic 兩個 published

執行方式：
    cd backend
    python3 tests/test_taxonomy_bootstrap.py
"""

import os
import tempfile
import threading

from admin_test_support import check, create_app, finish
import models as m
from extensions import db
from services import taxonomy_bootstrap_service as boot
from services.subcategory_methodology import QUESTION_CAREER, QUESTION_LEADERSHIP, SUBCATEGORY_METHODOLOGY


print("========== 1. empty DB bootstrap ==========")
app = create_app()
with app.app_context():
    from services.classify_v2 import resolve_published_taxonomy_prompt
    from services.taxonomy_service import PublishedTaxonomyNotFoundError
    try:
        resolve_published_taxonomy_prompt(QUESTION_LEADERSHIP)
        check("bootstrap 前 fail-closed（沒有 published taxonomy）", False)
    except PublishedTaxonomyNotFoundError:
        check("bootstrap 前 fail-closed（沒有 published taxonomy）", True)

    result = boot.bootstrap_legacy_taxonomy()
    check("status=created", result["status"] == "created")
    check("建立兩個 legacy Topic", sorted(result["created_topics"]) == sorted([QUESTION_LEADERSHIP, QUESTION_CAREER]))
    for topic_key in (QUESTION_LEADERSHIP, QUESTION_CAREER):
        versions = m.Taxonomy_Version.query.filter_by(topic_key=topic_key).all()
        check(f"{topic_key}：恰好 1 個 v1 published（migrated_legacy）",
              len(versions) == 1 and versions[0].version_number == 1 and versions[0].status == "published"
              and versions[0].source == "migrated_legacy")
        subs = {c.sub_category for c in versions[0].categories}
        check(f"{topic_key}：子類別與 legacy 表完全一致", subs == set(SUBCATEGORY_METHODOLOGY[topic_key]))
    prompt, lookup, version = resolve_published_taxonomy_prompt(QUESTION_LEADERSHIP)
    check("bootstrap 後 production 入口可取得 published taxonomy", bool(prompt) and version.status == "published")
    check("bootstrap 寫入 audit", m.Admin_Audit_Log.query.filter_by(action="taxonomy_bootstrap").count() == 1)


print("\n========== 2. repeated startup idempotency ==========")
with app.app_context():
    counts_before = (m.Topic.query.count(), m.Taxonomy_Version.query.count(), m.Taxonomy_Category.query.count())
    for _ in range(3):
        result = boot.bootstrap_legacy_taxonomy()
        check("再次啟動 -> skipped_existing", result["status"] == "skipped_existing")
    counts_after = (m.Topic.query.count(), m.Taxonomy_Version.query.count(), m.Taxonomy_Category.query.count())
    check("Topic / Version / Category 數量完全不變", counts_before == counts_after)
    check("audit 沒有重複", m.Admin_Audit_Log.query.filter_by(action="taxonomy_bootstrap").count() == 1)


print("\n========== 3. existing taxonomy preservation ==========")
app2 = create_app()
with app2.app_context():
    db.session.add(m.Topic(topic_key="custom_only", title="既有自訂 Topic"))
    db.session.add(m.Taxonomy_Version(topic_key="custom_only", version_number=1, status="draft", source="manual"))
    db.session.commit()
    result = boot.bootstrap_legacy_taxonomy()
    check("DB 已有任何版本（即使只有別的 Topic 的 draft）-> skipped_existing", result["status"] == "skipped_existing")
    check("沒有建立 legacy Topic", m.Topic.query.get(QUESTION_LEADERSHIP) is None)
    check("既有 draft 完全不動", m.Taxonomy_Version.query.filter_by(topic_key="custom_only").one().status == "draft")


print("\n========== 4. concurrent initialization ==========")
tmp_dir = tempfile.mkdtemp()
db_path = os.path.join(tmp_dir, "bootstrap.db")
app3 = create_app(f"sqlite:///{db_path}?timeout=30")

barrier = threading.Barrier(2)
original_is_empty = boot.taxonomy_is_empty
calls = {"n": 0}
lock = threading.Lock()


def racing_is_empty():
    empty = original_is_empty()
    with lock:
        calls["n"] += 1
        n = calls["n"]
    # 前兩次檢查（兩個 worker 的第一次檢查）都在「空表」狀態下會合，
    # 模擬兩個 worker 同時通過檢查；之後的檢查照實回報。
    if n <= 2:
        try:
            barrier.wait(timeout=10)
        except threading.BrokenBarrierError:
            pass
    return empty


boot.taxonomy_is_empty = racing_is_empty
results = []
errors = []


def worker():
    with app3.app_context():
        try:
            results.append(boot.bootstrap_legacy_taxonomy()["status"])
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))
        finally:
            db.session.remove()


threads = [threading.Thread(target=worker) for _ in range(2)]
for t in threads:
    t.start()
for t in threads:
    t.join(timeout=60)
boot.taxonomy_is_empty = original_is_empty

check("兩個 worker 都沒有丟出未處理例外", errors == [])
check("恰好一個 worker 建立資料", results.count("created") == 1)
check("另一個 worker 安全放棄（concurrent_bootstrap / skipped_existing）",
      len(results) == 2 and any(r in ("concurrent_bootstrap", "skipped_existing") for r in results))
with app3.app_context():
    for topic_key in (QUESTION_LEADERSHIP, QUESTION_CAREER):
        check(f"{topic_key}：最後只有 1 個版本", m.Taxonomy_Version.query.filter_by(topic_key=topic_key).count() == 1)


print("\n========== 5. published 唯一索引 ==========")
with app.app_context():
    from sqlalchemy.exc import IntegrityError
    db.session.add(m.Taxonomy_Version(topic_key=QUESTION_LEADERSHIP, version_number=2, status="published", source="manual"))
    try:
        db.session.commit()
        check("同一 Topic 第二個 published 被 DB 拒絕", False)
    except IntegrityError:
        db.session.rollback()
        check("同一 Topic 第二個 published 被 DB 拒絕", True)
    check("索引建立結果冪等", boot.ensure_published_topic_unique_index() == "created")

finish()
