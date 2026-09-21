#!/usr/bin/env python
"""
測試腳本：驗證 Taxonomy-based Sandbox
（services/taxonomy_sandbox_service.py + POST .../sandbox 路由）。

涵蓋：
    1. published / draft / archived 版本皆可正常試跑
    2. 版本沒有 categories -> 422
    3. topic/version 不存在 -> 404
    4. answer_texts 數量 / 單筆 / 總字數超限 -> 422
    5. Gemini 例外 -> 502，且不留任何殘留資料
    6. 【架構保證】跑完 sandbox 後 Response_Classification /
       Uploaded_Answer 筆數完全不變
    7. Admin auth 保護
    8. Gemini 回傳不存在的 sub_category 時，原樣透傳
       status=methodology_not_found，不是 API 錯誤

全程 mock google.generativeai，不消耗真實 API quota。

執行方式：
    cd backend
    export JWT_SECRET_KEY=test-secret
    python3 tests/test_taxonomy_sandbox.py
"""

import sys
import os
import json

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

FAILED = []


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    if status == "FAIL":
        FAILED.append(label)
    print(f"[{status}] {label}")


# ── Mock：backend 現已改用內部 services/gemini_client.py 包裝
#    google-genai SDK（跟這次 Sandbox 工作無關的獨立遷移），
#    services/classify_v2.py 是 `from services import gemini_client as genai`，
#    所以這裡直接對 services.gemini_client 模組本身打補丁即可——
#    genai 這個名稱在 classify_v2 模組裡就是同一個模組物件的引用，
#    不需要（也不能再）透過 sys.modules["google"]/["google.generativeai"]
#    這種舊方式 mock，那樣做反而會污染真正的 google 套件命名空間，
#    讓其他需要真正 google.genai 的程式碼路徑跟著壞掉。
_queue = []


class _FakeResp:
    def __init__(self, text):
        self.text = text


class _FakeGenerativeModel:
    def __init__(self, model_name=None, system_instruction=None, **kwargs):
        self.model_name = model_name
        self.system_instruction = system_instruction

    def generate_content(self, contents, **kwargs):
        item = _queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return _FakeResp(item)


import services.gemini_client as gemini_client  # noqa: E402

gemini_client.GenerativeModel = _FakeGenerativeModel
gemini_client.configure = lambda **kwargs: None


def q(obj_or_text_or_exc):
    if isinstance(obj_or_text_or_exc, (str, Exception)):
        _queue.append(obj_or_text_or_exc)
    else:
        _queue.append(json.dumps(obj_or_text_or_exc, ensure_ascii=False))


from flask import Flask
from extensions import db
import models as m
from routes.admin.ai_admin import ai_admin_bp
from routes.auth.admin_guard import build_admin_token
from services import taxonomy_sandbox_service as sandbox_svc

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
        m.Survey_Template.__table__,
        m.Survey_Response.__table__,
        m.Response_Classification.__table__,
        m.Uploaded_Answer.__table__,
    ]
    db.metadata.create_all(bind=db.engine, tables=tables)
    admin = m.Admin(admin_name="tester", email="admin@example.com", password_hash="x")
    db.session.add(admin)
    db.session.commit()
    admin_id = admin.admin_id

    db.session.add(m.Topic(topic_key="topic_sandbox", title="沙盒測試主題"))
    published = m.Taxonomy_Version(topic_key="topic_sandbox", version_number=1, status="published", source="manual")
    draft = m.Taxonomy_Version(topic_key="topic_sandbox", version_number=2, status="draft", source="manual")
    archived = m.Taxonomy_Version(topic_key="topic_sandbox", version_number=0, status="archived", source="manual")
    empty_version = m.Taxonomy_Version(topic_key="topic_sandbox", version_number=3, status="draft", source="manual")
    db.session.add_all([published, draft, archived, empty_version])
    db.session.flush()
    for v in (published, draft, archived):
        db.session.add(m.Taxonomy_Category(version_id=v.version_id, main_category="M", sub_category="有方法論", sort_order=1, definition="d", methodology="法A", citation="Author (2020)"))
    db.session.commit()
    published_id, draft_id, archived_id, empty_id = published.version_id, draft.version_id, archived.version_id, empty_version.version_id

client = app.test_client()
AUTH = {"Authorization": f"Bearer {build_admin_token(admin_id)}"}


def post_sandbox(version_id, answer_texts, topic_key="topic_sandbox", auth=True):
    return client.post(
        f"/api/admin/ai/topics/{topic_key}/taxonomy/{version_id}/sandbox",
        headers=AUTH if auth else {},
        json={"answer_texts": answer_texts},
    )


VALID_CLASSIFICATION = {
    "main_category": "M", "sub_category": "有方法論",
    "secondary_sub_category": None, "reasoning": "r", "summary": "s", "confidence": 0.95,
}


def classification_with_index(index, overrides=None):
    return {"index": index, **VALID_CLASSIFICATION, **(overrides or {})}


print("========== 測試 1：published / draft / archived 皆可正常試跑 ==========")

for label, version_id in [("published", published_id), ("draft", draft_id), ("archived", archived_id)]:
    _queue.clear()
    q({"segments": ["測試回答內容"]})
    q({"classifications": [classification_with_index(0)]})
    resp = post_sandbox(version_id, ["測試回答內容"])
    check(f"{label} 版本：HTTP 200", resp.status_code == 200)
    body = resp.get_json()
    check(f"{label} 版本：taxonomy_version 資訊正確", body["taxonomy_version"]["version_id"] == version_id)
    check(f"{label} 版本：results 有 1 筆", len(body["results"]) == 1)
    check(f"{label} 版本：分類結果 status=completed", body["results"][0]["segments"][0]["status"] == "completed")
    check(f"{label} 版本：methodology/citation 正確帶出", body["results"][0]["segments"][0]["methodology"] == "法A")
    check(f"{label} 版本：confidence 正確帶出（float）", body["results"][0]["segments"][0]["confidence"] == 0.95)
    check(f"{label} 版本：高信心不被 flag（needs_human_review=False）", body["results"][0]["segments"][0]["needs_human_review"] is False)


print("\n========== 測試 8：Gemini 回傳不存在的 sub_category，原樣透傳，不是 API 錯誤 ==========")

_queue.clear()
q({"segments": ["測試回答內容"]})
q({"classifications": [classification_with_index(0, {"sub_category": "Gemini亂編的子類別"})]})
resp = post_sandbox(draft_id, ["測試回答內容"])
check("HTTP 200（不是錯誤）", resp.status_code == 200)
check("segment status 為 methodology_not_found", resp.get_json()["results"][0]["segments"][0]["status"] == "methodology_not_found")
check("methodology_not_found 也會被標記 needs_human_review=True", resp.get_json()["results"][0]["segments"][0]["needs_human_review"] is True)
check("review_flag_reason 為 methodology_not_found", resp.get_json()["results"][0]["segments"][0]["review_flag_reason"] == "methodology_not_found")


print("\n========== 測試 8b：低信心結果 -> needs_human_review=True，但 Sandbox 不寫 DB ==========")

with app.app_context():
    rc_before = m.Response_Classification.query.count()

_queue.clear()
q({"segments": ["測試回答內容"]})
q({"classifications": [classification_with_index(0, {"confidence": 0.4})]})
resp = post_sandbox(draft_id, ["測試回答內容"])
seg = resp.get_json()["results"][0]["segments"][0]
check("HTTP 200", resp.status_code == 200)
check("低信心 confidence=0.4 正確帶出", seg["confidence"] == 0.4)
check("低信心被標記 needs_human_review=True", seg["needs_human_review"] is True)
check("review_flag_reason 為 low_confidence", seg["review_flag_reason"] == "low_confidence")

with app.app_context():
    check("低信心結果不會建立任何 Response_Classification（sandbox 不寫 DB）", m.Response_Classification.query.count() == rc_before)


print("\n========== 測試 2：版本沒有 categories -> 422 ==========")

resp = post_sandbox(empty_id, ["測試回答內容"])
check("HTTP 422", resp.status_code == 422)
check("完全沒有消耗 Gemini queue", len(_queue) == 0)


print("\n========== 測試 3：topic/version 不存在 -> 404 ==========")

resp = post_sandbox(999999, ["a"])
check("version_id 不存在時回 404", resp.status_code == 404)

resp = post_sandbox(draft_id, ["a"], topic_key="topic_not_exist")
check("topic_key 不存在時回 404", resp.status_code == 404)


print("\n========== 測試 3b：version 存在但不屬於這個 topic -> 404 ==========")

with app.app_context():
    db.session.add(m.Topic(topic_key="topic_other", title="另一個主題"))
    other_version = m.Taxonomy_Version(topic_key="topic_other", version_number=1, status="published", source="manual")
    db.session.add(other_version)
    db.session.flush()
    db.session.add(m.Taxonomy_Category(version_id=other_version.version_id, main_category="M", sub_category="S", sort_order=1, definition="d"))
    db.session.commit()
    other_version_id = other_version.version_id

resp = post_sandbox(other_version_id, ["a"], topic_key="topic_sandbox")
check("version 屬於別的 topic 時回 404（不可跨 topic 借用版本）", resp.status_code == 404)


print("\n========== 測試 4：批次上限 ==========")

check("MAX_ANSWER_COUNT 為 20（獨立於 generation 的 500）", sandbox_svc.MAX_ANSWER_COUNT == 20)
check("MAX_SINGLE_ANSWER_CHARS 為 2000", sandbox_svc.MAX_SINGLE_ANSWER_CHARS == 2000)
check("MAX_TOTAL_ANSWER_CHARS 為 20000（獨立於 generation 的 200000）", sandbox_svc.MAX_TOTAL_ANSWER_CHARS == 20_000)

resp = post_sandbox(draft_id, ["測試"] * (sandbox_svc.MAX_ANSWER_COUNT + 1))
check("數量超限回 422", resp.status_code == 422)

resp = post_sandbox(draft_id, ["字" * (sandbox_svc.MAX_SINGLE_ANSWER_CHARS + 1)])
check("單筆過長回 422", resp.status_code == 422)

resp = post_sandbox(draft_id, [])
check("空陣列回 400", resp.status_code == 400)

resp = post_sandbox(draft_id, ["   ", ""])
check("全部是空白字串回 422（格式上是非空陣列，內容驗證失敗）", resp.status_code == 422)


print("\n========== 測試 5：Gemini 例外時，原樣透傳失敗診斷資訊（不是 API 錯誤）==========")
# classify_response_multi_segment() 既有設計：Gemini/解析失敗會被吞掉，
# 轉成帶 segmentation_error_detail 的正常回傳值（跟 production
# classification 完全一致），不會讓例外往外拋——這裡驗證的是「sandbox
# 如實透傳這個既有行為」，不是「sandbox 自己把它轉成 502」。

with app.app_context():
    rc_before = m.Response_Classification.query.count()
    ua_before = m.Uploaded_Answer.query.count()

_queue.clear()
q(RuntimeError("模擬 Gemini 掛掉"))
resp = post_sandbox(draft_id, ["測試回答內容"])
check("HTTP 200（Gemini 失敗不是 sandbox 的 API 錯誤）", resp.status_code == 200)
body = resp.get_json()
check("segmentation_status 為 failed", body["results"][0]["segmentation_status"] == "failed")
check("segmentation_error_detail 帶有失敗原因", "模擬 Gemini 掛掉" in (body["results"][0]["segmentation_error_detail"] or ""))
check("segments 為空陣列（沒有半套分類結果）", body["results"][0]["segments"] == [])

with app.app_context():
    check("Gemini 例外後 Response_Classification 筆數不變", m.Response_Classification.query.count() == rc_before)
    check("Gemini 例外後 Uploaded_Answer 筆數不變", m.Uploaded_Answer.query.count() == ua_before)


print("\n========== 測試 6：【架構保證】正常試跑完全不寫入正式資料 ==========")

with app.app_context():
    rc_before = m.Response_Classification.query.count()
    ua_before = m.Uploaded_Answer.query.count()
    version_before = m.Taxonomy_Version.query.filter_by(topic_key="topic_sandbox").count()
    category_before = m.Taxonomy_Category.query.count()

_queue.clear()
q({"segments": ["測試 A", "測試 B"]})
q({"classifications": [classification_with_index(0), classification_with_index(1)]})
resp = post_sandbox(draft_id, ["測試 A、測試 B 一起送"])
check("HTTP 200", resp.status_code == 200)

with app.app_context():
    check("跑完 sandbox 後 Response_Classification 筆數完全不變", m.Response_Classification.query.count() == rc_before)
    check("跑完 sandbox 後 Uploaded_Answer 筆數完全不變", m.Uploaded_Answer.query.count() == ua_before)
    check("跑完 sandbox 後 Taxonomy_Version 筆數不變（沒有 clone/publish 副作用）", m.Taxonomy_Version.query.filter_by(topic_key="topic_sandbox").count() == version_before)
    check("跑完 sandbox 後 Taxonomy_Category 筆數不變", m.Taxonomy_Category.query.count() == category_before)
    check("draft 版本狀態仍是 draft（sandbox 沒有偷偷 publish）", m.Taxonomy_Version.query.get(draft_id).status == "draft")


print("\n========== 測試 7：Admin auth 保護 ==========")

resp = post_sandbox(draft_id, ["a"], auth=False)
check("沒帶 token 時回 401", resp.status_code == 401)


print("\n" + "=" * 50)
if FAILED:
    print(f"共 {len(FAILED)} 項測試失敗：")
    for f in FAILED:
        print("  -", f)
    sys.exit(1)
else:
    print("全部測試通過！")
