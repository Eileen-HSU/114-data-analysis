"""
分類相關 API：
  POST /api/survey-response          -> 送出系統問卷，自動拆解文字題並分類
  POST /api/classification/upload    -> 上傳 Excel，逐列分類
  GET  /api/classification/<response_id> -> 查詢某份問卷的所有分類結果

routing／segmentation／classification 的完整資料流：

    answer_text
        ↓
    mask_pii_with_mapping() + segmentation_service（在 classify_v2.py 內部完成）
        ↓
    classify_response_multi_segment(answer_text, prompt_content, question_type)
        ↓
    {segmentation_status, segmentation_error_detail, segments:[...]}
        ↓
    _persist_segmentation_result()：
        寫 1 筆 Response_Segmentation_Status（回答層級現況快照）
        寫 0~N 筆 Response_Classification（每個驗證通過的 segment 各一筆）

question_type 的來源（這兩者都是「一次性」判斷，不是每則回答判斷一次）：
    survey：      Survey_Template.question_json 裡每題各自的 question_type
                  （建立問卷時由 question_routing_service 自動判斷一次）
    user_upload： 上傳當下，用「欄位名稱 + 遮罩後樣本」呼叫
                  question_routing_service 判斷一次，整批共用

question_type 判斷不出來（None）時：
    survey：      該題跳過分類，原始回答仍在 Survey_Response.answer_json
    user_upload： 原始內容仍寫入 Uploaded_Answer，但不進 segmentation/classification
"""

import uuid

from flask import Blueprint, jsonify, request
from extensions import db
from models import (
    Survey_Response,
    Survey_Template,
    Prompt_Template,
    Response_Classification,
    Response_Segmentation_Status,
    Uploaded_Answer,
)
from services.classify_v2 import classify_response_multi_segment, is_text_response
from services.privacy_service import mask_pii, PiiMaskingError
from services.question_routing_service import route_question_type
import pandas as pd

classification_bp = Blueprint("classification", __name__)

_MAX_ROUTING_SAMPLES = 5


def _build_routing_context(column_name: str, samples: list) -> str:
    if not samples:
        return f"欄位名稱：{column_name}"
    sample_block = "\n".join(f"- {s}" for s in samples)
    return f"欄位名稱：{column_name}\n\n實際回答範例（已遮罩個資）：\n{sample_block}"


def _collect_masked_routing_samples(df, text_column: str) -> list:
    """
    取前 _MAX_ROUTING_SAMPLES 筆非空文字樣本，各自用既有 mask_pii()
    遮罩後才能拿去給 routing 用。任何一筆 masking 失敗，直接排除
    那一筆，不拿原文 fallback；不會因為單筆失敗就整個中止取樣。
    """
    samples = []
    for val in df[text_column]:
        if len(samples) >= _MAX_ROUTING_SAMPLES:
            break
        if not is_text_response(val):
            continue
        try:
            samples.append(mask_pii(str(val)))
        except PiiMaskingError as e:
            print("[ROUTING SAMPLE MASKING FAILED]", repr(e))
            continue
    return samples


def _persist_segmentation_result(
    result: dict,
    source_type: str,
    answer_text: str,
    question_id: str,
    response_id: int = None,
    upload_batch_id: str = None,
    uploaded_answer_id: int = None,
):
    """
    把 classify_response_multi_segment() 的回傳結果寫進 DB：
    1 筆 Response_Segmentation_Status（回答層級現況）+
    0~N 筆 Response_Classification（每個驗證通過的 segment 各一筆）。

    只負責 db.session.add()，不呼叫 commit()，交給呼叫端統一 commit。

    回傳 (status_row, classification_rows)，供呼叫端組 API 回應用。
    """
    status_row = Response_Segmentation_Status(
        response_id=response_id,
        upload_batch_id=upload_batch_id,
        uploaded_answer_id=uploaded_answer_id,
        question_id=question_id,
        source_type=source_type,
        segmentation_status=result["segmentation_status"],
        error_detail=result["segmentation_error_detail"],
    )
    db.session.add(status_row)

    classification_rows = []
    for seg in result["segments"]:
        # Response_Classification 目前沒有獨立的 error_detail 欄位，
        # 分類失敗（status != completed）時，把 error_detail 放進
        # reasoning（該情況下 Gemini 本來就沒有真正的 reasoning 可存），
        # 避免除錯資訊被默默丟棄，同時不需要為此新增欄位。
        reasoning = seg["reasoning"]
        if seg["status"] != "completed" and seg.get("error_detail"):
            reasoning = seg["error_detail"]

        row = Response_Classification(
            response_id=response_id,
            upload_batch_id=upload_batch_id,
            uploaded_answer_id=uploaded_answer_id,
            source_type=source_type,
            question_id=question_id,
            answer_text=answer_text,
            segment_start=seg["orig_start"],
            segment_end=seg["orig_end"],
            main_category=seg["main_category"],
            sub_category=seg["sub_category"],
            secondary_sub_category=seg["secondary_sub_category"],
            reasoning=reasoning,
            summary=seg["summary"],
            methodology=seg["methodology"],
            citation=seg["citation"],
            secondary_methodology=seg["secondary_methodology"],
            secondary_citation=seg["secondary_citation"],
            status=seg["status"],
        )
        db.session.add(row)
        classification_rows.append(row)

    return status_row, classification_rows


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

    # 建立 question_id -> question_type 對照（來自建立問卷時的 routing 結果）
    question_type_map = {}
    template = Survey_Template.query.get(template_id)
    if template and template.question_json:
        for item in template.question_json.get("items", []):
            question_type_map[item.get("id")] = item.get("question_type")

    all_classification_rows = []
    classified_question_count = 0
    skipped_question_ids = []

    for question_id, answer in answers.items():
        if not is_text_response(answer):
            continue

        question_type = question_type_map.get(question_id)
        if not question_type:
            # routing 沒有結果（None）或這題不在 question_json 裡：
            # 跳過分類，原始回答本來就已經完整存在 survey.answer_json，不受影響
            skipped_question_ids.append(question_id)
            continue

        prompt_row = Prompt_Template.query.get(question_type)
        if prompt_row is None:
            # 理論上 question_type 合法值都應該有對應 Prompt_Template；
            # 真的查不到時保守跳過，不讓整個問卷送出失敗
            skipped_question_ids.append(question_id)
            continue

        answer_text = str(answer)
        result = classify_response_multi_segment(answer_text, prompt_row.live_content, question_type)
        _, rows = _persist_segmentation_result(
            result,
            source_type="survey",
            answer_text=answer_text,
            question_id=question_id,
            response_id=survey.response_id,
        )
        all_classification_rows.extend(rows)
        classified_question_count += 1

    db.session.commit()

    return jsonify({
        "response_id": survey.response_id,
        "classified_question_count": classified_question_count,
        "skipped_question_ids": skipped_question_ids,
        "classifications": [r.to_dict() for r in all_classification_rows],
    }), 201


# ---------- 2. Excel 上傳分類 ----------
@classification_bp.route("/api/classification/upload", methods=["POST"])
def upload_excel_for_classification():
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "請提供檔案"}), 400

    df = pd.read_excel(file)
    text_column = request.form.get("text_column")
    if not text_column or text_column not in df.columns:
        return jsonify({"error": "請指定有效的 text_column 欄位名稱"}), 400

    upload_batch_id = str(uuid.uuid4())

    # 一次上傳只 routing 一次：欄位名稱 + 前幾筆遮罩後樣本
    samples = _collect_masked_routing_samples(df, text_column)
    routing_context = _build_routing_context(text_column, samples)
    question_type = route_question_type(routing_context)

    prompt_row = None
    if question_type:
        prompt_row = Prompt_Template.query.get(question_type)
        if prompt_row is None:
            # 理論上不該發生；保守處理成沒有 routing 結果
            question_type = None

    saved_answer_count = 0
    classified_count = 0
    all_classification_rows = []

    for idx, row in df.iterrows():
        answer = row[text_column]
        if not is_text_response(answer):
            continue

        answer_text = str(answer)

        # 不論 routing 有沒有結果，原始內容一律先保存
        uploaded_answer = Uploaded_Answer(
            upload_batch_id=upload_batch_id,
            source_column=text_column,
            row_index=idx,
            answer_text=answer_text,
            question_type=question_type,
        )
        db.session.add(uploaded_answer)
        db.session.flush()  # 取得 uploaded_answer.id，供下面 FK 使用
        saved_answer_count += 1

        if question_type and prompt_row:
            result = classify_response_multi_segment(answer_text, prompt_row.live_content, question_type)
            _, rows = _persist_segmentation_result(
                result,
                source_type="user_upload",
                answer_text=answer_text,
                question_id=f"{text_column}_row{idx}",
                upload_batch_id=upload_batch_id,
                uploaded_answer_id=uploaded_answer.id,
            )
            all_classification_rows.extend(rows)
            classified_count += 1
        # question_type 沒有結果：這筆 Uploaded_Answer 已經保存，
        # 停在「待處理」狀態，不建立 Response_Segmentation_Status /
        # Response_Classification

    db.session.commit()

    return jsonify({
        "upload_batch_id": upload_batch_id,
        "question_type": question_type,
        "saved_answer_count": saved_answer_count,
        "classified_count": classified_count,
        "classifications": [r.to_dict() for r in all_classification_rows],
    }), 201


# ---------- 3. 查詢分類結果 ----------
@classification_bp.route("/api/classification/<int:response_id>", methods=["GET"])
def get_classifications(response_id):
    records = Response_Classification.query.filter_by(response_id=response_id).all()
    return jsonify({
        "response_id": response_id,
        "classifications": [r.to_dict() for r in records],
    }), 200