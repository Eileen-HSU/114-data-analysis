"""
「全部重試」：在背景把無法分類的資料一次重跑一遍。

處理的資料（跟 Admin「其他／未歸屬資料」頁相同，見 admin_recovery_service）：
    1. 分類失敗的結果（failed）         -> retry_failed_classification
    2. 分析過但沒有任何結果的上傳回答    -> retry_failed_answer
    3. 判斷不出主題的上傳回答（unrouted）-> reroute_answer
每一筆都會走跟手動按「重新處理／重新判斷主題」一模一樣的流程與 audit。

規則：
    - 每次都「重新查下一筆還沒處理好的」，不預先列清單：同一則回答的多個
      失敗片段，重試一次就整則重新處理，不會被重複重試。
    - 每一筆在同一次工作裡最多試一次；真的失敗（AI 回答格式錯、資料有問題）
      就記成 still_failed 繼續下一筆，不會無限重跑。
    - AI 額度用完（429）或服務暫時不可用（503）不算這筆失敗：等一下、放慢
      速度、之後再試同一筆。連續 MAX_CONSECUTIVE_QUOTA 次都是額度問題就
      自動暫停（paused_quota），避免一直白打。
    - 速度自動調整：順利時逐步加快（最快每筆間隔 BULK_RETRY_MIN_DELAY_SECONDS），
      遇到額度問題就放慢。免費方案（每分鐘 15 次）跟付費方案都適用。
    - 同一時間只會有一個執行中的工作。執行它的 worker 重啟的話，heartbeat
      會停止更新，超過 STALE_AFTER 就視為中斷，可以重新開始；已經處理好的
      資料不會再被處理（它們已經不是失敗狀態了）。
"""

import logging
import os
import threading
import time
from datetime import timedelta

from classification_models import (
    BULK_RETRY_CANCELLED,
    BULK_RETRY_COMPLETED,
    BULK_RETRY_FAILED,
    BULK_RETRY_PAUSED_QUOTA,
    BULK_RETRY_RUNNING,
    Bulk_Retry_Job,
)
from extensions import db, taiwan_now

logger = logging.getLogger(__name__)

MAX_CONSECUTIVE_QUOTA = 5
QUOTA_BACKOFF_SECONDS = 60
MAX_DELAY_SECONDS = 30.0
STALE_AFTER = timedelta(minutes=5)
# 暫時性的 AI 問題（failure_explainer 的 code）：等一下再試，不算這筆失敗
_TRANSIENT_CODES = {"AI_QUOTA_EXCEEDED", "AI_SERVICE_BUSY", "AI_TIMEOUT"}
_RETRY_REASON = "全部重試（背景）"

KIND_RETRY = "retry"
KIND_SECOND_OPINION = "second_opinion"   # 見 services/second_opinion_service.py
KINDS = (KIND_RETRY, KIND_SECOND_OPINION)
SYSTEM_ADMIN_ID = 0                     # 排程自動開始的工作（沒有管理員）

# 測試會換掉這兩個，避免真的等待
_sleep = time.sleep


def _min_delay() -> float:
    try:
        return max(0.0, float(os.environ.get("BULK_RETRY_MIN_DELAY_SECONDS", "2")))
    except ValueError:
        return 2.0


class BulkRetryError(Exception):
    def __init__(self, code, message, http_status=409, job=None):
        super().__init__(message)
        self.code, self.message, self.http_status, self.job = code, message, http_status, job


# ── 狀態 ──────────────────────────────────────────────────────────

def _is_stale(job) -> bool:
    if job.heartbeat_at is None:
        return True
    heartbeat = job.heartbeat_at
    now = taiwan_now()
    if heartbeat.tzinfo is None and now.tzinfo is not None:
        now = now.replace(tzinfo=None)
    return now - heartbeat > STALE_AFTER


def _latest_job(kind=KIND_RETRY):
    return (Bulk_Retry_Job.query.filter(Bulk_Retry_Job.kind == kind)
            .order_by(Bulk_Retry_Job.job_id.desc()).first())


def job_view(job):
    if job is None:
        return None
    data = job.to_dict()
    data["interrupted"] = job.status == BULK_RETRY_RUNNING and _is_stale(job)
    return data


def remaining_counts() -> dict:
    from services.admin_recovery_service import KIND_FAILED, KIND_UNROUTED, unassigned_counts

    counts = unassigned_counts()
    return {"failed": counts[KIND_FAILED], "unrouted": counts[KIND_UNROUTED],
            "total": counts[KIND_FAILED] + counts[KIND_UNROUTED]}


def _remaining(kind) -> dict:
    if kind == KIND_SECOND_OPINION:
        from services.second_opinion_service import eligible_count

        return {"total": eligible_count()}
    return remaining_counts()


def status(kind=KIND_RETRY) -> dict:
    return {"job": job_view(_latest_job(kind)), "remaining": _remaining(kind)}


# ── 下一筆要處理的 ──────────────────────────────────────────────────

def _scope_key(row):
    if row.uploaded_answer_id is not None:
        return ("answer", row.uploaded_answer_id)
    return ("survey", row.response_id, row.question_id)


def attempt_cutoff(exclude_job_id=None):
    """最近一次「完整跑完」的全部重試（排程或 Admin 按的都算）的結束時間。
    比它更早建立的無法分類資料都已經被重試過一次；沒有跑完過的 -> None（全部都還沒試）。"""
    query = Bulk_Retry_Job.query.filter(Bulk_Retry_Job.kind == KIND_RETRY, Bulk_Retry_Job.status == BULK_RETRY_COMPLETED)
    if exclude_job_id is not None:
        query = query.filter(Bulk_Retry_Job.job_id != exclude_job_id)
    job = query.order_by(Bulk_Retry_Job.finished_at.desc()).first()
    return job.finished_at if job else None


def _untried_queries(since):
    """(失敗分類列, 零片段失敗回答, 判斷不出主題回答) 三個 query；since 不是 None 時
    只留 since 之後才出現的（還沒被自動重試過的）。"""
    from services.admin_recovery_service import (
        _failed_query, _unrouted_answers_query, _zero_segment_failed_answers_query,
    )
    from classification_models import Response_Classification, Uploaded_Answer

    failed, zero, unrouted = _failed_query(), _zero_segment_failed_answers_query(), _unrouted_answers_query()
    if since is not None:
        failed = failed.filter(Response_Classification.created_at > since)
        zero = zero.filter(Uploaded_Answer.created_at > since)
        unrouted = unrouted.filter(Uploaded_Answer.created_at > since)
    return failed, zero, unrouted


def retry_split() -> dict:
    """無法分類的資料分成兩半：
        pending      ：還沒被自動重試過 -> 系統排程會處理，不需要人
        still_failed ：已經自動重試過（最近一次跑完的重試之前就存在）仍然失敗 -> 才需要人
    pending + still_failed == remaining_counts()['total']"""
    total = remaining_counts()["total"]
    pending = sum(q.count() for q in _untried_queries(attempt_cutoff()))
    pending = min(pending, total)
    return {"pending": pending, "still_failed": total - pending, "total": total}


def _next_item(tried, since=None):
    """回傳 (kind, id, scope_key)；沒有了回傳 None。tried 是這次工作已經
    處理過（成功或真的失敗）的 scope_key 集合。since：排程自動重試只處理
    這個時間之後才出現的資料（已經自動重試過的不再重試，避免每次排程都白打）。"""
    from classification_models import Response_Classification, Uploaded_Answer

    failed_q, zero_q, unrouted_q = _untried_queries(since)
    for row in failed_q.order_by(Response_Classification.classification_id.asc()).yield_per(200):
        key = _scope_key(row)
        if key not in tried:
            return "failed_classification", row.classification_id, key
    for answer in zero_q.order_by(Uploaded_Answer.id.asc()).yield_per(200):
        key = ("answer", answer.id)
        if key not in tried:
            return "failed_answer", answer.id, key
    for answer in unrouted_q.order_by(Uploaded_Answer.id.asc()).yield_per(200):
        key = ("answer", answer.id)
        if key not in tried:
            return "unrouted_answer", answer.id, key
    return None


def _process(kind, item_id, admin_id):
    """處理一筆。回傳 (outcome, failure_code, message)，outcome 是
    success / failed / transient / skipped。"""
    from services.admin_recovery_service import (
        RecoveryError, reroute_answer, retry_failed_answer, retry_failed_classification,
    )
    from services.failure_explainer import explain_failure

    try:
        if kind == "failed_classification":
            result = retry_failed_classification(item_id, admin_id, reason=_RETRY_REASON)
            ok, failure = result.get("succeeded"), result.get("failure")
        elif kind == "failed_answer":
            result = retry_failed_answer(item_id, admin_id, reason=_RETRY_REASON)
            ok, failure = result.get("succeeded"), result.get("failure")
        else:
            from services.question_routing_service import (
                ROUTING_ERROR_RATE_LIMITED, ROUTING_ERROR_SERVICE_UNAVAILABLE, ROUTING_ERROR_TIMEOUT,
            )

            result = reroute_answer(item_id, admin_id)
            ok = bool(result.get("routed")) and result.get("succeeded", True) is not False
            failure = result.get("failure")
            routing_error = result.get("routing_error")
            if not ok and routing_error in (ROUTING_ERROR_RATE_LIMITED, ROUTING_ERROR_SERVICE_UNAVAILABLE,
                                            ROUTING_ERROR_TIMEOUT):
                return "transient", "AI_QUOTA_EXCEEDED" if routing_error == ROUTING_ERROR_RATE_LIMITED else "AI_SERVICE_BUSY", \
                    "判斷主題時 AI 暫時無法使用"
            if not ok and failure is None:
                failure = {"code": routing_error or "ROUTING_UNDETERMINED",
                           "message": result.get("routing_reason") or "判斷不出主題"}
    except RecoveryError as exc:
        db.session.rollback()
        return "skipped", exc.code, exc.message
    except Exception as exc:  # noqa: BLE001 — 單筆的非預期錯誤不能讓整個工作停下來
        db.session.rollback()
        failure = explain_failure(str(exc)) or {}
        code = failure.get("code")
        if code in _TRANSIENT_CODES:
            return "transient", code, failure.get("message")
        logger.exception("bulk retry item failed: %s %s", kind, item_id)
        return "failed", code or "UNEXPECTED_ERROR", str(exc)[:500]

    if ok:
        return "success", None, None
    code = (failure or {}).get("code")
    if code in _TRANSIENT_CODES:
        return "transient", code, (failure or {}).get("message")
    return "failed", code, (failure or {}).get("message")


# ── 執行 ──────────────────────────────────────────────────────────

def _finish(job, status_value, message=None):
    job.status = status_value
    job.finished_at = taiwan_now()
    job.heartbeat_at = job.finished_at
    if message:
        job.last_error = message
    db.session.commit()


def run_job(job_id):
    """在目前的 app context 裡把工作跑完（背景 thread 或測試直接呼叫）。"""
    job = db.session.get(Bulk_Retry_Job, job_id)
    admin_id = job.started_by_admin_id
    if job.kind == KIND_SECOND_OPINION:
        from services import second_opinion_service

        next_item, process = second_opinion_service.next_item, second_opinion_service.process
    else:
        # 排程（系統）自動開始的重試只處理還沒被自動重試過的；Admin 手動按的照舊處理全部
        since = attempt_cutoff(exclude_job_id=job_id) if admin_id == SYSTEM_ADMIN_ID else None
        next_item, process = (lambda tried: _next_item(tried, since=since)), _process
    tried = set()
    transient_tries = {}
    consecutive_quota = 0
    delay = _min_delay()

    try:
        while True:
            db.session.refresh(job)
            if job.cancel_requested:
                _finish(job, BULK_RETRY_CANCELLED)
                return
            nxt = next_item(tried)
            if nxt is None:
                _finish(job, BULK_RETRY_COMPLETED)
                return
            kind, item_id, key = nxt

            outcome, code, message = process(kind, item_id, admin_id)
            job = db.session.get(Bulk_Retry_Job, job_id)
            job.heartbeat_at = taiwan_now()

            if outcome == "transient":
                consecutive_quota += 1
                job.quota_waits += 1
                job.last_error = message
                transient_tries[key] = transient_tries.get(key, 0) + 1
                if consecutive_quota >= MAX_CONSECUTIVE_QUOTA:
                    _finish(job, BULK_RETRY_PAUSED_QUOTA,
                            "AI 額度用完或服務暫時無法使用，已自動暫停。額度恢復後再按一次即可接續。")
                    return
                if transient_tries[key] >= MAX_CONSECUTIVE_QUOTA:
                    # 同一筆一直遇到暫時性錯誤：這次工作先放過它
                    tried.add(key)
                    job.still_failed += 1
                    job.processed += 1
                db.session.commit()
                delay = min(MAX_DELAY_SECONDS, delay * 2 + 5)
                _sleep(QUOTA_BACKOFF_SECONDS)
                continue

            consecutive_quota = 0
            tried.add(key)
            job.processed += 1
            if outcome == "success":
                job.succeeded += 1
                delay = max(_min_delay(), delay * 0.8)
            elif outcome == "skipped":
                job.skipped += 1
                job.last_error = message
            else:
                job.still_failed += 1
                job.last_error = message
            db.session.commit()
            if delay:
                _sleep(delay)
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        logger.exception("bulk retry job %s crashed", job_id)
        job = db.session.get(Bulk_Retry_Job, job_id)
        if job is not None:
            _finish(job, BULK_RETRY_FAILED, f"背景工作發生錯誤：{str(exc)[:300]}")


def _run_in_thread(app, job_id):
    from services import gemini_client

    # 背景 thread 不會繼承請求的 context，要自己切換成 Admin 的 key
    token = gemini_client.use_api_key(gemini_client.admin_api_key())
    with app.app_context():
        try:
            run_job(job_id)
        finally:
            db.session.remove()
            gemini_client.reset_api_key(token)


def start(admin_id, app=None, run_inline=False, kind=KIND_RETRY) -> dict:
    """開始一個新的背景工作（全部重試或 AI 再確認）。同一種已經有執行中（且沒有中斷）的 -> 409。"""
    latest = _latest_job(kind)
    if latest is not None and latest.status == BULK_RETRY_RUNNING:
        if not _is_stale(latest):
            raise BulkRetryError("BULK_RETRY_RUNNING", "已經有一個全部重試正在執行中", 409, job_view(latest))
        _finish(latest, BULK_RETRY_FAILED, "執行中的 worker 已經重啟，工作中斷（已處理好的資料不受影響）")

    remaining = _remaining(kind)
    if remaining["total"] == 0:
        raise BulkRetryError("NOTHING_TO_RETRY", "目前沒有需要處理的資料", 409)

    now = taiwan_now()
    job = Bulk_Retry_Job(
        kind=kind, status=BULK_RETRY_RUNNING, started_by_admin_id=admin_id, total_at_start=remaining["total"],
        started_at=now, heartbeat_at=now,
    )
    db.session.add(job)
    db.session.commit()
    job_id = job.job_id

    if run_inline:
        run_job(job_id)
    else:
        thread = threading.Thread(target=_run_in_thread, args=(app, job_id), daemon=True,
                                  name=f"bulk-retry-{job_id}")
        thread.start()
    return job_view(db.session.get(Bulk_Retry_Job, job_id))


def cancel(admin_id, kind=KIND_RETRY) -> dict:
    job = _latest_job(kind)
    if job is None or job.status != BULK_RETRY_RUNNING:
        raise BulkRetryError("NOT_RUNNING", "目前沒有執行中的背景工作", 409)
    if _is_stale(job):
        _finish(job, BULK_RETRY_CANCELLED)
    else:
        job.cancel_requested = True
        db.session.commit()
    return job_view(job)


def scheduled_second_opinion(app):
    """排程呼叫（app.py，每 10 分鐘）：有需要 AI 再確認的資料、而且沒有正在跑的，
    就在這條排程 thread 裡直接跑完。用 Admin 的 Gemini key（系統背景工作，
    不佔使用者的額度）。多個 worker 各自有排程時，start() 的「同一種只能有
    一個執行中」會擋掉重複的。額度用完而暫停的，下一次排程會自動接續。"""
    from services import gemini_client

    token = gemini_client.use_api_key(gemini_client.admin_api_key())
    with app.app_context():
        try:
            from services.second_opinion_service import eligible_count

            if eligible_count() == 0:
                return
            start(SYSTEM_ADMIN_ID, run_inline=True, kind=KIND_SECOND_OPINION)
        except BulkRetryError:
            pass  # 已經有一個在跑，或剛好沒有資料
        except Exception:  # noqa: BLE001 — 排程不能因為一次失敗就停掉
            logger.exception("scheduled second opinion failed")
            db.session.rollback()
        finally:
            db.session.remove()
            gemini_client.reset_api_key(token)



def scheduled_auto_retry(app):
    """排程呼叫（app.py，每 15 分鐘）：無法分類的資料自動批次重試，不用等 Admin 按「全部重試」。
    只處理還沒被自動重試過的（見 retry_split）；重試後仍失敗的才會出現在「需要人工決策」。
    跟手動全部重試共用同一種工作（kind=retry），同時只會有一個在跑。"""
    from services import gemini_client

    token = gemini_client.use_api_key(gemini_client.admin_api_key())
    with app.app_context():
        try:
            if retry_split()["pending"] == 0:
                return
            start(SYSTEM_ADMIN_ID, run_inline=True, kind=KIND_RETRY)
        except BulkRetryError:
            pass
        except Exception:  # noqa: BLE001
            logger.exception("scheduled auto retry failed")
            db.session.rollback()
        finally:
            db.session.remove()
            gemini_client.reset_api_key(token)
