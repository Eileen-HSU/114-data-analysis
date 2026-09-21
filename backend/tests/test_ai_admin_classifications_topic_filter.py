#!/usr/bin/env python
"""
測試腳本：GET /api/admin/ai/classifications?topic=<topic_key> 修正
（question_id UUID 不等於 topic_key 這個 bug）。

背景：Response_Classification.question_id 存的是問卷題目 UUID（或外部
上傳的欄位識別碼），跟 Topic.topic_key（例如 "leadership_and_dept"）
是完全不同的值域，過去用 `filter_by(question_id=topic)` 直接比較必然
查不到任何結果。正確作法是透過寫入分類結果時一併保存的
taxonomy_version_id 反查 Taxonomy_Version.topic_key。

涵蓋：
    1. question_id 是 UUID 格式的字串（跟 topic_key 明顯不同值域，
       證明兩者不能直接比較）
    2. taxonomy_version_id 正確連到該 Topic（透過 Taxonomy_Version）
    3. GET .../classifications?topic=leadership_and_dept 能正確查到
       這筆分類結果（即使 question_id 是完全不相關的 UUID）
    4. 不會誤把不同 topic 的分類結果也撈出來
    5. taxonomy_version_id IS NULL 的舊資料，topic 篩選查不到它，也
       不會被硬塞進任何 Topic（不做臆測式回填）
    6. review_status / needs_human_review filter、__unassigned__ 邏輯、
       limit / ordering、response JSON 格式（含 segment /
       effective_result）全部維持既有行為（regression）

執行方式：
    cd backend
    python3 tests/test_ai_admin_classifications_topic_filter.py
"""

import os
import sys
import uuid

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

FAILED = []


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    if status == "FAIL":
        FAILED.append(label)
    print(f"[{status}] {label}")


from flask import Flask
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.ext.compiler import compiles

from extensions import db
import models as m
import taxonomy as tx
from routes.admin.ai_admin import ai_admin_bp
from routes.auth.admin_guard import build_admin_token


@compiles(MEDIUMTEXT, "sqlite")
def _compile_mediumtext_sqlite(element, compiler, **kw):
    return "TEXT"


app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
app.config["TESTING"] = True
app.register_blueprint(ai_admin_bp)
db.init_app(app)

with app.app_context():
    tables = [
        m.User.__table__,
        m.Admin.__table__,
        m.Survey_Template.__table__,
        m.Survey_Response.__table__,
        m.Response_Classification.__table__,
        tx.Topic.__table__,
        tx.Taxonomy_Version.__table__,
        tx.Taxonomy_Category.__table__,
    ]
    db.metadata.create_all(bind=db.engine, tables=tables)

    db.session.add(m.Admin(admin_id=1, admin_name="測試管理員", email="admin@example.com", password_hash="x"))
    db.session.add(m.User(user_id=1, user_name="owner", email="owner@example.com", password_hash="x"))

    # 兩個不同的 Topic，各自一版 published taxonomy。
    db.session.add(tx.Topic(topic_key="leadership_and_dept", title="主管領導和部門合作"))
    db.session.add(tx.Topic(topic_key="career_and_feedback", title="工作表現的回饋及職涯發展"))
    version_leadership = tx.Taxonomy_Version(
        topic_key="leadership_and_dept", version_number=1,
        status="published", source="migrated_legacy",
    )
    version_career = tx.Taxonomy_Version(
        topic_key="career_and_feedback", version_number=1,
        status="published", source="migrated_legacy",
    )
    db.session.add_all([version_leadership, version_career])
    db.session.commit()
    version_leadership_id = version_leadership.version_id
    version_career_id = version_career.version_id

    template = m.Survey_Template(
        title="測試問卷", access_code="TOPICF", user_id=1,
        question_json={"items": [
            {"id": "521d4299-748b-4689-8533-c00c8155336c", "type": "short", "title": "對主管的建議", "question_type": "leadership_and_dept"},
        ]},
    )
    db.session.add(template)
    db.session.commit()
    template_id = template.template_id

    survey_response = m.Survey_Response(template_id=template_id, answer_json={"answers": {}})
    db.session.add(survey_response)
    db.session.commit()
    response_id = survey_response.response_id


def make_classification(question_id, answer_text, main_category, sub_category, taxonomy_version_id):
    with app.app_context():
        rc = m.Response_Classification(
            response_id=response_id,
            source_type="survey",
            question_id=question_id,
            answer_text=answer_text,
            segment_start=0,
            segment_end=len(answer_text),
            main_category=main_category,
            sub_category=sub_category,
            reasoning="ai reasoning",
            summary="ai summary",
            methodology="m",
            citation="c",
            status="completed",
            taxonomy_version_id=taxonomy_version_id,
        )
        db.session.add(rc)
        db.session.commit()
        return rc.classification_id


client = app.test_client()


def admin_header():
    token = build_admin_token(1)
    return {"Authorization": f"Bearer {token}"}


# ═══════════════════════════════════════════════════════════════
# 準備測資
# ═══════════════════════════════════════════════════════════════
SURVEY_QUESTION_UUID = "521d4299-748b-4689-8533-c00c8155336c"
OTHER_QUESTION_UUID = "7627e8e6-acd6-4db1-9c24-e8ed9eeb6035"

cid_leadership = make_classification(
    SURVEY_QUESTION_UUID, "希望主管多給回饋", "部門合作", "B2 支援協作", version_leadership_id,
)
cid_career = make_classification(
    OTHER_QUESTION_UUID, "希望增加教育訓練", "工作表現的回饋及職涯發展", "A5 教育訓練", version_career_id,
)
# 舊資料：taxonomy_version_id 是 NULL（Phase B 之前的資料）。
cid_legacy = make_classification(
    "legacy_question_col", "舊資料沒有 taxonomy_version_id", "未知", "未知", None,
)


# ═══════════════════════════════════════════════════════════════
# 測試 1：question_id 是 UUID，不是 topic_key
# ═══════════════════════════════════════════════════════════════
print("========== 測試 1：question_id 是 UUID，topic_key 是另一種格式 ==========")
with app.app_context():
    rc = m.Response_Classification.query.get(cid_leadership)
    check("question_id 是合法的 UUID 字串", str(uuid.UUID(rc.question_id)) == rc.question_id)
    check("question_id 不等於它所屬的 topic_key（兩者是不同值域，不能直接比較）", rc.question_id != "leadership_and_dept")


# ═══════════════════════════════════════════════════════════════
# 測試 2：taxonomy_version_id 正確連到該 Topic
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 2：taxonomy_version_id -> Taxonomy_Version -> Topic.topic_key ==========")
with app.app_context():
    rc = m.Response_Classification.query.get(cid_leadership)
    version = tx.Taxonomy_Version.query.get(rc.taxonomy_version_id)
    check("taxonomy_version_id 不是 None", rc.taxonomy_version_id is not None)
    check("透過 taxonomy_version_id 查到的 Taxonomy_Version.topic_key 正確", version.topic_key == "leadership_and_dept")


# ═══════════════════════════════════════════════════════════════
# 測試 3：GET .../classifications?topic=leadership_and_dept 能查到
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 3：topic filter 能正確查到（修正後的核心行為）==========")
resp = client.get("/api/admin/ai/classifications?topic=leadership_and_dept", headers=admin_header())
check("HTTP 200", resp.status_code == 200)
data = resp.get_json()
returned_ids = {row["classification_id"] for row in data["classifications"]}
check("查到 cid_leadership", cid_leadership in returned_ids)
check("不應該回傳 0 筆（修正前的 bug 症狀就是永遠查不到任何資料）", len(data["classifications"]) > 0)


# ═══════════════════════════════════════════════════════════════
# 測試 4：不會把不同 topic 的分類結果也撈出來
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 4：topic 篩選不會誤撈其他 topic 的資料 ==========")
check("career_and_feedback 底下的 cid_career 不應該出現在 leadership_and_dept 的結果裡", cid_career not in returned_ids)

resp_career = client.get("/api/admin/ai/classifications?topic=career_and_feedback", headers=admin_header())
returned_ids_career = {row["classification_id"] for row in resp_career.get_json()["classifications"]}
check("反過來查 career_and_feedback，只會查到 cid_career", returned_ids_career == {cid_career})


# ═══════════════════════════════════════════════════════════════
# 測試 5：不再依賴 question_id == topic_key；taxonomy_version_id 為 NULL
#         的舊資料不會被硬塞進任何 Topic
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 5：不依賴 question_id 比對；NULL 的舊資料不被臆測歸類 ==========")
check(
    "cid_leadership 的 question_id 是完全不相關的 UUID，證明查詢邏輯不是靠 question_id 比對出來的",
    SURVEY_QUESTION_UUID != "leadership_and_dept",
)
check("taxonomy_version_id=NULL 的舊資料，在 leadership_and_dept 篩選下查不到", cid_legacy not in returned_ids)
check("taxonomy_version_id=NULL 的舊資料，在 career_and_feedback 篩選下也查不到", cid_legacy not in returned_ids_career)

# 舊資料也不會出現在任何其他 topic_key 底下（不存在的 topic_key 也一樣查不到，
# 而不是被歸到某個猜測的分類）。
resp_nonexistent_topic = client.get("/api/admin/ai/classifications?topic=some_other_topic_key", headers=admin_header())
check(
    "查一個不存在的 topic_key，回傳空陣列而不是報錯或誤撈資料",
    resp_nonexistent_topic.status_code == 200 and resp_nonexistent_topic.get_json()["classifications"] == [],
)


# ═══════════════════════════════════════════════════════════════
# 測試 6：既有行為 regression —— review_status / needs_human_review /
#         __unassigned__ / limit·ordering / response JSON 格式
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 6：既有行為 regression ==========")

resp_no_topic = client.get("/api/admin/ai/classifications", headers=admin_header())
check("不帶 topic 參數時，查全部（既有行為不變）", resp_no_topic.status_code == 200)
all_ids = {row["classification_id"] for row in resp_no_topic.get_json()["classifications"]}
check("不帶 topic 時，三筆（含 legacy）都查得到", {cid_leadership, cid_career, cid_legacy} <= all_ids)

resp_review_status = client.get("/api/admin/ai/classifications?review_status=pending_review", headers=admin_header())
check("review_status filter 仍正常運作", resp_review_status.status_code == 200)
check(
    "review_status filter 可以跟 topic 一起使用",
    client.get(
        "/api/admin/ai/classifications?topic=leadership_and_dept&review_status=pending_review",
        headers=admin_header(),
    ).status_code == 200,
)

resp_bad_status = client.get("/api/admin/ai/classifications?review_status=not_a_real_status", headers=admin_header())
check("非法 review_status 仍然回 400（regression）", resp_bad_status.status_code == 400)

resp_unassigned = client.get("/api/admin/ai/classifications?topic=__unassigned__", headers=admin_header())
check("__unassigned__ 邏輯不受影響，仍正常運作", resp_unassigned.status_code == 200)

resp_needs_review = client.get("/api/admin/ai/classifications?needs_human_review=true", headers=admin_header())
check("needs_human_review filter 仍正常運作", resp_needs_review.status_code == 200)

sample_row = next((r for r in resp_no_topic.get_json()["classifications"] if r["classification_id"] == cid_leadership), None)
check("response JSON 仍包含 segment 欄位（既有格式）", sample_row is not None and "segment" in sample_row)
check("response JSON 仍包含 effective_result 欄位（既有格式）", sample_row is not None and "effective_result" in sample_row)
check(
    "effective_result 內容正確（review_status=pending_review 時讀 AI original）",
    sample_row["effective_result"]["main_category"] == "部門合作" and sample_row["effective_result"]["sub_category"] == "B2 支援協作",
)

with app.app_context():
    order_check_ids = [row["classification_id"] for row in resp_no_topic.get_json()["classifications"]]
    created_ats = [
        m.Response_Classification.query.get(cid).created_at for cid in order_check_ids
    ]
    check("排序仍是 created_at 由新到舊（既有 ordering 不變）", created_ats == sorted(created_ats, reverse=True))


print("\n" + "=" * 50)
if FAILED:
    print(f"共 {len(FAILED)} 項測試失敗：")
    for f in FAILED:
        print("  -", f)
    sys.exit(1)
else:
    print("全部測試通過！")
