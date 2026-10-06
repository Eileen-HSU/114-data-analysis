"""
後台「系統紀錄」頁（手冊 4.3）用的查詢：系統狀態總覽、操作紀錄（稽核紀錄）查詢。
錯誤紀錄見 services/error_log_service.py。全部只讀。
"""

import os
from datetime import datetime, time, timedelta

from sqlalchemy import text

from extensions import db, taiwan_now

SYSTEM_LABEL = "系統"


class MonitorError(Exception):
    def __init__(self, code, message, http_status=400):
        super().__init__(message)
        self.code, self.message, self.http_status = code, message, http_status


def _configured(*names) -> bool:
    return all(os.environ.get(n, "").strip() for n in names)


def build_status() -> dict:
    """系統各部分目前是否正常。只回報「有沒有設定」，不會回傳任何 key 或密碼的值。"""
    from routes.workspaces.trash import scheduler_running
    from services import bulk_retry_service, error_log_service
    from services.second_opinion_service import second_opinion_model
    from services.system_health_service import taxonomy_bootstrap_health

    try:
        db.session.execute(text("SELECT 1"))
        database = {"ok": True}
    except Exception:  # noqa: BLE001
        db.session.rollback()
        database = {"ok": False}

    return {
        "checked_at": taiwan_now().isoformat(),
        "database": database,
        "ai": {
            "user_key_configured": _configured("GEMINI_API_KEY") or _configured("GOOGLE_API_KEY"),
            "admin_key_configured": _configured("ADMIN_GEMINI_API_KEY"),
            "second_opinion_model": second_opinion_model(),
        },
        "mail": {"configured": _configured("BREVO_API_KEY", "BREVO_FROM_EMAIL")},
        "scheduler": {"running": scheduler_running()},
        "background_jobs": {
            kind: bulk_retry_service.status(kind=kind)["job"] for kind in bulk_retry_service.KINDS
        },
        "errors": error_log_service.summary(),
        "taxonomy_bootstrap": taxonomy_bootstrap_health(),
    }


def _parse_date(value, end_of_day=False):
    if not value:
        return None
    try:
        day = datetime.strptime(value.strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        raise MonitorError("INVALID_DATE", "日期格式要是 YYYY-MM-DD", 400)
    moment = datetime.combine(day, time.min)
    return moment + timedelta(days=1) if end_of_day else moment


def list_audit_logs(action=None, admin_id=None, entity_type=None, entity_id=None,
                    date_from=None, date_to=None, page=1, page_size=50) -> dict:
    """操作紀錄總覽：可依動作、人員、對象、日期篩選。date_to 包含當天。"""
    from audit import Admin_Audit_Log
    from models import Admin

    query = Admin_Audit_Log.query
    if action:
        query = query.filter(Admin_Audit_Log.action == action)
    if admin_id == "system":
        query = query.filter(db.or_(Admin_Audit_Log.admin_id.is_(None), Admin_Audit_Log.admin_id == 0))
    elif admin_id not in (None, ""):
        try:
            query = query.filter(Admin_Audit_Log.admin_id == int(admin_id))
        except ValueError:
            raise MonitorError("INVALID_ADMIN", "admin_id 要是數字或 system", 400)
    if entity_type:
        query = query.filter(Admin_Audit_Log.entity_type == entity_type)
    if entity_id:
        query = query.filter(Admin_Audit_Log.entity_id == str(entity_id))
    start, end = _parse_date(date_from), _parse_date(date_to, end_of_day=True)
    if start:
        query = query.filter(Admin_Audit_Log.created_at >= start)
    if end:
        query = query.filter(Admin_Audit_Log.created_at < end)

    total = query.count()
    rows = (query.order_by(Admin_Audit_Log.created_at.desc(), Admin_Audit_Log.audit_id.desc())
            .offset((page - 1) * page_size).limit(page_size).all())
    admins = {a.admin_id: a for a in Admin.query.all()}

    def who(admin_id_value):
        if admin_id_value in (None, 0):
            return SYSTEM_LABEL
        admin = admins.get(admin_id_value)
        return admin.admin_name if admin else f"已刪除的管理員 #{admin_id_value}"

    items = []
    for row in rows:
        item = row.to_dict()
        item["admin_name"] = who(row.admin_id)
        items.append(item)
    actions = [a for (a,) in db.session.query(Admin_Audit_Log.action).distinct().order_by(Admin_Audit_Log.action).all()]
    return {
        "items": items, "total": total, "page": page, "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
        "actions": actions,
        "admins": [{"admin_id": a.admin_id, "admin_name": a.admin_name} for a in admins.values()],
    }
