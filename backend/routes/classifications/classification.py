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
    Response_Classification,
    Response_Segmentation_Status,
    Uploaded_Answer,
)
from services.classify_v2 import classify_existing_segments, classify_response_multi_segment, is_text_response, resolve_published_taxonomy_prompt
from services import classification_attempt_service as attempt_service
from services.secondary_classification_service import get_secondaries
from classification_models import SECONDARY_KIND_AI
from services.confidence_gate import evaluate_confidence_gate
from services.effective_classification_service import effective_view, CLASSIFICATION_STATUS_SUPERSEDED
from services.workspace_result_service import compute_review_revision
from services.privacy_service import mask_pii, PiiMaskingError
from services.question_routing_service import route_question_type_with_reason, ROUTING_REASON_API_FAILURE, ROUTING_REASON_NO_CANDIDATES
from services.batch_classification_service import run_batch_analysis
from services.aggregated_summary_service import build_aggregated_summary, build_aggregated_summary_pair, AggregatedSummaryError
from services.subcategory_methodology import QUESTION_OTHER, compute_display_sub_categories
from services.taxonomy_service import PublishedTaxonomyNotFoundError, PublishedTaxonomyIntegrityError
from routes.surveys.survey import verify_token, find_survey_by_access_or_short_code
import pandas as pd

classification_bp = Blueprint("classification", __name__)

# normalize_main_category 搬到 services/classification_persistence.py（重新分析的
# attempt service 也要用），這裡保留同名匯入，既有呼叫端 / 測試不用改。
from services.classification_persistence import normalize_main_category  # noqa: E402,F401


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


def _resolve_taxonomy_open(routed_topic, label, sample_texts, question_text=None):
    """開放式分類的統一入口（見 services/open_classification.py）：

    - 判斷出主題：用該主題的已發布分類架構（開放式 prompt，可提出新類別）；
      沒有已發布版本時，用暫定草稿，或依這批回答自動歸納一份草稿。
    - 判斷不出主題：依欄位名稱 / 題目文字建立或沿用「自動主題」。
    - OPEN_CLASSIFICATION_ENABLED=0：維持原本 fail-closed 行為。
    """
    from services.open_classification import open_mode_enabled, resolve_for_unrouted, resolve_taxonomy

    if routed_topic and routed_topic != QUESTION_OTHER:
        return resolve_taxonomy(routed_topic, sample_texts=sample_texts, title=label, question_text=question_text or label)
    if open_mode_enabled():
        return resolve_for_unrouted(label, sample_texts, question_text=question_text)
    return {"prompt": None, "lookup": None, "version_id": None, "topic_key": None,
            "provisional": False, "generated": False, "error": "判斷不出主題"}


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
        # 【Human Review 生效】一律透過 effective_view() 取得這筆列的
        # 有效分類（modified 用 final_*、excluded / failed / superseded
        # 回傳 None 直接跳過、confirmed / pending 用 AI original），跟
        # Report / Export / Chat 追問 / Admin 清單共用同一套規則。
        view = effective_view(r)
        if view is None:
            continue

        sub_category = view["sub_category"] or ""
        if "無具體建議" in sub_category:
            continue  # 這種萬用分類不該出現在彙整結果裡

        key = (normalize_main_category(view["main_category"]), sub_category)
        if key not in groups:
            groups[key] = {"items": [], "is_new_category": False}
            order.append(key)
        # 開放式分類：AI 提出、尚未被管理員採用的新類別（人工確認 / 修改
        # 過的列就不再是「待審新類別」）。
        if getattr(r, "status", None) == "new_category" and getattr(r, "review_status", None) in (None, "pending_review"):  # 剛建立尚未 flush 時是 None
            groups[key]["is_new_category"] = True

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
            "reasoning": view["reasoning"] or "",
            "summary": view["summary"] or "",
            "is_secondary": False,
        })

        # 次要分類（可能不只一個）：這個片段也列進次要類別的分組，標示為次要，
        # 跟 Report（services/aggregation_service.py）的分組規則一致。
        for secondary in view.get("secondary_categories") or []:
            secondary_sub = secondary.get("sub_category") or ""
            if not secondary.get("main_category") or not secondary_sub or "無具體建議" in secondary_sub:
                continue
            secondary_key = (normalize_main_category(secondary["main_category"]), secondary_sub)
            if secondary_key not in groups:
                groups[secondary_key] = {"items": [], "is_new_category": False}
                order.append(secondary_key)
            groups[secondary_key]["items"].append({
                "respondent_number": (row_index + 1) if row_index is not None else None,
                "excerpt": f"{excerpt}（次要分類）",
                "reasoning": view["reasoning"] or "",
                "summary": view["summary"] or "",
                "is_secondary": True,
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
            "secondary_count": sum(1 for it in items if it.get("is_secondary")),
            "is_new_category": groups[key]["is_new_category"],
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
    attempt_no: int = 1,
):
    """
    第一次分析一則回答：把 classify_response_multi_segment() 的回傳結果寫進 DB，
    1 筆 Response_Segmentation_Status（回答層級現況，attempt_no）+
    0~N 筆 Response_Classification（每個驗證通過的 segment 各一筆）。

    重新分析（已經有 status 列）不要用這個函式，改用
    services.classification_attempt_service.apply_attempt()——那邊會保留舊
    attempt、保護人工審核結果、確保冪等。

    只負責 db.session.add()，不呼叫 commit()，交給呼叫端統一 commit。
    回傳 (status_row, classification_rows)。
    """
    from services.classification_persistence import build_classification_rows

    status_row = Response_Segmentation_Status(
        response_id=response_id,
        upload_batch_id=upload_batch_id,
        uploaded_answer_id=uploaded_answer_id,
        question_id=question_id,
        source_type=source_type,
        segmentation_status=result["segmentation_status"],
        error_detail=result["segmentation_error_detail"],
        attempt_no=attempt_no,
    )
    db.session.add(status_row)
    scope = {
        "source_type": source_type, "response_id": response_id, "question_id": question_id,
        "upload_batch_id": upload_batch_id, "uploaded_answer_id": uploaded_answer_id, "answer_text": answer_text,
    }
    classification_rows = build_classification_rows(scope, result["segments"], taxonomy_version_id, attempt_no=attempt_no)
    return status_row, classification_rows


# ---------- 1. 系統問卷送出 ----------
@classification_bp.route("/api/survey-response", methods=["POST"])
def submit_survey_response():
    auth_user_id, auth_error = verify_token(request)
    if auth_error:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    template_id = data.get("template_id")
    answers = (data.get("answer_json") or {}).get("answers", {})

    if not template_id or not answers:
        return jsonify({"error": "缺少 template_id 或 answers"}), 400

    template = Survey_Template.query.get(template_id)
    if template is None:
        return jsonify({"error": "找不到這份問卷"}), 404
    if template.user_id != auth_user_id:
        return jsonify({"error": "無權限"}), 403

    survey = Survey_Response(template_id=template_id, answer_json=data.get("answer_json"))
    db.session.add(survey)
    db.session.flush()  # 先取得 response_id，還沒 commit

    # 建立 question_id -> question_type 對照（來自建立問卷時的 routing 結果）
    question_type_map = {}
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

        taxonomy = _resolve_taxonomy_open(question_type, str(question_id), [str(answer)])
        prompt_content, category_lookup, taxonomy_version_id = taxonomy["prompt"], taxonomy["lookup"], taxonomy["version_id"]
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
        routed_question_type, routing_reason = route_question_type_with_reason(routing_context)

        column_texts = [str(v) for v in df[text_column] if is_text_response(v)]
        # 自動歸納分類架構會自己 commit / 失敗時 rollback；先把前面欄位已經
        # 寫好的資料 commit，避免被這一欄的 rollback 一起丟掉。
        db.session.commit()
        taxonomy = _resolve_taxonomy_open(routed_question_type, str(text_column), column_texts)
        prompt_content_for_batch = taxonomy["prompt"]
        category_lookup = taxonomy["lookup"]
        taxonomy_version_id = taxonomy["version_id"]
        taxonomy_unavailable = prompt_content_for_batch is None
        question_type = (taxonomy["topic_key"] if not taxonomy_unavailable else None) or routed_question_type or QUESTION_OTHER

        # 【未分類資料來源統一】routing 判斷不出來時，Uploaded_Answer.question_type
        # 存 NULL（這張表的既定語意：NULL = 尚未判斷出來、待處理），不再把
        # 內部 fallback 值 "other" 寫進 DB；原因另外存在 routing_status /
        # routing_detail，Admin 未分類頁據此顯示並提供指派 Topic / 重新 routing。
        # 開放式分類：判斷不出主題時改用「自動主題」（auto_topic）；只有連
        # AI 自動歸納都失敗時，才是未分類（原因寫進 routing_detail）。
        if not taxonomy_unavailable and routed_question_type is None:
            stored_question_type = taxonomy["topic_key"]
            routing_status = "auto_topic"
            routing_detail = (
                f"routing_reason={routing_reason}；使用自動主題 {taxonomy['topic_key']}"
                f"（{'本次 AI 新歸納' if taxonomy['generated'] else '沿用'}暫定分類架構）"
            )
        elif not taxonomy_unavailable:
            stored_question_type = routed_question_type
            routing_status = "routed"
            routing_detail = "使用暫定分類架構（待管理員發布）" if taxonomy["provisional"] else None
        elif routed_question_type is None:
            stored_question_type = None
            routing_status = {
                ROUTING_REASON_API_FAILURE: "routing_failed",
                ROUTING_REASON_NO_CANDIDATES: "no_topic_candidates",
            }.get(routing_reason, "unrouted")
            routing_detail = f"routing_reason={routing_reason}" + (f"；{taxonomy['error']}" if taxonomy["error"] else "")
        else:
            stored_question_type = routed_question_type
            routing_status = "taxonomy_unavailable"
            routing_detail = taxonomy["error"] or f"topic_key={routed_question_type} 沒有可用的 published taxonomy"

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
                question_type=stored_question_type,
                routing_status=routing_status,
                routing_detail=routing_detail,
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
                "_uploaded_answer": uploaded_answer,
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
                if result.get("segmentation_status") == "failed" or (
                    rows and all(r.status == "failed" for r in rows)
                ):
                    item["_uploaded_answer"].routing_status = "classification_failed"
                    item["_uploaded_answer"].routing_detail = (
                        result.get("segmentation_error_detail") or "all segments failed"
                    )[:2000]

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
            "question_type": stored_question_type,
            "routing_status": routing_status,
            "provisional_taxonomy": bool(taxonomy["provisional"]) and not taxonomy_unavailable,
            "auto_topic": routing_status == "auto_topic",
            "taxonomy_version_id": taxonomy_version_id,
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

    # 畫面呈現指紋：前端存進 Chat_History 訊息 meta，之後 Human Review
    # 改變 effective classification 時可以判斷這份快照是否需要重建
    # （見 services/workspace_result_service.py）。
    review_revision = compute_review_revision(
        {"source_type": "user_upload", "upload_batch_id": upload_batch_id}
    )

    return jsonify({
        "upload_batch_id": upload_batch_id,
        "source_type": "user_upload",
        "review_revision": review_revision,
        "provisional_taxonomy": any(c["provisional_taxonomy"] for c in columns_summary),
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
    每組各自去重 + 批次分類。

    每則回答依 services/classification_attempt_service.plan_reanalysis()：
      - 從沒分析過：第一次分析（attempt 1）
      - 已完成（completed）：沿用，可作為 duplicate reference
      - failed / partial_failed / 卡住，且沒有人工審核結果：整則重新分析，
        新 attempt 生效、舊列標記 superseded（不刪除）
      - 有人工審核結果：只把失敗片段用原位置重新分類；沒有失敗片段就不動
      - 新 attempt AI 失敗：舊結果維持生效
    每題在同一個 transaction 寫入；重複按不會產生多份 current attempt。
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
    question_title_map = {
        item.get("id"): (item.get("title") or item.get("question_title") or item.get("id") or "")
        for item in items
        if item.get("type") == "short"
    }
    provisional_question_ids = []

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

        question_answers = [
            str((r.answer_json or {}).get("answers", {}).get(question_id))
            for r in responses
            if is_text_response((r.answer_json or {}).get("answers", {}).get(question_id))
        ]
        db.session.commit()  # 同上：保護前面題目已寫入的結果
        taxonomy = _resolve_taxonomy_open(
            question_type if question_type != QUESTION_OTHER else None,
            question_title_map.get(question_id) or str(question_id),
            question_answers,
        )
        prompt_content_for_batch = taxonomy["prompt"]
        category_lookup = taxonomy["lookup"]
        taxonomy_version_id = taxonomy["version_id"]
        if prompt_content_for_batch is None:
            # 開放式分類下只有在「連 AI 自動歸納都失敗」或關閉開放模式時
            # 才會走到這裡：整題跳過，原始回答仍完整存在 answer_json。
            per_question_diagnostic[question_id] = {"taxonomy_unavailable": True, "reason": taxonomy["error"]}
            continue
        question_type = taxonomy["topic_key"] or question_type
        if taxonomy["provisional"]:
            provisional_question_ids.append(question_id)

        existing_references = []
        pending_items = []      # 第一次分析 / 整則重新分析（MODE_NEW / MODE_FULL）
        segment_retries = []    # 有人工審核結果：只重新分類失敗片段（MODE_RETRY_SEGMENTS）
        diag = {
            "total_responses": len(responses), "missing_key": 0, "invalid_text": 0, "valid": 0,
            "reanalyzed": 0, "segment_retries": 0, "blocked_by_review": 0,
            "kept_previous": 0, "attempt_conflicts": 0,
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

            # 重新分析不再 hard-delete 舊結果：見 services/classification_attempt_service.py
            scope = attempt_service.survey_scope(response.response_id, question_id, answer_text)
            plan = attempt_service.plan_reanalysis(scope)
            current = plan["rows"]

            if plan["mode"] in (attempt_service.MODE_REUSE, attempt_service.MODE_SKIP, attempt_service.MODE_RETRY_SEGMENTS):
                # 目前生效的結果（含人工審核過的片段）照常計入彙整
                rows_by_question_type.setdefault(question_type, []).extend(current)
            if plan["mode"] == attempt_service.MODE_REUSE:
                # 已完成的回答可以當 duplicate reference（superseded 不列入）
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
                            "secondary_main_category": r.secondary_main_category,
                            # 沿用時次要分類要完整帶過去（可能不只一個）
                            "secondary_categories": get_secondaries(r, SECONDARY_KIND_AI),
                            "reasoning": r.reasoning,
                            "summary": r.summary,
                            "methodology": r.methodology,
                            "citation": r.citation,
                            "secondary_methodology": r.secondary_methodology,
                            "secondary_citation": r.secondary_citation,
                            "status": r.status,
                            "confidence": r.confidence,
                        }
                        for r in current
                    ],
                })
            elif plan["mode"] == attempt_service.MODE_SKIP:
                diag["blocked_by_review"] += 1
            elif plan["mode"] == attempt_service.MODE_RETRY_SEGMENTS:
                segment_retries.append((scope, plan))
            else:
                if plan["mode"] == attempt_service.MODE_FULL:
                    diag["reanalyzed"] += 1
                pending_items.append({
                    "identifier": response.response_id,
                    "answer_text": answer_text,
                    "_scope": scope,
                    "_plan": plan,
                })

        per_question_diagnostic[question_id] = diag

        if not pending_items and not segment_retries:
            continue  # 這題沒有需要處理的回答

        results = run_batch_analysis(
            existing_references,
            [{"identifier": item["identifier"], "answer_text": item["answer_text"]} for item in pending_items],
            prompt_content_for_batch, question_type,
            category_lookup=category_lookup, taxonomy_version_id=taxonomy_version_id,
        ) if pending_items else []

        work = [(item["_scope"], item["_plan"], result, None) for item, result in zip(pending_items, results)]
        for scope, plan in segment_retries:
            retry_rows = plan["retry_rows"]
            result = classify_existing_segments(
                scope["answer_text"], [(r.segment_start, r.segment_end) for r in retry_rows],
                prompt_content_for_batch, question_type, category_lookup=category_lookup,
            )
            work.append((scope, plan, result, [r.classification_id for r in retry_rows]))
            diag["segment_retries"] += 1

        rerun_happened = False
        for scope, plan, result, retry_ids in work:
            outcome = attempt_service.apply_attempt(
                scope, result, taxonomy_version_id, plan["expected_attempt_no"], plan["mode"],
                retry_row_ids=retry_ids,
            )
            if outcome.applied:
                newly_classified_count += 1
                rerun_happened = rerun_happened or plan["mode"] != attempt_service.MODE_NEW
                if plan["mode"] == attempt_service.MODE_RETRY_SEGMENTS:
                    # 目前生效的列：重新查一次（被取代的失敗片段已經 superseded）
                    fresh = attempt_service.current_rows(scope)
                    bucket = rows_by_question_type.setdefault(question_type, [])
                    stale = {r.classification_id for r in plan["rows"]}
                    bucket[:] = [r for r in bucket if r.classification_id not in stale] + fresh
                else:
                    rows_by_question_type.setdefault(question_type, []).extend(outcome.rows)
            elif outcome.outcome == attempt_service.OUTCOME_KEPT_PREVIOUS:
                diag["kept_previous"] += 1
                if plan["mode"] == attempt_service.MODE_FULL:
                    rows_by_question_type.setdefault(question_type, []).extend(plan["rows"])
            elif outcome.outcome == attempt_service.OUTCOME_CONFLICT:
                diag["attempt_conflicts"] += 1
            elif outcome.outcome == attempt_service.OUTCOME_BLOCKED:
                diag["blocked_by_review"] += 1
                rows_by_question_type.setdefault(question_type, []).extend(plan["rows"])

        # 每題一個 transaction：這題的所有 attempt 一起生效
        db.session.commit()
        if rerun_happened:
            from services.report_service import OUTDATED_CLASSIFICATION_RERUN, mark_reports_outdated_for_sources
            mark_reports_outdated_for_sources([("survey", template_id, None)], OUTDATED_CLASSIFICATION_RERUN)
            db.session.commit()

        analyzed_question_ids.append(question_id)

    db.session.commit()

    
    aggregated_groups = []
    for q_type, rows in rows_by_question_type.items():
        aggregated_groups.extend(
            _build_aggregated_groups(rows, response_id_to_number, q_type, id_field="response_id")
        )

    return jsonify({
        "template_id": template_id,
        "source_type": "survey",
        "review_revision": compute_review_revision({"source_type": "survey", "template_id": template_id}),
        "provisional_taxonomy": bool(provisional_question_ids),
        "provisional_question_ids": provisional_question_ids,
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
    auth_user_id, auth_error = verify_token(request)
    if auth_error:
        return jsonify({"error": "Unauthorized"}), 401

    response = Survey_Response.query.get(response_id)
    if response is None:
        return jsonify({"error": "找不到這筆問卷回覆"}), 404

    template = Survey_Template.query.get(response.template_id)
    if template is None or template.user_id != auth_user_id:
        return jsonify({"error": "無權限"}), 403

    records = Response_Classification.query.filter_by(response_id=response_id).all()
    return jsonify({
        "response_id": response_id,
        "classifications": [r.to_dict() for r in records],
    }), 200