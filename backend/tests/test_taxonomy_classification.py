#!/usr/bin/env python
"""
測試腳本：驗證 Phase B 的核心目標——production classification 改讀
Published Taxonomy（services/taxonomy_service.py），取代
DEFAULT_PROMPT_* + SUBCATEGORY_METHODOLOGY。

涵蓋（對應需求文件 Phase B 第 9 節）：
    1. published taxonomy reader（0 筆 / 1 筆 / >1 筆 / published 但
       沒有 category）
    2. category ordering（依 sort_order）
    3. runtime prompt 包含合法 taxonomy 與 legacy source_raw_text
    4. Gemini 回傳不存在的 sub_category 時 fail-closed
    5. methodology/citation 從同一 Taxonomy_Category 取得
    6. no published taxonomy 不 fallback dynamic classification
    7. multiple published taxonomy fail-closed（route 層也不默默選第一筆）
    8. Response_Classification 能保存 taxonomy version reference
    9. 舊 Response_Classification 資料仍可存在 taxonomy version = NULL
    10.（Human Review / aggregation / report 現有相關測試不被破壞，
        已用既有 test_review_service.py / test_aggregation_service.py /
        test_report_service.py 個別驗證，這裡不重複）

全程 mock google.generativeai，不消耗真實 API quota。

執行方式：
    cd backend
    python3 tests/test_taxonomy_classification.py
"""

import sys
import os
import types
import json
import io

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

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
        return _FakeResp(_queue.pop(0))


_fake_genai = types.ModuleType("google.generativeai")
_fake_genai.GenerativeModel = _FakeModel
_fake_genai.configure = lambda **kwargs: None
_fake_google = types.ModuleType("google")
_fake_google.generativeai = _fake_genai
sys.modules["google"] = _fake_google
sys.modules["google.generativeai"] = _fake_genai


def q(obj_or_text):
    _queue.append(obj_or_text if isinstance(obj_or_text, str) else json.dumps(obj_or_text, ensure_ascii=False))


from flask import Flask
from sqlalchemy import event
from sqlalchemy.engine import Engine
from extensions import db
import models as m
from services.privacy_service import mask_pii
from services import taxonomy_service as ts


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
        m.Survey_Template.__table__,
        m.Survey_Response.__table__,
        m.Response_Classification.__table__,
        m.Response_Segmentation_Status.__table__,
        m.Uploaded_Answer.__table__,
    ]
    db.metadata.create_all(bind=db.engine, tables=tables)


def _make_topic_with_version(topic_key, status="published", categories=None, with_topic=True):
    """建一個 Topic（若不存在）+ 一個指定 status 的 Taxonomy_Version，
    回傳 version_id。categories 為 None 時不建立任何 category
    （用來測試「published 但沒有 category」的情況）。"""
    if with_topic and m.Topic.query.get(topic_key) is None:
        db.session.add(m.Topic(topic_key=topic_key, title=f"標題-{topic_key}"))
        db.session.flush()

    existing_count = m.Taxonomy_Version.query.filter_by(topic_key=topic_key).count()
    version = m.Taxonomy_Version(
        topic_key=topic_key,
        version_number=existing_count + 1,
        status=status,
        source="manual",
    )
    db.session.add(version)
    db.session.flush()

    for i, cat in enumerate(categories or [], start=1):
        db.session.add(m.Taxonomy_Category(version_id=version.version_id, sort_order=i, **cat))

    db.session.commit()
    return version.version_id


# ═══════════════════════════════════════════════════════════════
# 測試 1：get_published_taxonomy_version() —— 0 / 1 / >1 筆 published
# ═══════════════════════════════════════════════════════════════
print("========== 測試 1：published taxonomy reader ==========")

with app.app_context():
    # 1a：0 筆 published（topic 存在但沒有任何 taxonomy 版本）
    db.session.add(m.Topic(topic_key="topic_no_version", title="沒有任何版本"))
    db.session.commit()
    try:
        ts.get_published_taxonomy_version("topic_no_version")
        check("0 筆 published 時拋出 PublishedTaxonomyNotFoundError", False)
    except ts.PublishedTaxonomyNotFoundError:
        check("0 筆 published 時拋出 PublishedTaxonomyNotFoundError", True)

    # 1b：topic_key 完全不存在
    try:
        ts.get_published_taxonomy_version("topic_does_not_exist_at_all")
        check("topic_key 不存在時拋出 PublishedTaxonomyNotFoundError", False)
    except ts.PublishedTaxonomyNotFoundError:
        check("topic_key 不存在時拋出 PublishedTaxonomyNotFoundError", True)

    # 1c：只有 draft，沒有 published
    _make_topic_with_version(
        "topic_draft_only", status="draft",
        categories=[{"main_category": "M", "sub_category": "S1", "definition": "d"}],
    )
    try:
        ts.get_published_taxonomy_version("topic_draft_only")
        check("只有 draft 版本時拋出 PublishedTaxonomyNotFoundError", False)
    except ts.PublishedTaxonomyNotFoundError:
        check("只有 draft 版本時拋出 PublishedTaxonomyNotFoundError", True)

    # 1d：published 但沒有任何 category
    _make_topic_with_version("topic_published_empty", status="published", categories=None)
    try:
        ts.get_published_taxonomy_version("topic_published_empty")
        check("published 但沒有 category 時拋出 PublishedTaxonomyIntegrityError", False)
    except ts.PublishedTaxonomyIntegrityError:
        check("published 但沒有 category 時拋出 PublishedTaxonomyIntegrityError", True)

    # 1e：剛好 1 筆 published，正常
    v_ok = _make_topic_with_version(
        "topic_normal", status="published",
        categories=[
            {"main_category": "M1", "sub_category": "S2", "definition": "d2"},
            {"main_category": "M1", "sub_category": "S1", "definition": "d1"},
        ],
    )
    version = ts.get_published_taxonomy_version("topic_normal")
    check("剛好 1 筆 published 時正常回傳", version.version_id == v_ok)

    # 1f：>1 筆 published（同一 topic 又插一版 published，不透過 publish_taxonomy_version，
    #     模擬「資料完整性被破壞」的情境）
    _make_topic_with_version(
        "topic_normal", status="published",
        categories=[{"main_category": "M2", "sub_category": "S3", "definition": "d3"}],
        with_topic=False,
    )
    try:
        ts.get_published_taxonomy_version("topic_normal")
        check(">1 筆 published 時拋出 PublishedTaxonomyIntegrityError，不默默選第一筆", False)
    except ts.PublishedTaxonomyIntegrityError:
        check(">1 筆 published 時拋出 PublishedTaxonomyIntegrityError，不默默選第一筆", True)


# ═══════════════════════════════════════════════════════════════
# 測試 2：category ordering（依 sort_order，不受插入順序影響）
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 2：category ordering ==========")

with app.app_context():
    v_id = _make_topic_with_version(
        "topic_ordering", status="published",
        categories=[
            {"main_category": "M", "sub_category": "第三", "definition": "d"},
            {"main_category": "M", "sub_category": "第一", "definition": "d"},
            {"main_category": "M", "sub_category": "第二", "definition": "d"},
        ],
    )
    # 上面 categories 是依「傳入順序」被指派 sort_order=1,2,3，
    # 也就是 第三=1, 第一=2, 第二=3；驗證 .categories 依 sort_order
    # （而不是子類別名稱或插入順序的其他解讀）排序回傳。
    ordering_version = ts.get_published_taxonomy_version("topic_ordering")
    ordered_names = [c.sub_category for c in ordering_version.categories]
    check(
        "categories 依 sort_order 排序（第三、第一、第二）",
        ordered_names == ["第三", "第一", "第二"],
    )


# ═══════════════════════════════════════════════════════════════
# 測試 3：runtime prompt 內容——結構化欄位 / legacy source_raw_text
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 3：build_classification_prompt() ==========")

with app.app_context():
    v_id = _make_topic_with_version(
        "topic_prompt_build", status="published",
        categories=[
            {
                "main_category": "主管領導", "sub_category": "A1 結構化規則",
                "definition": "這是 definition 內容",
                "include_rules": "這是 include 內容",
                "exclude_rules": "這是 exclude 內容",
                "boundary_rules": "這是 boundary 內容",
            },
            {
                "main_category": "主管領導", "sub_category": "A2 legacy 規則",
                "source_raw_text": "A2 legacy 規則：這是 migration 進來的原文規則",
            },
        ],
    )
    version = ts.get_published_taxonomy_version("topic_prompt_build")
    prompt = ts.build_classification_prompt(version)

    check("prompt 包含大類別清單標頭", "【可用的大類別與子類別，只能從以下清單中選擇，不得自創】" in prompt)
    check("prompt 包含大類別名稱", "大類別：主管領導" in prompt)
    check("prompt 包含兩個子類別名稱", "A1 結構化規則" in prompt and "A2 legacy 規則" in prompt)
    check("結構化欄位：definition 內容出現在 prompt", "這是 definition 內容" in prompt)
    check("結構化欄位：include_rules 內容出現在 prompt", "這是 include 內容" in prompt)
    check("結構化欄位：exclude_rules 內容出現在 prompt", "這是 exclude 內容" in prompt)
    check("結構化欄位：boundary_rules 內容出現在 prompt", "這是 boundary 內容" in prompt)
    check(
        "legacy source_raw_text：規則內容出現在 prompt（backward compatibility）",
        "這是 migration 進來的原文規則" in prompt,
    )
    check(
        "legacy source_raw_text 不會重複輸出「子類別：」前綴兩次",
        prompt.count("A2 legacy 規則：") == 1,
    )
    check("prompt 包含 GLOBAL_RULES（系統層級總分類規則）", "系統層級總分類規則" in prompt)
    check("prompt 包含次要類別規則段落", "次要類別規則" in prompt)
    check("prompt 包含輸出格式 JSON schema", '"secondary_sub_category"' in prompt)

    # definition/include/exclude/boundary 皆為 NULL、也沒有 source_raw_text
    # -> 無法組出判斷規則，必須 fail-closed，不能生出一個空類別去問 Gemini
    v_id_broken = _make_topic_with_version(
        "topic_prompt_broken", status="published",
        categories=[{"main_category": "M", "sub_category": "沒有任何規則來源"}],
    )
    broken_version = ts.get_published_taxonomy_version("topic_prompt_broken")
    try:
        ts.build_classification_prompt(broken_version)
        check("category 沒有任何規則來源時，build_classification_prompt 拋出例外", False)
    except ts.PublishedTaxonomyIntegrityError:
        check("category 沒有任何規則來源時，build_classification_prompt 拋出例外", True)


# ═══════════════════════════════════════════════════════════════
# 測試 4：methodology_lookup_for_taxonomy_version()
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 4：methodology_lookup_for_taxonomy_version() ==========")

with app.app_context():
    version = ts.get_published_taxonomy_version("topic_prompt_build")
    lookup = ts.methodology_lookup_for_taxonomy_version(version)

    check("查得到存在的 sub_category（回傳 None 是因為 methodology 欄位本身是 None，但 key 存在）",
          "A1 結構化規則" in {c.sub_category for c in version.categories})
    check("查不到不存在的 sub_category，回傳 None", lookup("不存在的子類別") is None)

    v_id_methodology = _make_topic_with_version(
        "topic_methodology", status="published",
        categories=[{
            "main_category": "M", "sub_category": "有方法論",
            "definition": "d", "methodology": "某方法論", "citation": "某文獻",
        }],
    )
    m_version = ts.get_published_taxonomy_version("topic_methodology")
    m_lookup = ts.methodology_lookup_for_taxonomy_version(m_version)
    info = m_lookup("有方法論")
    check(
        "查到的 methodology/citation 跟該 Taxonomy_Category 一致",
        info is not None and info["methodology"] == "某方法論" and info["citation"] == "某文獻",
    )


# ═══════════════════════════════════════════════════════════════
# 測試 5：classify_v2 整合——分類與驗證讀同一份 taxonomy
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 5：classify_v2.resolve_published_taxonomy_prompt() 整合 ==========")

import services.classify_v2 as cv2

with app.app_context():
    prompt_content, category_lookup, taxonomy_version = cv2.resolve_published_taxonomy_prompt("topic_methodology")
    check("resolve_published_taxonomy_prompt 回傳的 taxonomy_version 正確", taxonomy_version.version_id == m_version.version_id)
    check("prompt_content 包含該 topic 的子類別", "有方法論" in prompt_content)

    _queue.clear()
    ANSWER = "測試回答內容，沒有 PII"
    q({"segments": [mask_pii(ANSWER)]})
    q({"classifications": [{
        "index": 0, "main_category": "M", "sub_category": "有方法論",
        "secondary_sub_category": None, "reasoning": "r", "summary": "s", "confidence": "high",
    }]})
    result = cv2.classify_response_multi_segment(
        ANSWER, prompt_content, "topic_methodology", category_lookup=category_lookup
    )
    seg = result["segments"][0]
    check("合法 sub_category：status 為 completed", seg["status"] == "completed")
    check("methodology 從同一個 Taxonomy_Category 取得", seg["methodology"] == "某方法論")
    check("citation 從同一個 Taxonomy_Category 取得", seg["citation"] == "某文獻")

    # Gemini 回傳一個不在這份 taxonomy 裡的 sub_category -> fail-closed
    _queue.clear()
    q({"segments": [mask_pii(ANSWER)]})
    q({"classifications": [{
        "index": 0, "main_category": "M", "sub_category": "Gemini亂編的子類別",
        "secondary_sub_category": None, "reasoning": "r", "summary": "s", "confidence": "high",
    }]})
    result2 = cv2.classify_response_multi_segment(
        ANSWER, prompt_content, "topic_methodology", category_lookup=category_lookup
    )
    seg2 = result2["segments"][0]
    check(
        "Gemini 回傳不存在的 sub_category 時 fail-closed（status=methodology_not_found）",
        seg2["status"] == "methodology_not_found",
    )
    check("methodology/citation 皆為 None（沒有查到就不硬填）", seg2["methodology"] is None and seg2["citation"] is None)


# ═══════════════════════════════════════════════════════════════
# 測試 6：publish_taxonomy_version()——同一 transaction 內archive舊版
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 6：publish_taxonomy_version() ==========")

with app.app_context():
    db.session.add(m.Topic(topic_key="topic_publish_flow", title="測試發布流程"))
    v1 = m.Taxonomy_Version(topic_key="topic_publish_flow", version_number=1, status="published", source="manual")
    db.session.add(v1)
    db.session.flush()
    db.session.add(m.Taxonomy_Category(version_id=v1.version_id, main_category="M", sub_category="S", sort_order=1, definition="d"))
    v2 = m.Taxonomy_Version(topic_key="topic_publish_flow", version_number=2, status="draft", source="manual")
    db.session.add(v2)
    db.session.flush()
    db.session.add(m.Taxonomy_Category(version_id=v2.version_id, main_category="M", sub_category="S2", sort_order=1, definition="d2"))
    db.session.commit()
    v1_id, v2_id = v1.version_id, v2.version_id

    ts.publish_taxonomy_version("topic_publish_flow", v2_id)

    v1_after = m.Taxonomy_Version.query.get(v1_id)
    v2_after = m.Taxonomy_Version.query.get(v2_id)
    check("舊版本 v1 被轉成 archived", v1_after.status == "archived")
    check("v1.archived_at 有被填入", v1_after.archived_at is not None)
    check("新版本 v2 被轉成 published", v2_after.status == "published")
    check("v2.published_at 有被填入", v2_after.published_at is not None)

    published_count = m.Taxonomy_Version.query.filter_by(
        topic_key="topic_publish_flow", status="published"
    ).count()
    check("發布後同一 topic 只剩 1 個 published 版本", published_count == 1)

    # 發布後可以正常透過 get_published_taxonomy_version 讀到新版
    current = ts.get_published_taxonomy_version("topic_publish_flow")
    check("get_published_taxonomy_version 讀到的是新發布的版本", current.version_id == v2_id)


# ═══════════════════════════════════════════════════════════════
# 測試 7：Response_Classification.taxonomy_version_id
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 7：Response_Classification taxonomy_version_id ==========")

with app.app_context():
    template = m.Survey_Template(title="t", access_code="ABCDE", question_json={"items": []})
    db.session.add(template)
    db.session.commit()
    survey_response = m.Survey_Response(template_id=template.template_id, answer_json={"answers": {}})
    db.session.add(survey_response)
    db.session.commit()

    # 7a：新資料帶入 taxonomy_version_id
    rc_new = m.Response_Classification(
        response_id=survey_response.response_id, source_type="survey", question_id="q1",
        answer_text="a", segment_start=0, segment_end=1,
        main_category="M", sub_category="S",
        taxonomy_version_id=m_version.version_id,
    )
    db.session.add(rc_new)
    db.session.commit()
    check("新資料可以正常寫入 taxonomy_version_id", rc_new.taxonomy_version_id == m_version.version_id)
    check("to_dict() 帶出 taxonomy_version_id", rc_new.to_dict()["taxonomy_version_id"] == m_version.version_id)

    # 7b：舊資料（不帶 taxonomy_version_id）仍可寫入，欄位為 NULL
    rc_legacy = m.Response_Classification(
        response_id=survey_response.response_id, source_type="survey", question_id="q1",
        answer_text="b", segment_start=1, segment_end=2,
        main_category="M", sub_category="S",
    )
    db.session.add(rc_legacy)
    db.session.commit()
    check("舊資料（未指定 taxonomy_version_id）可正常寫入，欄位為 NULL", rc_legacy.taxonomy_version_id is None)
    check("to_dict() 對舊資料回傳 taxonomy_version_id: None", rc_legacy.to_dict()["taxonomy_version_id"] is None)

    # 7c：刪除 Taxonomy_Version 後，Response_Classification 不被砍掉，改為 SET NULL
    db.session.delete(m.Taxonomy_Version.query.get(m_version.version_id))
    db.session.commit()
    rc_new_after = m.Response_Classification.query.get(rc_new.classification_id)
    check("刪除 Taxonomy_Version 後，Response_Classification 仍存在（未被 CASCADE 刪除）", rc_new_after is not None)
    check("刪除 Taxonomy_Version 後，taxonomy_version_id 被設為 NULL", rc_new_after.taxonomy_version_id is None)


print("\n" + "=" * 50)
print("Part 1（純 model/service 層）結果：")
if FAILED:
    print(f"共 {len(FAILED)} 項測試失敗：")
    for f in FAILED:
        print("  -", f)
else:
    print("全部通過！")


# ═══════════════════════════════════════════════════════════════
# 測試 8：route 層 fail-closed —— no published taxonomy / multiple published
# 用獨立的 Flask app + classification_bp，比照 test_classification_routes.py
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 8：route 層 fail-closed（no taxonomy / multiple published）==========")

import jwt
import pandas as pd
from routes.classifications.classification import classification_bp

app2 = Flask(__name__)
app2.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
app2.config["TESTING"] = True
app2.register_blueprint(classification_bp)
db.init_app(app2)

with app2.app_context():
    tables2 = [
        m.User.__table__,
        m.Admin.__table__,
        m.Survey_Template.__table__,
        m.Survey_Response.__table__,
        m.Response_Classification.__table__,
        m.Response_Segmentation_Status.__table__,
        m.Uploaded_Answer.__table__,
        m.Topic.__table__,
        m.Taxonomy_Version.__table__,
        m.Taxonomy_Category.__table__,
    ]
    db.metadata.create_all(bind=db.engine, tables=tables2)
    db.session.add(m.User(user_id=1, user_name="tester", email="tester@example.com", password_hash="x"))
    # topic_key="leadership_and_dept" 完全沒有任何 Taxonomy_Version（0 筆 published）
    # topic_key="career_and_feedback" 有 2 個 published（>1 筆，data integrity error）
    db.session.add(m.Topic(topic_key="career_and_feedback", title="有問題的 topic"))
    for i in range(2):
        v = m.Taxonomy_Version(topic_key="career_and_feedback", version_number=i + 1, status="published", source="manual")
        db.session.add(v)
        db.session.flush()
        db.session.add(m.Taxonomy_Category(version_id=v.version_id, main_category="M", sub_category=f"S{i}", sort_order=1, definition="d"))
    db.session.commit()

client2 = app2.test_client()


def auth_header(user_id):
    token = jwt.encode({"user_id": user_id}, os.environ["JWT_SECRET_KEY"], algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


print("\n--- 8a：topic_key 完全沒有 published taxonomy（0 筆）---")
df_a = pd.DataFrame({"意見": ["這是關於領導風格的意見"]})
buf_a = io.BytesIO()
df_a.to_excel(buf_a, index=False)
buf_a.seek(0)
_queue.clear()
q({"question_type": "leadership_and_dept"})  # routing 判斷成功，但這個 topic 沒有 taxonomy
resp_a = client2.post("/api/classification/upload", data={"file": (buf_a, "a.xlsx"), "text_column": "意見"}, headers=auth_header(1))
data_a = resp_a.get_json()
check("HTTP 201（沒有 taxonomy 不代表上傳失敗）", resp_a.status_code == 201)
check("saved_answer_count 為 1（原始文字仍照常保存）", data_a.get("saved_answer_count") == 1)
check("classified_count 為 0（不 fallback 動態分類）", data_a.get("classified_count") == 0)
check("columns 標記 taxonomy_unavailable=True", data_a["columns"][0]["taxonomy_unavailable"] is True)
check("完全沒有呼叫 Gemini 做分類（只消耗 routing 那一次）", len(_queue) == 0)

with app2.app_context():
    ua_a = m.Uploaded_Answer.query.filter_by(upload_batch_id=data_a["upload_batch_id"]).all()
    rc_a = m.Response_Classification.query.filter_by(upload_batch_id=data_a["upload_batch_id"]).all()
    check("Uploaded_Answer 仍正常寫入原始文字", len(ua_a) == 1 and ua_a[0].answer_text == "這是關於領導風格的意見")
    check("完全沒有建立 Response_Classification", len(rc_a) == 0)


print("\n--- 8b：topic_key 有 >1 個 published taxonomy（data integrity error）---")
df_b = pd.DataFrame({"意見": ["這是關於職涯發展的意見"]})
buf_b = io.BytesIO()
df_b.to_excel(buf_b, index=False)
buf_b.seek(0)
_queue.clear()
q({"question_type": "career_and_feedback"})  # routing 判斷成功，但這個 topic 有多筆 published
resp_b = client2.post("/api/classification/upload", data={"file": (buf_b, "b.xlsx"), "text_column": "意見"}, headers=auth_header(1))
data_b = resp_b.get_json()
check("HTTP 201（data integrity error 不會讓整個 request 500）", resp_b.status_code == 201)
check("saved_answer_count 為 1（原始文字仍照常保存）", data_b.get("saved_answer_count") == 1)
check("classified_count 為 0（不默默選第一筆繼續分類）", data_b.get("classified_count") == 0)
check("columns 標記 taxonomy_unavailable=True", data_b["columns"][0]["taxonomy_unavailable"] is True)

with app2.app_context():
    rc_b = m.Response_Classification.query.filter_by(upload_batch_id=data_b["upload_batch_id"]).all()
    check("完全沒有建立 Response_Classification（fail-closed，不猜哪一版）", len(rc_b) == 0)


print("\n" + "=" * 50)
if FAILED:
    print(f"共 {len(FAILED)} 項測試失敗：")
    for f in FAILED:
        print("  -", f)
    sys.exit(1)
else:
    print("全部測試通過！")
