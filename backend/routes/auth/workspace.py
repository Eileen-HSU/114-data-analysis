from datetime import timedelta

from flask import Blueprint, jsonify, request
from apscheduler.schedulers.background import BackgroundScheduler

from extensions import db
from models import Workspace, taiwan_now

workspace_bp = Blueprint("workspace", __name__)

SOFT_DELETE_DAYS = 30  # 軟刪除後幾天永久刪除


# ── 工具函式 ────────────────────────────────────────────────

def workspace_to_dict(w):
    return {
        "project_id":   w.project_id,
        "user_id":      w.user_id,
        "project_name": w.project_name,
        "search_tag":   w.search_tag,
        "status":       w.status,
        "created_at":   w.created_at.isoformat() if w.created_at else None,
        "is_deleted":   w.is_deleted,
        "deleted_at":   w.deleted_at.isoformat() if w.deleted_at else None,
    }


# ── 路由 ────────────────────────────────────────────────────

@workspace_bp.route("/api/workspace", methods=["POST"])
def create_workspace():
    """建立新專案"""
    data = request.get_json(silent=True) or {}
    user_id      = data.get("user_id")
    project_name = data.get("project_name")

    if not user_id or not project_name:
        return jsonify({"error": "請提供 user_id 與 project_name"}), 400

    workspace = Workspace(
        user_id      = user_id,
        project_name = project_name,
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


@workspace_bp.route("/api/workspace/user/<int:user_id>", methods=["GET"])
def get_workspaces(user_id):
    """取得使用者所有未刪除的專案"""
    workspaces = Workspace.query.filter_by(
        user_id    = user_id,
        is_deleted = False,
    ).order_by(Workspace.created_at.desc()).all()

    return jsonify([workspace_to_dict(w) for w in workspaces]), 200


@workspace_bp.route("/api/workspace/<int:project_id>", methods=["GET"])
def get_workspace(project_id):
    """取得單一專案"""
    workspace = Workspace.query.filter_by(
        project_id = project_id,
        is_deleted = False,
    ).first()

    if not workspace:
        return jsonify({"error": "找不到專案"}), 404

    return jsonify(workspace_to_dict(workspace)), 200


@workspace_bp.route("/api/workspace/<int:project_id>", methods=["PUT"])
def update_workspace(project_id):
    """更新專案資料"""
    workspace = Workspace.query.filter_by(
        project_id = project_id,
        is_deleted = False,
    ).first()

    if not workspace:
        return jsonify({"error": "找不到專案"}), 404

    data = request.get_json(silent=True) or {}
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


@workspace_bp.route("/api/workspace/<int:project_id>", methods=["DELETE"])
def delete_workspace(project_id):
    """軟刪除專案（30 天後自動永久刪除）"""
    workspace = Workspace.query.filter_by(
        project_id = project_id,
        is_deleted = False,
    ).first()

    if not workspace:
        return jsonify({"error": "找不到專案"}), 404

    try:
        workspace.is_deleted = True
        workspace.deleted_at = taiwan_now()
        db.session.commit()
        return jsonify({"message": "專案已移至垃圾桶，30 天後將永久刪除"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@workspace_bp.route("/api/workspace/<int:project_id>/restore", methods=["POST"])
def restore_workspace(project_id):
    """還原已軟刪除的專案"""
    workspace = Workspace.query.filter_by(
        project_id = project_id,
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
def permanent_delete_workspace(project_id):
    """永久刪除專案（垃圾桶內手動永久刪除）"""
    workspace = Workspace.query.filter_by(
        project_id = project_id,
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


@workspace_bp.route("/api/workspace/user/<int:user_id>/trash", methods=["GET"])
def get_trash(user_id):
    """取得垃圾桶內的專案（軟刪除中）"""
    workspaces = Workspace.query.filter_by(
        user_id    = user_id,
        is_deleted = True,
    ).order_by(Workspace.deleted_at.desc()).all()

    return jsonify([workspace_to_dict(w) for w in workspaces]), 200


# ── 自動永久刪除排程 ────────────────────────────────────────

def hard_delete_expired_workspaces():
    """刪除所有軟刪除超過 30 天的專案"""
    from app import app  # 避免 circular import
    with app.app_context():
        expiry = taiwan_now() - timedelta(days=SOFT_DELETE_DAYS)
        expired = Workspace.query.filter(
            Workspace.is_deleted == True,
            Workspace.deleted_at <= expiry,
        ).all()

        if not expired:
            return

        for w in expired:
            db.session.delete(w)

        try:
            db.session.commit()
            print(f"[Scheduler] 永久刪除 {len(expired)} 個過期專案")
        except Exception as e:
            db.session.rollback()
            print(f"[Scheduler] 永久刪除失敗：{e}")


def start_scheduler():
    """在 app 啟動時呼叫這個函式來啟動排程"""
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        hard_delete_expired_workspaces,
        trigger = "interval",
        hours   = 24,        # 每 24 小時執行一次
        id      = "hard_delete_workspaces",
    )
    scheduler.start()
    print("[Scheduler] 自動永久刪除排程已啟動")