"""
分類相關 API：
  POST /api/survey-response              -> （legacy，見下方說明）
  POST /api/surveys/<access_code>/analyze -> 觸發整份問卷的批次分析
  POST /api/classification/upload         -> 上傳 Excel，批次分類
  GET  /api/classification/<response_id>  -> 查詢某份問卷的所有分類結果

關於 /api/survey-response：
    這支路由目前沒有被前端呼叫（真正的問卷填答路徑是
    routes/surveys/survey.py 的 POST /api/surveys/<access_code>/responses，
    那支只保存 answer_json，不做任何分類）。這支路由先保留、不刪除，
    但新的批次分析（/analyze）完全不會呼叫它，兩者互不依賴。等新的
    批次流程完整驗證過，再另外決定要不要清理這支孤兒端點。

survey 批次分析的設計：
    填答階段（POST .../responses）只保存原始回答，不觸發任何 Gemini
    呼叫。使用者之後主動觸發 POST .../analyze，才依 template_id 撈出
    所有 Survey_Response，依 question_id 分組（不同題目的回答絕對不會
    混在一起做去重），每組各自呼叫 batch_classification_service 做
    去重 + 批次分類。已經有 Response_Segmentation_Status 紀錄的回答
    （不論狀態是 completed / partial_failed / failed）一律視為「已
    處理」，不會被重新送 Gemini，但仍然可以作為新回答的 duplicate
    reference。

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
from services.batch_classification_service import run_batch_analysis
from services.aggregated_summary_service import build_aggregated_summary, AggregatedSummaryError
from routes.surveys.survey import verify_token, find_survey_by_access_or_short_code
import pandas as pd

classification_bp = Blueprint("classification", __name__)


# 【新增｜受試者分組彙整】把「一筆分類一列」的結果，依 (大類別、子類別)
# 分組成一列，同一組內所有受試者片段合併顯示、「判斷原因」跟「建議摘要」
# 各自再呼叫一次 build_aggregated_summary() 統整成一段話。
# 「無具體建議」這種勉強歸類的結果，分組前就先排除，不參與彙整、不顯示。
def _build_aggregated_groups(all_classification_rows, answer_id_to_row_index):
    groups = {}  # (main_category, sub_category) -> {"items": [...]}
    order = []   # 記錄分組第一次出現的順序，回傳時維持穩定順序

    for r in all_classification_rows:
        sub_category = r.sub_category or ""
        if "無具體建議" in sub_category:
            continue  # 這種萬用分類不該出現在彙整結果裡

        key = (r.main_category or "", sub_category)
        if key not in groups:
            groups[key] = {"items": []}
            order.append(key)

        row_index = answer_id_to_row_index.get(r.uploaded_answer_id)
        excerpt = r.answer_text
        if (
            isinstance(r.segment_start, int)
            and isinstance(r.segment_end, int)
            and 0 <= r.segment_start < r.segment_end <= len(r.answer_text)
        ):
            excerpt = r.answer_text[r.segment_start:r.segment_end]

        groups[key]["items"].append({
            "respondent_number": (row_index + 1) if row_index is not None else None,
            "excerpt": excerpt,
            "reasoning": r.reasoning or "",
            "summary": r.summary or "",
        })

    result = []
    for key in order:
        main_category, sub_category = key
        items = groups[key]["items"]

        respondent_text = "\n".join(
            f"受試者{it['respondent_number']}：{it['excerpt']}"
            if it["respondent_number"] is not None else it["excerpt"]
            for it in items
        )

        # 彙整這一步失敗時（Gemini 出錯、格式跑掉），不能讓整支 API 跟著
        # 失敗——每個人的分類結果已經成功存進資料庫了，退回成簡單拼接文字，
        # 並標記 synthesis_status 讓前端知道這組是 fallback 出來的。
        synthesis_status = "ok"
        try:
            reasoning_items = [{"matched_segment_text": it["reasoning"]} for it in items if it["reasoning"]]
            aggregated_reasoning = (
                build_aggregated_summary(main_category, sub_category, reasoning_items)
                if reasoning_items else ""
            )
            summary_items = [{"matched_segment_text": it["summary"]} for it in items if it["summary"]]
            aggregated_summary = (
                build_aggregated_summary(main_category, sub_category, summary_items)
                if summary_items else ""
            )
        except AggregatedSummaryError as e:
            print("[AGGREGATED_SUMMARY_FAILED]", repr(e))
            synthesis_status = "fallback"
            aggregated_reasoning = "；".join(it["reasoning"] for it in items if it["reasoning"])
            aggregated_summary = "；".join(it["summary"] for it in items if it["summary"])

        result.append({
            "main_category": main_category,
            "sub_category": sub_category,
            "respondent_text": respondent_text,
            "aggregated_reasoning": aggregated_reasoning,
            "aggregated_summary": aggregated_summary,
            "synthesis_status": synthesis_status,
            "respondent_count": len(items),
        })

    return result

_MAX_ROUTING_SAMPLES = 5


def _build_routing_context(column_name: str, samples: list) -> str:
    if not samples:
        return f"欄位名稱：{column_name}"
    sample_block = "\n".join(f"- {s}" for s in samples)
    return f"欄位名稱：{column_name}\n\n實際回答範例（已遮罩個資）：\n{sample_block}"


# 【新增｜2026-08-27｜串接前端「不用手動輸入欄位名稱」的需求】
# 使用者上傳 Excel 時不再需要自己打文字欄位名稱，改由後端自動判斷。
# 判斷邏輯：只看文字型（非數字）欄位，排除明顯是 ID / 編號的欄位名稱，
# 在剩下的欄位裡取「平均字數最長」的那一欄——開放式回答通常比姓名、
# 選項這類欄位長很多，用平均字數是最穩定、不用額外套件的判斷方式。
_ID_LIKE_COLUMN_KEYWORDS = ("id", "編號", "序號", "代碼", "code", "no.", "no")


def _auto_detect_text_column(df):
    candidates = []
    for col in df.columns:
        col_str = str(col).strip().lower()
        if col_str in _ID_LIKE_COLUMN_KEYWORDS:
            continue
        if pd.api.types.is_numeric_dtype(df[col]) or pd.api.types.is_bool_dtype(df[col]):
            continue
        series = df[col].dropna().astype(str)
        if series.empty:
            continue
        avg_len = series.str.len().mean()
        if avg_len < 2:  # 太短的欄位（例如姓名、代號）不太可能是開放式回答
            continue
        candidates.append((col, avg_len))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[0][0]


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
    # Human Review 需要知道「這批上傳是誰的」才能做 ownership 判斷，
    # 因此這條路由從這次改動起強制要求登入；沿用既有 verify_token()，
    # 不另建第二套 authentication。
    auth_user_id, auth_error = verify_token(request)
    if auth_error:
        return jsonify({"error": "Unauthorized"}), 401

    file = request.files.get("file")
    if not file:
        return jsonify({"error": "請提供檔案"}), 400

    df = pd.read_excel(file)
    text_column = request.form.get("text_column")

    # 【新增｜2026-08-27】前端不再強制使用者輸入欄位名稱：
    # 沒有提供、或提供的欄位名稱不存在時，自動判斷最可能的開放式文字欄位。
    # 仍然保留手動指定 text_column 的能力（例如未來別的呼叫端要精準指定時可用）。
    auto_detected = False
    if not text_column or text_column not in df.columns:
        text_column = _auto_detect_text_column(df)
        auto_detected = True

    if not text_column or text_column not in df.columns:
        return jsonify({"error": "無法自動判斷文字欄位，請確認 Excel 內容是否包含開放式文字回答"}), 400

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
    # 【新增｜受試者編號】記錄「這筆 Uploaded_Answer 對應到 Excel 裡第幾列」，
    # 這樣分類結果回傳時才能標出「受試者N」，方便對照原始資料。
    # 只在這支 route 的回應裡組出來，不寫進資料庫，不影響任何既有欄位/表格。
    answer_id_to_row_index = {}

    # 先把整批要送分類的資料收集起來（Uploaded_Answer 不論
    # question_type 有沒有結果都先各自保存），question_type 有結果時
    # 才收進 pending_items，交給批次協調服務一次處理整批（同一次
    # upload_batch_id + source_column 內部互相去重，不需要每列各自
    # 呼叫 Gemini）。upload_batch_id 每次上傳都是全新 UUID，所以這裡
    # 的 existing_references 永遠是空清單——不可能有「這批資料裡有些
    # 是舊的、已經分析過」的情況。
    pending_items = []  # 每個元素額外帶一個 _question_id，DB 寫入時才用得到

    for idx, row in df.iterrows():
        answer = row[text_column]
        if not is_text_response(answer):
            continue

        answer_text = str(answer)

        uploaded_answer = Uploaded_Answer(
            upload_batch_id=upload_batch_id,
            user_id=auth_user_id,
            source_column=text_column,
            row_index=idx,
            answer_text=answer_text,
            question_type=question_type,
        )
        db.session.add(uploaded_answer)
        db.session.flush()  # 取得 uploaded_answer.id，供下面 FK 使用
        answer_id_to_row_index[uploaded_answer.id] = idx
        saved_answer_count += 1

        if question_type and prompt_row:
            pending_items.append({
                "identifier": uploaded_answer.id,
                "answer_text": answer_text,
                "_question_id": f"{text_column}_row{idx}",
            })
        # question_type 沒有結果：這筆 Uploaded_Answer 已經保存，
        # 停在「待處理」狀態，不建立 Response_Segmentation_Status /
        # Response_Classification

    if pending_items:
        results = run_batch_analysis(
            existing_references=[],
            pending_items=[
                {"identifier": item["identifier"], "answer_text": item["answer_text"]}
                for item in pending_items
            ],
            prompt_content=prompt_row.live_content,
            question_type=question_type,
        )
        for item, result in zip(pending_items, results):
            _, rows = _persist_segmentation_result(
                result,
                source_type="user_upload",
                answer_text=item["answer_text"],
                question_id=item["_question_id"],
                upload_batch_id=upload_batch_id,
                uploaded_answer_id=item["identifier"],
            )
            all_classification_rows.extend(rows)
            classified_count += 1

    db.session.commit()

    # 【新增｜受試者編號】把 row_index 換算成「受試者N」（從 1 開始比較符合
    # 一般人講話習慣），組進每一筆分類結果的字典裡，不動 to_dict() 本身、
    # 不動資料庫，只在這支 API 回傳前額外加一個欄位。
    classifications_payload = []
    for r in all_classification_rows:
        d = r.to_dict()
        row_index = answer_id_to_row_index.get(r.uploaded_answer_id)
        d["respondent_number"] = (row_index + 1) if row_index is not None else None
        classifications_payload.append(d)

    # 【新增｜受試者分組彙整】依類別分組、合併受試者片段、統整判斷原因與建議摘要
    aggregated_groups = _build_aggregated_groups(all_classification_rows, answer_id_to_row_index)

    return jsonify({
        "upload_batch_id": upload_batch_id,
        "question_type": question_type,
        "saved_answer_count": saved_answer_count,
        "classified_count": classified_count,
        "classifications": classifications_payload,
        "aggregated_groups": aggregated_groups,
        # 【新增｜2026-08-27】讓前端可以顯示「系統自動判斷用的是哪一欄」，
        # 方便使用者確認判斷得對不對，判斷錯的話也知道問題出在哪。
        "text_column": text_column,
        "text_column_auto_detected": auto_detected,
    }), 201


# ---------- 3. 觸發整份問卷的批次分析 ----------
@classification_bp.route("/api/surveys/<access_code>/analyze", methods=["POST"])
def analyze_survey(access_code):
    """
    使用者主動觸發，對整份問卷（同一 template_id）依 question_id 分組，
    每組各自去重 + 批次分類。已經有 Response_Segmentation_Status 紀錄
    的回答（不論狀態）一律視為已處理，不重新送 Gemini，但仍可作為
    duplicate reference；只有真正沒有紀錄的回答才會被送進批次協調服務。
    """
    auth_user_id, auth_error = verify_token(request)
    if auth_error:
        return jsonify({"error": "Unauthorized"}), 401

    survey = find_survey_by_access_or_short_code(access_code)
    if not survey:
        return jsonify({"error": "找不到這份問卷"}), 404
    if survey.user_id != auth_user_id:
        return jsonify({"error": "無權限"}), 403

    template_id = survey.template_id
    question_json = survey.question_json or {}
    items = question_json.get("items", [])

    # 只處理已經有 routing 結果的開放式文字題；type != "short" 或
    # question_type 是 None 的題目，這裡完全不會碰
    question_type_map = {
        item.get("id"): item.get("question_type")
        for item in items
        if item.get("type") == "short" and item.get("question_type")
    }

    if not question_type_map:
        return jsonify({
            "template_id": template_id,
            "analyzed_question_ids": [],
            "newly_classified_count": 0,
        }), 200

    responses = Survey_Response.query.filter_by(template_id=template_id).all()

    analyzed_question_ids = []
    newly_classified_count = 0

    for question_id, question_type in question_type_map.items():
        prompt_row = Prompt_Template.query.get(question_type)
        if prompt_row is None:
            continue  # 理論上不該發生，保守跳過

        existing_references = []
        pending_items = []

        for response in responses:
            answers = (response.answer_json or {}).get("answers", {})
            if question_id not in answers:
                continue
            answer_value = answers[question_id]
            if not is_text_response(answer_value):
                continue
            answer_text = str(answer_value)

            existing_status = Response_Segmentation_Status.query.filter_by(
                response_id=response.response_id, question_id=question_id
            ).first()

            if existing_status is not None:
                # 已處理過（不論 completed / partial_failed / failed），
                # 不重新分類，但可以當 duplicate reference
                existing_rows = Response_Classification.query.filter_by(
                    response_id=response.response_id, question_id=question_id
                ).all()
                existing_references.append({
                    "identifier": response.response_id,
                    "answer_text": answer_text,
                    "segments": [
                        {
                            "orig_start": r.segment_start,
                            "orig_end": r.segment_end,
                            "main_category": r.main_category,
                            "sub_category": r.sub_category,
                            "secondary_sub_category": r.secondary_sub_category,
                            "reasoning": r.reasoning,
                            "summary": r.summary,
                            "methodology": r.methodology,
                            "citation": r.citation,
                            "secondary_methodology": r.secondary_methodology,
                            "secondary_citation": r.secondary_citation,
                            "status": r.status,
                        }
                        for r in existing_rows
                    ],
                })
            else:
                pending_items.append({
                    "identifier": response.response_id,
                    "answer_text": answer_text,
                })

        if not pending_items:
            continue  # 這題沒有新回答需要處理

        results = run_batch_analysis(
            existing_references, pending_items, prompt_row.live_content, question_type
        )

        for item, result in zip(pending_items, results):
            _persist_segmentation_result(
                result,
                source_type="survey",
                answer_text=item["answer_text"],
                question_id=question_id,
                response_id=item["identifier"],
            )
            newly_classified_count += 1

        analyzed_question_ids.append(question_id)

    db.session.commit()

    return jsonify({
        "template_id": template_id,
        "analyzed_question_ids": analyzed_question_ids,
        "newly_classified_count": newly_classified_count,
    }), 200


# ---------- 4. 查詢分類結果 ----------
@classification_bp.route("/api/classification/<int:response_id>", methods=["GET"])
def get_classifications(response_id):
    records = Response_Classification.query.filter_by(response_id=response_id).all()
    return jsonify({
        "response_id": response_id,
        "classifications": [r.to_dict() for r in records],
    }), 200