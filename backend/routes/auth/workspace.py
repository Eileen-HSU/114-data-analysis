from datetime import timedelta

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from apscheduler.schedulers.background import BackgroundScheduler

from extensions import db
from models import Workspace, taiwan_now

workspace_bp = Blueprint("workspace", __name__)

SOFT_DELETE_DAYS = 30


def workspace_to_dict(w):
    days_left = None
    if w.deleted_at:
        days_left = max(0, SOFT_DELETE_DAYS - (taiwan_now() - w.deleted_at).days)

    return {
        "project_id":   w.project_id,
        "user_id":      w.user_id,
        "project_name": w.project_name,
        "folder_name":  w.folder_name,
        "search_tag":   w.search_tag,
        "status":       w.status,
        "created_at":   w.created_at.isoformat() if w.created_at else None,
        "is_deleted":   w.is_deleted,
        "deleted_at":   w.deleted_at.isoformat() if w.deleted_at else None,
        "days_left":    days_left,
    }


@workspace_bp.route("/api/workspace", methods=["POST"])
@jwt_required()  
def create_workspace():
    current_user_id = get_jwt_identity()
    data = request.get_json(silent=True) or {}
    project_name = data.get("project_name")

    if not project_name:
        return jsonify({"error": "請提供 project_name"}), 400

    workspace = Workspace(
        user_id      = current_user_id,
        project_name = project_name,
        folder_name  = data.get("folder_name"),
        search_tag   = data.get("search_tag"),
        status       = data.get("status", "Pending"),
    )

    try:
        db.session.add(workspace)
        db.session.commit()
        return jsonify(workspace_to_dict(workspace)), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@workspace_bp.route("/api/workspace/user", methods=["GET"])
@jwt_required()  
def get_workspaces():
    current_user_id = get_jwt_identity()
    workspaces = Workspace.query.filter_by(
        user_id    = current_user_id,
        is_deleted = False,
    ).order_by(Workspace.created_at.desc()).all()

    return jsonify([workspace_to_dict(w) for w in workspaces]), 200


@workspace_bp.route("/api/workspace/user/trash", methods=["GET"])
@jwt_required()  
def get_trash():
    current_user_id = get_jwt_identity()
    workspaces = Workspace.query.filter_by(
        user_id    = current_user_id,
        is_deleted = True,
    ).order_by(Workspace.deleted_at.desc()).all()

    return jsonify([workspace_to_dict(w) for w in workspaces]), 200


@workspace_bp.route("/api/workspace/<int:project_id>", methods=["GET"])
@jwt_required()  
def get_workspace(project_id):
    current_user_id = get_jwt_identity()
    workspace = Workspace.query.filter_by(
        project_id = project_id,
        user_id    = current_user_id,
        is_deleted = False,
    ).first()

    if not workspace:
        return jsonify({"error": "找不到專案"}), 404

    return jsonify(workspace_to_dict(workspace)), 200


@workspace_bp.route("/api/workspace/<int:project_id>", methods=["PUT"])
@jwt_required()  
def update_workspace(project_id):
    current_user_id = get_jwt_identity()
    workspace = Workspace.query.filter_by(
        project_id = project_id,
        user_id    = current_user_id,
        is_deleted = False,
    ).first()

    if not workspace:
        return jsonify({"error": "找不到專案"}), 404

    data = request.get_json(silent=True) or {}

    if "folder_name" in data:
        workspace.folder_name = data["folder_name"]
    if "project_name" in data:
        workspace.project_name = data["project_name"]
    if "search_tag" in data:
        workspace.search_tag = data["search_tag"]
    if "status" in data:
        workspace.status = data["status"]

    try:
        db.session.commit()
        return jsonify(workspace_to_dict(workspace)), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@workspace_bp.route("/api/workspace/<project_id>", methods=["DELETE"])
@jwt_required()  
def delete_workspace(project_id):
    try:
        workspace = None
        if str(project_id).isdigit():
            workspace = Workspace.query.get(int(project_id))

        if workspace:
            workspace.is_deleted = True
            workspace.deleted_at = taiwan_now()
            db.session.commit()
            return jsonify({"message": "專案已移至垃圾桶（實體更新成功）"}), 200
        else:
            return jsonify({"message": "專案已移至垃圾桶（模擬更新成功）"}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@workspace_bp.route("/api/workspace/<int:project_id>/restore", methods=["POST"])
@jwt_required()
def restore_workspace(project_id):
    current_user_id = get_jwt_identity()
    workspace = Workspace.query.filter_by(
        project_id = project_id,
        user_id    = current_user_id,
        is_deleted = True,
    ).first()

    if not workspace:
        return jsonify({"error": "找不到已刪除的專案"}), 404

    try:
        workspace.is_deleted = False
        workspace.deleted_at = None
        db.session.commit()
        return jsonify({"message": "專案已還原"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@workspace_bp.route("/api/workspace/<int:project_id>/permanent", methods=["DELETE"])
@jwt_required()  
def permanent_delete_workspace(project_id):
    current_user_id = get_jwt_identity()
    workspace = Workspace.query.filter_by(
        project_id = project_id,
        user_id    = current_user_id,
        is_deleted = True,
    ).first()

    if not workspace:
        return jsonify({"error": "找不到已刪除的專案"}), 404

    try:
        db.session.delete(workspace)
        db.session.commit()
        return jsonify({"message": "專案已永久刪除"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


def hard_delete_expired_workspaces(app):
    with app.app_context():
        try:
            expiry = taiwan_now() - timedelta(days=SOFT_DELETE_DAYS)
            expired = Workspace.query.filter(
                Workspace.is_deleted == True,
                Workspace.deleted_at <= expiry,
            ).all()

            if not expired:
                return

            for w in expired:
                db.session.delete(w)

            db.session.commit()
            print(f"[Scheduler] 永久刪除 {len(expired)} 個過期專案")
        except Exception as e:
            db.session.rollback()
            print(f"[Scheduler] 永久刪除失敗：{e}")


def start_scheduler(app):
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        hard_delete_expired_workspaces,
        trigger = "interval",
        hours   = 24,
        args    = [app],
        id      = "hard_delete_workspaces",
    )
    scheduler.start()
    print("[Scheduler] 自動永久刪除排程已啟動")