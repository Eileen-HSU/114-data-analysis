"""Admin 操作稽核紀錄的唯一寫入入口（見 audit.py）。只 add，不 commit。"""

from extensions import db
from audit import Admin_Audit_Log

# action 常數：前後端、測試共用同一組字串，避免拼字不一致。
ACTION_QUICK_CONFIRM = "quick_confirm"
ACTION_BATCH_CONFIRM = "batch_confirm"
ACTION_MODIFY = "modify"
ACTION_EXCLUDE = "exclude"
ACTION_BULK_EXCLUDE = "bulk_exclude"
ACTION_REOPEN = "reopen"
ACTION_ASSIGN_TOPIC = "assign_topic"
ACTION_REROUTE = "reroute"
ACTION_RECLASSIFY = "reclassify"
ACTION_RETRY_FAILED = "retry_failed"
ACTION_TAXONOMY_PUBLISH = "taxonomy_publish"
ACTION_REPORT_REGENERATE = "report_regenerate"
ACTION_TAXONOMY_BOOTSTRAP = "taxonomy_bootstrap"

ENTITY_CLASSIFICATION = "classification"
ENTITY_UPLOADED_ANSWER = "uploaded_answer"
ENTITY_TAXONOMY_VERSION = "taxonomy_version"
ENTITY_REPORT = "report"


def classification_state(row) -> dict:
    """稽核用的 Response_Classification 狀態快照。"""
    return {
        "review_status": row.review_status,
        "status": row.status,
        "main_category": row.main_category,
        "sub_category": row.sub_category,
        "final_main_category": row.final_main_category,
        "final_sub_category": row.final_sub_category,
        "final_secondary_main_category": row.final_secondary_main_category,
        "final_secondary_sub_category": row.final_secondary_sub_category,
    }


def record(action, entity_type, entity_id, admin_id, before=None, after=None, reason=None, batch_id=None):
    entry = Admin_Audit_Log(
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        admin_id=admin_id,
        before_state=before,
        after_state=after,
        reason=reason,
        batch_id=batch_id,
    )
    db.session.add(entry)
    return entry


def list_for_entity(entity_type, entity_id):
    return (
        Admin_Audit_Log.query
        .filter_by(entity_type=entity_type, entity_id=str(entity_id))
        .order_by(Admin_Audit_Log.created_at.asc(), Admin_Audit_Log.audit_id.asc())
        .all()
    )
