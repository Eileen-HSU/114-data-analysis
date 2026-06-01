from flask import Blueprint, jsonify, request
from extensions import db
from sqlalchemy import exists
from models import Chat_History, Workspace
from utils.auth import authorize_request  

chat_bp = Blueprint("chat", __name__)

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
    belongs_to_user = db.session.query(
        exists().where(
            Workspace.project_id == project_id,
            Workspace.user_id    == current_user_id,
            Workspace.is_deleted == False,
        )
    ).scalar()

    if not belongs_to_user:
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
    

@chat_bp.route("/api/chat/history/<int:project_id>", methods=["GET"])
def get_chat_history(project_id):
    try:
        # 1. 權限驗證
        current_user_id, auth_error = authorize_request()
        if auth_error:
            return auth_error

        # 2. 權限防禦
        belongs_to_user = db.session.query(
            exists().where(
                Workspace.project_id == project_id,
                Workspace.user_id == current_user_id,
                Workspace.is_deleted == False,
            )
        ).scalar()

        if not belongs_to_user:
            return jsonify({"error": "找不到該專案或您無權限操作"}), 404

        # 3. 撈歷史訊息，依時間正序
        histories = (
            Chat_History.query
            .filter_by(project_id=project_id)
            .order_by(Chat_History.created_at.asc())
            .all()
        )

        chat_history = []

        for history in histories:
            chat_history.append({
                "chat_id":         history.chat_id,
                "project_id":      history.project_id,
                "template_id":     history.template_id,
                "sender_type":     history.sender_type, 
                "role":            "user" if history.sender_type == "user" else "assistant", # ✨ 新增 role 給前端直讀
                "message_content": history.message_content,
                "content":         history.message_content, # ✨ 新增 content 對齊前端用到的欄位
                "status":          history.status,
                "created_at":      history.created_at.isoformat() if history.created_at else None,
            })

        return jsonify({
            "project_id": project_id,
            "chat_history": chat_history,
        }), 200

    except Exception as error:
        print("[GET CHAT HISTORY ERROR]", repr(error))
        return jsonify({
            "error": str(error),
            "route": f"/api/chat/history/{project_id}",
        }), 500