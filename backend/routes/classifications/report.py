"""
Report / Aggregation Readiness API：
  GET  /api/reports/<source_type>/<identifier>/readiness   Aggregation Readiness
  POST /api/reports/<source_type>/<identifier>/generate     產生新版本 Report Snapshot
  GET  /api/reports/<source_type>/<identifier>/versions     列出所有版本
  GET  /api/reports/<report_id>                             取得單一版本完整內容（快照）

<source_type> 只能是 survey 或 user_upload：
    survey     ：<identifier> 是 template_id（整數）
    user_upload：<identifier> 是 upload_batch_id（字串）

沿用既有 verify_token()；ownership 檢查全部在
services/report_service.py 裡做，這裡只負責解析 request/組 HTTP
response，不重複寫業務邏輯。
"""

from flask import Blueprint, jsonify, request

from routes.surveys.survey import verify_token
from report import SOURCE_TYPE_SURVEY, SOURCE_TYPE_USER_UPLOAD
from services import report_service
from services.report_service import ReportError

report_bp = Blueprint("report", __name__)


def _require_auth(req):
    auth_user_id, auth_error = verify_token(req)
    if auth_error:
        return None, (jsonify({"error": "Unauthorized"}), 401)
    return auth_user_id, None


def _parse_source(source_type, identifier):
    """把 URL 上的 <source_type>/<identifier> 轉成
    (template_id, upload_batch_id) 給 service 層用。回傳
    (template_id, upload_batch_id, error_response_or_None)。"""
    if source_type == SOURCE_TYPE_SURVEY:
        try:
            template_id = int(identifier)
        except (TypeError, ValueError):
            return None, None, (jsonify({"error": "survey 的 identifier 必須是 template_id（整數）"}), 400)
        return template_id, None, None

    if source_type == SOURCE_TYPE_USER_UPLOAD:
        return None, identifier, None

    return None, None, (jsonify({"error": "source_type 只能是 survey 或 user_upload"}), 400)


@report_bp.route("/api/reports/<source_type>/<identifier>/readiness", methods=["GET"])
def readiness(source_type, identifier):
    auth_user_id, err = _require_auth(request)
    if err:
        return err
    template_id, upload_batch_id, parse_err = _parse_source(source_type, identifier)
    if parse_err:
        return parse_err
    try:
        data = report_service.get_readiness_for(
            source_type, auth_user_id, template_id=template_id, upload_batch_id=upload_batch_id,
        )
        return jsonify(data), 200
    except ReportError as e:
        return jsonify({"error": e.message}), e.http_status


@report_bp.route("/api/reports/<source_type>/<identifier>/generate", methods=["POST"])
def generate(source_type, identifier):
    auth_user_id, err = _require_auth(request)
    if err:
        return err
    template_id, upload_batch_id, parse_err = _parse_source(source_type, identifier)
    if parse_err:
        return parse_err
    try:
        report = report_service.generate_report(
            source_type, auth_user_id, template_id=template_id, upload_batch_id=upload_batch_id,
        )
        status_code = 201 if report.status == "completed" else 500
        return jsonify(report.to_dict()), status_code
    except ReportError as e:
        return jsonify({"error": e.message}), e.http_status


@report_bp.route("/api/reports/<source_type>/<identifier>/versions", methods=["GET"])
def versions(source_type, identifier):
    auth_user_id, err = _require_auth(request)
    if err:
        return err
    template_id, upload_batch_id, parse_err = _parse_source(source_type, identifier)
    if parse_err:
        return parse_err
    try:
        data = report_service.list_versions(
            source_type, auth_user_id, template_id=template_id, upload_batch_id=upload_batch_id,
        )
        return jsonify({"versions": data}), 200
    except ReportError as e:
        return jsonify({"error": e.message}), e.http_status


@report_bp.route("/api/reports/<int:report_id>", methods=["GET"])
def get_report(report_id):
    auth_user_id, err = _require_auth(request)
    if err:
        return err
    try:
        data = report_service.get_report_detail(report_id, auth_user_id)
        return jsonify(data), 200
    except ReportError as e:
        return jsonify({"error": e.message}), e.http_status
