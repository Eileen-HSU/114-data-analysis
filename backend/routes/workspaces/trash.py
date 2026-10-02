import os
from datetime import timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from flask import Blueprint, jsonify, request

from extensions import db
from models import Chat_History, Workspace, taiwan_now
from routes.workspaces.workspace import SOFT_DELETE_DAYS, authorize_request, workspace_to_dict

trash_bp = Blueprint("trash", __name__)


@trash_bp.route("/api/workspace/user/trash", methods=["GET"])
def get_trash():
    current_user_id, auth_error = authorize_request()
    if auth_error:
        return auth_error
    workspaces = Workspace.query.filter_by(
        user_id    = current_user_id,
        is_deleted = True,
    ).order_by(Workspace.deleted_at.desc()).all()

    return jsonify([workspace_to_dict(w) for w in workspaces]), 200


@trash_bp.route("/api/workspace/<int:project_id>/restore", methods=["POST"])
def restore_workspace(project_id):
    current_user_id, auth_error = authorize_request()
    if auth_error:
        return auth_error

    workspace = Workspace.query.filter_by(
        project_id = project_id,
        user_id    = current_user_id,
        is_deleted = True,
    ).first()

    if not workspace:
        return jsonify({"error": "找不到已刪除的專案"}), 404

    data = request.get_json(silent=True) or {}

    try:
        workspace.is_deleted  = False
        workspace.deleted_at  = None
        workspace.folder_name = data.get("folder_name")
        db.session.commit()
        return jsonify({"message": "專案已還原"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@trash_bp.route("/api/workspace/<int:project_id>/permanent", methods=["DELETE"])
def permanent_delete_workspace(project_id):
    current_user_id, auth_error = authorize_request()
    if auth_error:
        return auth_error

    target = Workspace.query.filter_by(
        project_id = project_id,
        user_id    = current_user_id,
    ).first()

    if not target:
        return jsonify({"error": "找不到該項目"}), 404

    try:
        is_folder_request = request.args.get("is_folder", "false").lower() == "true"

        if is_folder_request and target.folder_name:
            Workspace.query.filter_by(
                user_id     = current_user_id,
                folder_name = target.folder_name,
                is_deleted  = True,
            ).update({"folder_name": None}, synchronize_session=False)
            db.session.commit()
            return jsonify({"message": "資料夾外殼已永久刪除，專案已釋放"}), 200

        else:
            Chat_History.query.filter_by(project_id=project_id).delete(synchronize_session=False)
            db.session.delete(target)
            db.session.commit()
            return jsonify({"message": "專案已永久刪除"}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

def hard_delete_expired_workspaces(app):
    with app.app_context():
        try:
            expiry = taiwan_now() - timedelta(days=SOFT_DELETE_DAYS)
            deleted_count = Workspace.query.filter(
                Workspace.is_deleted == True,
                Workspace.deleted_at != None,
                Workspace.deleted_at <= expiry,
            ).delete(synchronize_session=False)

            if deleted_count:
                db.session.commit()
                print(f"[Scheduler] 永久刪除 {deleted_count} 個過期專案")
        except Exception as e:
            db.session.rollback()
            print(f"[Scheduler] 永久刪除失敗：{e}")


_scheduler = None


def scheduler_running() -> bool:
    """這個 process 的排程有沒有在跑（後台系統狀態用）。"""
    return _scheduler is not None and _scheduler.running


def _purge_error_logs(app):
    from services.error_log_service import purge_old

    with app.app_context():
        purge_old()


def start_scheduler(app):
    global _scheduler
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        hard_delete_expired_workspaces,
        trigger = "interval",
        hours   = 24,
        args    = [app],
        id      = "hard_delete_workspaces",
    )
    # AI 第二意見：每 10 分鐘檢查有沒有低信心、需要再確認的結果（見 services/second_opinion_service.py）
    from services.bulk_retry_service import scheduled_second_opinion

    scheduler.add_job(
        scheduled_second_opinion,
        trigger="interval",
        minutes=10,
        args=[app],
        id="second_opinion",
        max_instances=1,
        coalesce=True,
    )
    # 系統錯誤紀錄保留期限：已處理 90 天、未處理 180 天（見 services/error_log_service.py）
    scheduler.add_job(_purge_error_logs, trigger="interval", hours=24, args=[app], id="purge_error_logs")
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not app.debug:
        scheduler.start()
        _scheduler = scheduler
        print("[Scheduler] 自動永久刪除排程已啟動")
