import os
import random
import string
from datetime import timedelta

import jwt
from flask import Blueprint, jsonify, request

from extensions import db
from models import Workspace, Chat_History, taiwan_now

workspace_bp = Blueprint("workspace", __name__)

SOFT_DELETE_DAYS = 30

_JWT_SECRET: str | None = None


def get_jwt_secret() -> str:
    global _JWT_SECRET
    if _JWT_SECRET is None:
        _JWT_SECRET = os.getenv("JWT_SECRET_KEY")
        if not _JWT_SECRET:
            raise RuntimeError("JWT_SECRET_KEY 環境變數未設定")
    return _JWT_SECRET


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
    """取得單一專案的詳細資訊，包含是否在垃圾桶中、剩餘天數等"""
    current_user_id, auth_error = authorize_request()
    if auth_error:
        return auth_error

    workspace = db.session.get(Workspace, project_id)
    if not workspace or workspace.user_id != current_user_id or workspace.is_deleted:
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


@workspace_bp.route("/api/workspace/<int:project_id>", methods=["DELETE", "PATCH"])
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
        return jsonify({"message": "專案已在垃圾桶中"}), 200

    if request.method == "PATCH":
        data = request.get_json(silent=True) or {}
        if data.get("is_deleted") not in [1, True]:
            return jsonify({"error": "不合法的 PATCH 參數"}), 400

    try:
        workspace.is_deleted = True
        workspace.deleted_at = taiwan_now()
        db.session.commit()
        return jsonify({
            "message":   "專案已移至垃圾桶，30 天後將永久刪除",
            "workspace": workspace_to_dict(workspace),
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# ---------- 邀請瀏覽 ----------
# 這兩支路由對應「邀請瀏覽」這個功能：擁有者產生一組邀請碼，
# 任何人拿著這組碼都能唯讀查看這個工作區的對話紀錄，不需要登入
# ——比照 Survey_Template.access_code 讓問卷可以免登入被填寫的設計。
# 「唯讀」是刻意的邊界：這兩支路由都不提供任何寫入操作（不能傳訊息、
# 不能上傳檔案觸發分類），避免邀請連結被拿來冒充擁有者操作帳號內容。

def _generate_unique_share_code():
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        if not Workspace.query.filter_by(share_code=code).first():
            return code


@workspace_bp.route("/api/workspace/<int:project_id>/share", methods=["POST"])
def create_share_link(project_id):
    """擁有者產生（或拿回既有的）邀請碼。需要登入、且必須是這個工作區的擁有者。"""
    current_user_id, auth_error = authorize_request()
    if auth_error:
        return auth_error

    workspace = Workspace.query.filter_by(
        project_id=project_id, user_id=current_user_id, is_deleted=False
    ).first()
    if not workspace:
        return jsonify({"error": "找不到專案"}), 404

    if not workspace.share_code:
        workspace.share_code = _generate_unique_share_code()
        db.session.commit()

    return jsonify({"share_code": workspace.share_code}), 200


@workspace_bp.route("/api/public/workspace/<string:share_code>", methods=["GET"])
def get_shared_workspace(share_code):
    """
    給邀請連結用，刻意不呼叫 authorize_request()——任何人拿著正確的邀請碼
    都應該能看到內容，這是「邀請瀏覽」的定義，不是漏掉權限檢查。

    只回傳唯讀資訊（工作區名稱、對話紀錄），不包含任何可以拿去操作
    帳號本身的欄位（例如 user_id、其他 workspace 清單）。
    """
    workspace = Workspace.query.filter_by(share_code=share_code, is_deleted=False).first()
    if not workspace:
        return jsonify({"error": "邀請連結無效或已失效"}), 404

    chats = (
        Chat_History.query.filter_by(project_id=workspace.project_id)
        .order_by(Chat_History.created_at.asc())
        .all()
    )

    return jsonify({
        "project_name": workspace.project_name,
        "messages": [
            {
                "chat_id": c.chat_id,
                "sender_type": c.sender_type,
                "content": c.message_content,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in chats
        ],
    }), 200