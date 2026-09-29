"""
重新分析（re-analysis）的 attempt 模型。

【為什麼需要】
原本問卷重新分析時，只要某題的拆分狀態不是 completed（failed /
partial_failed / 卡在 pending），就把那題「所有」Response_Classification
hard-delete 後重跑——partial_failed 的回答裡已經被人工確認 / 修改 / 排除
的片段會一起消失，Classification_Review 還掛著外鍵時甚至會直接 500。

【規則】
1. 永遠不 hard-delete Response_Classification。重新分析產生新的 attempt：
   舊結果標記 status=superseded（保留 review、audit、final_*、reviewer、
   review 時間），新結果 attempt_no = 目前 +1；Response_Segmentation_Status
   原地更新（attempt_no、拆分狀態），它就是「目前生效的是第幾次」的明確
   參照。
2. 受保護的結果（review_status 是 confirmed / modified / excluded，或曾經
   有過 review 對話紀錄）不會被重新分析取代：
     - 回答裡有受保護的片段時，不重新拆分整則回答（新拆出來的片段會跟
       人工確認過的片段重疊、重複計數），只把「處理失敗」的片段用原本的
       位置重新分類（mode=retry_segments）。
     - 沒有失敗片段可以重試時不動（mode=skip，原因 BLOCKED_BY_REVIEW）。
3. 新結果沒有任何可用片段（AI 全部失敗）時不採用，舊結果維持生效，只把
   失敗原因記在 status.last_attempt_error（第一次分析沒有舊結果時例外：
   照常寫入，讓失敗有紀錄、Admin 可以重試）。
4. 冪等：規劃（plan_reanalysis）時記下 attempt_no；寫入（apply_attempt）
   時鎖住 status 列再比對，不一致代表另一個請求已經完成 -> 放棄這次結果。
   新回答（還沒有 status 列）靠 unique constraint 擋重複寫入。
5. 每則回答的寫入都在 savepoint（begin_nested）裡：任何一步失敗整則
   rollback，不會出現「舊結果已失效、新結果卻沒寫完」的半套狀態。

Workspace / Report / Export 讀的是 status 不在 NON_COUNTABLE_STATUSES
（failed、superseded）的列，也就是 current effective attempt，新舊結果
不會重複計數。
"""

from sqlalchemy.exc import IntegrityError, OperationalError

from classification_models import (
    REVIEW_STATUS_CONFIRMED,
    REVIEW_STATUS_EXCLUDED,
    REVIEW_STATUS_MODIFIED,
    SEGMENTATION_STATUS_COMPLETED,
    SEGMENTATION_STATUS_FAILED,
    SEGMENTATION_STATUS_PARTIAL_FAILED,
    SOURCE_TYPE_USER_UPLOAD,
    Classification_Review,
    Response_Classification,
    Response_Segmentation_Status,
)
from extensions import db, taiwan_now
from services.effective_classification_service import (
    CLASSIFICATION_STATUS_FAILED,
    CLASSIFICATION_STATUS_SUPERSEDED,
)

PROTECTED_REVIEW_STATUSES = (REVIEW_STATUS_CONFIRMED, REVIEW_STATUS_MODIFIED, REVIEW_STATUS_EXCLUDED)

MODE_NEW = "new"                  # 從來沒分析過
MODE_FULL = "full"                # 整則重新拆分 + 分類
MODE_RETRY_SEGMENTS = "retry_segments"  # 只重新分類失敗的片段（有受保護片段時）
MODE_REUSE = "reuse"              # 已完成，沿用
MODE_SKIP = "skip"                # 不能動（受保護且沒有可重試的片段）

OUTCOME_APPLIED = "applied"
OUTCOME_CONFLICT = "attempt_conflict"        # 另一個請求已經完成（冪等）
OUTCOME_KEPT_PREVIOUS = "kept_previous"      # 新 attempt 失敗，舊結果維持生效
OUTCOME_BLOCKED = "blocked_by_review"


class AttemptOutcome:
    def __init__(self, outcome, rows=None, reason=None):
        self.outcome = outcome
        self.rows = rows or []
        self.reason = reason

    @property
    def applied(self):
        return self.outcome == OUTCOME_APPLIED


# ═══════════════════════════════════════════════════════════════
# scope：一則回答（survey：response_id + question_id；upload：uploaded_answer_id）
# ═══════════════════════════════════════════════════════════════

def survey_scope(response_id, question_id, answer_text):
    return {
        "source_type": "survey", "response_id": response_id, "question_id": question_id,
        "upload_batch_id": None, "uploaded_answer_id": None, "answer_text": answer_text,
    }


def _rows_query(scope):
    query = Response_Classification.query
    if scope["source_type"] == SOURCE_TYPE_USER_UPLOAD:
        return query.filter_by(uploaded_answer_id=scope["uploaded_answer_id"])
    return query.filter_by(response_id=scope["response_id"], question_id=scope["question_id"])


def _status_query(scope):
    query = Response_Segmentation_Status.query
    if scope["source_type"] == SOURCE_TYPE_USER_UPLOAD:
        return query.filter_by(uploaded_answer_id=scope["uploaded_answer_id"])
    return query.filter_by(response_id=scope["response_id"], question_id=scope["question_id"])


def current_rows(scope, lock=False):
    query = _rows_query(scope).filter(
        db.or_(Response_Classification.status.is_(None),
               Response_Classification.status != CLASSIFICATION_STATUS_SUPERSEDED)
    ).order_by(Response_Classification.segment_start.asc(), Response_Classification.classification_id.asc())
    return (query.with_for_update() if lock else query).all()


def protected_row_ids(rows):
    """人工定案過、或曾經有 review 對話紀錄的列（重新分析不可取代）。"""
    ids = {r.classification_id for r in rows if r.review_status in PROTECTED_REVIEW_STATUSES}
    candidate_ids = [r.classification_id for r in rows if r.classification_id not in ids]
    if candidate_ids:
        reviewed = db.session.query(Classification_Review.classification_id).filter(
            Classification_Review.classification_id.in_(candidate_ids)
        ).distinct().all()
        ids.update(cid for (cid,) in reviewed)
    return ids


def _usable_segments(segments):
    return [s for s in segments if s.get("status") != CLASSIFICATION_STATUS_FAILED]


def _segmentation_status_for(rows):
    if not rows:
        return SEGMENTATION_STATUS_FAILED
    failed = [r for r in rows if r.status == CLASSIFICATION_STATUS_FAILED]
    if not failed:
        return SEGMENTATION_STATUS_COMPLETED
    return SEGMENTATION_STATUS_PARTIAL_FAILED if len(failed) < len(rows) else SEGMENTATION_STATUS_FAILED


# ═══════════════════════════════════════════════════════════════
# 規劃
# ═══════════════════════════════════════════════════════════════

def plan_reanalysis(scope):
    """決定這則回答這次要怎麼處理（不寫 DB）。

    Returns dict:
        mode, expected_attempt_no, status_row, rows,
        retry_rows（retry_segments 時：要重新分類的失敗片段）, reason
    """
    status = _status_query(scope).first()
    if status is None:
        return {"mode": MODE_NEW, "expected_attempt_no": 0, "status_row": None, "rows": [], "retry_rows": []}
    rows = current_rows(scope)
    expected = status.attempt_no or 1
    if status.segmentation_status == SEGMENTATION_STATUS_COMPLETED:
        return {"mode": MODE_REUSE, "expected_attempt_no": expected, "status_row": status, "rows": rows, "retry_rows": []}

    protected = protected_row_ids(rows)
    if not protected:
        return {"mode": MODE_FULL, "expected_attempt_no": expected, "status_row": status, "rows": rows, "retry_rows": []}

    retry_rows = [r for r in rows if r.status == CLASSIFICATION_STATUS_FAILED and r.classification_id not in protected]
    if not retry_rows:
        return {
            "mode": MODE_SKIP, "expected_attempt_no": expected, "status_row": status, "rows": rows,
            "retry_rows": [], "reason": OUTCOME_BLOCKED,
        }
    return {"mode": MODE_RETRY_SEGMENTS, "expected_attempt_no": expected, "status_row": status,
            "rows": rows, "retry_rows": retry_rows}


# ═══════════════════════════════════════════════════════════════
# 寫入
# ═══════════════════════════════════════════════════════════════

def apply_attempt(scope, result, taxonomy_version_id, expected_attempt_no, mode, retry_row_ids=None):
    """把一次分析結果寫成新的 attempt（見檔案開頭規則 1~5）。

    result：classify_response_multi_segment() 的回傳格式；mode=retry_segments
    時 result["segments"] 與 retry_row_ids 一一對應（同樣的原文位置）。
    只 flush、不 commit；savepoint 失敗時整則 rollback 並回傳 conflict。
    """
    try:
        with db.session.begin_nested():
            return _apply_locked(scope, result, taxonomy_version_id, expected_attempt_no, mode, retry_row_ids or [])
    except (IntegrityError, OperationalError) as exc:
        # 兩個請求同時第一次分析同一則回答：unique constraint / 鎖等待失敗，
        # 另一個請求的結果已經（或即將）生效，這次結果放棄。
        print("[ATTEMPT][CONFLICT]", repr(exc)[:300])
        return AttemptOutcome(OUTCOME_CONFLICT, reason="concurrent_first_attempt")


def _apply_locked(scope, result, taxonomy_version_id, expected_attempt_no, mode, retry_row_ids):
    from services.classification_persistence import build_classification_rows

    now = taiwan_now()
    status = _status_query(scope).with_for_update().first()
    current_no = (status.attempt_no or 1) if status is not None else 0
    if current_no != expected_attempt_no:
        return AttemptOutcome(OUTCOME_CONFLICT, reason=f"attempt_no {current_no} != expected {expected_attempt_no}")

    segments = result.get("segments") or []
    usable = _usable_segments(segments)

    if status is None:
        # 第一次分析：照常寫入（失敗也要有紀錄，Admin 才能看到、重試）
        status = Response_Segmentation_Status(
            response_id=scope["response_id"], upload_batch_id=scope["upload_batch_id"],
            uploaded_answer_id=scope["uploaded_answer_id"], question_id=scope["question_id"],
            source_type=scope["source_type"], segmentation_status=result["segmentation_status"],
            error_detail=result.get("segmentation_error_detail"), attempt_no=1,
        )
        db.session.add(status)
        db.session.flush()
        rows = build_classification_rows(scope, segments, taxonomy_version_id, attempt_no=1)
        return AttemptOutcome(OUTCOME_APPLIED, rows=rows)

    rows = current_rows(scope, lock=True)
    protected = protected_row_ids(rows)
    next_no = current_no + 1

    if not usable:
        status.last_attempt_error = (result.get("segmentation_error_detail")
                                     or _first_error(segments) or "AI 沒有產生任何可用的分類結果")[:2000]
        status.last_attempt_at = now
        return AttemptOutcome(OUTCOME_KEPT_PREVIOUS, reason=status.last_attempt_error)

    if mode == MODE_FULL:
        if protected:
            # 規劃之後有人審核了這則回答：不能整則取代
            return AttemptOutcome(OUTCOME_BLOCKED, reason="reviewed_after_plan")
        for row in rows:
            row.status = CLASSIFICATION_STATUS_SUPERSEDED
            row.updated_at = now
        db.session.flush()
        new_rows = build_classification_rows(scope, segments, taxonomy_version_id, attempt_no=next_no)
        status.segmentation_status = result["segmentation_status"]
        status.error_detail = result.get("segmentation_error_detail")
    elif mode == MODE_RETRY_SEGMENTS:
        by_id = {r.classification_id: r for r in rows}
        new_rows = []
        for row_id, seg in zip(retry_row_ids, segments):
            old = by_id.get(row_id)
            if old is None or row_id in protected or old.status != CLASSIFICATION_STATUS_FAILED:
                continue  # 規劃之後狀態變了：這一段不動
            if seg.get("status") == CLASSIFICATION_STATUS_FAILED:
                continue  # 這一段仍失敗：保留舊的失敗列
            old.status = CLASSIFICATION_STATUS_SUPERSEDED
            old.updated_at = now
            db.session.flush()
            new_rows.extend(build_classification_rows(
                scope, [{**seg, "orig_start": old.segment_start, "orig_end": old.segment_end}],
                # 記錄這次分類實際使用的 taxonomy version（prompt 與人工審核範例都來自它）
                taxonomy_version_id or old.taxonomy_version_id, attempt_no=next_no,
            ))
        if not new_rows:
            status.last_attempt_error = _first_error(segments) or "失敗片段重新分類仍然失敗"
            status.last_attempt_at = now
            return AttemptOutcome(OUTCOME_KEPT_PREVIOUS, reason=status.last_attempt_error)
        db.session.flush()
        status.segmentation_status = _segmentation_status_for(current_rows(scope))
        status.error_detail = None if status.segmentation_status == SEGMENTATION_STATUS_COMPLETED else status.error_detail
    else:
        raise ValueError(f"apply_attempt 不支援 mode={mode}")

    status.attempt_no = next_no
    status.last_attempt_error = None
    status.last_attempt_at = now
    db.session.flush()
    return AttemptOutcome(OUTCOME_APPLIED, rows=new_rows)


def _first_error(segments):
    for seg in segments:
        if seg.get("error_detail"):
            return str(seg["error_detail"])[:2000]
    return None
