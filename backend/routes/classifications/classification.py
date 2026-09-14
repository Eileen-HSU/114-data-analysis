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
from services.classify_v2 import classify_response_multi_segment, is_text_response, DYNAMIC_GENERAL_PROMPT
from services.privacy_service import mask_pii, PiiMaskingError
from services.question_routing_service import route_question_type
from services.batch_classification_service import run_batch_analysis
from services.aggregated_summary_service import build_aggregated_summary, build_aggregated_summary_pair, AggregatedSummaryError
from services.subcategory_methodology import all_subcategories, QUESTION_OTHER
from routes.surveys.survey import verify_token, find_survey_by_access_or_short_code
import pandas as pd

classification_bp = Blueprint("classification", __name__)


# 【新增｜受試者分組彙整】把「一筆分類一列」的結果，依 (大類別、子類別)
# 分組成一列，同一組內所有受試者片段合併顯示、「判斷原因」跟「建議摘要」
# 各自再呼叫一次 build_aggregated_summary() 統整成一段話。
# 「無具體建議」這種勉強歸類的結果，分組前就先排除，不參與彙整、不顯示。
def _build_aggregated_groups(all_classification_rows, id_to_row_index, question_type, id_field="uploaded_answer_id"):
    """
    依 (大類別、子類別) 分組、合併受試者片段、彙整判斷原因與建議摘要。

    id_field: 用哪個欄位當「受試者編號」的查表 key。Excel 上傳來源用
        "uploaded_answer_id"（原本的行為，預設值，不影響既有呼叫端）；
        問卷來源改用 "response_id"，因為問卷的 Response_Classification
        沒有 uploaded_answer_id（那是 Excel 上傳專用欄位），而是用
        response_id 對應到是哪一筆問卷回覆。
    """
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

        row_index = id_to_row_index.get(getattr(r, id_field))
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

    # 【修正｜排序】原本是「哪個類別先出現在資料裡就排第幾個」，等於是隨機的。
    # 改成照 subcategory_methodology.py 裡固定清單本來的順序排（A1、A2、A3…、
    # B1、B2…），跟你們團隊文件裡的排法一致。清單裡查不到的子類別（理論上
    # 不該發生，但保守起見還是處理一下）排在最後面，順序照它們原本出現的
    # 先後，不會憑空消失。
    canonical_order = all_subcategories(question_type)
    order_index = {sub: i for i, sub in enumerate(canonical_order)}
    order.sort(key=lambda key: order_index.get(key[1], len(canonical_order)))

    # 【新增｜子類別重新編號】原本的編號是完整清單裡的位置（例如這批資料
    # 只出現 A2、A5、A8，畫面上就會直接顯示 A2、A5、A8，看起來像跳號）。
    # 改成依照排序後「這批資料實際出現的順序」重新編號，字母（大類別
    # 對應的那個字母）保留，數字從 1 開始，同一個大類別底下依序累加、
    # 換下一個大類別時歸零重來。原始 sub_category 字串格式固定是
    # 「{字母}{數字} {說明文字}」（例如「A5 教育訓練」），用正則抓出
    # 字母跟說明文字，數字整個換成重新編過的。
    import re as _re
    renumbered_sub_category = {}
    counter_by_main = {}
    for key in order:
        main_category, sub_category = key
        m = _re.match(r"^([A-Za-z]+)\d+\s*(.*)$", sub_category)
        if m:
            letter, description = m.group(1), m.group(2)
            counter_by_main[main_category] = counter_by_main.get(main_category, 0) + 1
            renumbered_sub_category[key] = f"{letter}{counter_by_main[main_category]} {description}"
        else:
            # 格式不符預期（理論上不該發生）時，保留原字串，不硬套規則
            renumbered_sub_category[key] = sub_category

    result = []
    for key in order:
        main_category, sub_category = key
        items = groups[key]["items"]
        display_sub_category = renumbered_sub_category[key]

        # 【修正｜同一受試者被拆成多段時，同一組內連續出現的同一人合併成一行】
        # all_classification_rows 的順序本來就是「同一筆原始回答的所有 segment
        # 連續出現」，所以同一組（同一大類別/子類別）裡，同一個受試者的
        # 多個 segment 一定是相鄰的，可以簡單依序合併，不用另外排序。
        merged_lines = []
        for it in items:
            if (
                merged_lines
                and it["respondent_number"] is not None
                and merged_lines[-1]["respondent_number"] == it["respondent_number"]
            ):
                merged_lines[-1]["excerpt"] += it["excerpt"]
            else:
                merged_lines.append({
                    "respondent_number": it["respondent_number"],
                    "excerpt": it["excerpt"],
                })

        respondent_text = "\n".join(
            f"受試者{ml['respondent_number']}：{ml['excerpt']}"
            if ml["respondent_number"] is not None else ml["excerpt"]
            for ml in merged_lines
        )

        # 彙整這一步失敗時（Gemini 出錯、格式跑掉），不能讓整支 API 跟著
        # 失敗——每個人的分類結果已經成功存進資料庫了，退回成簡單拼接文字，
        # 並標記 synthesis_status 讓前端知道這組是 fallback 出來的。
        synthesis_status = "ok"
        synthesis_error = None
        try:
            reasoning_items = [{"matched_segment_text": it["reasoning"]} for it in items if it["reasoning"]]
            summary_items = [{"matched_segment_text": it["summary"]} for it in items if it["summary"]]
            # 合併成 1 次 Gemini 呼叫（原本 reasoning、summary 各打一次，
            # 一個 group 就要 2 次；免費層 RPM 額度緊，先從這裡減半）。
            aggregated_reasoning, aggregated_summary = build_aggregated_summary_pair(
                main_category, sub_category, reasoning_items, summary_items
            )
        except AggregatedSummaryError as e:
            print("[AGGREGATED_SUMMARY_FAILED]", repr(e))
            synthesis_status = "fallback"
            # 【新增】原本失敗原因只印在後端 log 裡，前端完全看不到，
            # 只能靠猜。現在把訊息也帶進回應裡，畫面上就能直接顯示。
            synthesis_error = str(e)[:300]
            aggregated_reasoning = "\n".join(it["reasoning"] for it in items if it["reasoning"])
            aggregated_summary = "\n".join(it["summary"] for it in items if it["summary"])

        result.append({
            "main_category": main_category,
            "sub_category": display_sub_category,
            "respondent_text": respondent_text,
            "aggregated_reasoning": aggregated_reasoning,
            "aggregated_summary": aggregated_summary,
            "synthesis_status": synthesis_status,
            "synthesis_error": synthesis_error,
            "respondent_count": len(items),
        })

    return result

_MAX_ROUTING_SAMPLES = 5


def _build_routing_context(column_name: str, samples: list) -> str:
    if not samples:
        return f"欄位名稱：{column_name}"
    sample_block = "\n".join(f"- {s}" for s in samples)
    return f"欄位名稱：{column_name}\n\n實際回答範例（已遮罩個資）：\n{sample_block}"


# 排除明顯是 ID / 編號的欄位名稱，不當成開放式文字回答欄位。
_ID_LIKE_COLUMN_KEYWORDS = ("id", "編號", "序號", "代碼", "code", "no.", "no")


def _detect_candidate_text_columns(df):
    """
    回傳「每一欄」看起來像開放式文字回答的欄位（依原始欄位順序），
    不是只挑一欄。

    【背景】原本的批次分類架構（services/batch_classification_service.py
    的 TF-IDF 去重）本來就是以 (upload_batch_id, source_column) 為單位
    各自去重、各自分類——設計上早就支援一份 Excel 有多個開放式問題
    （多個文字欄位）。但這支 route 之前只挑「看起來最像」的單一欄位
    分析，等於漏掉了其他欄位裡的受試者回答。這裡改成把所有合格欄位
    都找出來，呼叫端會對每一欄各自跑一次完整流程（各自 routing、
    各自 TF-IDF 去重、各自分類），彼此不會互相影響。

    篩選規則跟原本單欄判斷一致：排除明顯是 ID/編號的欄位名稱、排除
    數值/布林欄位、排除平均字數太短（< 2）的欄位（例如姓名、代號）。
    """
    candidates = []
    for col in df.columns:
        col_str = str(col).strip().lower()
        if col_str in _ID_LIKE_COLUMN_KEYWORDS:
            continue
        if pd.api.types.is_numeric_dtype(df[col]) or pd.api.types.is_bool_dtype(df[col]):
            continue
        series = df[col].dropna().astype(str)
        series = series[series.str.strip() != ""]
        if series.empty:
            continue
        avg_len = series.str.len().mean()
        if avg_len < 2:
            continue
        candidates.append(col)
    return candidates


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
        return jsonify({"error": "Missing template ID or answers"}), 400

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
        return jsonify({"error": "Please provide a file"}), 400

    df = pd.read_excel(file)
    text_column_param = request.form.get("text_column")
    total_row_count = len(df)

    # 【修正｜每個欄位都要分析，不能只挑一欄】
    # 原本這裡只自動判斷「一個」最像開放式回答的欄位，如果 Excel 裡
    # 有好幾個開放式問題（好幾個文字欄位），其他欄位的受試者回答會
    # 整批被漏掉，而且沒有任何提示——這正是先前「上傳 26 筆卻只跑出
    # 幾筆結果」的根本原因之一。
    #
    # 現在改成：沒有手動指定 text_column 時，把每一個看起來像開放式
    # 文字回答的欄位都找出來（_detect_candidate_text_columns），逐欄
    # 各自跑一次完整流程。TF-IDF 去重（services/batch_classification_service
    # 的 run_batch_analysis）本來就是以 (upload_batch_id, source_column)
    # 為單位各自比對，不同欄位的回答不會被誤判成重複，這裡沿用同一套
    # 邏輯，只是從「只呼叫一次」改成「每欄各呼叫一次」。
    #
    # 仍然保留手動指定單一 text_column 的能力（例如未來別的呼叫端要
    # 精準指定某一欄時可用），這種情況維持原本「只分析這一欄」的行為。
    if text_column_param and text_column_param in df.columns:
        text_columns = [text_column_param]
        auto_detected = False
    else:
        text_columns = _detect_candidate_text_columns(df)
        auto_detected = True

    if not text_columns:
        return jsonify({"error": "Unable to detect a text column. Check that your Excel file contains open-ended responses."}), 400

    upload_batch_id = str(uuid.uuid4())

    saved_answer_count = 0
    classified_count = 0
    all_classification_rows = []
    # 【受試者編號】記錄「這筆 Uploaded_Answer 對應到 Excel 裡第幾列」，
    # 這樣分類結果回傳時才能標出「受試者N」，方便對照原始資料。同一列
    # 在不同欄位各自有獨立的 Uploaded_Answer，但都對應同一個 row_index，
    # 所以「受試者N」的編號在跨欄位時仍然一致。
    answer_id_to_row_index = {}
    aggregated_groups = []   # 攤平版本：向後相容，只看這個欄位的舊呼叫端不用改
    columns_summary = []     # 新增：每個欄位各自的統計 + 各自的 aggregated_groups

    for text_column in text_columns:
        # 每個欄位各自 routing 一次（欄位名稱 + 這一欄前幾筆遮罩後樣本）
        # ——不同欄位很可能對應不同題目、不同 question_type，不能共用
        # 同一次判斷結果。
        samples = _collect_masked_routing_samples(df, text_column)
        routing_context = _build_routing_context(text_column, samples)
        routed_question_type = route_question_type(routing_context)
        # 【動態分類】routing 判斷不出來（None）就 fall back 到「其他
        # 主題」動態分類，不直接放棄這一欄。
        if routed_question_type:
            prompt_row = Prompt_Template.query.get(routed_question_type)
            if prompt_row is not None:
                question_type = routed_question_type
                prompt_content_for_batch = prompt_row.live_content
            else:
                # 理論上不該發生（合法 question_type 卻查無 Prompt_Template）；
                # 保守 fallback 成動態分類，不讓這一欄整個被跳過
                question_type = QUESTION_OTHER
                prompt_content_for_batch = DYNAMIC_GENERAL_PROMPT
        else:
            question_type = QUESTION_OTHER
            prompt_content_for_batch = DYNAMIC_GENERAL_PROMPT

        pending_items = []  # 每個元素額外帶一個 _question_id，DB 寫入時才用得到
        column_saved_count = 0

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
            column_saved_count += 1

            pending_items.append({
                "identifier": uploaded_answer.id,
                "answer_text": answer_text,
                "_question_id": f"{text_column}_row{idx}",
            })

        column_classification_rows = []
        if pending_items:
            # 【TF-IDF 去重】沿用既有 run_batch_analysis：這裡每個欄位
            # 各自呼叫一次，去重比對只發生在「同一欄位」內部，不會跟
            # 其他欄位的回答混在一起判斷相似度。
            results = run_batch_analysis(
                existing_references=[],
                pending_items=[
                    {"identifier": item["identifier"], "answer_text": item["answer_text"]}
                    for item in pending_items
                ],
                prompt_content=prompt_content_for_batch,
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
                column_classification_rows.extend(rows)
                classified_count += 1

        all_classification_rows.extend(column_classification_rows)

        # 每個欄位各自彙整成自己的一組表格，不會把不同問題的回答混在
        # 同一組摘要裡（不同欄位就是不同題目，混在一起彙整沒有意義）。
        column_groups = _build_aggregated_groups(
            column_classification_rows, answer_id_to_row_index, question_type
        )
        for g in column_groups:
            g["source_column"] = text_column
            g["question_type"] = question_type
        aggregated_groups.extend(column_groups)

        columns_summary.append({
            "column": text_column,
            "question_type": question_type,
            "saved_answer_count": column_saved_count,
            "classified_count": len(column_classification_rows),
            "aggregated_groups": column_groups,
        })

    db.session.commit()

    # 【受試者編號】把 row_index 換算成「受試者N」（從 1 開始比較符合
    # 一般人講話習慣），組進每一筆分類結果的字典裡，不動 to_dict() 本身、
    # 不動資料庫，只在這支 API 回傳前額外加一個欄位。
    classifications_payload = []
    for r in all_classification_rows:
        d = r.to_dict()
        row_index = answer_id_to_row_index.get(r.uploaded_answer_id)
        d["respondent_number"] = (row_index + 1) if row_index is not None else None
        classifications_payload.append(d)

    return jsonify({
        "upload_batch_id": upload_batch_id,
        "saved_answer_count": saved_answer_count,
        "classified_count": classified_count,
        "classifications": classifications_payload,
        # 攤平版本：所有欄位的分組結果合併成一個 list，每組多帶
        # source_column / question_type，讓舊前端不用改也能繼續運作
        # （只是現在看得到「所有」欄位的結果，不再只有一欄）。
        "aggregated_groups": aggregated_groups,
        # 新增：依欄位拆開的版本，之後前端想分別顯示「第一題」「第二題」
        # 各自的表格時可以用這個，不用自己從攤平版本反推。
        "columns": columns_summary,
        "text_columns": text_columns,
        "text_column_auto_detected": auto_detected,
        "total_row_count": total_row_count,
        # 向後相容：舊前端可能還在讀單數的 text_column / question_type，
        # 多欄情況下沒有單一答案，給第一欄的值當 fallback。
        "text_column": text_columns[0] if text_columns else None,
        "question_type": columns_summary[0]["question_type"] if columns_summary else None,
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
        return jsonify({"error": "Survey not found"}), 404
    if survey.user_id != auth_user_id:
        return jsonify({"error": "Access denied"}), 403

    template_id = survey.template_id
    question_json = survey.question_json or {}
    items = question_json.get("items", [])


    question_type_map = {
        item.get("id"): (item.get("question_type") or QUESTION_OTHER)
        for item in items
        if item.get("type") == "short"
    }

    if not question_type_map:

        short_type_items = [item for item in items if item.get("type") == "short"]
        return jsonify({
            "template_id": template_id,
            "analyzed_question_ids": [],
            "newly_classified_count": 0,
            "aggregated_groups": [],
            "diagnostic": {
                "total_question_items": len(items),
                "short_type_question_count": len(short_type_items),
                "short_type_with_routing_count": len(
                    [item for item in short_type_items if item.get("question_type")]
                ),
                "message": (
                    "This survey has no open-ended questions with a classification route. "
                    "Classification results cannot be generated, regardless of the number of responses."
                ),
            },
        }), 200

    responses = Survey_Response.query.filter_by(template_id=template_id).order_by(
        Survey_Response.response_id.asc()
    ).all()


    response_id_to_number = {
        response.response_id: idx for idx, response in enumerate(responses)
    }

    analyzed_question_ids = []
    newly_classified_count = 0
    rows_by_question_type = {}
    per_question_diagnostic = {}

    for question_id, question_type in question_type_map.items():

        if question_type == QUESTION_OTHER:
            prompt_content_for_batch = DYNAMIC_GENERAL_PROMPT
        else:
            prompt_row = Prompt_Template.query.get(question_type)
            if prompt_row is None:
                continue  # 理論上不該發生，保守跳過
            prompt_content_for_batch = prompt_row.live_content

        existing_references = []
        pending_items = []
        diag = {
            "total_responses": len(responses), "missing_key": 0, "invalid_text": 0, "valid": 0,
            "reset_stuck_records": 0,
        }

        for response in responses:
            answers = (response.answer_json or {}).get("answers", {})
            if question_id not in answers:
                diag["missing_key"] += 1
                continue
            answer_value = answers[question_id]
            if not is_text_response(answer_value):
                diag["invalid_text"] += 1
                continue
            answer_text = str(answer_value)
            diag["valid"] += 1

            existing_status = Response_Segmentation_Status.query.filter_by(
                response_id=response.response_id, question_id=question_id
            ).first()

            if existing_status is not None and existing_status.segmentation_status == "completed":

                existing_rows = Response_Classification.query.filter_by(
                    response_id=response.response_id, question_id=question_id
                ).all()

                rows_by_question_type.setdefault(question_type, []).extend(existing_rows)
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
                if existing_status is not None:
                    # 卡在 failed / partial_failed 狀態——清掉舊的狀態紀錄
                    # 跟任何殘留的分類結果（不完整、不可信，不該留著混淆
                    # 彙整畫面），讓這筆回答用全新的狀態重新走一次分類流程。
                    diag["reset_stuck_records"] += 1
                    Response_Classification.query.filter_by(
                        response_id=response.response_id, question_id=question_id
                    ).delete()
                    db.session.delete(existing_status)
                    # 【修正】一定要先 flush，把上面的刪除真的送進資料庫，
                    # 不然等一下新分類結果要寫入同一個 (response_id,
                    # question_id) 組合時，資料庫還看得到「舊紀錄還在」，
                    # 會撞到唯一鍵限制直接報錯。
                    db.session.flush()
                pending_items.append({
                    "identifier": response.response_id,
                    "answer_text": answer_text,
                })

        per_question_diagnostic[question_id] = diag

        if not pending_items:
            continue  # 這題沒有新回答需要處理

        results = run_batch_analysis(
            existing_references, pending_items, prompt_content_for_batch, question_type
        )

        for item, result in zip(pending_items, results):
            _, new_rows = _persist_segmentation_result(
                result,
                source_type="survey",
                answer_text=item["answer_text"],
                question_id=question_id,
                response_id=item["identifier"],
            )
            rows_by_question_type.setdefault(question_type, []).extend(new_rows)
            newly_classified_count += 1

        analyzed_question_ids.append(question_id)

    db.session.commit()

    # 【受試者分組彙整】依 question_type 分開彙整（不同題目對應不同
    # 固定分類清單，排序邏輯不能混在一起），結果合併成一個列表回傳，
    # 前端可以直接沿用 Excel 上傳那條路已經在用的表格渲染元件。
    aggregated_groups = []
    for q_type, rows in rows_by_question_type.items():
        aggregated_groups.extend(
            _build_aggregated_groups(rows, response_id_to_number, q_type, id_field="response_id")
        )

    return jsonify({
        "template_id": template_id,
        "analyzed_question_ids": analyzed_question_ids,
        "newly_classified_count": newly_classified_count,
        "aggregated_groups": aggregated_groups,
        "diagnostic": {
            "question_type_map_size": len(question_type_map),
            "total_responses": len(responses),
            "per_question": per_question_diagnostic,
        },
    }), 200


# ---------- 4. 查詢分類結果 ----------
@classification_bp.route("/api/classification/<int:response_id>", methods=["GET"])
def get_classifications(response_id):
    records = Response_Classification.query.filter_by(response_id=response_id).all()
    return jsonify({
        "response_id": response_id,
        "classifications": [r.to_dict() for r in records],
    }), 200