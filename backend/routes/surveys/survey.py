import logging
import os
import random
import re
import string
import json
from urllib.parse import urlencode, urlsplit, quote
from urllib.request import urlopen

import jwt
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Blueprint, request, jsonify, Response
from sqlalchemy import func
from sqlalchemy.orm.attributes import flag_modified

from extensions import db
from models import Survey_Template, Survey_Response, Chat_History
from services.question_routing_service import route_question_type
from services.export_file_service import build_survey_xlsx, build_survey_docx

survey_bp = Blueprint('survey', __name__)

TAIPEI_TZ = ZoneInfo("Asia/Taipei")
BASE36_ALPHABET = string.digits + string.ascii_uppercase
DEFAULT_FRONTEND_ORIGIN = "https://site--frontend--d6tvmpswrhlp.code.run"
# 快取 JWT secret
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
    token = auth_header.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=["HS256"])
        return payload.get("user_id"), None
    except jwt.ExpiredSignatureError:
        return None, "Token expired"
    except jwt.InvalidTokenError:
        return None, "Invalid token"


def generate_unique_access_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))


def encode_survey_short_code(template_id):
    template_id = int(template_id or 0)
    if template_id <= 0:
        return ""
    chars = []
    while template_id:
        template_id, remainder = divmod(template_id, 36)
        chars.append(BASE36_ALPHABET[remainder])
    return ''.join(reversed(chars))


def decode_survey_short_code(short_code):
    token = (short_code or "").strip().upper()
    if not token or any(char not in BASE36_ALPHABET for char in token):
        return None
    value = 0
    for char in token:
        value = value * 36 + BASE36_ALPHABET.index(char)
    return value or None


def find_survey_by_access_or_short_code(raw_code):
    token = (raw_code or "").strip().upper()
    if not token:
        return None
    survey = Survey_Template.query.filter_by(access_code=token).first()
    if survey:
        return survey
    template_id = decode_survey_short_code(token)
    if not template_id:
        return None
    return Survey_Template.query.filter_by(template_id=template_id).first()


def survey_short_code(survey):
    return encode_survey_short_code(survey.template_id)


def is_allowed_short_url_target(url):
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    allowed_origins = {
        os.getenv("FRONTEND_PUBLIC_URL", DEFAULT_FRONTEND_ORIGIN).rstrip("/"),
        DEFAULT_FRONTEND_ORIGIN,
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    }
    return f"{parsed.scheme}://{parsed.netloc}" in allowed_origins


def create_external_short_url(long_url):
    cuttly_api_key = os.getenv("CUTTLY_API_KEY", "").strip()
    providers = [
        *(
            [(
                "cuttly",
                f"https://cutt.ly/api/api.php?{urlencode({'key': cuttly_api_key, 'short': long_url})}",
                ("https://cutt.ly/", "http://cutt.ly/"),
            )] if cuttly_api_key else []
        ),
        (
            "is.gd",
            f"https://is.gd/create.php?{urlencode({'format': 'simple', 'url': long_url})}",
            ("https://is.gd/",),
        ),
        (
            "v.gd",
            f"https://v.gd/create.php?{urlencode({'format': 'simple', 'url': long_url})}",
            ("https://v.gd/",),
        ),
        (
            "tinyurl",
            f"https://tinyurl.com/api-create.php?{urlencode({'url': long_url})}",
            ("https://tinyurl.com/",),
        ),
    ]
    errors = []
    for provider_name, api_url, allowed_prefixes in providers:
        try:
            request_timeout = 5 if provider_name == "cuttly" else 2
            with urlopen(api_url, timeout=request_timeout) as response:
                body = response.read().decode("utf-8").strip()
            if provider_name == "cuttly":
                payload = json.loads(body)
                url_info = payload.get("url") or {}
                short_url = (url_info.get("shortLink") or "").strip()
                if url_info.get("status") != 7:
                    errors.append(f"cuttly: status {url_info.get('status')}")
                    continue
            else:
                short_url = body
            if short_url.startswith(allowed_prefixes):
                return short_url
            errors.append(f"{provider_name}: {short_url or 'empty response'}")
        except Exception as e:
            errors.append(f"{provider_name}: {e}")
    raise ValueError("; ".join(errors) or "All shorteners failed")


@survey_bp.route('/api/short-links', methods=['POST'])
def create_short_link():
    data = request.get_json(silent=True) or {}
    long_url = (data.get("url") or "").strip()
    if not is_allowed_short_url_target(long_url):
        return jsonify({"error": "Unsupported URL"}), 400
    try:
        return jsonify({"short_url": create_external_short_url(long_url)}), 200
    except Exception as e:
        logging.warning(f"External short link creation failed: {e}")
        return jsonify({"error": "Short link creation failed"}), 502


def normalize_deadline(deadline):
    if not deadline:
        return None
    if isinstance(deadline, str):
        return parse_deadline(deadline)
    if deadline.tzinfo is None:
        return deadline.replace(tzinfo=TAIPEI_TZ)
    return deadline.astimezone(TAIPEI_TZ)


def parse_deadline(deadline_at):
    if not deadline_at:
        return None
    try:
        normalized = str(deadline_at).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        return normalize_deadline(parsed)
    except ValueError:
        return None


def deadline_to_iso(deadline):
    normalized = normalize_deadline(deadline)
    return normalized.isoformat() if normalized else None


def get_survey_deadline_at(survey, question_json=None):
    question_json = question_json if question_json is not None else (survey.question_json or {})
    return deadline_to_iso(survey.due_date) or question_json.get("deadline_at")


def is_survey_expired(question_json, due_date=None, now=None):
    """now 可由外部傳入，避免同一 request 重複呼叫 datetime.now()"""
    deadline = normalize_deadline(due_date) or parse_deadline((question_json or {}).get("deadline_at"))
    if not deadline:
        return False
    if now is None:
        now = datetime.now(TAIPEI_TZ)
    return now > deadline


@survey_bp.route('/api/public/surveys/<access_code>', methods=['GET'])
def get_public_survey(access_code):
    survey = find_survey_by_access_or_short_code(access_code)
    if not survey:
        return jsonify({"error": "Survey not found"}), 404

    question_json = survey.question_json or {}
    deadline_at = get_survey_deadline_at(survey, question_json)
    if is_survey_expired(question_json, survey.due_date):
        return jsonify({
            "error": "Survey expired",
            "expired": True,
            "template_id": survey.template_id,
            "title": survey.title,
            "access_code": survey.access_code,
            "short_code": survey_short_code(survey),
            "deadline_at": deadline_at,
        }), 410

    return jsonify({
        "template_id": survey.template_id,
        "title": survey.title,
        "description": question_json.get("description") or "",
        "identity_mode": question_json.get("identity_mode") or ("anonymous" if survey.is_anonymous else "identified"),
        "access_code": survey.access_code,
        "short_code": survey_short_code(survey),
        "created_at": survey.created_at.isoformat() if survey.created_at else None,
        "deadline_at": deadline_at,
        "questions": question_json.get("items") or [],
    }), 200


@survey_bp.route('/api/surveys', methods=['POST'])
def create_survey():
    auth_user_id, auth_error = verify_token(request)
    if auth_error:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    title = data.get('title')
    questions = data.get('questions')
    deadline_at = data.get('deadline_at')
    identity_mode = data.get('identity_mode') if data.get('identity_mode') in ["anonymous", "identified"] else "anonymous"

    if not title or not isinstance(questions, list):
        return jsonify({"error": "缺少問卷標題或題目資料"}), 400

    deadline = None
    if deadline_at:
        deadline = parse_deadline(deadline_at)
        if not deadline:
            return jsonify({"error": "截止時間格式不正確"}), 400

        now = datetime.now(TAIPEI_TZ)  # 只取一次
        if deadline <= now:
            return jsonify({"error": "截止時間必須晚於現在"}), 400

    try:
        access_code = generate_unique_access_code()

        # 對每道開放式文字題（type == "short"）自動判斷一次
        # question_type（leadership_and_dept / career_and_feedback），
        # 只在「建立問卷」這個時間點呼叫一次 Gemini，不是每則回答各判斷
        # 一次。route_question_type() 本身已經是 fail-safe 設計，任何
        # 判斷不出來或呼叫失敗的情況都回傳 None，這裡不需要額外
        # try/except——問卷一律照常建立成功，只是該題 question_type
        # 留 None，之後這題的回答會跳過自動分類（原始回答仍會完整保存）。
        for question in questions:
            if isinstance(question, dict) and question.get("type") == "short":
                question["question_type"] = route_question_type(question.get("title") or "")

        survey_content = {
            "description": data.get('description'),
            "identity_mode": identity_mode,
            "items": questions,
        }
        new_template = Survey_Template(
            title=title,
            access_code=access_code,
            question_json=survey_content,
            user_id=auth_user_id,
            due_date=deadline,
            is_anonymous=identity_mode == "anonymous",
        )
        db.session.add(new_template)
        db.session.flush()
        template_id = new_template.template_id
        short_code = encode_survey_short_code(template_id)
        db.session.commit()
        return jsonify({
            "message": "問卷建立成功",
            "access_code": access_code,
            "short_code": short_code,
            "template_id": template_id,
        }), 201
    except Exception as e:
        logging.error(f"Survey creation failed: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({"error": "問卷建立失敗", "detail": str(e)}), 500


@survey_bp.route('/api/surveys/<access_code>', methods=['GET'])
def get_survey(access_code):
    auth_user_id, auth_error = verify_token(request)
    if auth_error:
        return jsonify({"error": "Unauthorized"}), 401
    survey = find_survey_by_access_or_short_code(access_code)
    if not survey:
        return jsonify({"error": "找不到這份問卷"}), 404
    if survey.user_id != auth_user_id:
        return jsonify({"error": "無權限"}), 403
    question_json = survey.question_json or {}
    return jsonify({
        "template_id":  survey.template_id,
        "title":        survey.title,
        "access_code":  survey.access_code,
        "created_at":   survey.created_at.isoformat() if survey.created_at else None,
        "questions":    question_json.get("items") or [],
    }), 200


@survey_bp.route('/api/surveys/mine', methods=['GET'])
def get_user_surveys():
    auth_user_id, auth_error = verify_token(request)
    if auth_error:
        return jsonify({"error": "Unauthorized"}), 401

    try:
        limit = request.args.get("limit", type=int)
        if limit is not None:
            limit = max(1, min(limit, 50))

        query = (
            db.session.query(
                Survey_Template.template_id,
                Survey_Template.title,
                Survey_Template.access_code,
                Survey_Template.created_at,
                Survey_Template.due_date,
            )
            .filter(Survey_Template.user_id == auth_user_id)
            .order_by(Survey_Template.created_at.desc())
        )

        if limit is not None:
            query = query.limit(limit)

        surveys = (
            query
            .all()
        )

        if not surveys:
            return jsonify([]), 200

        # 一次 GROUP BY 查詢取得所有問卷的回覆數，取代 N+1 查詢
        template_ids = [s.template_id for s in surveys]
        counts = dict(
            db.session.query(
                Survey_Response.template_id,
                func.count(Survey_Response.response_id),
            )
            .filter(Survey_Response.template_id.in_(template_ids))
            .group_by(Survey_Response.template_id)
            .all()
        )

        result = []
        for survey in surveys:
            result.append({
                "template_id": survey.template_id,
                "title": survey.title,
                "access_code": survey.access_code,
                "short_code": encode_survey_short_code(survey.template_id),
                "created_at": survey.created_at.isoformat() if survey.created_at else "",
                "deadline_at": deadline_to_iso(survey.due_date),
                "response_count": counts.get(survey.template_id, 0),
            })
        return jsonify(result), 200
    except Exception as e:
        logging.error(f"Get user surveys failed: {e}", exc_info=True)
        return jsonify({"error": "取得問卷失敗"}), 500


@survey_bp.route('/api/surveys/<access_code>/deadline', methods=['PATCH'])
def update_survey_deadline(access_code):
    auth_user_id, auth_error = verify_token(request)
    if auth_error:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    deadline = parse_deadline(data.get("deadline_at"))
    if not deadline:
        return jsonify({"error": "截止時間格式不正確"}), 400
    if deadline <= datetime.now(TAIPEI_TZ):
        return jsonify({"error": "截止時間必須晚於現在。"}), 400

    try:
        survey = find_survey_by_access_or_short_code(access_code)
        if not survey:
            return jsonify({"error": "找不到這份問卷"}), 404

        question_json = dict(survey.question_json or {})
        question_json.pop("deadline_at", None)
        survey.question_json = question_json
        flag_modified(survey, "question_json")
        survey.due_date = deadline
        db.session.commit()

        return jsonify({
            "message": "截止時間已更新",
            "access_code": survey.access_code,
            "short_code": survey_short_code(survey),
            "deadline_at": get_survey_deadline_at(survey, question_json),
        }), 200
    except Exception as e:
        logging.error(f"Survey deadline update failed: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({"error": "截止時間更新失敗", "detail": str(e)}), 500

@survey_bp.route('/api/surveys/<access_code>/responses', methods=['GET'])
def get_survey_responses(access_code):
    auth_user_id, auth_error = verify_token(request)
    if auth_error:
        return jsonify({"error": "Unauthorized"}), 401
    survey = find_survey_by_access_or_short_code(access_code)
    if not survey:
        return jsonify({"error": "找不到這份問卷"}), 404
    if survey.user_id != auth_user_id:
        return jsonify({"error": "無權限"}), 403
    responses = Survey_Response.query.filter_by(
        template_id=survey.template_id
    ).order_by(Survey_Response.submitted_at.asc()).all()
    return jsonify({
        "responses": [
            {
                "response_id":         r.response_id,
                "submitted_at":        r.submitted_at.isoformat() if r.submitted_at else None,
                "answers":             (r.answer_json or {}).get("answers", {}),
                "respondent_identity": (r.answer_json or {}).get("respondent_identity"),
            }
            for r in responses
        ]
    }), 200

@survey_bp.route('/api/surveys/<access_code>/responses', methods=['POST'])
def submit_survey_response(access_code):
    data = request.get_json(silent=True) or {}
    if not isinstance(data.get('answers'), dict):
        return jsonify({"error": "缺少問卷答案資料"}), 400

    try:
        survey = find_survey_by_access_or_short_code(access_code)
        if not survey:
            return jsonify({"error": "找不到此邀請碼對應的問卷"}), 404

        question_json = survey.question_json or {}
        deadline_at = get_survey_deadline_at(survey, question_json)
        if is_survey_expired(question_json, survey.due_date):
            return jsonify({
                "error": "這份問卷已截止",
                "expired": True,
                "deadline_at": deadline_at,
            }), 410

        response = Survey_Response(
            template_id=survey.template_id,
            answer_json={
                "answers": data.get('answers'),
                "respondent_identity": data.get('respondent_identity'),
            },
        )
        db.session.add(response)
        db.session.commit()
        return jsonify({
            "message": "問卷送出成功",
            "response_id": response.response_id,
        }), 201
    except Exception as e:
        logging.error(f"Survey response submission failed: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({"error": "問卷送出失敗", "detail": str(e)}), 500


@survey_bp.route('/api/surveys/<access_code>/bind', methods=['PATCH'])
def bind_survey_to_workspace(access_code):
    auth_user_id, auth_error = verify_token(request)
    if auth_error:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    project_id = data.get('project_id')
    if not project_id:
        return jsonify({"error": "請提供 project_id"}), 400

    survey = find_survey_by_access_or_short_code(access_code)
    if not survey:
        return jsonify({"error": "找不到問卷"}), 404
    if survey.user_id != auth_user_id:
        return jsonify({"error": "無權限"}), 403

    return jsonify({
        "message": "綁定成功",
        "project_id": project_id,
    }), 200


# ═══════════════════════════════════════════════════════════════
# 【新增｜問卷原始回覆匯出】GET /api/surveys/<access_code>/export
#
# 設計定案：即時產生、即時下載，不寫入 Export_File、不建立
# Chat_History、不要求問卷先匯入 Workspace、不動 Export_File
# schema、不新增 DB table/column。
#
# 原因：Export_File 目前的 ownership 鏈是
#     Export_File -> Chat_History -> Workspace -> User
# 但問卷原始回覆直接屬於 Survey_Template.user_id，跟上面那條鏈是不同
# 的 domain。硬要共用 Export_File 只會製造不合理的資料關聯（例如
# 為了塞進一筆 Export_File 而先建一個跟這次匯出無關的假 Chat_History），
# 所以問卷匯出直接從 Survey_Template / Survey_Response 查詢後即時產生
# 檔案回傳，不經過 Export_File 這張表。既有 /api/exports 系列 API、
# Export_File 資料表、build_xlsx()/build_docx() 分類結果的輸出行為，
# 這裡完全不動。
# ═══════════════════════════════════════════════════════════════

# 各格式對應的副檔名與 MIME type，下載時要用（獨立於
# routes/exports/export.py 的 _FORMAT_META，避免這兩支互不相關的路由
# 彼此 import 對方的私有實作細節）。
_SURVEY_EXPORT_FORMAT_META = {
    "xlsx": {
        "ext": "xlsx",
        "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    },
    "docx": {
        "ext": "docx",
        "mimetype": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    },
}

# 檔名裡不能出現的字元：路徑分隔符號、Windows 保留字元、控制字元。
_UNSAFE_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def _sanitize_survey_export_filename_part(name):
    """把問卷標題清成可以安全放進檔名的字串。中文字元原樣保留——
    下載時走 RFC 5987 filename* 的 UTF-8 percent-encoding，不受影響；
    只需要濾掉會讓檔案系統或 HTTP header 出問題的符號。"""
    cleaned = _UNSAFE_FILENAME_CHARS.sub("", str(name or "")).strip()
    return cleaned or "問卷回覆"


@survey_bp.route('/api/surveys/<access_code>/export', methods=['GET'])
def export_survey_responses(access_code):
    """
    匯出「問卷原始回覆」成 Excel 或 Word，即時產生、即時下載。

    權限完全比照既有 get_survey_responses()：只有問卷擁有者可以匯出，
    公開填答者即使知道 access_code，也無法下載全部問卷回覆。
    """
    auth_user_id, auth_error = verify_token(request)
    if auth_error:
        return jsonify({"error": "Unauthorized"}), 401

    survey = find_survey_by_access_or_short_code(access_code)
    if not survey:
        return jsonify({"error": "找不到這份問卷"}), 404

    if survey.user_id != auth_user_id:
        return jsonify({"error": "無權限"}), 403

    export_format = (request.args.get("format") or "").strip().lower()
    format_meta = _SURVEY_EXPORT_FORMAT_META.get(export_format)
    if not format_meta:
        return jsonify({"error": "format 參數僅支援 xlsx 或 docx"}), 400

    responses = Survey_Response.query.filter_by(
        template_id=survey.template_id
    ).order_by(Survey_Response.submitted_at.asc()).all()

    if not responses:
        return jsonify({"error": "目前尚無問卷回覆可供匯出"}), 400

    question_json = survey.question_json or {}
    # 題目順序必須完全依 question_json.items 原始順序，不能自行排序。
    questions = question_json.get("items") or []
    identity_mode = question_json.get("identity_mode") or (
        "anonymous" if survey.is_anonymous else "identified"
    )

    # 這裡刻意不直接把 Survey_Response ORM 物件傳進 builder，而是先轉成
    # 單純的 dict：builder（export_file_service.py）不需要、也不應該
    # 知道 SQLAlchemy model 的存在，職責切乾淨、也方便之後單獨對 builder
    # 寫不依賴資料庫的單元測試。res_iden 欄位是目前完全沒被使用的舊欄位
    # （見分析報告），這裡刻意不讀它，一律用 answer_json.respondent_identity。
    response_payload = [
        {
            "answers": (r.answer_json or {}).get("answers") or {},
            "respondent_identity": (r.answer_json or {}).get("respondent_identity"),
            "submitted_at": r.submitted_at,
        }
        for r in responses
    ]

    try:
        if export_format == "xlsx":
            file_bytes = build_survey_xlsx(
                title=survey.title,
                questions=questions,
                responses=response_payload,
                identity_mode=identity_mode,
            )
        else:
            file_bytes = build_survey_docx(
                title=survey.title,
                questions=questions,
                responses=response_payload,
                identity_mode=identity_mode,
            )
    except Exception:
        # 不把完整 exception/stack trace 暴露給前端，只記在後端 log。
        logging.error(
            f"問卷匯出檔案產生失敗：template_id={survey.template_id}, format={export_format}",
            exc_info=True,
        )
        return jsonify({"error": "問卷匯出檔案產生失敗，請稍後再試"}), 500

    safe_title = _sanitize_survey_export_filename_part(survey.title)
    export_filename = f"{safe_title}_問卷回覆.{format_meta['ext']}"

    # 中文檔名走 RFC 5987/6266：filename 放純英數保底檔名（給不支援新
    # 標準的舊工具用），filename* 用 UTF-8 + percent-encoding 放真正的
    # 中文檔名。比照 routes/exports/export.py 的 download_export() 既有
    # 作法，避免中文檔名在 gunicorn 送出回應時因 Content-Disposition
    # 只能是 Latin-1 字元而整個 worker 500。
    encoded_filename = quote(export_filename)
    content_disposition = (
        f"attachment; filename=\"survey_export.{format_meta['ext']}\"; "
        f"filename*=UTF-8''{encoded_filename}"
    )

    return Response(
        file_bytes,
        mimetype=format_meta["mimetype"],
        headers={"Content-Disposition": content_disposition},
    )