"""
Workspace 分類結果（Chat_History 裡 [[CLASSIFICATION_TABLE]] 訊息）與
DB 最新 effective classification 的同步。

【背景】Excel 上傳 / 問卷 /analyze 完成當下，前端把後端算好的
aggregated_groups 存進 Chat_History.message_content（快照）。之後 Admin
在 Human Review 裡 modified / excluded / reopen，DB 已經改變，但這份
快照不會跟著變——重新整理頁面、匯出檔案都還是舊結果。

這裡提供後端權威的同步機制（不是前端 state workaround）：
    - compute_review_revision()：依 effective 規則算出「畫面呈現指紋」，
      只有會影響畫面的變更（modified / excluded / reopen 後改回 AI
      original / failed / superseded）才會改變指紋；單純 confirm 不影響。
    - is_chat_result_stale()：比對訊息裡存的 meta.review_revision。舊訊息
      沒有這個欄位時，改跟「修正前的行為」（全部用 AI original）比較，
      沒有被 Human Review 影響的舊訊息不會被判定為過期。
    - refresh_chat_result()：用 DB 重建 aggregated_groups（跟 upload /
      analyze 同一個 _build_aggregated_groups()、同樣的分組與排序），
      覆寫回 Chat_History（DB persistence），回傳新的 rows。
"""

import hashlib
import json

from extensions import db, taiwan_now
from models import Response_Classification, Survey_Response, Survey_Template, Uploaded_Answer
from classification_models import SOURCE_TYPE_SURVEY, SOURCE_TYPE_USER_UPLOAD
from services.effective_classification_service import display_fingerprint_entry
from services.source_lookup_service import fetch_classifications_in_scope
from services.subcategory_methodology import QUESTION_OTHER

CLASSIFICATION_TABLE_MARKER = "[[CLASSIFICATION_TABLE]]"


def parse_classification_message(content):
    if not content or not content.startswith(CLASSIFICATION_TABLE_MARKER):
        return None
    try:
        return json.loads(content[len(CLASSIFICATION_TABLE_MARKER):])
    except (TypeError, ValueError):
        return None


def build_classification_message(payload: dict) -> str:
    return CLASSIFICATION_TABLE_MARKER + json.dumps(payload, ensure_ascii=False)


def source_for_chat(chat, parsed=None):
    """回傳這則分類結果訊息對應的分析單位；判斷不出來回傳 None
    （舊格式訊息沒有存來源時，維持原本快照，不猜測）。"""
    parsed = parsed if parsed is not None else parse_classification_message(chat.message_content)
    if parsed is None:
        return None
    meta = parsed.get("meta") or {}
    template_id = meta.get("template_id") or chat.template_id
    if template_id:
        return {"source_type": SOURCE_TYPE_SURVEY, "template_id": int(template_id)}
    if meta.get("upload_batch_id"):
        return {"source_type": SOURCE_TYPE_USER_UPLOAD, "upload_batch_id": meta["upload_batch_id"]}
    return None


def _scope_rows(source):
    if source["source_type"] == SOURCE_TYPE_SURVEY:
        return fetch_classifications_in_scope(SOURCE_TYPE_SURVEY, template_id=source["template_id"])
    return fetch_classifications_in_scope(SOURCE_TYPE_USER_UPLOAD, upload_batch_id=source["upload_batch_id"])


def compute_review_revision(source, rows=None, mode="effective") -> str:
    rows = rows if rows is not None else _scope_rows(source)
    entries = sorted(
        (display_fingerprint_entry(r, mode=mode) for r in rows),
        key=lambda e: (e[0] or 0),
    )
    return hashlib.sha1(json.dumps(entries, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def live_rating_stats(source):
    """問卷來源：用 DB 目前所有填答重新計算 rating 題統計（跟 /analyze 同一個
    _build_rating_stats()）。新增填答後，Chat 重新整理與 Excel / Word 匯出
    都用這份，不再沿用分析當下的快照。非問卷來源回傳 None。"""
    if source is None or source["source_type"] != SOURCE_TYPE_SURVEY:
        return None
    from routes.classifications.classification import _build_rating_stats

    template = db.session.get(Survey_Template, source["template_id"])
    items = ((template.question_json or {}).get("items", []) if template else [])
    responses = (
        Survey_Response.query.filter_by(template_id=source["template_id"])
        .order_by(Survey_Response.response_id.asc()).all()
    )
    return _build_rating_stats(items, responses)


def is_chat_result_stale(chat, parsed=None) -> dict:
    parsed = parsed if parsed is not None else parse_classification_message(chat.message_content)
    source = source_for_chat(chat, parsed)
    if source is None:
        return {"has_source": False, "stale": False, "review_revision": None, "stored_revision": None}

    rows = _scope_rows(source)
    current = compute_review_revision(source, rows)
    stored = (parsed.get("meta") or {}).get("review_revision")
    if stored:
        stale = stored != current
    else:
        # 舊訊息：跟修正前的產生方式（全部 AI original）比較。
        stale = compute_review_revision(source, rows, mode="legacy_original") != current
    rating_stale = False
    live_ratings = live_rating_stats(source)
    if live_ratings is not None:
        # 問卷新增填答後 rating 題統計會變，但分類指紋不一定變：也要判定過期
        rating_stale = (parsed.get("rating_stats") or []) != live_ratings
        stale = stale or rating_stale
    return {
        "rating_stats_stale": rating_stale,
        "has_source": True,
        "stale": stale,
        "review_revision": current,
        "stored_revision": stored,
        "source": source,
    }


def build_live_groups(source) -> list:
    """用 DB 目前資料重建 aggregated_groups，分組／排序方式跟
    upload_excel_for_classification() / analyze_survey() 完全一致。"""
    from routes.classifications.classification import _build_aggregated_groups

    rows = _scope_rows(source)

    if source["source_type"] == SOURCE_TYPE_SURVEY:
        template = db.session.get(Survey_Template, source["template_id"])
        items = ((template.question_json or {}).get("items", []) if template else [])
        question_order = {}
        question_type_map = {}
        for idx, item in enumerate(items):
            if item.get("type") == "short":
                question_order[item.get("id")] = idx
                question_type_map[item.get("id")] = item.get("question_type") or QUESTION_OTHER

        responses = (
            Survey_Response.query.filter_by(template_id=source["template_id"])
            .order_by(Survey_Response.response_id.asc()).all()
        )
        response_index = {r.response_id: i for i, r in enumerate(responses)}

        rows_by_type = {}
        type_order = []
        for row in sorted(
            rows,
            key=lambda r: (
                question_order.get(r.question_id, 10**6),
                response_index.get(r.response_id, 10**6),
                r.segment_start or 0,
            ),
        ):
            q_type = question_type_map.get(row.question_id, QUESTION_OTHER)
            if q_type not in rows_by_type:
                rows_by_type[q_type] = []
                type_order.append(q_type)
            rows_by_type[q_type].append(row)

        groups = []
        for q_type in type_order:
            groups.extend(_build_aggregated_groups(rows_by_type[q_type], response_index, q_type, id_field="response_id"))
        return groups

    answers = (
        Uploaded_Answer.query.filter_by(upload_batch_id=source["upload_batch_id"])
        .order_by(Uploaded_Answer.id.asc()).all()
    )
    answer_by_id = {a.id: a for a in answers}
    row_index_by_id = {a.id: a.row_index for a in answers}
    column_order = []
    column_type = {}
    for a in answers:
        if a.source_column not in column_type:
            column_order.append(a.source_column)
            column_type[a.source_column] = a.question_type or QUESTION_OTHER

    rows_by_column = {}
    for row in sorted(rows, key=lambda r: (row_index_by_id.get(r.uploaded_answer_id, 10**6), r.segment_start or 0)):
        answer = answer_by_id.get(row.uploaded_answer_id)
        if answer is None:
            continue
        rows_by_column.setdefault(answer.source_column, []).append(row)

    groups = []
    for column in column_order:
        column_rows = rows_by_column.get(column, [])
        if not column_rows:
            continue
        column_groups = _build_aggregated_groups(column_rows, row_index_by_id, column_type[column])
        for g in column_groups:
            g["source_column"] = column
            g["question_type"] = column_type[column]
        groups.extend(column_groups)
    return groups


def _group_to_row(g):
    return {
        "main_category": g.get("main_category") or "",
        "sub_category": g.get("sub_category") or "",
        "respondent_text": g.get("respondent_text") or "",
        "aggregated_reasoning": g.get("aggregated_reasoning") or "",
        "aggregated_summary": g.get("aggregated_summary") or "",
        "synthesis_status": g.get("synthesis_status") or "ok",
        "synthesis_error": g.get("synthesis_error"),
        "respondent_count": g.get("respondent_count"),
        "secondary_count": g.get("secondary_count") or 0,
        "is_new_category": bool(g.get("is_new_category")),
    }


def live_upload_diagnostics(upload_batch_id, previous_meta=None, displayed_groups=None) -> dict:
    """依 DB 目前狀態重算上傳批次的計數與診斷（規則同上傳當下，見
    services/analysis_diagnostics.py）：回答至少有一個 current、非 failed 的
    分類列 = 分類成功；其餘 = 失敗。還在失敗的欄位沿用上一次的診斷 code。"""
    from services import analysis_diagnostics as diag
    from services.effective_classification_service import NON_COUNTABLE_STATUSES

    previous = {c.get("column"): c for c in (previous_meta or {}).get("columns") or []}
    answers = Uploaded_Answer.query.filter_by(upload_batch_id=upload_batch_id).all()
    ok_answer_ids = {
        r.uploaded_answer_id
        for r in Response_Classification.query.filter_by(upload_batch_id=upload_batch_id).all()
        if r.status not in NON_COUNTABLE_STATUSES
    }
    by_column = {}
    for answer in answers:
        stats = by_column.setdefault(answer.source_column, [0, 0])
        stats[0] += 1
        if answer.id in ok_answer_ids:
            stats[1] += 1
    columns = []
    for column, (saved, classified) in by_column.items():
        old = previous.get(column) or {}
        failed = saved - classified
        failure_code = old.get("diagnostic_code") if old.get("diagnostic_code") != diag.PARTIAL_CLASSIFICATION else None
        entry = diag.build_column_diagnostic(
            saved, classified, failed, failure_code=failure_code,
            failure_detail={"code": old.get("failure_code")} if failed and old.get("failure_code") else None,
        )
        columns.append({
            "column": column, "routing_status": old.get("routing_status"),
            **{k: entry[k] for k in ("analysis_status", "diagnostic_code", "failure_code",
                                     "saved_answer_count", "classified_count", "failed_count")},
        })
    batch = diag.build_batch_diagnostic(columns, displayed_groups if displayed_groups is not None else 1)
    return {**{k: batch[k] for k in ("analysis_status", "diagnostic_code", "saved_answer_count",
                                     "classified_count", "failed_count")}, "columns": columns}


def refresh_chat_result(chat) -> dict:
    """重建並持久化這則分類結果訊息。只 add/修改，不 commit（交給呼叫端）。

    Returns: 更新後的訊息 payload（{"rows", "meta", "rating_stats"}）。
    """
    parsed = parse_classification_message(chat.message_content)
    source = source_for_chat(chat, parsed)
    if source is None:
        raise ValueError("這則訊息沒有可追溯的分析來源，無法重新整理")

    groups = build_live_groups(source)
    meta = dict(parsed.get("meta") or {})
    if source["source_type"] == SOURCE_TYPE_USER_UPLOAD and meta.get("analysis_status"):
        # Admin 重新處理 / 重新判斷後，計數與診斷跟著 DB 更新（Chat History、UI、
        # API 用同一組數字）
        meta.update(live_upload_diagnostics(source["upload_batch_id"], meta, displayed_groups=len(groups)))
    meta["review_revision"] = compute_review_revision(source)
    meta["refreshed_at"] = taiwan_now().isoformat()
    meta["source_type"] = source["source_type"]
    if source["source_type"] == SOURCE_TYPE_SURVEY:
        meta["template_id"] = source["template_id"]
    else:
        meta["upload_batch_id"] = source["upload_batch_id"]

    live_ratings = live_rating_stats(source)
    payload = {
        "rows": [_group_to_row(g) for g in groups],
        "meta": meta,
        "rating_stats": live_ratings if live_ratings is not None else (parsed.get("rating_stats") or []),
    }
    chat.message_content = build_classification_message(payload)
    return payload
