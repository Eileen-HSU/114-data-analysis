from flask import Blueprint, jsonify, request
from extensions import db
from models import Chat_History

chat_bp = Blueprint("chat", __name__)

@chat_bp.route("/api/chat/history", methods=["POST"])
def save_chat_history():
    """純粹將前端丟過來的問卷大文字寫入 T06 Chat_History 資料表"""
    data = request.get_json(silent=True) or {}
    project_id      = data.get("project_id")
    sender_type     = data.get("sender_type")     # 前端會送 'user'
    message_content = data.get("message_content") # 問卷大文字

    # 保留詳細的錯誤提示
    if not project_id or not sender_type or not message_content:
        return jsonify({"error": "缺少必要欄位：project_id, sender_type 或 message_content"}), 400

    chat = Chat_History(
        project_id      = project_id,
        chat_name       = "問卷匯入紀錄",  
        sender_type     = sender_type,
        message_content = message_content
    )

    try:
        db.session.add(chat)
        db.session.commit()
        return jsonify({"message": "成功寫入 Chat_History 資料表"}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500