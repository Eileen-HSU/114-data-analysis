#!/usr/bin/env python3
import json
import os
import sys

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flask import Flask
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.ext.compiler import compiles

import models as m
from extensions import db
from routes.auth.admin_guard import build_admin_token
from routes.classifications.review import review_bp
from services.aggregation_service import build_aggregation
from services.effective_classification_service import get_effective_classification
from services.report_service import get_readiness
import services.gemini_client as gemini_client


@compiles(MEDIUMTEXT, "sqlite")
def _compile_mediumtext_sqlite(element, compiler, **kwargs):
    return "TEXT"


class _FakeResponse:
    def __init__(self, payload):
        self.text = json.dumps(payload, ensure_ascii=False)


class _FakeModel:
    response = None

    def __init__(self, **kwargs):
        pass

    def generate_content(self, *args, **kwargs):
        return _FakeResponse(self.response)


gemini_client.GenerativeModel = _FakeModel

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
app.config["TESTING"] = True
app.register_blueprint(review_bp)
db.init_app(app)

with app.app_context():
    tables = [
        m.User.__table__,
        m.Admin.__table__,
        m.Survey_Template.__table__,
        m.Survey_Response.__table__,
        m.Response_Classification.__table__,
        m.Classification_Review.__table__,
        m.Classification_Review_Message.__table__,
        m.Report.__table__,
        m.Topic.__table__,
        m.Taxonomy_Version.__table__,
        m.Taxonomy_Category.__table__,
    ]
    db.metadata.create_all(bind=db.engine, tables=tables)

    db.session.add_all([
        m.User(user_id=1, user_name="owner", email="owner@example.com", password_hash="x"),
        m.Admin(admin_id=1, admin_name="Alice", email="alice@example.com", password_hash="x"),
        m.Admin(admin_id=2, admin_name="Bob", email="bob@example.com", password_hash="x"),
    ])
    topic = m.Topic(topic_key="custom_topic", title="Custom Topic")
    version = m.Taxonomy_Version(
        topic_key="custom_topic", version_number=1, status="published", source="manual",
    )
    db.session.add_all([topic, version])
    db.session.flush()
    categories = [
        ("Custom Main", "C1 Original", "Original method", "Original citation"),
        ("Custom Main", "C2 Candidate", "Candidate method", "Candidate citation"),
    ]
    for index, (main, sub, methodology, citation) in enumerate(categories):
        db.session.add(m.Taxonomy_Category(
            version_id=version.version_id,
            main_category=main,
            sub_category=sub,
            methodology=methodology,
            citation=citation,
            sort_order=index,
        ))
    template = m.Survey_Template(
        title="Review test", access_code="REOPEN", user_id=1,
        question_json={"items": [{"id": "q1", "type": "short", "question_type": "custom_topic"}]},
    )
    db.session.add(template)
    db.session.flush()
    response = m.Survey_Response(template_id=template.template_id, answer_json={"answers": {"q1": "text"}})
    db.session.add(response)
    db.session.commit()
    template_id = template.template_id
    response_id = response.response_id
    version_id = version.version_id


def admin_header(admin_id):
    return {"Authorization": f"Bearer {build_admin_token(admin_id)}"}


def make_classification(*, status="completed", review_status="confirmed"):
    with app.app_context():
        row = m.Response_Classification(
            response_id=response_id,
            source_type="survey",
            question_id="q1",
            answer_text="text",
            segment_start=0,
            segment_end=4,
            main_category="Custom Main",
            sub_category="C1 Original",
            reasoning="original reasoning",
            methodology="Original method",
            citation="Original citation",
            final_main_category="Final Main",
            final_sub_category="Final Sub",
            final_reasoning="final reasoning",
            status=status,
            review_status=review_status,
            taxonomy_version_id=version_id,
        )
        db.session.add(row)
        db.session.commit()
        return row.classification_id


client = app.test_client()

# Reopen preserves history and values, and creates a new active session.
cid = make_classification()
with app.app_context():
    old = m.Classification_Review(classification_id=cid, admin_id=1, status="confirmed")
    db.session.add(old)
    db.session.flush()
    db.session.add(m.Classification_Review_Message(
        review_id=old.review_id, role="user", content="old question",
    ))
    db.session.add(m.Classification_Review_Message(
        review_id=old.review_id, role="assistant", content="old answer",
    ))
    db.session.add(m.Report(
        source_type="survey", template_id=template_id, version=1,
        generated_by=1, status="completed", is_outdated=False,
        eligible_count_at_generation=1, pending_count_at_generation=0,
        excluded_count_at_generation=0,
    ))
    db.session.commit()
    old_review_id = old.review_id
    original = m.Response_Classification.query.get(cid)
    original_values = (
        original.main_category, original.sub_category,
        original.final_main_category, original.final_sub_category,
    )

reopen = client.post(f"/api/classification/{cid}/review/reopen", headers=admin_header(1))
assert reopen.status_code == 200
new_review_id = reopen.get_json()["review_id"]
assert new_review_id != old_review_id
with app.app_context():
    row = m.Response_Classification.query.get(cid)
    assert row.review_status == "pending_review"
    assert (row.main_category, row.sub_category, row.final_main_category, row.final_sub_category) == original_values
    assert m.Classification_Review_Message.query.filter_by(review_id=old_review_id).count() == 2
    assert m.Report.query.first().is_outdated is True

# Another admin cannot reopen while the new session is active.
assert client.post(f"/api/classification/{cid}/review/reopen", headers=admin_header(2)).status_code == 409

# A new session with no messages may confirm original.
assert client.post(f"/api/classification/{cid}/review/confirm-original", headers=admin_header(1)).status_code == 200

# A new session with a message must use confirm-candidate, not confirm-original.
cid_chat = make_classification()
assert client.post(f"/api/classification/{cid_chat}/review/reopen", headers=admin_header(1)).status_code == 200
_FakeModel.response = {
    "reply": "candidate",
    "candidate_sub_category": "C2 Candidate",
    "candidate_secondary_sub_category": None,
    "candidate_reasoning": "candidate reasoning",
}
assert client.post(
    f"/api/classification/{cid_chat}/review/message",
    headers=admin_header(1),
    json={"message": "change"},
).status_code == 201
assert client.post(
    f"/api/classification/{cid_chat}/review/confirm-original",
    headers=admin_header(1),
).status_code == 409
assert client.post(
    f"/api/classification/{cid_chat}/review/confirm-candidate",
    headers=admin_header(1),
).status_code == 200

# Failed classifications are not confirmable or reportable.
cid_failed = make_classification(status="failed", review_status="pending_review")
assert client.post(
    f"/api/classification/{cid_failed}/review/confirm-original",
    headers=admin_header(1),
).status_code == 409
assert client.post(
    f"/api/classification/{cid_failed}/review/confirm-candidate",
    headers=admin_header(1),
).status_code == 409
with app.app_context():
    assert get_readiness("survey", template_id=template_id)["eligible"] == 2
    aggregation_items = [
        item
        for group in build_aggregation("survey", template_id=template_id)
        for item in group["items"]
    ]
    assert all(item["classification_id"] != cid_failed for item in aggregation_items)

# Dynamic candidate and effective methodology/citation use the same taxonomy version.
with app.app_context():
    _FakeModel.response = {
        "reply": "dynamic candidate",
        "candidate_sub_category": "C2 Candidate",
        "candidate_secondary_sub_category": None,
        "candidate_reasoning": "dynamic reasoning",
    }
    cid_dynamic = make_classification(review_status="pending_review")
    classification = m.Response_Classification.query.get(cid_dynamic)
    taxonomy_categories = [
        {
            "main_category": category.main_category,
            "sub_category": category.sub_category,
            "methodology": category.methodology,
            "citation": category.citation,
        }
        for category in m.Taxonomy_Version.query.get(version_id).categories
    ]

    from services.review_ai_service import build_review_reply
    result = build_review_reply(
        question_type="custom_topic",
        segment_text="text",
        ai_main_category=classification.main_category,
        ai_sub_category=classification.sub_category,
        ai_secondary_sub_category=None,
        ai_reasoning=classification.reasoning,
        candidate_sub_category=classification.sub_category,
        candidate_secondary_sub_category=None,
        conversation_history=[],
        user_message="change",
        taxonomy_categories=taxonomy_categories,
    )
    assert result["candidate_sub_category"] == "C2 Candidate"
    assert result["candidate_main_category"] == "Custom Main"

    classification.review_status = "modified"
    classification.final_main_category = "Custom Main"
    classification.final_sub_category = "C2 Candidate"
    effective = get_effective_classification(classification)
    assert effective["methodology"] == "Candidate method"
    assert effective["citation"] == "Candidate citation"

    legacy = make_classification(review_status="modified")
    legacy_row = m.Response_Classification.query.get(legacy)
    legacy_row.taxonomy_version_id = None
    assert get_effective_classification(legacy_row)["methodology"] is None

print("focused review/reopen/failed/dynamic tests: PASS")
