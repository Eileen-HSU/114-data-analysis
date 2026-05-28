from datetime import timedelta
import os
import jwt

from flask import Blueprint, jsonify, request
from apscheduler.schedulers.background import BackgroundScheduler

from extensions import db
from models import Workspace, taiwan_now

workspace_bp = Blueprint("workspace", __name__)

SOFT_DELETE_DAYS = 30


def get_jwt_secret():
    secret = os.getenv("JWT_SECRET_KEY")
    if not secret:
        raise RuntimeError("JWT_SECRET_KEY 環境變數未設定")
    return secret


def verify_token(request):
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None, "Unauthorized"

    token = auth_header.split(" ")[1]
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=["HS256"])
        return payload.get("user_id"), None
    except jwt.ExpiredSignatureError:
        return None, "Token expired"
    except jwt.InvalidTokenError:
        return None, "Invalid token"


def authorize_request():
    auth_user_id, error = verify_token(request)
    if error:
        return None, (jsonify({"error": "Unauthorized"}), 401)
    return auth_user_id, None


def workspace_to_dict(w):
    days_left = None
    if w.deleted_at:
        now_naive = taiwan_now().replace(tzinfo=None)
        deleted_at_naive = w.deleted_at.replace(tzinfo=None)
        days_left = max(0, SOFT_DELETE_DAYS - (now_naive - deleted_at_naive).days)

    return {
        "project_id":   w.project_id,
        "user_id":      w.user_id,
        "project_name": w.project_name,
        "folder_name":  w.folder_name,
        "created_at":   w.created_at.isoformat() if w.created_at else None,
        "is_deleted":   w.is_deleted,
        "deleted_at":   w.deleted_at.isoformat() if w.deleted_at else None,
        "days_left":    days_left,
    }


@workspace_bp.route("/api/workspace/user", methods=["GET"])
def get_workspaces():
    current_user_id, auth_error = authorize_request()
    if auth_error:
        return auth_error
    workspaces = Workspace.query.filter_by(
        user_id    = current_user_id,
        is_deleted = False,
    ).order_by(Workspace.created_at.desc()).all()

    return jsonify([workspace_to_dict(w) for w in workspaces]), 200


@workspace_bp.route("/api/workspace/user/trash", methods=["GET"])
def get_trash():
    current_user_id, auth_error = authorize_request()
    if auth_error:
        return auth_error
    workspaces = Workspace.query.filter_by(
        user_id    = current_user_id,
        is_deleted = True,
    ).order_by(Workspace.deleted_at.desc()).all()

    return jsonify([workspace_to_dict(w) for w in workspaces]), 200


@workspace_bp.route("/api/workspace/user/folder/<string:folder_name>", methods=["GET"])
def get_workspaces_by_folder(folder_name):
    current_user_id, auth_error = authorize_request()
    if auth_error:
        return auth_error
    workspaces = Workspace.query.filter_by(
        user_id     = current_user_id,
        folder_name = folder_name,
        is_deleted  = False,
    ).order_by(Workspace.created_at.desc()).all()

    return jsonify([workspace_to_dict(w) for w in workspaces]), 200


@workspace_bp.route("/api/workspace", methods=["POST"])
def create_workspace():
    current_user_id, auth_error = authorize_request()
    if auth_error:
        return auth_error
    data = request.get_json(silent=True) or {}
    project_name = data.get("project_name")

    if not project_name:
        return jsonify({"error": "請提供 project_name"}), 400

    workspace = Workspace(
        user_id      = current_user_id,
        project_name = project_name,
        folder_name  = data.get("folder_name"),
    )

    try:
        db.session.add(workspace)
        db.session.commit()
        return jsonify(workspace_to_dict(workspace)), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@workspace_bp.route("/api/workspace/<int:project_id>", methods=["GET"])
def get_workspace(project_id):
    current_user_id, auth_error = authorize_request()
    if auth_error:
        return auth_error
    workspace = Workspace.query.filter_by(
        project_id = project_id,
        user_id    = current_user_id,
        is_deleted = False,
    ).first()

    if not workspace:
        return jsonify({"error": "找不到專案"}), 404

    return jsonify(workspace_to_dict(workspace)), 200


@workspace_bp.route("/api/workspace/<int:project_id>", methods=["PUT"])
def update_workspace(project_id):
    current_user_id, auth_error = authorize_request()
    if auth_error:
        return auth_error
    workspace = Workspace.query.filter_by(
        project_id = project_id,
        user_id    = current_user_id,
        is_deleted = False,
    ).first()

    if not workspace:
        return jsonify({"error": "找不到專案"}), 404

    data = request.get_json(silent=True)

    if "folder_name" in data:
        workspace.folder_name = data["folder_name"]
    if "project_name" in data:
        workspace.project_name = data["project_name"]

    try:
        db.session.commit()
        return jsonify(workspace_to_dict(workspace)), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@workspace_bp.route("/api/workspace/<int:project_id>", methods=["DELETE"])
def delete_workspace(project_id):
    current_user_id, auth_error = authorize_request()
    if auth_error:
        return auth_error
    
    workspace = Workspace.query.filter(
        Workspace.project_id == project_id,
        Workspace.user_id    == current_user_id,
        Workspace.is_deleted != True,
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
        workspace.is_deleted = False
        workspace.deleted_at = None
        workspace.folder_name = data.get("folder_name") 
        db.session.commit()
        return jsonify({"message": "專案已還原"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@workspace_bp.route("/api/workspace/<int:project_id>/permanent", methods=["DELETE"])
def permanent_delete_workspace(project_id):
    current_user_id, auth_error = authorize_request()
    if auth_error:
        return auth_error
        
    workspace = Workspace.query.filter_by(
        project_id = project_id,
        user_id    = current_user_id
    ).first()

    if not workspace:
        return jsonify({"error": "找不到該專案"}), 404
    
    if not workspace.is_deleted:  
        return jsonify({"error": "請先移至垃圾桶才能永久刪除"}), 400

    try:
        # 1. 安全斷開：把所有關聯的問卷範本 project_id 設為空
        for template in workspace.templates:
            template.project_id = None
            
        # 2. 安全斷開：把所有關聯的聊天紀錄 project_id 設為空
        for chat in workspace.chats:
            chat.project_id = None
        
        # 3. 執行永久刪除（單純抹除 Workspace 這一筆資料）
        db.session.delete(workspace)
        db.session.commit()
        
        return jsonify({"message": "專案已永久刪除，聊天紀錄與問卷範本已安全保留"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

def hard_delete_expired_workspaces(app):
    with app.app_context():
        try:
            expiry = taiwan_now() - timedelta(days=SOFT_DELETE_DAYS)
            expired = Workspace.query.filter(
                Workspace.is_deleted == True,
                Workspace.deleted_at != None,
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