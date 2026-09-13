"""Internal AI administration API.

All endpoints are deliberately read-only or candidate-only until a Golden Test
run marks the candidate as publishable.  Production classifications are never
changed by this blueprint.
"""

from flask import Blueprint, jsonify, request

from extensions import db
from models import Prompt_Template, User
from response_classification import Response_Classification, ALLOWED_REVIEW_STATUSES
from routes.surveys.survey import verify_token
from services.classify_v2 import _run_classification
from services.golden_test_set import GOLDEN_TEST_SET
from services.prompt_admin_service import update_draft, test_draft_prompt, publish_prompt
from services.subcategory_methodology import SUBCATEGORY_METHODOLOGY


ai_admin_bp = Blueprint("ai_admin", __name__, url_prefix="/api/admin/ai")


def _admin_or_error():
    user_id, error = verify_token(request)
    if error:
        return None, (jsonify({"error": error}), 401)
    user = User.query.get(user_id)
    if not user or user.role != "admin":
        return None, (jsonify({"error": "Admin access required"}), 403)
    return user, None


def _topic(row):
    return {
        "prompt_key": row.prompt_key,
        "production_status": "published" if row.live_content else "not_published",
        "candidate_status": "validated" if row.draft_validated else "needs_validation",
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@ai_admin_bp.get("/topics")
def list_topics():
    _, failure = _admin_or_error()
    if failure:
        return failure
    rows = Prompt_Template.query.order_by(Prompt_Template.prompt_key).all()
    return jsonify({"topics": [_topic(row) for row in rows]})


@ai_admin_bp.route("/topics/<prompt_key>", methods=["GET", "PUT"])
def candidate(prompt_key):
    _, failure = _admin_or_error()
    if failure:
        return failure
    row = Prompt_Template.query.get(prompt_key)
    if not row:
        return jsonify({"error": "Classification topic not found"}), 404
    if request.method == "GET":
        return jsonify(row.to_dict())

    payload = request.get_json(silent=True) or {}
    content = payload.get("draft_content")
    if not isinstance(content, str) or not content.strip():
        return jsonify({"error": "draft_content is required"}), 400
    # update_draft invalidates a previous validation result by design.
    return jsonify(update_draft(prompt_key, content))


@ai_admin_bp.post("/topics/<prompt_key>/sandbox")
def sandbox(prompt_key):
    _, failure = _admin_or_error()
    if failure:
        return failure
    row = Prompt_Template.query.get(prompt_key)
    if not row:
        return jsonify({"error": "Classification topic not found"}), 404
    payload = request.get_json(silent=True) or {}
    answer_text = (payload.get("answer_text") or "").strip()
    if not answer_text:
        return jsonify({"error": "answer_text is required"}), 400
    # _run_classification only calls the model; it never persists a production row.
    result = _run_classification(answer_text, row.draft_content, prompt_key)
    return jsonify({"result": result})


@ai_admin_bp.post("/topics/<prompt_key>/validate")
def validate_candidate(prompt_key):
    _, failure = _admin_or_error()
    if failure:
        return failure
    try:
        return jsonify(test_draft_prompt(prompt_key))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@ai_admin_bp.post("/topics/<prompt_key>/publish")
def publish_candidate(prompt_key):
    _, failure = _admin_or_error()
    if failure:
        return failure
    try:
        return jsonify(publish_prompt(prompt_key))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 409


@ai_admin_bp.get("/classifications")
def reviewed_classifications():
    _, failure = _admin_or_error()
    if failure:
        return failure
    review_status = request.args.get("review_status")
    topic = request.args.get("topic")
    query = Response_Classification.query
    if review_status:
        if review_status not in ALLOWED_REVIEW_STATUSES:
            return jsonify({"error": "Invalid review_status"}), 400
        query = query.filter_by(review_status=review_status)
    if topic:
        query = query.filter_by(question_id=topic)
    rows = query.order_by(Response_Classification.created_at.desc()).limit(200).all()
    results = []
    for row in rows:
        item = row.to_dict()
        item["segment"] = row.answer_text[row.segment_start:row.segment_end]
        item["effective_result"] = {
            "main_category": row.final_main_category if row.review_status == "modified" else row.main_category,
            "sub_category": row.final_sub_category if row.review_status == "modified" else row.sub_category,
            "secondary_category": row.final_secondary_sub_category if row.review_status == "modified" else row.secondary_sub_category,
            "reasoning": row.final_reasoning if row.review_status == "modified" else row.reasoning,
        }
        results.append(item)
    return jsonify({"classifications": results})


@ai_admin_bp.get("/taxonomy")
def taxonomy():
    _, failure = _admin_or_error()
    if failure:
        return failure
    topics = []
    for key, subcategories in SUBCATEGORY_METHODOLOGY.items():
        items = [
            {"sub_category": sub, **metadata}
            for sub, metadata in subcategories.items()
        ]
        topics.append({"prompt_key": key, "subcategories": items})
    return jsonify({"topics": topics})


@ai_admin_bp.get("/golden-tests")
def golden_tests():
    _, failure = _admin_or_error()
    if failure:
        return failure
    cases = []
    for prompt_key, items in GOLDEN_TEST_SET.items():
        cases.extend({"prompt_key": prompt_key, **item} for item in items)
    return jsonify({"cases": cases})
