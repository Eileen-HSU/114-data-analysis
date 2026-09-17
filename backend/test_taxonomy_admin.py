#!/usr/bin/env python
"""
測試腳本：驗證 Phase D 的核心目標——
routes/admin/ai_admin.py 新增的 Taxonomy Review/Edit/Publish API
（透過 services/taxonomy_service.py 的 CRUD/clone/publish 邏輯）。

涵蓋（對應需求文件 Phase D 第 14 節，1~17；18/19 另外驗證）：
    1. Topic list 正確顯示 published/draft 狀態
    2. 讀 taxonomy detail
    3. draft category update
    4. draft add category
    5. draft delete category
    6. reorder
    7. published taxonomy 禁止直接 edit
    8. clone published -> draft 成功且原版不變
    9. publish draft -> old published archived / draft published
    10. invalid draft 無法 publish
    11. duplicate sub_category 無法 publish
    12. production classification publish 後讀到新版
    13. citation NULL 可正常保存/發布
    14. methodology NULL 可正常保存/發布
    15. generation API batch limit 生效
    16. version conflict 不留半套資料
    17. Admin auth 正常保護 taxonomy API

執行方式：
    cd backend
    export JWT_SECRET_KEY=test-secret
    python3 test_taxonomy_admin.py
"""

import sys
import os
import types

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only")
sys.path.insert(0, os.path.dirname(__file__))

FAILED = []


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    if status == "FAIL":
        FAILED.append(label)
    print(f"[{status}] {label}")


_fake_genai = types.ModuleType("google.generativeai")
_fake_genai.GenerativeModel = object
_fake_genai.configure = lambda **kwargs: None
_fake_google = types.ModuleType("google")
_fake_google.generativeai = _fake_genai
sys.modules["google"] = _fake_google
sys.modules["google.generativeai"] = _fake_genai


from flask import Flask
from sqlalchemy import event
from sqlalchemy.engine import Engine
from extensions import db
import models as m
from services import taxonomy_service as ts
from services import taxonomy_generation_service as gen
from routes.admin.ai_admin import ai_admin_bp
from routes.auth.admin_guard import build_admin_token


@event.listens_for(Engine, "connect")
def _enable_sqlite_fk(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
app.config["TESTING"] = True
app.register_blueprint(ai_admin_bp)
db.init_app(app)

with app.app_context():
    tables = [
        m.Admin.__table__,
        m.Topic.__table__,
        m.Taxonomy_Version.__table__,
        m.Taxonomy_Category.__table__,
    ]
    db.metadata.create_all(bind=db.engine, tables=tables)
    admin = m.Admin(admin_name="tester", email="admin@example.com", password_hash="x")
    db.session.add(admin)
    db.session.commit()
    admin_id = admin.admin_id

client = app.test_client()
AUTH = {"Authorization": f"Bearer {build_admin_token(admin_id)}"}


def api(method, path, **kwargs):
    return getattr(client, method)(path, **kwargs)


# ═══════════════════════════════════════════════════════════════
# 前置資料：3 個 Topic —— published、draft-only、無 taxonomy
# ═══════════════════════════════════════════════════════════════
with app.app_context():
    db.session.add(m.Topic(topic_key="topic_published", title="已發布主題"))
    v1 = m.Taxonomy_Version(topic_key="topic_published", version_number=1, status="published", source="migrated_legacy")
    db.session.add(v1)
    db.session.flush()
    db.session.add(m.Taxonomy_Category(
        version_id=v1.version_id, main_category="M1", sub_category="A1 結構化", sort_order=1,
        definition="結構化定義", methodology="方法論X", citation="Author (2020)",
    ))
    db.session.add(m.Taxonomy_Category(
        version_id=v1.version_id, main_category="M1", sub_category="A2 legacy",
        sort_order=2, source_raw_text="A2 legacy：舊版原文規則",
    ))
    db.session.commit()
    topic_published_v1_id = v1.version_id

    db.session.add(m.Topic(topic_key="topic_draft_only", title="只有草稿的主題"))
    v_draft = m.Taxonomy_Version(topic_key="topic_draft_only", version_number=1, status="draft", source="manual")
    db.session.add(v_draft)
    db.session.flush()
    db.session.add(m.Taxonomy_Category(
        version_id=v_draft.version_id, main_category="M", sub_category="B1", sort_order=1, definition="d",
    ))
    db.session.commit()
    topic_draft_only_v_id = v_draft.version_id

    db.session.add(m.Topic(topic_key="topic_empty", title="還沒有 taxonomy 的主題"))
    db.session.commit()


print("========== 測試 17：Admin auth 保護 ==========")

resp = api("get", "/api/admin/ai/taxonomy-topics")
check("沒帶 token 時回 401", resp.status_code == 401)

resp = api("get", "/api/admin/ai/taxonomy-topics", headers=AUTH)
check("帶正確 Admin token 時可以正常存取", resp.status_code == 200)


print("\n========== 測試 1：Topic list 狀態 ==========")

resp = api("get", "/api/admin/ai/taxonomy-topics", headers=AUTH)
topics_by_key = {t["topic_key"]: t for t in resp.get_json()["topics"]}
check("topic_published 狀態為 published", topics_by_key["topic_published"]["status"] == "published")
check("topic_draft_only 狀態為 draft", topics_by_key["topic_draft_only"]["status"] == "draft")
check("topic_empty 狀態為 no_taxonomy", topics_by_key["topic_empty"]["status"] == "no_taxonomy")
check(
    "topic_published 有 published_version 資訊",
    topics_by_key["topic_published"]["published_version"]["version_id"] == topic_published_v1_id,
)
check("topic_draft_only 沒有 published_version", topics_by_key["topic_draft_only"]["published_version"] is None)


print("\n========== 測試 2：taxonomy version detail ==========")

resp = api("get", f"/api/admin/ai/topics/topic_published/taxonomy/{topic_published_v1_id}", headers=AUTH)
detail = resp.get_json()["taxonomy_version"]
check("HTTP 200", resp.status_code == 200)
check("回傳 2 筆 categories，依 sort_order", [c["sub_category"] for c in detail["categories"]] == ["A1 結構化", "A2 legacy"])
check("legacy category 有回 source_raw_text 供參考", detail["categories"][1]["source_raw_text"] == "A2 legacy：舊版原文規則")
check("legacy category 沒有被自動拆分成 definition", detail["categories"][1]["definition"] is None)

resp_404 = api("get", "/api/admin/ai/topics/topic_published/taxonomy/999999", headers=AUTH)
check("不存在的 version_id 回 404", resp_404.status_code == 404)


print("\n========== 測試 3/13/14：draft category update ==========")

with app.app_context():
    draft_category_id = ts.get_taxonomy_version("topic_draft_only", topic_draft_only_v_id).categories[0].category_id

resp = api(
    "put", f"/api/admin/ai/topics/topic_draft_only/taxonomy/{topic_draft_only_v_id}/categories/{draft_category_id}",
    headers=AUTH, json={"definition": "更新後的定義", "citation": None, "methodology": None},
)
check("HTTP 200", resp.status_code == 200)
updated = resp.get_json()["category"]
check("definition 已更新", updated["definition"] == "更新後的定義")
check("citation 可以正常設為 NULL", updated["citation"] is None)
check("methodology 可以正常設為 NULL", updated["methodology"] is None)


print("\n========== 測試 4：draft add category ==========")

resp = api(
    "post", f"/api/admin/ai/topics/topic_draft_only/taxonomy/{topic_draft_only_v_id}/categories",
    headers=AUTH, json={"main_category": "M", "sub_category": "B2 新增", "definition": "新類別定義"},
)
check("HTTP 201", resp.status_code == 201)
new_category_id = resp.get_json()["category"]["category_id"]
check("sort_order 自動接在最後（=2）", resp.get_json()["category"]["sort_order"] == 2)

resp_bad = api(
    "post", f"/api/admin/ai/topics/topic_draft_only/taxonomy/{topic_draft_only_v_id}/categories",
    headers=AUTH, json={"main_category": "M", "sub_category": ""},
)
check("sub_category 為空字串時回 400", resp_bad.status_code == 400)


print("\n========== 測試 6：reorder ==========")

with app.app_context():
    version = ts.get_taxonomy_version("topic_draft_only", topic_draft_only_v_id)
    all_ids = [c.category_id for c in version.categories]

reversed_ids = list(reversed(all_ids))
resp = api(
    "post", f"/api/admin/ai/topics/topic_draft_only/taxonomy/{topic_draft_only_v_id}/categories/reorder",
    headers=AUTH, json={"ordered_category_ids": reversed_ids},
)
check("HTTP 200", resp.status_code == 200)
reordered = resp.get_json()["categories"]
check("reorder 後順序反轉", [c["category_id"] for c in reordered] == reversed_ids)
check("sort_order 重新指派為 1, 2", [c["sort_order"] for c in reordered] == [1, 2])

resp_bad_reorder = api(
    "post", f"/api/admin/ai/topics/topic_draft_only/taxonomy/{topic_draft_only_v_id}/categories/reorder",
    headers=AUTH, json={"ordered_category_ids": [all_ids[0]]},
)
check("ordered_category_ids 數量不對時回 400", resp_bad_reorder.status_code == 400)


print("\n========== 測試 5：draft delete category ==========")

resp = api(
    "delete", f"/api/admin/ai/topics/topic_draft_only/taxonomy/{topic_draft_only_v_id}/categories/{new_category_id}",
    headers=AUTH,
)
check("HTTP 200", resp.status_code == 200)
with app.app_context():
    check("category 真的被刪除", m.Taxonomy_Category.query.get(new_category_id) is None)


print("\n========== 測試 7：published taxonomy 禁止直接 edit ==========")

with app.app_context():
    published_category_id = ts.get_taxonomy_version("topic_published", topic_published_v1_id).categories[0].category_id

resp_put = api(
    "put", f"/api/admin/ai/topics/topic_published/taxonomy/{topic_published_v1_id}/categories/{published_category_id}",
    headers=AUTH, json={"definition": "試圖竄改正式資料"},
)
check("PUT published category 回 409", resp_put.status_code == 409)

resp_post = api(
    "post", f"/api/admin/ai/topics/topic_published/taxonomy/{topic_published_v1_id}/categories",
    headers=AUTH, json={"main_category": "M", "sub_category": "偷加的類別", "definition": "d"},
)
check("POST（新增）到 published version 回 409", resp_post.status_code == 409)

resp_del = api(
    "delete", f"/api/admin/ai/topics/topic_published/taxonomy/{topic_published_v1_id}/categories/{published_category_id}",
    headers=AUTH,
)
check("DELETE published category 回 409", resp_del.status_code == 409)

with app.app_context():
    check(
        "published version 的 category 完全沒被改動（definition 仍是原值）",
        m.Taxonomy_Category.query.get(published_category_id).definition == "結構化定義",
    )


print("\n========== 測試 8：clone ==========")

resp = api("post", f"/api/admin/ai/topics/topic_published/taxonomy/{topic_published_v1_id}/clone", headers=AUTH)
check("HTTP 201", resp.status_code == 201)
cloned = resp.get_json()["taxonomy_version"]
check("clone 出來的版本 status 為 draft", cloned["status"] == "draft")
check("clone 出來的版本 version_number 為 2", cloned["version_number"] == 2)
check("clone 的 categories 數量跟原版一致", len(cloned["categories"]) == 2)
cloned_version_id = cloned["version_id"]

with app.app_context():
    original_after_clone = m.Taxonomy_Version.query.get(topic_published_v1_id)
    check("原本 published 版本的 status 完全沒變", original_after_clone.status == "published")
    check("原本 published 版本的 category 數量沒變", len(original_after_clone.categories) == 2)


print("\n========== 測試 11：duplicate sub_category 無法 publish ==========")

resp_dup_add = api(
    "post", f"/api/admin/ai/topics/topic_published/taxonomy/{cloned_version_id}/categories",
    headers=AUTH, json={"main_category": "M2（不同大類別）", "sub_category": "A1 結構化", "definition": "d"},
)
check("可以新增一筆跟既有 sub_category 同名、但 main_category 不同的 category", resp_dup_add.status_code == 201)

resp_publish_dup = api("post", f"/api/admin/ai/topics/topic_published/taxonomy/{cloned_version_id}/publish", headers=AUTH)
check("publish 時偵測到 sub_category 重複，回 422", resp_publish_dup.status_code == 422)

with app.app_context():
    check("publish 失敗，版本 status 仍是 draft，沒有被改動", m.Taxonomy_Version.query.get(cloned_version_id).status == "draft")
    check("publish 失敗，既有 published v1 完全沒被 archive", m.Taxonomy_Version.query.get(topic_published_v1_id).status == "published")

dup_category_id = resp_dup_add.get_json()["category"]["category_id"]
api("delete", f"/api/admin/ai/topics/topic_published/taxonomy/{cloned_version_id}/categories/{dup_category_id}", headers=AUTH)


print("\n========== 測試 10：invalid draft 無法 publish ==========")

with app.app_context():
    db.session.add(m.Topic(topic_key="topic_invalid_draft", title="不完整草稿測試"))
    v_invalid = m.Taxonomy_Version(topic_key="topic_invalid_draft", version_number=1, status="draft", source="manual")
    db.session.add(v_invalid)
    db.session.flush()
    db.session.add(m.Taxonomy_Category(version_id=v_invalid.version_id, main_category="M", sub_category="沒有規則內容", sort_order=1))
    db.session.commit()
    invalid_version_id = v_invalid.version_id

resp = api("post", f"/api/admin/ai/topics/topic_invalid_draft/taxonomy/{invalid_version_id}/publish", headers=AUTH)
check("缺少 definition/source_raw_text 時 publish 回 422", resp.status_code == 422)
with app.app_context():
    check("publish 失敗，版本狀態仍是 draft", m.Taxonomy_Version.query.get(invalid_version_id).status == "draft")


print("\n========== 測試 9/12：publish 成功 ==========")

resp = api("post", f"/api/admin/ai/topics/topic_published/taxonomy/{cloned_version_id}/publish", headers=AUTH)
check("HTTP 200", resp.status_code == 200)
published_result = resp.get_json()["taxonomy_version"]
check("新版本 status 變成 published", published_result["status"] == "published")

with app.app_context():
    old_v1 = m.Taxonomy_Version.query.get(topic_published_v1_id)
    check("舊版本被 archive", old_v1.status == "archived")
    check("同一 topic 只剩一個 published 版本", m.Taxonomy_Version.query.filter_by(topic_key="topic_published", status="published").count() == 1)

    current_for_production = ts.get_published_taxonomy_version("topic_published")
    check("production classification（get_published_taxonomy_version）讀到的是新版", current_for_production.version_id == cloned_version_id)
    check("沒有維護第二份 current taxonomy id 欄位", not hasattr(m.Topic, "current_taxonomy_version_id"))


print("\n========== 測試 15：generation batch limit ==========")

with app.app_context():
    too_many_answers = ["一則回答內容"] * (gen.MAX_ANSWER_COUNT + 1)
    try:
        gen.generate_taxonomy_draft(topic_key="topic_batch_limit_count", answer_texts=too_many_answers, topic_title="批次上限測試")
        check("answer_texts 數量超過上限時 fail-closed", False)
    except gen.TaxonomyGenerationValidationError as e:
        check("answer_texts 數量超過上限時 fail-closed", True)
        check("錯誤訊息有指出實際上限", str(gen.MAX_ANSWER_COUNT) in str(e))

    too_long_single = "字" * (gen.MAX_SINGLE_ANSWER_CHARS + 1)
    try:
        gen.generate_taxonomy_draft(topic_key="topic_batch_limit_single", answer_texts=[too_long_single], topic_title="單筆過長測試")
        check("單筆回答過長時 fail-closed", False)
    except gen.TaxonomyGenerationValidationError:
        check("單筆回答過長時 fail-closed", True)

    check("topic_batch_limit_count 沒有因為超限而被建立", m.Topic.query.get("topic_batch_limit_count") is None)


print("\n========== 測試 16：version conflict fail-closed ==========")

with app.app_context():
    topics_before = m.Topic.query.count()
    versions_before = m.Taxonomy_Version.query.count()
    categories_before = m.Taxonomy_Category.query.count()

    _orig_get_next = ts.get_next_version_number
    ts.get_next_version_number = lambda topic_key: 1

    try:
        ts.clone_taxonomy_version("topic_draft_only", topic_draft_only_v_id)
        check("version_number 撞號時拋出 TaxonomyVersionConflictError", False)
    except ts.TaxonomyVersionConflictError:
        check("version_number 撞號時拋出 TaxonomyVersionConflictError", True)
    finally:
        ts.get_next_version_number = _orig_get_next

    check("撞號失敗後沒有新增 Topic", m.Topic.query.count() == topics_before)
    check("撞號失敗後沒有新增 Taxonomy_Version（不留半套）", m.Taxonomy_Version.query.count() == versions_before)
    check("撞號失敗後沒有新增 Taxonomy_Category（不留孤兒 category）", m.Taxonomy_Category.query.count() == categories_before)


print("\n" + "=" * 50)
if FAILED:
    print(f"共 {len(FAILED)} 項測試失敗：")
    for f in FAILED:
        print("  -", f)
    sys.exit(1)
else:
    print("全部測試通過！")
