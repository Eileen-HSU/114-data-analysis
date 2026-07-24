from flask import Blueprint, jsonify, request
from extensions import db
from models import Chat_History, Workspace, UploadedFile
from routes.auth.workspace import authorize_request
import os

chat_bp = Blueprint("chat", __name__)

# 負責處理與聊天紀錄相關的 API，包括儲存對話紀錄、取得對話紀錄，以及上傳和取得對話相關的檔案。
@chat_bp.route("/api/chat/history", methods=["POST"])
def save_chat_history():
    # 1. 權限驗證
    current_user_id, auth_error = authorize_request()
    if auth_error:
        return auth_error

    data = request.get_json(silent=True) or {}

    # 2. 取值
    raw_project_id  = data.get("project_id")
    sender_type     = data.get("sender_type")
    message_content = data.get("message_content")
    template_id     = data.get("template_id")

    # 3. 轉型 project_id
    try:
        project_id = int(raw_project_id) if raw_project_id is not None else None
    except (ValueError, TypeError):
        return jsonify({"error": "不合法的 project_id 格式"}), 400

    # 4. 驗證必要欄位
    if project_id is None or not sender_type or not message_content:
        return jsonify({"error": "缺少必要欄位：project_id, sender_type 或 message_content"}), 400

    # 5. 驗證 sender_type 合法值
    if sender_type not in ("user", "ai"):
        return jsonify({"error": "sender_type 必須為 'user' 或 'ai'"}), 400

    # 6. 權限防禦
    workspace = Workspace.query.filter_by(
        project_id = project_id,
        user_id    = current_user_id,
        is_deleted = False,
    ).options(db.load_only(Workspace.project_id)).first()

    if not workspace:
        return jsonify({"error": "找不到該專案或您無權限操作"}), 404
    
    # 7. 寫入 DB
    chat = Chat_History(
        project_id      = project_id,
        template_id     = template_id,
        message_content = message_content,
        sender_type     = sender_type,
        status          = "completed",
    )
    try:
        db.session.add(chat)
        db.session.commit()
        return jsonify({
            "message": "對話紀錄已成功同步至資料庫",
            "chat_history": {
                "chat_id":         chat.chat_id,
                "project_id":      chat.project_id,
                "template_id":     chat.template_id,
                "sender_type":     chat.sender_type,
                "message_content": chat.message_content,
                "status":          chat.status,
                "created_at":      chat.created_at.isoformat() if chat.created_at else None,
            }
        }), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# 取得對話紀錄，包含訊息和檔案，並且按照時間排序
@chat_bp.route("/api/chat/history/<int:project_id>", methods=["GET"])
def get_chat_history(project_id):
    try:
        current_user_id, auth_error = authorize_request()
        if auth_error:
            return auth_error

        # 權限 + 存在性一次確認
        workspace = Workspace.query.filter_by(
            project_id = project_id,
            user_id    = current_user_id,
            is_deleted = False,
        ).options(db.load_only(Workspace.project_id)).first()

        if not workspace:
            return jsonify({"error": "找不到該專案或您無權限操作"}), 404
        
        # 撈對話紀錄
        histories = (
            Chat_History.query
            .filter_by(project_id=project_id)
            .order_by(Chat_History.created_at.asc())
            .all()
        )
        # 撈檔案
        chat_ids = [h.chat_id for h in histories]
        files = (
            UploadedFile.query
            .filter(UploadedFile.chat_id.in_(chat_ids))
            .all()
        ) if chat_ids else []

        items = [
            {
                "type":            "message",
                "chat_id":         h.chat_id,
                "project_id":      h.project_id,
                "template_id":     h.template_id,
                "sender_type":     h.sender_type,
                "role":            "user" if h.sender_type == "user" else "assistant",
                "message_content": h.message_content,
                "content":         h.message_content,
                "status":          h.status,
                "created_at":      h.created_at.isoformat() if h.created_at else None,
            }
            for h in histories
        ] + [
            {
                "type":        "file",
                "file_id":     f.file_id,
                "chat_id":     f.chat_id,
                "file_name":   f.file_name,
                "file_type":   f.file_type,
                "uploaded_at": f.uploaded_at.isoformat() if f.uploaded_at else None,
                "created_at":  f.uploaded_at.isoformat() if f.uploaded_at else None,
            }
            for f in files
        ]

        items.sort(key=lambda x: x["created_at"] or "")

        return jsonify({"project_id": project_id, "chat_history": items}), 200

    except Exception as error:
        db.session.rollback()
        print("[GET CHAT HISTORY ERROR]", repr(error))
        return jsonify({"error": str(error), "route": f"/api/chat/history/{project_id}"}), 500

def _get_chat_with_auth(chat_id, user_id):
    """回傳 chat 物件，同時驗證該 user 有權限，沒有就回 None"""
    return (
        db.session.query(Chat_History)
        .join(Workspace, Workspace.project_id == Chat_History.project_id)
        .filter(
            Chat_History.chat_id  == chat_id,
            Workspace.user_id     == user_id,
            Workspace.is_deleted  == False,
        )
        .first()
    )

# 上傳檔案並關聯到 chat_id，支援 csv、xlsx、txt 格式，並且儲存在 uploads/{project_id} 目錄底下
@chat_bp.route("/api/chat/<int:chat_id>/files", methods=["POST"])
def upload_file(chat_id):
    '''上傳檔案並關聯到 chat_id'''
    current_user_id, auth_error = authorize_request()
    if auth_error:
        return auth_error

    chat = _get_chat_with_auth(chat_id, current_user_id)
    if not chat:
        return jsonify({"error": "找不到該對話或無權限操作"}), 404

    # 3. 取得檔案
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "請提供檔案"}), 400

    file_name = file.filename
    ext = os.path.splitext(file_name)[-1].lower().lstrip(".")
    if ext not in ("csv", "xlsx", "txt"):
        return jsonify({"error": "不支援的檔案格式"}), 400

    # 4. 儲存檔案
    upload_dir = os.path.join("uploads", str(chat.project_id))
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, file_name)
    file.save(file_path)

    # 5. 寫入 DB
    uploaded = UploadedFile(
        chat_id   = chat_id,
        file_name = file_name,
        file_path = file_path,
        file_type = ext,
    )
    try:
        db.session.add(uploaded)
        db.session.commit()
        return jsonify({
            "message": "檔案上傳成功",
            "file": {
                "file_id":     uploaded.file_id,
                "chat_id":     uploaded.chat_id,
                "file_name":   uploaded.file_name,
                "file_path":   uploaded.file_path,
                "file_type":   uploaded.file_type,
                "uploaded_at": uploaded.uploaded_at.isoformat() if uploaded.uploaded_at else None,
            }
        }), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# 取得對話紀錄底下的所有檔案資訊
@chat_bp.route("/api/chat/<int:chat_id>/files", methods=["GET"])
def get_chat_files(chat_id):
    '''回傳該 chat 底下的所有檔案資訊'''
    current_user_id, auth_error = authorize_request()
    if auth_error:
        return auth_error

    chat = _get_chat_with_auth(chat_id, current_user_id)
    if not chat:
        return jsonify({"error": "找不到該對話或無權限操作"}), 404
    
    # 撈檔案
    files = UploadedFile.query.filter_by(chat_id=chat_id).all()
    return jsonify({
        "chat_id": chat_id,
        "files": [
            {
                "file_id":     f.file_id,
                "file_name":   f.file_name,
                "file_path":   f.file_path,
                "file_type":   f.file_type,
                "uploaded_at": f.uploaded_at.isoformat() if f.uploaded_at else None,
            }
            for f in files
        ]
    }), 200