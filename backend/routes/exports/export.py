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
import base64

from extensions import db
from models import Export_File, Chat_History, Workspace
from routes.workspaces.workspace import authorize_request
from services.export_file_service import build_xlsx, build_docx
from sqlalchemy.orm import defer

exports_bp = Blueprint("exports", __name__)

# 每種格式對應的副檔名跟 MIME type，下載時要用
_FORMAT_META = {
    "xlsx": {
        "ext": "xlsx",
        "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    },
    "docx": {
        "ext": "docx",
        "mimetype": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    },
}


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
    row_count = data.get("row_count")
    # 【新增｜Excel／Word 匯出】export_type 決定要走哪條路：
    #   "csv"（預設，向下相容）：前端直接把組好的 CSV 文字放在 content，
    #     照舊直接存文字，不用後端額外處理。
    #   "xlsx" / "docx"：前端改傳結構化的 rows 資料，後端用
    #     services/export_file_service 真的產生二進位檔案，
    #     base64 編碼後存進同一個 content 欄位（MEDIUMTEXT 存不了原始
    #     二進位，base64 是最簡單、不用改資料庫欄位型別的做法）。

    export_type = data.get("export_type")
    if export_type not in _FORMAT_META:
        return jsonify({"error": "僅支援 Excel 或 Word 匯出"}), 400

    if not chat_id:
        return jsonify({"error": "缺少 chat_id"}), 400
    if not filename or not isinstance(filename, str):
        return jsonify({"error": "缺少 filename"}), 400

    chat = _get_owned_chat(chat_id, current_user_id)
    if not chat:
        return jsonify({"error": "找不到這個對話，或您無權限操作"}), 404

    rows = data.get("rows")

    if not rows or not isinstance(rows, list):
        return jsonify({
            "error": "缺少 rows"
        }), 400

    title = data.get("title") or "分類結果"

    try:
        if export_type == "xlsx":
            file_bytes = build_xlsx(rows, title=title)
        else:
            file_bytes = build_docx(rows, title=title)

    except Exception as e:
        return jsonify({
            "error": f"產生 {export_type} 檔案失敗：{str(e)[:200]}"
        }), 500

    stored_content = base64.b64encode(
        file_bytes
    ).decode("ascii")

    export = Export_File(
        chat_id=chat_id,
        export_name=filename,
        export_type=export_type,
        export_path="",  # 沒有真正的檔案儲存服務，內容直接存 content 欄位
        export_status="completed",
        content=stored_content,
        row_count=row_count if isinstance(row_count, int) else None,
    )
    db.session.add(export)
    db.session.commit()

    # 【新增｜匯出來源路徑】新增當下也一起回傳，跟清單 API 保持一致
    workspace = Workspace.query.get(chat.project_id)
    result = export.to_dict()
    result["source_path"] = _build_source_path(workspace) if workspace else None
    result["project_id"] = chat.project_id
    return jsonify(result), 201


def _build_source_path(workspace):
    """把 Workspace 組成「資料夾 / 工作區名稱」這種路徑字串，
    沒有資料夾的話就只顯示工作區名稱。"""
    if workspace.folder_name:
        return f"{workspace.folder_name} / {workspace.project_name}"
    return workspace.project_name


@exports_bp.route("/api/exports", methods=["GET"])
def list_exports():
    current_user_id, auth_error = authorize_request()
    if auth_error:
        return auth_error

    # 【新增｜匯出來源路徑】使用者要能一眼看出這筆匯出是從哪個工作區
    # 匯出的，一起把 Workspace 撈出來，不用額外多打一次 API。
    # 【修正｜清單載入很慢】原本這裡用 query(Export_File, Workspace)，
    # SQLAlchemy 預設會把 Export_File 的「所有欄位」都從資料庫撈出來，
    # 包含 content 這個存放 base64 二進位檔案內容的欄位（可能好幾十~
    # 上百 KB），即使 to_dict() 根本不會用到它。隨著匯出檔案累積越多，
    # 這支清單 API 要傳輸的資料量會跟著線性變大、越來越慢。
    # 用 defer(Export_File.content) 明確告訴 SQLAlchemy 不要抓這個欄位，
    # 只有真的呼叫 .content 屬性時才會另外查一次（清單畫面用不到，
    # 所以這裡永遠不會觸發額外查詢）。
    rows = (
        db.session.query(Export_File, Workspace)
        .options(defer(Export_File.content))
        .join(Chat_History, Chat_History.chat_id == Export_File.chat_id)
        .join(Workspace, Workspace.project_id == Chat_History.project_id)
        .filter(Workspace.user_id == current_user_id)
        .order_by(Export_File.created_at.desc())
        .all()
    )
    result = []
    for export, workspace in rows:
        item = export.to_dict()
        item["source_path"] = _build_source_path(workspace)
        item["project_id"] = workspace.project_id
        result.append(item)
    return jsonify(result), 200


@exports_bp.route("/api/exports/<int:export_id>", methods=["PATCH"])
def rename_export(export_id):
    """
    重新命名一筆匯出紀錄。預設檔名是原始上傳檔案的名稱（由前端組出來，
    見 downloadClassificationFile 的 baseFilename 邏輯），這支路由讓
    使用者事後可以改成自己想要的名稱。

    只改名字（export_name），不動副檔名本身代表的格式（export_type）、
    也不重新產生檔案內容——重新命名跟「這是什麼格式」是兩件事，不用
    因為改名字就重新跑一次 openpyxl/python-docx。
    """
    current_user_id, auth_error = authorize_request()
    if auth_error:
        return auth_error

    data = request.get_json(silent=True) or {}
    new_filename = data.get("filename")
    if not new_filename or not isinstance(new_filename, str) or not new_filename.strip():
        return jsonify({"error": "缺少 filename，或 filename 不能是空字串"}), 400
    new_filename = new_filename.strip()

    export = (
        db.session.query(Export_File)
        .options(defer(Export_File.content))
        .join(Chat_History, Chat_History.chat_id == Export_File.chat_id)
        .join(Workspace, Workspace.project_id == Chat_History.project_id)
        .filter(Export_File.export_id == export_id, Workspace.user_id == current_user_id)
        .first()
    )
    if not export:
        return jsonify({"error": "找不到這筆匯出紀錄"}), 404

    # 【修正】使用者改名字時，很容易忘記或不小心把副檔名一起改掉/刪掉，
    # 這裡保守處理：如果新名字沒有以正確的副檔名結尾，自動幫他補上，
    # 不會因為漏打副檔名就下載出一個打不開、副檔名對不上內容的檔案。
    correct_ext = "." + _FORMAT_META[export.export_type]["ext"]
    if not new_filename.lower().endswith(correct_ext.lower()):
        new_filename = f"{new_filename}{correct_ext}"

    export.export_name = new_filename
    db.session.commit()

    workspace = Workspace.query.get(export.chat.project_id) if export.chat else None
    result = export.to_dict()
    result["source_path"] = _build_source_path(workspace) if workspace else None
    return jsonify(result), 200


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

    format_meta = _FORMAT_META.get(export.export_type)

    if not format_meta:
        return jsonify({
            "error": "這筆匯出格式已不再支援"
        }), 400
    
    # 【新增｜Excel／Word 下載】csv 是純文字，直接回傳；xlsx/docx 存的是
    # base64，要先解碼回原始二進位，不然下載下來的檔案打不開。
    try:
        file_data = base64.b64decode(export.content or "")
    except Exception:
        return jsonify({
            "error": "檔案內容毀損，無法下載"
        }), 500

    # 【修正｜中文檔名讓下載直接 500】HTTP 標頭只能放 Latin-1 字元，
    # export_name 是中文（例如「分類結果_2026-08-29.csv」），直接塞進
    # Content-Disposition 會在真正的 WSGI 伺服器（gunicorn）送出回應時
    # UnicodeEncodeError，導致整個 worker 掛掉——這也是為什麼本機用
    # Flask test_client 測不出來，只有接上真的 gunicorn 才會爆。
    # 改用 RFC 5987/6266 標準寫法：filename 放一個純英數的保底檔名（給
    # 不支援新標準的舊工具用），filename* 用 UTF-8 + percent-encoding
    # 放真正的中文檔名，現代瀏覽器都認得這個標準、會下載成正確的中文檔名。
    encoded_filename = quote(export.export_name or f"export.{format_meta['ext']}")
    content_disposition = (
        f"attachment; filename=\"export.{format_meta['ext']}\"; "
        f"filename*=UTF-8''{encoded_filename}"
    )

    return Response(
        file_data,
        mimetype=format_meta["mimetype"],
        headers={"Content-Disposition": content_disposition},
    )