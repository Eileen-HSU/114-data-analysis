"""
分類相關 API：
  POST /api/survey-response          -> 送出系統問卷，自動拆解文字題並分類
  POST /api/classification/upload    -> 上傳 Excel，逐列分類
  GET  /api/classification/<response_id> -> 查詢某份問卷的所有分類結果
"""

from flask import Blueprint, jsonify, request
from extensions import db
from models import Survey_Response, Response_Classification
from routes.auth.classify import classify_response, is_text_response
import pandas as pd

classification_bp = Blueprint("classification", __name__)


def _save_classification(answer_text, source_type, response_id=None, question_id=None):
    """呼叫分類服務並寫入一筆 Response_Classification，失敗時 fallback 為「其他」"""
    record = Response_Classification(
        response_id=response_id,
        source_type=source_type,
        question_id=question_id,
        answer_text=answer_text,
    )
    try:
        result = classify_response(answer_text)
        record.main_category = result["main_category"]
        record.sub_category  = result["sub_category"]
        record.reasoning     = result["reasoning"]
        record.summary       = result["summary"]
        record.methodology   = result["methodology"]
        record.status        = "completed"
    except Exception as e:
        print("[CLASSIFY ERROR]", repr(e))
        record.main_category = "其他"
        record.sub_category  = "其他"
        record.reasoning     = "分類失敗，待人工檢視"
        record.summary       = ""
        record.methodology   = "其他"
        record.status        = "failed"

    db.session.add(record)
    return record


# ---------- 1. 系統問卷送出 ----------
@classification_bp.route("/api/survey-response", methods=["POST"])
def submit_survey_response():
    data = request.get_json(silent=True) or {}
    template_id = data.get("template_id")
    answers = (data.get("answer_json") or {}).get("answers", {})

    if not template_id or not answers:
        return jsonify({"error": "缺少 template_id 或 answers"}), 400

    survey = Survey_Response(template_id=template_id, answer_json=data.get("answer_json"))
    db.session.add(survey)
    db.session.flush()  # 先取得 response_id，還沒 commit

    classified = []
    for question_id, answer in answers.items():
        if is_text_response(answer):
            record = _save_classification(
                answer_text=str(answer),
                source_type="survey",
                response_id=survey.response_id,
                question_id=question_id,
            )
            classified.append(record)

    db.session.commit()

    return jsonify({
        "response_id": survey.response_id,
        "classified_count": len(classified),
        "classifications": [r.to_dict() for r in classified],
    }), 201


# ---------- 2. Excel 上傳分類 ----------
@classification_bp.route("/api/classification/upload", methods=["POST"])
def upload_excel_for_classification():
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "請提供檔案"}), 400

    df = pd.read_excel(file)
    text_column = request.form.get("text_column")  # 前端指定哪一欄是文字回答
    if not text_column or text_column not in df.columns:
        return jsonify({"error": "請指定有效的 text_column 欄位名稱"}), 400

    classified = []
    for idx, row in df.iterrows():
        answer = row[text_column]
        if is_text_response(answer):
            record = _save_classification(
                answer_text=str(answer),
                source_type="user_upload",
                response_id=None,
                question_id=f"{text_column}_row{idx}",
            )
            classified.append(record)

    db.session.commit()

    return jsonify({
        "classified_count": len(classified),
        "classifications": [r.to_dict() for r in classified],
    }), 201


# ---------- 3. 查詢分類結果 ----------
@classification_bp.route("/api/classification/<int:response_id>", methods=["GET"])
def get_classifications(response_id):
    records = Response_Classification.query.filter_by(response_id=response_id).all()
    return jsonify({
        "response_id": response_id,
        "classifications": [r.to_dict() for r in records],
    }), 200