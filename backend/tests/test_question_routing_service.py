"""
測試腳本：backend/services/question_routing_service.py（Dynamic Topic
routing 版本）。

涵蓋（對應本次需求文件的測試清單）：
    1. 3 個 Topic，其中 2 個 published、1 個只有 draft
       → _get_routing_candidates() 只回傳那 2 個 published 的
    2. Gemini 可選任意自訂 topic_key（不限舊有的 leadership_and_dept /
       career_and_feedback 兩個），只要那個 Topic 目前有 published
       taxonomy
    3. unpublished（draft-only）Topic 不可被選中，即使 Gemini 回傳
       它的 topic_key，也視為不合法值、fallback 成 None
    4. Gemini 回傳完全不存在於候選清單裡的字串 → None
    5. Gemini 回傳 null → None
    6. candidates 為空（目前沒有任何 Topic 有 published taxonomy）時，
       完全不呼叫 Gemini
    7. Topic.description 是 NULL 時，routing prompt 仍可用
       question_text / 子類別名稱摘要組出有意義的內容，不會出現
       "None" 這種字面字串、也不會整個空白
    8. 同一個 Topic 同時有 >1 筆 published Taxonomy_Version 時，這個
       Topic 被排除在候選之外、印出 integrity error log，但不影響
       其他資料正常的 Topic 仍然出現在候選裡

    另外保留原本就有的 retry / 空字串輸入 / 非法 JSON 等既有行為，
    只是改成在有 DB-backed candidates 的前提下驗證（因為
    route_question_type() 現在需要查 DB 才能組出候選清單，跟改版前
    完全不依賴 DB 的版本不同）。

不依賴真實 google.genai 網路呼叫：跟本專案其餘 tests/test_*.py 一致，
用假的 services.gemini_client.GenerativeModel 攔截「送進去的
system_instruction / 收到的假回應」，不會真的打 API，也不使用會跟
目前 gemini_client.py（新版 google-genai SDK）衝突的
sys.modules["google"] 偽造寫法。

執行方式：
    cd backend
    export JWT_SECRET_KEY=test-secret-key-for-testing-only
    python3 tests/test_question_routing_service.py
"""

import contextlib
import io
import json
import os
import sys
import time

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

FAILED = []


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    if status == "FAIL":
        FAILED.append(label)
    print(f"[{status}] {label}")


# ═══════════════════════════════════════════════════════════════
# 假的 GenerativeModel：攔截送進去的 system_instruction / contents，
# 用佇列依序回傳假回應（字串或 Exception），不打真實 API。
# ═══════════════════════════════════════════════════════════════

_queued_responses = []
_call_log = []  # 每次 generate_content 呼叫都記一筆，用來驗證「有沒有呼叫過」


class _FakeResp:
    def __init__(self, text):
        self.text = text


class _FakeGenerativeModel:
    def __init__(self, model_name=None, system_instruction=None, **kwargs):
        self.model_name = model_name
        self.system_instruction = system_instruction

    def generate_content(self, contents, **kwargs):
        _call_log.append({"system_instruction": self.system_instruction, "contents": contents})
        item = _queued_responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return _FakeResp(item)


def queue_json(obj):
    _queued_responses.append(json.dumps(obj, ensure_ascii=False))


def reset_gemini_spy():
    _queued_responses.clear()
    _call_log.clear()


import services.gemini_client as gemini_client_module
gemini_client_module.GenerativeModel = _FakeGenerativeModel

import services.question_routing_service as qrs


# ═══════════════════════════════════════════════════════════════
# Flask app + SQLite in-memory：Topic / Taxonomy_Version /
# Taxonomy_Category 三張表，供 _get_routing_candidates() 查詢。
# ═══════════════════════════════════════════════════════════════

from flask import Flask
from extensions import db
import models as m
from taxonomy import (
    TAXONOMY_VERSION_STATUS_PUBLISHED,
    TAXONOMY_VERSION_STATUS_DRAFT,
)

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
app.config["TESTING"] = True
db.init_app(app)

with app.app_context():
    db.metadata.create_all(bind=db.engine, tables=[
        m.Topic.__table__,
        m.Taxonomy_Version.__table__,
        m.Taxonomy_Category.__table__,
    ])


def make_topic(topic_key, title, question_text=None, description=None):
    topic = m.Topic(topic_key=topic_key, title=title, question_text=question_text, description=description)
    db.session.add(topic)
    return topic


def make_version(topic_key, version_number, status, categories=None):
    version = m.Taxonomy_Version(
        topic_key=topic_key, version_number=version_number, status=status, source="manual",
    )
    db.session.add(version)
    db.session.flush()
    for i, (main_category, sub_category) in enumerate(categories or [], start=1):
        db.session.add(m.Taxonomy_Category(
            version_id=version.version_id, sort_order=i,
            main_category=main_category, sub_category=sub_category,
        ))
    return version


with app.app_context():

    print("========== 1. 3 個 Topic（2 published + 1 draft-only）：candidates 只有那 2 個 ==========")

    make_topic("leadership_and_dept", "主管領導和部門合作")
    make_version("leadership_and_dept", 1, TAXONOMY_VERSION_STATUS_PUBLISHED,
                 categories=[("主管領導", "A1 工作與生活邊界"), ("主管領導", "A2 回饋與溝通")])

    make_topic("career_and_feedback", "工作表現的回饋及職涯發展")
    make_version("career_and_feedback", 1, TAXONOMY_VERSION_STATUS_PUBLISHED,
                 categories=[("工作表現的回饋及職涯發展", "A5 教育訓練")])

    make_topic("draft_only_topic", "還在草稿階段的新主題")
    make_version("draft_only_topic", 1, TAXONOMY_VERSION_STATUS_DRAFT,
                 categories=[("草稿主類別", "草稿子類別")])

    db.session.commit()

    candidates = qrs._get_routing_candidates()
    candidate_keys = {c["topic_key"] for c in candidates}

    check("candidates 剛好 2 個", len(candidates) == 2)
    check("candidates 包含 leadership_and_dept", "leadership_and_dept" in candidate_keys)
    check("candidates 包含 career_and_feedback", "career_and_feedback" in candidate_keys)
    check("draft-only 的 Topic 不在 candidates 裡", "draft_only_topic" not in candidate_keys)


    print("\n========== 2. Gemini 可選任意自訂 topic_key（不限舊兩個） ==========")

    make_topic("custom_topic_x", "自訂主題 X")
    make_version("custom_topic_x", 1, TAXONOMY_VERSION_STATUS_PUBLISHED,
                 categories=[("自訂大類", "自訂子類 1")])

    make_topic("another_new_topic", "另一個全新主題")
    make_version("another_new_topic", 1, TAXONOMY_VERSION_STATUS_PUBLISHED,
                 categories=[("另一大類", "另一子類 1")])

    db.session.commit()

    reset_gemini_spy()
    queue_json({"question_type": "custom_topic_x"})
    result = qrs.route_question_type("這是一段關於自訂主題 X 的測試內容")
    check("Gemini 選第 3 個自訂 topic_key（custom_topic_x）能正確回傳，不受限於舊白名單", result == "custom_topic_x")

    reset_gemini_spy()
    queue_json({"question_type": "another_new_topic"})
    result = qrs.route_question_type("這是一段關於另一個全新主題的測試內容")
    check("Gemini 選第 4 個自訂 topic_key（another_new_topic）也能正確回傳", result == "another_new_topic")

    check(
        "這次 system_instruction 裡確實列出了全部 4 個候選（含自訂的兩個）",
        all(
            key in _call_log[-1]["system_instruction"]
            for key in ["leadership_and_dept", "career_and_feedback", "custom_topic_x", "another_new_topic"]
        ),
    )


    print("\n========== 3. unpublished（draft-only）Topic 不可被選中 ==========")

    reset_gemini_spy()
    queue_json({"question_type": "draft_only_topic"})
    result = qrs.route_question_type("這段內容故意讓 Gemini 選還沒 published 的 Topic")
    check("Gemini 選了 draft-only 的 topic_key，仍視為不合法、回傳 None", result is None)


    print("\n========== 4. unknown key（完全不在候選清單裡的字串）→ None ==========")

    reset_gemini_spy()
    queue_json({"question_type": "totally_made_up_topic_key"})
    result = qrs.route_question_type("測試完全不存在的 key")
    check("Gemini 回傳不存在的 topic_key，回傳 None", result is None)


    print("\n========== 5. Gemini 回傳 null → None ==========")

    reset_gemini_spy()
    queue_json({"question_type": None})
    result = qrs.route_question_type("今天天氣如何")
    check("Gemini 主動回傳 null，回傳 None", result is None)


    print("\n========== 6. candidates 為空時完全不呼叫 Gemini ==========")

    # 暫時把所有 published 版本都下架（改成 archived），模擬「目前
    # 完全沒有任何 Topic 有 published taxonomy」的情境。
    published_versions = m.Taxonomy_Version.query.filter_by(status=TAXONOMY_VERSION_STATUS_PUBLISHED).all()
    original_statuses = [(v.version_id, v.status) for v in published_versions]
    for v in published_versions:
        v.status = "archived"
    db.session.commit()

    reset_gemini_spy()
    result = qrs.route_question_type("這段內容不管講什麼，反正沒有任何 Topic 可以選")
    check("candidates 為空時回傳 None", result is None)
    check("candidates 為空時完全沒有呼叫過 Gemini（call log 是空的）", len(_call_log) == 0)

    # 還原，後面的測試還需要正常的候選清單。
    for version_id, status in original_statuses:
        v = m.Taxonomy_Version.query.get(version_id)
        v.status = status
    db.session.commit()


    print("\n========== 7. description=NULL 時，prompt 仍可用 question_text / 子類別摘要組出內容 ==========")

    make_topic(
        "no_description_topic", "沒有填 description 的主題",
        question_text="您對主管平時的帶領方式有什麼建議？",
        description=None,
    )
    make_version("no_description_topic", 1, TAXONOMY_VERSION_STATUS_PUBLISHED,
                 categories=[("測試大類", "測試子類 A"), ("測試大類", "測試子類 B")])
    db.session.commit()

    candidates = qrs._get_routing_candidates()
    target = next(c for c in candidates if c["topic_key"] == "no_description_topic")
    check("這個 Topic 的 description 確實是 None（測試前提成立）", target["description"] is None)
    check("category_summary 有抓到子類別名稱", len(target["category_summary"]) >= 1)

    prompt_text = qrs._build_routing_prompt(candidates)
    check("prompt 沒有出現字面上的 'None' 字串（沒有把 None 直接串進去）", "None" not in prompt_text)
    check("prompt 包含這個 Topic 的 question_text 內容", "您對主管平時的帶領方式有什麼建議" in prompt_text)
    check("prompt 包含這個 Topic 的子類別摘要", "測試子類 A" in prompt_text)
    check("prompt 仍然包含這個 Topic 的 topic_key 本身", "no_description_topic" in prompt_text)


    print("\n========== 8. 同一 Topic 同時有 >1 筆 published → 排除該 Topic 並 log，不影響其他 Topic ==========")

    make_topic("duplicate_topic", "資料異常：同時有兩個 published 版本")
    make_version("duplicate_topic", 1, TAXONOMY_VERSION_STATUS_PUBLISHED, categories=[("大類", "子類 1")])
    make_version("duplicate_topic", 2, TAXONOMY_VERSION_STATUS_PUBLISHED, categories=[("大類", "子類 2")])

    make_topic("normal_topic_after_duplicate", "正常的另一個主題")
    make_version("normal_topic_after_duplicate", 1, TAXONOMY_VERSION_STATUS_PUBLISHED,
                 categories=[("正常大類", "正常子類")])

    db.session.commit()

    captured_stdout = io.StringIO()
    with contextlib.redirect_stdout(captured_stdout):
        candidates = qrs._get_routing_candidates()
    log_output = captured_stdout.getvalue()
    candidate_keys = {c["topic_key"] for c in candidates}

    check("duplicate_topic（>1 個 published）被排除在候選之外", "duplicate_topic" not in candidate_keys)
    check("正常的 normal_topic_after_duplicate 仍然在候選裡，不受影響", "normal_topic_after_duplicate" in candidate_keys)
    check("其他既有正常 Topic（leadership_and_dept）也不受影響", "leadership_and_dept" in candidate_keys)
    check("有印出 [ROUTING_TOPIC_INTEGRITY_ERROR] log", "[ROUTING_TOPIC_INTEGRITY_ERROR]" in log_output)
    check("log 內容有指名是哪個 topic_key 出問題", "duplicate_topic" in log_output)


    print("\n========== 9.（既有行為回歸）空字串 / None / 純空白輸入，不呼叫 Gemini ==========")

    reset_gemini_spy()
    check("空字串輸入直接 None", qrs.route_question_type("") is None)
    check("None 輸入直接 None", qrs.route_question_type(None) is None)
    check("純空白字串直接 None", qrs.route_question_type("   ") is None)
    check("以上三種情況完全沒有呼叫過 Gemini", len(_call_log) == 0)


    print("\n========== 10.（既有行為回歸）429 限流重試機制 ==========")

    reset_gemini_spy()
    _queued_responses.append(
        Exception("429 Resource has been exhausted (e.g. check quota). Please retry in 0.01s")
    )
    queue_json({"question_type": "career_and_feedback"})
    _start = time.time()
    result = qrs.route_question_type("績效面談與職涯發展建議")
    _elapsed = time.time() - _start
    check("限流後重試成功，不會直接放棄變成 None", result == "career_and_feedback")
    check("有讀到訊息裡建議的等待秒數，不是傻等固定 20 秒", _elapsed < 5)

    reset_gemini_spy()
    for _ in range(3):  # 對應 _MAX_ATTEMPTS = 3
        _queued_responses.append(Exception("429 RESOURCE_EXHAUSTED. Please retry in 0.01s"))
    check("連續限流、重試用盡才 fallback 成 None", qrs.route_question_type("測試連續限流") is None)

    reset_gemini_spy()
    _queued_responses.append("not valid json")
    queue_json({"question_type": "leadership_and_dept"})
    check("非限流錯誤（JSON 解析失敗）fail-safe 成 None，不重試", qrs.route_question_type("測試非限流錯誤") is None)
    check("非限流錯誤沒有誤觸發重試，佇列裡的下一筆資料還在", len(_queued_responses) == 1)


print("\n" + "=" * 50)
if FAILED:
    print(f"共 {len(FAILED)} 項測試失敗：")
    for label in FAILED:
        print(f"  - {label}")
    sys.exit(1)
else:
    print("全部測試通過！")
