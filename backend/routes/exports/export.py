"""

匯出檔案 API：對應「專案管理 → 匯出檔案」這個頁面。

  POST /api/exports              -> 新增一筆匯出紀錄（儲存 CSV 內容）
  GET  /api/exports              -> 列出目前使用者的所有匯出紀錄
  GET  /api/exports/<id>/download -> 下載某一筆匯出的實際內容

用的是專案原本就有的 Export_File 這張表，不是另外新開一張表。
Export_File 沒有直接掛 user_id，是透過
    Export_File.chat_id -> Chat_History.project_id -> Workspace.user_id
這條關聯鏈判斷 ownership，所有查詢都要跟著這條鏈 join，不能只憑
export_id 就給資料，避免任何使用者看到或下載到別人的匯出檔案。

export_path 是這張表原本的欄位，語意是「檔案存放路徑」，這次沒有真正
的檔案儲存服務可用，所以固定填空字串，真正的內容存進另外新增的
content 欄位（見 models.py Export_File 的註解）。
"""

from flask import Blueprint, jsonify, request, Response
from urllib.parse import quote

from extensions import db
from models import Export_File, Chat_History, Workspace
from routes.workspaces.workspace import authorize_request

exports_bp = Blueprint("exports", __name__)


def _get_owned_chat(chat_id, current_user_id):
    """確認 chat_id 存在、而且屬於目前這個使用者，回傳 Chat_History 或 None。"""
    return (
        db.session.query(Chat_History)
        .join(Workspace, Workspace.project_id == Chat_History.project_id)
        .filter(Chat_History.chat_id == chat_id, Workspace.user_id == current_user_id)
        .first()
    )


@exports_bp.route("/api/exports", methods=["POST"])
def create_export():
    current_user_id, auth_error = authorize_request()
    if auth_error:
        return auth_error

    data = request.get_json(silent=True) or {}
    chat_id = data.get("chat_id")
    filename = data.get("filename")
    content = data.get("content")
    row_count = data.get("row_count")

    if not chat_id:
        return jsonify({"error": "缺少 chat_id"}), 400
    if not filename or not isinstance(filename, str):
        return jsonify({"error": "缺少 filename"}), 400
    if not content or not isinstance(content, str):
        return jsonify({"error": "缺少 content"}), 400

    chat = _get_owned_chat(chat_id, current_user_id)
    if not chat:
        return jsonify({"error": "找不到這個對話，或您無權限操作"}), 404

    export = Export_File(
        chat_id=chat_id,
        export_name=filename,
        export_type="csv",
        export_path="",  # 沒有真正的檔案儲存服務，內容直接存 content 欄位
        export_status="completed",
        content=content,
        row_count=row_count if isinstance(row_count, int) else None,
    )
    db.session.add(export)
    db.session.commit()

    return jsonify(export.to_dict()), 201


@exports_bp.route("/api/exports", methods=["GET"])
def list_exports():
    current_user_id, auth_error = authorize_request()
    if auth_error:
        return auth_error

    exports = (
        db.session.query(Export_File)
        .join(Chat_History, Chat_History.chat_id == Export_File.chat_id)
        .join(Workspace, Workspace.project_id == Chat_History.project_id)
        .filter(Workspace.user_id == current_user_id)
        .order_by(Export_File.created_at.desc())
        .all()
    )
    return jsonify([e.to_dict() for e in exports]), 200


@exports_bp.route("/api/exports/<int:export_id>/download", methods=["GET"])
def download_export(export_id):
    current_user_id, auth_error = authorize_request()
    if auth_error:
        return auth_error

    export = (
        db.session.query(Export_File)
        .join(Chat_History, Chat_History.chat_id == Export_File.chat_id)
        .join(Workspace, Workspace.project_id == Chat_History.project_id)
        .filter(Export_File.export_id == export_id, Workspace.user_id == current_user_id)
        .first()
    )
    if not export:
        return jsonify({"error": "找不到這筆匯出紀錄"}), 404

    # HTTP 標頭只能放 Latin-1 字元，
    # export_name 是中文（例如「分類結果_2026-08-29.csv」），直接塞進
    # Content-Disposition 會在真正的 WSGI 伺服器（gunicorn）送出回應時
    # UnicodeEncodeError，導致整個 worker 掛掉——這也是為什麼本機用
    # Flask test_client 測不出來，只有接上真的 gunicorn 才會爆。
    # 改用 RFC 5987/6266 標準寫法：filename 放一個純英數的保底檔名（給
    # 不支援新標準的舊工具用），filename* 用 UTF-8 + percent-encoding
    # 放真正的中文檔名，現代瀏覽器都認得這個標準、會下載成正確的中文檔名。
    encoded_filename = quote(export.export_name or "export.csv")
    content_disposition = f"attachment; filename=\"export.csv\"; filename*=UTF-8''{encoded_filename}"

    return Response(
        export.content or "",
        mimetype="text/csv",
        headers={"Content-Disposition": content_disposition},
    )