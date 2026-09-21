#!/usr/bin/env python
"""
測試腳本：驗證刪除 Taxonomy 草稿版本
（services.taxonomy_service.delete_taxonomy_version() +
DELETE /api/admin/ai/topics/<topic_key>/taxonomy/<version_id>）。

涵蓋：
    1. draft 成功刪除
    2. 刪除後底下的 Taxonomy_Category 全部消失（cascade）
    3. Topic 本身保留
    4. published -> 409
    5. archived -> 409
    6. in_review -> 409（比既有 _require_editable_version 更嚴格）
    7. version 不屬於該 topic -> 404
    8. version 不存在 -> 404
    9. 有 Response_Classification 引用 -> 409，且該筆分類紀錄不受影響
    10. 刪除某 version 不影響同一 topic 其他 version（含 published）
    11. Admin auth 保護

執行方式：
    cd backend
    export JWT_SECRET_KEY=test-secret
    python3 tests/test_taxonomy_delete_draft.py
"""

import sys
import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

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
        m.Taxonomy_Category.__table__,
        m.Survey_Template.__table__,
        m.Survey_Response.__table__,
        m.Response_Classification.__table__,
    ]
    db.metadata.create_all(bind=db.engine, tables=tables)
    admin = m.Admin(admin_name="tester", email="admin@example.com", password_hash="x")
    db.session.add(admin)
    db.session.commit()
    admin_id = admin.admin_id

client = app.test_client()
AUTH = {"Authorization": f"Bearer {build_admin_token(admin_id)}"}


def delete_version(topic_key, version_id, auth=True):
    return client.delete(f"/api/admin/ai/topics/{topic_key}/taxonomy/{version_id}", headers=AUTH if auth else {})


def make_version(topic_key, status, version_number, with_category=True):
    v = m.Taxonomy_Version(topic_key=topic_key, version_number=version_number, status=status, source="manual")
    db.session.add(v)
    db.session.flush()
    if with_category:
        db.session.add(m.Taxonomy_Category(version_id=v.version_id, main_category="M", sub_category=f"S{version_number}", sort_order=1, definition="d"))
    db.session.commit()
    return v.version_id


with app.app_context():
    db.session.add(m.Topic(topic_key="topic_delete_test", title="刪除測試主題"))
    db.session.commit()
    draft_id = make_version("topic_delete_test", "draft", 1)
    published_id = make_version("topic_delete_test", "published", 2)
    archived_id = make_version("topic_delete_test", "archived", 3)
    in_review_id = make_version("topic_delete_test", "in_review", 4)

    db.session.add(m.Topic(topic_key="topic_other_owner", title="另一個主題"))
    other_topic_draft_id = make_version("topic_other_owner", "draft", 1)

    referenced_draft_id = make_version("topic_delete_test", "draft", 5)
    template = m.Survey_Template(title="t", access_code="ABCDE", question_json={"items": []})
    db.session.add(template)
    db.session.commit()
    survey_response = m.Survey_Response(template_id=template.template_id, answer_json={"answers": {}})
    db.session.add(survey_response)
    db.session.commit()
    rc = m.Response_Classification(
        response_id=survey_response.response_id, source_type="survey", question_id="q1",
        answer_text="a", segment_start=0, segment_end=1,
        main_category="M", sub_category="S", taxonomy_version_id=referenced_draft_id,
    )
    db.session.add(rc)
    db.session.commit()
    rc_id = rc.classification_id


print("========== 測試 11：Admin auth 保護 ==========")

resp = delete_version("topic_delete_test", draft_id, auth=False)
check("沒帶 token 時回 401", resp.status_code == 401)


print("\n========== 測試 4/5/6：非 draft 狀態一律 409 ==========")

resp_pub = delete_version("topic_delete_test", published_id)
check("published -> 409", resp_pub.status_code == 409)

resp_arch = delete_version("topic_delete_test", archived_id)
check("archived -> 409", resp_arch.status_code == 409)

resp_review = delete_version("topic_delete_test", in_review_id)
check("in_review -> 409（比既有 editable 規則更嚴格）", resp_review.status_code == 409)

with app.app_context():
    check("published 版本沒有被刪除", m.Taxonomy_Version.query.get(published_id) is not None)
    check("archived 版本沒有被刪除", m.Taxonomy_Version.query.get(archived_id) is not None)
    check("in_review 版本沒有被刪除", m.Taxonomy_Version.query.get(in_review_id) is not None)


print("\n========== 測試 7/8：找不到 -> 404 ==========")

resp_not_exist = delete_version("topic_delete_test", 999999)
check("version_id 不存在 -> 404", resp_not_exist.status_code == 404)

resp_wrong_owner = delete_version("topic_delete_test", other_topic_draft_id)
check("version 屬於別的 topic -> 404（不可跨 topic 刪除）", resp_wrong_owner.status_code == 404)

with app.app_context():
    check("跨 topic 誤刪保護：other_topic_draft 沒被刪掉", m.Taxonomy_Version.query.get(other_topic_draft_id) is not None)


print("\n========== 測試 9：有 Response_Classification 引用 -> 409 ==========")

resp_referenced = delete_version("topic_delete_test", referenced_draft_id)
check("有引用的 draft -> 409", resp_referenced.status_code == 409)

with app.app_context():
    check("被引用的 draft 版本沒有被刪除", m.Taxonomy_Version.query.get(referenced_draft_id) is not None)
    rc_after = m.Response_Classification.query.get(rc_id)
    check("該筆 Response_Classification 完全不受影響", rc_after is not None and rc_after.taxonomy_version_id == referenced_draft_id)


print("\n========== 測試 1/2/3/10：draft 成功刪除，cascade，Topic 與其他版本不受影響 ==========")

with app.app_context():
    category_ids_before = [c.category_id for c in m.Taxonomy_Category.query.filter_by(version_id=draft_id).all()]
    check("刪除前確認有 category 存在", len(category_ids_before) == 1)

resp_delete_ok = delete_version("topic_delete_test", draft_id)
check("draft 成功刪除，回 200", resp_delete_ok.status_code == 200)
check("回應內容為 {deleted: true}", resp_delete_ok.get_json() == {"deleted": True})

with app.app_context():
    check("該 Taxonomy_Version 已被刪除", m.Taxonomy_Version.query.get(draft_id) is None)
    check("底下的 Taxonomy_Category 全部被 cascade 刪除", m.Taxonomy_Category.query.filter_by(version_id=draft_id).count() == 0)
    check("Topic 本身保留", m.Topic.query.get("topic_delete_test") is not None)
    check("同一 topic 的 published 版本不受影響", m.Taxonomy_Version.query.get(published_id).status == "published")
    check("同一 topic 的 archived 版本不受影響", m.Taxonomy_Version.query.get(archived_id).status == "archived")
    check("同一 topic 的 in_review 版本不受影響", m.Taxonomy_Version.query.get(in_review_id).status == "in_review")
    check("同一 topic 的 published 版本的 category 不受影響", m.Taxonomy_Category.query.filter_by(version_id=published_id).count() == 1)
    check("version_number 沒有 renumber（published 仍是 2）", m.Taxonomy_Version.query.get(published_id).version_number == 2)


print("\n" + "=" * 50)
if FAILED:
    print(f"共 {len(FAILED)} 項測試失敗：")
    for f in FAILED:
        print("  -", f)
    sys.exit(1)
else:
    print("全部測試通過！")
