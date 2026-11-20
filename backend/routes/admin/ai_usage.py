"""
Admin「AI 用量與成本」API。全部需要 Admin token（account_type == "admin"）。

    GET /api/admin/ai/usage/summary[?month=YYYY-MM]  整頁資料（用量、平均成本、配額監控）
    GET /api/admin/ai/usage/settings                 各模型單價／配額、匯率
    PUT /api/admin/ai/usage/settings                 更新單價／配額、匯率（寫入操作紀錄）

回應只有數字，不含任何 prompt、回答內容或使用者 email。
"""

import logging

from flask import Blueprint, jsonify, request

from extensions import db
from models import Admin
from routes.auth.admin_guard import verify_admin_token
from services import ai_usage_report_service as report

logger = logging.getLogger(__name__)

ai_usage_bp = Blueprint("ai_usage", __name__, url_prefix="/api/admin/ai/usage")

_TOKEN_ERROR_STATUS = {"Unauthorized": 401, "Token expired": 401, "Invalid token": 401}
MAX_SETTINGS_BYTES = 64 * 1024


def _admin_or_error():
    admin_id, error = verify_admin_token(request)
    if error:
        return None, (jsonify({"error": error}), _TOKEN_ERROR_STATUS.get(error, 403))
    admin = db.session.get(Admin, admin_id)
    if not admin:
        return None, (jsonify({"error": "Admin access required"}), 403)
    return admin, None


@ai_usage_bp.route("/summary", methods=["GET"])
def usage_summary():
    admin, error = _admin_or_error()
    if error:
        return error
    try:
        return jsonify(report.build_summary(month=request.args.get("month") or None))
    except report.SettingsError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:  # noqa: BLE001
        logger.exception("AI usage summary failed")
        return jsonify({"error": "無法取得 AI 用量資料，請稍後再試"}), 500


@ai_usage_bp.route("/settings", methods=["GET"])
def usage_settings():
    admin, error = _admin_or_error()
    if error:
        return error
    return jsonify(report.get_settings())


@ai_usage_bp.route("/settings", methods=["PUT"])
def update_usage_settings():
    admin, error = _admin_or_error()
    if error:
        return error
    if (request.content_length or 0) > MAX_SETTINGS_BYTES:
        return jsonify({"error": "資料太大"}), 413
    payload = request.get_json(silent=True)
    try:
        changed = report.update_settings(payload, admin.admin_id)
        db.session.commit()
    except report.SettingsError as exc:
        db.session.rollback()
        return jsonify({"error": str(exc)}), 400
    except Exception:  # noqa: BLE001
        db.session.rollback()
        logger.exception("AI usage settings update failed")
        return jsonify({"error": "儲存失敗，請稍後再試"}), 500
    return jsonify({"changed": changed, **report.get_settings()})
