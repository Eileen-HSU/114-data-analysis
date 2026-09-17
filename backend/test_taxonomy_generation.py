#!/usr/bin/env python
"""
測試腳本：驗證 Phase C 的核心目標——
services/taxonomy_generation_service.generate_taxonomy_draft()。

涵蓋（對應需求文件 Phase C 第 14 節）：
    1. valid structured Gemini output -> 成功建立 draft taxonomy version
    2. existing published version 完全不被改動
    3. version_number 正確遞增
    4. categories 全部寫入 structured fields
    5. duplicate sub_category fail-closed
    6. missing definition fail-closed
    7. invalid JSON / malformed Gemini output 不寫 DB
    8. Gemini exception 不留下半套 version
    9. methodology 可 NULL
    10. citation 可 NULL
    11. reference taxonomy 不會限制新 category 名稱
    12. generator 不會呼叫 publish_taxonomy_version()
    13. topic 不存在時的建立/錯誤策略符合設計
    14. transaction rollback 正常
    15. production classification 仍只讀 published version
    16.（既有 Phase A/B tests 不被破壞，另外用既有測試檔逐一重跑驗證，
        這裡不重複）

全程 mock google.generativeai，不消耗真實 API quota。

執行方式：
    cd backend
    python3 test_taxonomy_generation.py
"""

import sys
import os
import types
import json

sys.path.insert(0, os.path.dirname(__file__))

FAILED = []


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    if status == "FAIL":
        FAILED.append(label)
    print(f"[{status}] {label}")


# ── 假的 google.generativeai ──
_queue = []


class _FakeResp:
    def __init__(self, text):
        self.text = text


class _FakeModel:
    def __init__(self, system_instruction=None, **kwargs):
        self.system_instruction = system_instruction

    def generate_content(self, prompt, **kwargs):
        item = _queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return _FakeResp(item)


_fake_genai = types.ModuleType("google.generativeai")
_fake_genai.GenerativeModel = _FakeModel
_fake_genai.configure = lambda **kwargs: None
_fake_google = types.ModuleType("google")
_fake_google.generativeai = _fake_genai
sys.modules["google"] = _fake_google
sys.modules["google.generativeai"] = _fake_genai


def q(obj_or_text_or_exc):
    if isinstance(obj_or_text_or_exc, (str, Exception)):
        _queue.append(obj_or_text_or_exc)
    else:
        _queue.append(json.dumps(obj_or_text_or_exc, ensure_ascii=False))


from flask import Flask
from sqlalchemy import event
from sqlalchemy.engine import Engine
from extensions import db
import models as m
from services import taxonomy_service as ts
from services import taxonomy_generation_service as gen


@event.listens_for(Engine, "connect")
def _enable_sqlite_fk(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
app.config["TESTING"] = True
db.init_app(app)

with app.app_context():
    tables = [
        m.Admin.__table__,
        m.Topic.__table__,
        m.Taxonomy_Version.__table__,
        m.Taxonomy_Category.__table__,
    ]
    db.metadata.create_all(bind=db.engine, tables=tables)


VALID_CATEGORIES_PAYLOAD = {
    "categories": [
        {
            "main_category": "工作與生活平衡",
            "sub_category": "B1 加班文化",
            "definition": "回覆主要在討論長期加班或下班後仍需處理工作訊息",
            "include_rules": "提到加班、下班後回訊息、假日工作",
            "exclude_rules": "純粹討論薪資的內容不算",
            "boundary_rules": "若同時提到主管施壓則優先歸入主管相關類別",
            "methodology": "工作負荷與界線分析",
            "citation": None,
            "sort_order": 1,
        },
        {
            "main_category": "工作與生活平衡",
            "sub_category": "B2 遠距彈性",
            "definition": "回覆主要在討論希望增加遠距或彈性工時安排",
            "include_rules": "提到在家工作、彈性上下班",
            "exclude_rules": None,
            "boundary_rules": None,
            "methodology": None,
            "citation": None,
            "sort_order": 2,
        },
    ]
}


# ═══════════════════════════════════════════════════════════════
# 測試 1：valid structured Gemini output -> 成功建立 draft version
# ═══════════════════════════════════════════════════════════════
print("========== 測試 1：valid Gemini output ==========")

with app.app_context():
    _queue.clear()
    q(VALID_CATEGORIES_PAYLOAD)
    version = gen.generate_taxonomy_draft(
        topic_key="new_topic_1",
        answer_texts=["希望可以減少下班後的訊息轟炸", "想要有更多在家工作的彈性"],
        topic_title="新主題：工作彈性",
        question_text="關於工作彈性，你有什麼建議？",
    )
    check("回傳的版本 status 為 draft", version.status == "draft")
    check("回傳的版本 source 為 ai_generated", version.source == "ai_generated")
    check("version_number 從 1 開始", version.version_number == 1)
    check("Topic 被安全建立", m.Topic.query.get("new_topic_1") is not None)
    check("Topic.title 正確帶入", m.Topic.query.get("new_topic_1").title == "新主題：工作彈性")

    categories = m.Taxonomy_Category.query.filter_by(version_id=version.version_id).order_by(
        m.Taxonomy_Category.sort_order
    ).all()
    check("寫入 2 筆 Taxonomy_Category", len(categories) == 2)


# ═══════════════════════════════════════════════════════════════
# 測試 4/9/10：categories 完整寫入 structured fields，methodology/citation 可 NULL
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 4/9/10：structured fields 完整寫入，methodology/citation 可 NULL ==========")

with app.app_context():
    categories = m.Taxonomy_Category.query.filter_by(version_id=version.version_id).order_by(
        m.Taxonomy_Category.sort_order
    ).all()
    c1, c2 = categories[0], categories[1]

    check("c1.definition 正確寫入", c1.definition == "回覆主要在討論長期加班或下班後仍需處理工作訊息")
    check("c1.include_rules 正確寫入", c1.include_rules == "提到加班、下班後回訊息、假日工作")
    check("c1.exclude_rules 正確寫入", c1.exclude_rules == "純粹討論薪資的內容不算")
    check("c1.boundary_rules 正確寫入", c1.boundary_rules == "若同時提到主管施壓則優先歸入主管相關類別")
    check("c1.methodology 正確寫入（非 NULL 情況）", c1.methodology == "工作負荷與界線分析")
    check("c1.citation 為 NULL（Gemini 給 null，不硬填）", c1.citation is None)
    check("c1.source_raw_text 為 NULL（AI-generated 不使用 legacy raw text）", c1.source_raw_text is None)

    check("c2.exclude_rules 為 NULL", c2.exclude_rules is None)
    check("c2.boundary_rules 為 NULL", c2.boundary_rules is None)
    check("c2.methodology 為 NULL", c2.methodology is None)
    check("c2.citation 為 NULL", c2.citation is None)
    check("sort_order 依序為 1, 2", [c.sort_order for c in categories] == [1, 2])


# ═══════════════════════════════════════════════════════════════
# 測試 2/3：existing published version 不被改動，version_number 正確遞增
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 2/3：published 版本不受影響，version_number 遞增 ==========")

with app.app_context():
    db.session.add(m.Topic(topic_key="topic_with_published", title="已有正式版的主題"))
    published_version = m.Taxonomy_Version(
        topic_key="topic_with_published", version_number=1, status="published", source="manual",
    )
    db.session.add(published_version)
    db.session.flush()
    db.session.add(m.Taxonomy_Category(
        version_id=published_version.version_id, main_category="M", sub_category="既有正式子類別",
        definition="既有定義", sort_order=1,
    ))
    db.session.commit()
    published_version_id = published_version.version_id
    published_updated_at_snapshot = (published_version.status, published_version.version_number)

    _queue.clear()
    q(VALID_CATEGORIES_PAYLOAD)
    new_version = gen.generate_taxonomy_draft(
        topic_key="topic_with_published",
        answer_texts=["新的一批回答內容"],
    )

    check("新版本 version_number 正確遞增為 2（現有 published v1 之後）", new_version.version_number == 2)
    check("新版本 status 為 draft", new_version.status == "draft")

    published_after = m.Taxonomy_Version.query.get(published_version_id)
    check("既有 published 版本的 status 完全沒被改動", published_after.status == "published")
    check("既有 published 版本的 version_number 沒被改動", published_after.version_number == 1)
    published_categories_after = m.Taxonomy_Category.query.filter_by(version_id=published_version_id).all()
    check("既有 published 版本的 category 沒有被新增/刪除", len(published_categories_after) == 1)
    check("既有 published 版本的 category 內容沒被改動", published_categories_after[0].sub_category == "既有正式子類別")

    # 測試 15：production classification 仍只讀 published version
    current_published = ts.get_published_taxonomy_version("topic_with_published")
    check("get_published_taxonomy_version 讀到的仍是舊版本，不是新 draft", current_published.version_id == published_version_id)


# ═══════════════════════════════════════════════════════════════
# 測試 5：duplicate sub_category fail-closed
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 5：duplicate sub_category fail-closed ==========")

with app.app_context():
    topics_before = m.Topic.query.count()
    versions_before = m.Taxonomy_Version.query.count()
    categories_before = m.Taxonomy_Category.query.count()

    _queue.clear()
    q({"categories": [
        {"main_category": "M", "sub_category": "重複代碼", "definition": "d1"},
        {"main_category": "M", "sub_category": "重複代碼", "definition": "d2"},
    ]})
    try:
        gen.generate_taxonomy_draft(topic_key="topic_dup", answer_texts=["a"], topic_title="重複測試")
        check("duplicate sub_category 拋出 TaxonomyGenerationValidationError", False)
    except gen.TaxonomyGenerationValidationError:
        check("duplicate sub_category 拋出 TaxonomyGenerationValidationError", True)

    check("失敗時沒有新增任何 Topic", m.Topic.query.count() == topics_before)
    check("失敗時沒有新增任何 Taxonomy_Version", m.Taxonomy_Version.query.count() == versions_before)
    check("失敗時沒有新增任何 Taxonomy_Category（沒有孤兒 category）", m.Taxonomy_Category.query.count() == categories_before)


# ═══════════════════════════════════════════════════════════════
# 測試 6：missing definition fail-closed
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 6：missing definition fail-closed ==========")

with app.app_context():
    versions_before = m.Taxonomy_Version.query.count()

    _queue.clear()
    q({"categories": [{"main_category": "M", "sub_category": "沒有定義的類別"}]})
    try:
        gen.generate_taxonomy_draft(topic_key="topic_missing_def", answer_texts=["a"], topic_title="缺定義測試")
        check("缺少 definition 時拋出 TaxonomyGenerationValidationError", False)
    except gen.TaxonomyGenerationValidationError:
        check("缺少 definition 時拋出 TaxonomyGenerationValidationError", True)

    check("失敗時沒有新增任何 Taxonomy_Version", m.Taxonomy_Version.query.count() == versions_before)


# ═══════════════════════════════════════════════════════════════
# 測試 7：invalid JSON / malformed Gemini output 不寫 DB
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 7：invalid JSON / malformed output 不寫 DB ==========")

with app.app_context():
    topics_before = m.Topic.query.count()
    versions_before = m.Taxonomy_Version.query.count()

    _queue.clear()
    q("這不是合法 JSON，只是一段自然語言回應")
    try:
        gen.generate_taxonomy_draft(topic_key="topic_invalid_json", answer_texts=["a"], topic_title="無效輸出測試")
        check("無效 JSON 時拋出例外", False)
    except (gen.TaxonomyGenerationError, gen.TaxonomyGenerationValidationError):
        check("無效 JSON 時拋出例外", True)
    check("無效 JSON 時沒有建立任何 Topic", m.Topic.query.count() == topics_before)
    check("無效 JSON 時沒有建立任何 Taxonomy_Version", m.Taxonomy_Version.query.count() == versions_before)

    # 合法 JSON，但缺少 categories 欄位
    _queue.clear()
    q({"foo": "bar"})
    try:
        gen.generate_taxonomy_draft(topic_key="topic_missing_categories_key", answer_texts=["a"], topic_title="缺 categories key")
        check("缺少 categories 欄位時拋出 TaxonomyGenerationValidationError", False)
    except gen.TaxonomyGenerationValidationError:
        check("缺少 categories 欄位時拋出 TaxonomyGenerationValidationError", True)

    # categories 是空陣列
    _queue.clear()
    q({"categories": []})
    try:
        gen.generate_taxonomy_draft(topic_key="topic_empty_categories", answer_texts=["a"], topic_title="空 categories")
        check("categories 為空陣列時拋出 TaxonomyGenerationValidationError（不得出現完全空 taxonomy）", False)
    except gen.TaxonomyGenerationValidationError:
        check("categories 為空陣列時拋出 TaxonomyGenerationValidationError（不得出現完全空 taxonomy）", True)


# ═══════════════════════════════════════════════════════════════
# 測試 8/14：Gemini exception 不留下半套 version（transaction rollback）
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 8/14：Gemini exception / transaction rollback ==========")

with app.app_context():
    topics_before = m.Topic.query.count()
    versions_before = m.Taxonomy_Version.query.count()

    _queue.clear()
    q(RuntimeError("模擬 Gemini API 掛掉"))
    try:
        gen.generate_taxonomy_draft(topic_key="topic_gemini_crash", answer_texts=["a"], topic_title="Gemini 掛掉測試")
        check("Gemini 呼叫拋例外時，generate_taxonomy_draft 也要往上拋", False)
    except gen.TaxonomyGenerationError:
        check("Gemini 呼叫拋例外時，generate_taxonomy_draft 也要往上拋", True)

    check("Gemini 例外時沒有建立任何 Topic（沒有孤兒 Topic）", m.Topic.query.count() == topics_before)
    check("Gemini 例外時沒有建立任何 Taxonomy_Version（不留半套）", m.Taxonomy_Version.query.count() == versions_before)


# ═══════════════════════════════════════════════════════════════
# 測試 11：reference taxonomy 不會限制新 category 名稱
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 11：reference taxonomy 不限制新 category 名稱 ==========")

with app.app_context():
    reference_examples, reference_citations = gen.load_reference_material(["topic_with_published"])
    check("reference_examples 抽到既有 published 版本的範例", len(reference_examples) >= 1)
    check("reference_examples 只抽少量（<= max_examples_per_topic），不是整份 taxonomy", len(reference_examples) <= 2)

    _queue.clear()
    # Gemini 刻意回傳完全不在 reference 裡出現過的全新類別名稱
    q({"categories": [{
        "main_category": "全新大類別，跟 reference 完全無關",
        "sub_category": "Z9 完全原創子類別",
        "definition": "這批資料獨有的內容",
    }]})
    result_version = gen.generate_taxonomy_draft(
        topic_key="topic_with_reference",
        answer_texts=["這是一段跟 reference 主題完全不同的回答"],
        topic_title="reference 不設限測試",
        reference_examples=reference_examples,
        reference_citations=reference_citations,
    )
    result_categories = m.Taxonomy_Category.query.filter_by(version_id=result_version.version_id).all()
    check(
        "完全原創、不在 reference 裡的類別名稱可以正常通過驗證並寫入",
        len(result_categories) == 1 and result_categories[0].sub_category == "Z9 完全原創子類別",
    )


# ═══════════════════════════════════════════════════════════════
# 測試 4（延伸）：citation 白名單機制 —— 不在白名單內一律丟棄
# ═══════════════════════════════════════════════════════════════
print("\n========== citation 白名單：只有在 reference_citations 內才保留 ==========")

with app.app_context():
    _queue.clear()
    q({"categories": [
        {
            "main_category": "M", "sub_category": "有合法引用",
            "definition": "d", "citation": "Park et al. (2020)",
        },
        {
            "main_category": "M", "sub_category": "編造引用",
            "definition": "d", "citation": "Fake Author (9999). Journal of Nonexistent Things.",
        },
    ]})
    version_citation_test = gen.generate_taxonomy_draft(
        topic_key="topic_citation_whitelist",
        answer_texts=["a"],
        topic_title="citation 白名單測試",
        reference_citations=["Park et al. (2020)"],
    )
    cats = {c.sub_category: c for c in m.Taxonomy_Category.query.filter_by(version_id=version_citation_test.version_id).all()}
    check("在白名單內的 citation 被保留", cats["有合法引用"].citation == "Park et al. (2020)")
    check("不在白名單內的 citation 被強制丟棄成 NULL（防止 hallucination）", cats["編造引用"].citation is None)


# ═══════════════════════════════════════════════════════════════
# 測試 12：generator 不會呼叫 publish_taxonomy_version()
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 12：generator 不會呼叫 publish_taxonomy_version() ==========")

with app.app_context():
    _publish_call_count = {"n": 0}
    _orig_publish = ts.publish_taxonomy_version
    ts.publish_taxonomy_version = lambda *a, **kw: _publish_call_count.__setitem__("n", _publish_call_count["n"] + 1)

    _queue.clear()
    q(VALID_CATEGORIES_PAYLOAD)
    gen.generate_taxonomy_draft(topic_key="topic_no_publish_check", answer_texts=["a"], topic_title="不應觸發 publish")

    ts.publish_taxonomy_version = _orig_publish
    check("generate_taxonomy_draft 完全沒有呼叫 publish_taxonomy_version()", _publish_call_count["n"] == 0)


# ═══════════════════════════════════════════════════════════════
# 測試 13：topic 不存在時的建立/錯誤策略
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 13：topic 不存在時的建立/錯誤策略 ==========")

with app.app_context():
    # 13a：topic_key 不存在、且沒有提供 topic_title -> 明確拋錯，不猜測標題
    _queue.clear()
    q(VALID_CATEGORIES_PAYLOAD)
    try:
        gen.generate_taxonomy_draft(topic_key="topic_no_title_provided", answer_texts=["a"])
        check("topic 不存在且未提供 topic_title 時拋出 ValueError", False)
    except ValueError:
        check("topic 不存在且未提供 topic_title 時拋出 ValueError", True)
    check("失敗時沒有建立 Topic", m.Topic.query.get("topic_no_title_provided") is None)

    # 13b：topic_key 已存在時，即使又傳了 topic_title 也不覆寫既有值
    db.session.add(m.Topic(topic_key="topic_existing_title", title="原始標題，不應被覆蓋"))
    db.session.commit()
    _queue.clear()
    q(VALID_CATEGORIES_PAYLOAD)
    gen.generate_taxonomy_draft(
        topic_key="topic_existing_title", answer_texts=["a"], topic_title="想要覆蓋的新標題",
    )
    check("Topic 已存在時，title 不會被生成請求覆蓋", m.Topic.query.get("topic_existing_title").title == "原始標題，不應被覆蓋")


print("\n" + "=" * 50)
if FAILED:
    print(f"共 {len(FAILED)} 項測試失敗：")
    for f in FAILED:
        print("  -", f)
    sys.exit(1)
else:
    print("全部測試通過！")
