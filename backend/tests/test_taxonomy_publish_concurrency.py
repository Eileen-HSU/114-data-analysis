#!/usr/bin/env python
"""
P1-10：Taxonomy publish 併發保護。

情境：同一個 Topic 有 v1 published，兩位 Admin 同時各自發布 v2 / v3 草稿。
用檔案型 SQLite + 兩個 thread（各自獨立的 DB session），並在「鎖定並重新驗證
之後、真正寫入之前」讓兩個 transaction 會合，模擬兩邊的應用層檢查都通過。

期望：
    1. 恰好一個 publish 成功，另一個得到 TaxonomyVersionConflictError（HTTP 409
       TAXONOMY_PUBLISH_CONFLICT），不會出現兩個 published
    2. version number 不衝突、舊 published 正確 archived（只有一個 published）
    3. 同一版本重複 publish（重試）-> 422 驗證錯誤，不會重複 archive / 重複 audit
    4. 發布寫入 audit（admin、before/after）

執行方式：
    cd backend
    python3 tests/test_taxonomy_publish_concurrency.py
"""

import os
import tempfile
import threading

from admin_test_support import admin_header, check, create_app, finish, seed_people, seed_topic
import models as m
from extensions import db
from services import taxonomy_service as taxo

tmp_dir = tempfile.mkdtemp()
app = create_app(f"sqlite:///{os.path.join(tmp_dir, 'publish.db')}?timeout=30")
client = app.test_client()

with app.app_context():
    seed_people()
    v1 = seed_topic("race_topic")
    v2 = seed_topic("race_topic", status="draft", version_number=2)
    v3 = seed_topic("race_topic", status="draft", version_number=3)

barrier = threading.Barrier(2)
original_validate = taxo.validate_taxonomy_version_for_publish


def racing_validate(version):
    original_validate(version)
    # 只在「鎖定後重新驗證」那一次會合（呼叫端傳入 _validate 時）
    if threading.current_thread().name.startswith("publisher"):
        try:
            barrier.wait(timeout=10)
        except threading.BrokenBarrierError:
            pass


results = {}


def publisher(version_id, admin_id):
    with app.app_context():
        try:
            taxo.publish_taxonomy_version(
                "race_topic", version_id, admin_id=admin_id, _validate=racing_validate,
            )
            results[version_id] = "published"
        except taxo.TaxonomyVersionConflictError:
            results[version_id] = "conflict"
        except Exception as exc:  # noqa: BLE001
            results[version_id] = f"error:{exc!r}"
        finally:
            db.session.remove()


threads = [
    threading.Thread(target=publisher, args=(v2, 1), name="publisher-a"),
    threading.Thread(target=publisher, args=(v3, 2), name="publisher-b"),
]
for t in threads:
    t.start()
for t in threads:
    t.join(timeout=60)

print("results:", results)
print("========== 1. 同時發布 ==========")
check("恰好一個成功", list(results.values()).count("published") == 1)
check("另一個得到 conflict（不是其他錯誤）", list(results.values()).count("conflict") == 1)
with app.app_context():
    published = m.Taxonomy_Version.query.filter_by(topic_key="race_topic", status="published").all()
    check("DB 裡只有 1 個 published", len(published) == 1)
    check("v1 已 archived", db.session.get(m.Taxonomy_Version, v1).status == "archived")
    loser = v3 if results.get(v2) == "published" else v2
    check("失敗的一方仍是 draft（沒有半套狀態）", db.session.get(m.Taxonomy_Version, loser).status == "draft")
    numbers = [v.version_number for v in m.Taxonomy_Version.query.filter_by(topic_key="race_topic").all()]
    check("version_number 沒有衝突", len(numbers) == len(set(numbers)))
    check("只有成功的一方寫入 publish audit", m.Admin_Audit_Log.query.filter_by(action="taxonomy_publish").count() == 1)
    winner = published[0].version_id


print("\n========== 2. 透過 API：失敗方重試 / 已發布版本重試 ==========")
resp = client.post(f"/api/admin/ai/topics/race_topic/taxonomy/{winner}/publish", headers=admin_header(1))
check("已發布版本重試 -> 422 TAXONOMY_PUBLISH_INVALID", resp.status_code == 422 and resp.get_json()["code"] == "TAXONOMY_PUBLISH_INVALID")
resp = client.post(f"/api/admin/ai/topics/race_topic/taxonomy/{loser}/publish", headers=admin_header(2))
check("失敗方稍後正常重試 -> 200", resp.status_code == 200)
with app.app_context():
    check("仍然只有 1 個 published（換成 loser）", [v.version_id for v in m.Taxonomy_Version.query.filter_by(
        topic_key="race_topic", status="published").all()] == [loser])
    audit = m.Admin_Audit_Log.query.filter_by(action="taxonomy_publish").order_by(m.Admin_Audit_Log.audit_id).all()
    check("publish audit 記錄 admin 與被 archived 的版本",
          len(audit) == 2 and audit[-1].admin_id == 2 and audit[-1].before_state["archived_version_ids"] == [winner])

finish()
