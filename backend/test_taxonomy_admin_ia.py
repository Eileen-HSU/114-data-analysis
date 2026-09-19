#!/usr/bin/env python
"""
測試腳本：驗證 Topic-centric IA 重構對
GET /api/admin/ai/classifications 新增的 topic=__unassigned__ 支援。

涵蓋：
    1. 不傳 topic -> 查全部（既有行為，不可改壞）
    2. topic=X -> 只查該 topic（既有行為，不可改壞）
    3. topic=__unassigned__ -> question_id IS NULL 或 == "other"，
       不包含其他 topic 的資料
    4. review_status 篩選跟 topic 篩選可以同時使用（既有行為）

執行方式：
    cd backend
    export JWT_SECRET_KEY=test-secret
    python3 test_taxonomy_admin_ia.py
"""

import sys
import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only")
sys.path.insert(0, os.path.dirname(__file__))

FAILED = []


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    if status == "FAIL":
        FAILED.append(label)
    print(f"[{status}] {label}")


from flask import Flask
from extensions import db
import models as m
from routes.admin.ai_admin import ai_admin_bp
from routes.auth.admin_guard import build_admin_token

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
        m.Survey_Template.__table__,
        m.Survey_Response.__table__,
        m.Response_Classification.__table__,
    ]
    db.metadata.create_all(bind=db.engine, tables=tables)
    admin = m.Admin(admin_name="tester", email="admin@example.com", password_hash="x")
    db.session.add(admin)
    db.session.commit()
    admin_id = admin.admin_id

    template = m.Survey_Template(title="t", access_code="ABCDE", question_json={"items": []})
    db.session.add(template)
    db.session.commit()
    survey_response = m.Survey_Response(template_id=template.template_id, answer_json={"answers": {}})
    db.session.add(survey_response)
    db.session.commit()

    def make_row(question_id, sub_category):
        return m.Response_Classification(
            response_id=survey_response.response_id, source_type="survey", question_id=question_id,
            answer_text="a", segment_start=0, segment_end=1,
            main_category="M", sub_category=sub_category,
        )

    db.session.add(make_row("leadership_and_dept", "leadership-row"))
    db.session.add(make_row("career_and_feedback", "career-row"))
    db.session.add(make_row("other", "other-row"))
    db.session.add(make_row(None, "null-row"))
    db.session.commit()

client = app.test_client()
AUTH = {"Authorization": f"Bearer {build_admin_token(admin_id)}"}


def sub_categories(resp):
    return {row["sub_category"] for row in resp.get_json()["classifications"]}


print("========== 既有行為：不可改壞 ==========")

resp_all = client.get("/api/admin/ai/classifications", headers=AUTH)
check("不傳 topic 時查全部（4 筆）", sub_categories(resp_all) == {"leadership-row", "career-row", "other-row", "null-row"})

resp_leadership = client.get("/api/admin/ai/classifications?topic=leadership_and_dept", headers=AUTH)
check("topic=leadership_and_dept 只查到該 topic 的資料", sub_categories(resp_leadership) == {"leadership-row"})

resp_career = client.get("/api/admin/ai/classifications?topic=career_and_feedback", headers=AUTH)
check("topic=career_and_feedback 只查到該 topic 的資料", sub_categories(resp_career) == {"career-row"})


print("\n========== 新行為：topic=__unassigned__ ==========")

resp_unassigned = client.get("/api/admin/ai/classifications?topic=__unassigned__", headers=AUTH)
check(
    "topic=__unassigned__ 查到 question_id=NULL 與 question_id='other' 兩筆，且僅這兩筆",
    sub_categories(resp_unassigned) == {"other-row", "null-row"},
)

resp_unassigned_set = sub_categories(resp_unassigned)
check(
    "topic=__unassigned__ 不會漏出已歸屬到真正 topic 的資料",
    "leadership-row" not in resp_unassigned_set and "career-row" not in resp_unassigned_set,
)


print("\n========== review_status 與 topic 可同時篩選（既有行為）==========")

resp_combo = client.get("/api/admin/ai/classifications?topic=__unassigned__&review_status=pending_review", headers=AUTH)
check("HTTP 200（組合篩選正常運作）", resp_combo.status_code == 200)
check("組合篩選只回傳符合兩個條件的資料", sub_categories(resp_combo) == {"other-row", "null-row"})

resp_bad_status = client.get("/api/admin/ai/classifications?review_status=not_a_real_status", headers=AUTH)
check("不合法 review_status 仍然回 400（既有行為）", resp_bad_status.status_code == 400)


print("\n========== Admin auth 保護（既有行為）==========")

resp_no_auth = client.get("/api/admin/ai/classifications")
check("沒帶 token 時回 401", resp_no_auth.status_code == 401)


print("\n========== 新增：GET /topics/<topic_key>/taxonomy 列出全部版本（含 archived）==========")

with app.app_context():
    db.session.add(m.Topic(topic_key="topic_versions", title="版本列表測試"))
    for i, status in enumerate(["archived", "archived", "published"], start=1):
        v = m.Taxonomy_Version(topic_key="topic_versions", version_number=i, status=status, source="manual")
        db.session.add(v)
    db.session.commit()

resp_versions = client.get("/api/admin/ai/topics/topic_versions/taxonomy", headers=AUTH)
check("HTTP 200", resp_versions.status_code == 200)
versions_body = resp_versions.get_json()["versions"]
check("回傳全部 3 筆版本（含 2 筆 archived）", len(versions_body) == 3)
check("依 version_number 排序（新到舊）", [v["version_number"] for v in versions_body] == [3, 2, 1])
check("archived 版本有被列出", sum(1 for v in versions_body if v["status"] == "archived") == 2)

resp_versions_no_auth = client.get("/api/admin/ai/topics/topic_versions/taxonomy")
check("沒帶 token 時回 401", resp_versions_no_auth.status_code == 401)


print("\n" + "=" * 50)
if FAILED:
    print(f"共 {len(FAILED)} 項測試失敗：")
    for f in FAILED:
        print("  -", f)
    sys.exit(1)
else:
    print("全部測試通過！")
