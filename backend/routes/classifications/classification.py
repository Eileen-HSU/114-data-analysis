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
import re
import unicodedata

from flask import Blueprint, jsonify, request
from extensions import db
from models import (
    Survey_Response,
    Survey_Template,
    Response_Classification,
    Response_Segmentation_Status,
    Uploaded_Answer,
)
from services.classify_v2 import classify_response_multi_segment, is_text_response, resolve_published_taxonomy_prompt
from services.confidence_gate import evaluate_confidence_gate
from services.privacy_service import mask_pii, PiiMaskingError
from services.question_routing_service import route_question_type
from services.batch_classification_service import run_batch_analysis
from services.aggregated_summary_service import build_aggregated_summary, build_aggregated_summary_pair, AggregatedSummaryError
from services.subcategory_methodology import QUESTION_OTHER, compute_display_sub_categories
from services.taxonomy_service import PublishedTaxonomyNotFoundError, PublishedTaxonomyIntegrityError
from routes.surveys.survey import verify_token, find_survey_by_access_or_short_code
import pandas as pd

classification_bp = Blueprint("classification", __name__)

_MAIN_CATEGORY_PREFIX_RE = re.compile(r"^大類別[:：]\s*")
_WHITESPACE_RUN_RE = re.compile(r"[\s\t\n\r]+")


def normalize_main_category(raw) -> str:
    """把 main_category 正規化成唯一的 canonical 字串。

    步驟（依序執行，順序會影響結果，不能任意調換）：
      1. Unicode NFKC normalize（統一全形/半形符號，例如全形冒號「：」
         正規化後會變成半形「:」）
      2. strip 前後空白
      3. 移除開頭的「大類別：」或「大類別:」前綴（NFKC 之後兩種冒號
         寫法都會落在同一個 pattern，這裡仍明確列出兩種寫法以防這個
         函式未來被單獨拿去處理沒有先做過 NFKC 的字串）
      4. 把連續空白／tab／換行壓成單一半形空白
      5. 再 strip 一次（防止步驟 3 移除前綴後，「大類別： 　題目」這種
         前綴後面還帶空白的情況殘留前導空白）

    只處理字串層級的正規化，不改變分類語意本身：不會把不同的大類別
    名稱合併，只會把「同一個大類別的不同字串寫法」合併成同一種寫法。
    raw 是 None 時回傳空字串，跟既有 `r.main_category or ""` 的行為
    相容。
    """
    if raw is None:
        return ""
    text = unicodedata.normalize("NFKC", str(raw))
    text = text.strip()
    text = _MAIN_CATEGORY_PREFIX_RE.sub("", text)
    text = _WHITESPACE_RUN_RE.sub(" ", text)
    text = text.strip()
    return text


def _resolve_taxonomy_for_topic(question_type: str):
    """
    Phase B production classification 的唯一 taxonomy 來源入口。

    回傳 (prompt_content, category_lookup, taxonomy_version_id) 三元組；
    若這個 question_type 目前沒有可用的 Published Taxonomy（包含
    routing 判斷不出來、被視為 QUESTION_OTHER 的情況），回傳
    (None, None, None) 並印出診斷 log——呼叫端看到 None 三元組時必須
    跳過這批文字的分類（原始文字仍照舊寫入 Uploaded_Answer /
    Survey_Response，不受影響），不可以 fallback 到 DYNAMIC_GENERAL_PROMPT
    自創分類。沒有 taxonomy 的 Topic 之後要走 Taxonomy Generation
    （Phase C），不是 classification 當下 fallback。
    """
    if question_type == QUESTION_OTHER:
        print(f"[TAXONOMY_UNAVAILABLE] question_type={question_type!r}：routing 判斷不出來，非真正 Topic")
        return None, None, None
    try:
        prompt_content, category_lookup, taxonomy_version = resolve_published_taxonomy_prompt(question_type)
        return prompt_content, category_lookup, taxonomy_version.version_id
    except (PublishedTaxonomyNotFoundError, PublishedTaxonomyIntegrityError) as e:
        print(f"[TAXONOMY_UNAVAILABLE] question_type={question_type!r}：{e}")
        return None, None, None


def _safe_rating_int(raw):
    """把 rating 答案安全轉成 0~5 的整數；轉不出來或超出範圍回傳 None
    （代表這筆值不合法，呼叫端要直接跳過，不能讓一筆髒資料讓整份統計
    失敗）。

    刻意排除 bool：Python 的 bool 是 int 的子類別，True/False 轉出來會
    變成 1/0，混進 rating 分數裡會是很難查的資料錯誤。
    """
    if isinstance(raw, bool):
        return None
    try:
        if isinstance(raw, (int, float)):
            value = int(raw)
        else:
            value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    if 0 <= value <= 5:
        return value
    return None


def _build_rating_stats(items, responses):
    """對問卷裡所有 type == "rating" 的題目直接在後端算統計，完全不經過
    Gemini／Taxonomy／Human Review——這幾個管線本來就只認
    question_type_map（只收 type == "short"），rating 的 question_id
    從未出現在那裡，這裡的計算是純數學統計，不寫入
    Response_Classification／Response_Segmentation_Status 任何一張表，
    自然不會被 Human Review 摸到。

    規則（都跟「一位受試者一列」的問卷原始回覆匯出用同一套判斷邏輯，
    避免兩處各自維護一份、不小心兜不起來）：
      - 未作答的判斷是 `qid in answers`（key 存在與否），不是 truthy
        判斷——rating 答 0 分時 `0`／`"0"` 都是 falsy，用 `answer or ...`
        這種寫法會把「答 0 分」誤判成「沒有作答」，是這裡最需要避開的
        地雷。
      - 未作答的人不進 average、answered_count、distribution。
      - 轉不出 0~5 整數的值（例如被改壞的資料）視為非法值，直接跳過，
        不計入任何統計、也不讓整份匯出失敗。
      - distribution 固定是 0~5 六個桶，即使某個分數沒人選也要出現在
        結果裡（值是 0），不是動態長度的 dict。
      - 完全沒有人回答的 rating 題：average=None、answered_count=0，
        distribution 六個桶全是 0——這題仍然要出現在結果陣列裡，不能
        因為沒人答就從陣列裡消失（消失會讓使用者以為這題不存在）。
    """
    rating_stats = []
    for index, item in enumerate(items):
        if not isinstance(item, dict) or item.get("type") != "rating":
            continue

        qid = item.get("id")
        distribution = {str(score): 0 for score in range(6)}
        total = 0
        answered_count = 0

        for response in responses:
            answers = (response.answer_json or {}).get("answers") or {}
            if not isinstance(answers, dict) or qid not in answers:
                continue  # 未作答：不進平均、answered_count、distribution
            rating_value = _safe_rating_int(answers.get(qid))
            if rating_value is None:
                continue  # 非法 rating 值：直接跳過，不計入任何統計
            distribution[str(rating_value)] += 1
            total += rating_value
            answered_count += 1

        average = round(total / answered_count, 1) if answered_count else None

        rating_stats.append({
            "question_id": qid,
            "question_number": index + 1,
            "title": item.get("title") or item.get("question_title") or "",
            "average": average,
            "answered_count": answered_count,
            "distribution": distribution,
        })

    return rating_stats


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

        key = (normalize_main_category(r.main_category), sub_category)
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

    
    renumbered_sub_category = compute_display_sub_categories(order, question_type)
    order = list(renumbered_sub_category.keys())

    result = []
    for key in order:
        main_category, sub_category = key
        items = groups[key]["items"]
        display_sub_category = renumbered_sub_category[key]

       
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

        
        synthesis_status = "ok"
        synthesis_error = None
        try:
            reasoning_items = [{"matched_segment_text": it["reasoning"]} for it in items if it["reasoning"]]
            summary_items = [{"matched_segment_text": it["summary"]} for it in items if it["summary"]]
            
            aggregated_reasoning, aggregated_summary = build_aggregated_summary_pair(
                main_category, sub_category, reasoning_items, summary_items
            )
        except AggregatedSummaryError as e:
            print("[AGGREGATED_SUMMARY_FAILED]", repr(e))
            synthesis_status = "fallback"
            
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



_ID_LIKE_COLUMN_KEYWORDS = (
    "id", "編號", "序號", "代碼", "code", "no.", "no",
    "姓名", "名字", "email", "e-mail", "電子郵件",
    "電話", "手機", "聯絡電話", "身分證", "身分證字號",
    "tel", "phone",
)


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
    taxonomy_version_id: int = None,
):
    """
    把 classify_response_multi_segment() 的回傳結果寫進 DB：
    1 筆 Response_Segmentation_Status（回答層級現況）+
    0~N 筆 Response_Classification（每個驗證通過的 segment 各一筆）。

    taxonomy_version_id（Phase B 新增）：這批分類實際使用哪一版
    Published Taxonomy 產生的，原樣寫進每一筆 Response_Classification；
    不傳（None）時維持舊行為（legacy path 或無 taxonomy 可用時的
    未分類回答，欄位保持 NULL）。

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
        
        reasoning = seg["reasoning"]
        if seg["status"] != "completed" and seg.get("error_detail"):
            reasoning = seg["error_detail"]

        needs_human_review, review_flag_reason = evaluate_confidence_gate(seg)

        row = Response_Classification(
            response_id=response_id,
            upload_batch_id=upload_batch_id,
            uploaded_answer_id=uploaded_answer_id,
            source_type=source_type,
            question_id=question_id,
            answer_text=answer_text,
            segment_start=seg["orig_start"],
            segment_end=seg["orig_end"],
            main_category=normalize_main_category(seg["main_category"]),
            sub_category=seg["sub_category"],
            secondary_sub_category=seg["secondary_sub_category"],
            reasoning=reasoning,
            summary=seg["summary"],
            methodology=seg["methodology"],
            citation=seg["citation"],
            secondary_methodology=seg["secondary_methodology"],
            secondary_citation=seg["secondary_citation"],
            status=seg["status"],
            taxonomy_version_id=taxonomy_version_id,
            confidence=seg["confidence"] if isinstance(seg["confidence"], (int, float)) and not isinstance(seg["confidence"], bool) else None,
            needs_human_review=needs_human_review,
            review_flag_reason=review_flag_reason,
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

        prompt_content, category_lookup, taxonomy_version_id = _resolve_taxonomy_for_topic(question_type)
        if prompt_content is None:
            # 沒有 Published Taxonomy：這一題跳過分類，原始回答本來就
            # 已經完整存在 survey.answer_json，不受影響（見需求文件
            # Phase B 第 5 節：不可 fallback 到 DYNAMIC_GENERAL_PROMPT）
            skipped_question_ids.append(question_id)
            continue

        answer_text = str(answer)
        result = classify_response_multi_segment(
            answer_text, prompt_content, question_type,
            category_lookup=category_lookup, taxonomy_version_id=taxonomy_version_id,
        )
        _, rows = _persist_segmentation_result(
            result,
            source_type="survey",
            answer_text=answer_text,
            question_id=question_id,
            response_id=survey.response_id,
            taxonomy_version_id=taxonomy_version_id,
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
    
    auth_user_id, auth_error = verify_token(request)
    if auth_error:
        return jsonify({"error": "Unauthorized"}), 401

    file = request.files.get("file")
    if not file:
        return jsonify({"error": "請提供檔案"}), 400

    df = pd.read_excel(file)
    text_column_param = request.form.get("text_column")
    total_row_count = len(df)

    
    if text_column_param and text_column_param in df.columns:
        text_columns = [text_column_param]
        auto_detected = False
    else:
        text_columns = _detect_candidate_text_columns(df)
        auto_detected = True

    if not text_columns:
        return jsonify({"error": "無法自動判斷文字欄位，請確認 Excel 內容是否包含開放式文字回答"}), 400

    upload_batch_id = str(uuid.uuid4())

    saved_answer_count = 0
    classified_count = 0
    all_classification_rows = []
    
    answer_id_to_row_index = {}
    aggregated_groups = []   # 攤平版本：向後相容，只看這個欄位的舊呼叫端不用改
    columns_summary = []     # 新增：每個欄位各自的統計 + 各自的 aggregated_groups

    for text_column in text_columns:
        
        samples = _collect_masked_routing_samples(df, text_column)
        routing_context = _build_routing_context(text_column, samples)
        routed_question_type = route_question_type(routing_context)
        question_type = routed_question_type or QUESTION_OTHER

        prompt_content_for_batch, category_lookup, taxonomy_version_id = _resolve_taxonomy_for_topic(question_type)
        taxonomy_unavailable = prompt_content_for_batch is None

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
        if pending_items and not taxonomy_unavailable:
            results = run_batch_analysis(
                existing_references=[],
                pending_items=[
                    {"identifier": item["identifier"], "answer_text": item["answer_text"]}
                    for item in pending_items
                ],
                prompt_content=prompt_content_for_batch,
                question_type=question_type,
                category_lookup=category_lookup,
                taxonomy_version_id=taxonomy_version_id,
            )
            for item, result in zip(pending_items, results):
                _, rows = _persist_segmentation_result(
                    result,
                    source_type="user_upload",
                    answer_text=item["answer_text"],
                    question_id=item["_question_id"],
                    upload_batch_id=upload_batch_id,
                    uploaded_answer_id=item["identifier"],
                    taxonomy_version_id=taxonomy_version_id,
                )
                column_classification_rows.extend(rows)
                classified_count += 1

        all_classification_rows.extend(column_classification_rows)

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
            # Phase B 新增：這一欄沒有 Published Taxonomy 時，原始文字
            # 仍已寫入 Uploaded_Answer（saved_answer_count 不受影響），
            # 只是完全不會有分類結果（不 fallback 動態分類）。
            "taxonomy_unavailable": taxonomy_unavailable,
        })

    db.session.commit()

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
        "aggregated_groups": aggregated_groups,
        "columns": columns_summary,
        "text_columns": text_columns,
        "text_column_auto_detected": auto_detected,
        "total_row_count": total_row_count,
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
        return jsonify({"error": "找不到這份問卷"}), 404
    if survey.user_id != auth_user_id:
        return jsonify({"error": "無權限"}), 403

    template_id = survey.template_id
    question_json = survey.question_json or {}
    items = question_json.get("items", [])

    # 【新增｜rating 題後端直接統計】跟 question_type_map（只收
    # type == "short"）完全平行、互不相干：rating 的 question_id 從頭
    # 到尾不會出現在 question_type_map 裡，所以不管下面 short 題那條
    # 分類流程走不走得下去，rating 統計都要能獨立算出來——這也是「整份
    # 問卷只有 rating 題」時，這支 API 仍然要回傳有意義結果的關鍵。
    # responses 要在判斷 question_type_map 是否為空之前先查出來，
    # 因為 rating-only 問卷會直接命中下面那個早退分支，如果 responses
    # 查詢留在早退分支之後，rating-only 情境就永遠算不到統計。
    responses = Survey_Response.query.filter_by(template_id=template_id).order_by(
        Survey_Response.response_id.asc()
    ).all()

    rating_stats = _build_rating_stats(items, responses)

    
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
            "rating_stats": rating_stats,
            "diagnostic": {
                "total_question_items": len(items),
                "short_type_question_count": len(short_type_items),
                "short_type_with_routing_count": len(
                    [item for item in short_type_items if item.get("question_type")]
                ),
                "message": (
                    "這份問卷沒有任何一題符合「開放式文字題（type=short）且有分類"
                    "路由結果（question_type）」的條件，所以完全不會產生分類結果，"
                    "不管有幾個人回答都一樣。"
                ),
            },
        }), 200

    
    response_id_to_number = {
        response.response_id: idx for idx, response in enumerate(responses)
    }

    analyzed_question_ids = []
    newly_classified_count = 0
    rows_by_question_type = {}
    per_question_diagnostic = {}

    for question_id, question_type in question_type_map.items():

        prompt_content_for_batch, category_lookup, taxonomy_version_id = _resolve_taxonomy_for_topic(question_type)
        if prompt_content_for_batch is None:
            # 沒有 Published Taxonomy（含 QUESTION_OTHER）：整題跳過，
            # 不 fallback 到 DYNAMIC_GENERAL_PROMPT。原始回答仍完整存在
            # Survey_Response.answer_json，只是這次不會產生新分類結果。
            per_question_diagnostic[question_id] = {"taxonomy_unavailable": True}
            continue

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
                    diag["reset_stuck_records"] += 1
                    Response_Classification.query.filter_by(
                        response_id=response.response_id, question_id=question_id
                    ).delete()
                    db.session.delete(existing_status)
                    db.session.flush()
                pending_items.append({
                    "identifier": response.response_id,
                    "answer_text": answer_text,
                })

        per_question_diagnostic[question_id] = diag

        if not pending_items:
            continue  # 這題沒有新回答需要處理

        results = run_batch_analysis(
            existing_references, pending_items, prompt_content_for_batch, question_type,
            category_lookup=category_lookup, taxonomy_version_id=taxonomy_version_id,
        )

        for item, result in zip(pending_items, results):
            _, new_rows = _persist_segmentation_result(
                result,
                source_type="survey",
                answer_text=item["answer_text"],
                question_id=question_id,
                response_id=item["identifier"],
                taxonomy_version_id=taxonomy_version_id,
            )
            rows_by_question_type.setdefault(question_type, []).extend(new_rows)
            newly_classified_count += 1

        analyzed_question_ids.append(question_id)

    db.session.commit()

    
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
        "rating_stats": rating_stats,
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