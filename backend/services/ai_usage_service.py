"""
AI 用量紀錄：每次呼叫 AI 後記下「時間、功能、模型、結果、token 數、所屬單位」。

最重要的原則：用量紀錄失敗絕對不能影響原本的 AI 流程。
    - record_call() / finish_unit() 內部任何錯誤都只寫 log，不往外拋。
    - 寫入使用獨立的資料庫連線與交易（db.engine.begin()），不經過
      db.session：不會把呼叫端還沒 commit 的資料一起送出，記錄失敗
      也不會 rollback 呼叫端的分析結果。
    - 不存 prompt、原文、回答內容、AI 回應內容、email。只存數字。

「單位」（unit）用來算平均成本：
    - survey_generation：一次「上傳教材產生問卷」（unit_id = task_id）
    - analysis_batch   ：一次分析批次（上傳檔案分析 = upload_batch_id；
                         問卷分析 = 每次按「分析」產生一個新的批次 id）
  單位存在 ContextVar 裡：同一個 request／thread 內的 AI 呼叫自動歸到
  同一個單位；其他 request（gunicorn gthread）互不影響。背景 thread
  不會繼承 ContextVar，所以背景工作要自己呼叫 begin_unit()。
"""

from __future__ import annotations

import contextvars
import logging
import os
import re
import time
from contextlib import contextmanager
from datetime import date, timedelta

from extensions import db, taiwan_now

logger = logging.getLogger(__name__)

# 功能代碼 → 中英文名稱（前端也有同一份對照，見 AiUsagePage.jsx）
FEATURES = {
    "classification": ("回答分類", "Classification"),
    "segmentation": ("回答拆段", "Segmentation"),
    "routing": ("題目主題判斷", "Topic routing"),
    "summary": ("群組摘要", "Group summaries"),
    "second_opinion": ("AI 第二意見", "AI second opinion"),
    "review_chat": ("審核對話", "Review chat"),
    "taxonomy_generation": ("分類架構歸納", "Taxonomy generation"),
    "translation": ("類別名稱翻譯", "Category translation"),
    "chat_ask": ("分析結果追問", "Ask about results"),
    "survey_generation": ("問卷生成", "Survey generation"),
    "survey_revision": ("問卷 AI 修改", "Survey revision"),
    "other": ("其他", "Other"),
}

# 呼叫 GenerativeModel 的模組 → 功能代碼。GenerativeModel 建立時自動看是哪個
# 模組建立的，不用每個呼叫點各自傳參數（也不影響測試裡替換掉的假 model）。
MODULE_FEATURES = {
    "services.classify_v2": "classification",
    "services.classification_service": "classification",
    "services.segmentation_service": "segmentation",
    "services.question_routing_service": "routing",
    "services.aggregated_summary_service": "summary",
    "services.second_opinion_service": "second_opinion",
    "services.review_ai_service": "review_chat",
    "services.taxonomy_generation_service": "taxonomy_generation",
    "services.category_name_service": "translation",
    "services.chat_ask_service": "chat_ask",
    "services.ppt_survey_ai_service": "survey_generation",
}

UNIT_SURVEY_GENERATION = "survey_generation"
UNIT_ANALYSIS_BATCH = "analysis_batch"

OUTCOME_SUCCESS = "success"
OUTCOME_QUOTA = "quota"
OUTCOME_UNAVAILABLE = "unavailable"
OUTCOME_ERROR = "error"

DEFAULT_RETENTION_DAYS = 180

_app = None
_ctx: contextvars.ContextVar = contextvars.ContextVar("ai_usage_unit", default=None)
_STATUS_RE = re.compile(r"\b(400|401|403|404|408|409|429|500|502|503|504)\b")


def init_app(app):
    """app.py 啟動時呼叫：記住 app（背景 thread 沒有 app context 時用來寫入），
    並在每個 request 結束時把這個 request 開的單位收尾寫入。"""
    global _app
    _app = app

    @app.teardown_request
    def _finish_request_unit(exc):  # noqa: ANN001
        try:
            from flask import g

            token = g.pop("_ai_usage_unit_token", None)
            if token is not None:
                finish_unit(token, status="failed" if exc is not None else "completed")
        except Exception:  # noqa: BLE001
            logger.warning("AI usage: finishing request unit failed", exc_info=True)


def now_naive():
    return taiwan_now().replace(tzinfo=None)


def feature_for_module(module_name):
    return MODULE_FEATURES.get(module_name or "", "other")


# ── 單位（unit）──────────────────────────────────────────────

def begin_unit(unit_type, unit_id, user_id=None, feature=None):
    """開始一個單位，回傳 token（交給 finish_unit 收尾）。"""
    state = {
        "unit_type": unit_type,
        "unit_id": str(unit_id)[:64] if unit_id is not None else None,
        "user_id": user_id,
        "feature": feature,
        "item_count": 0,
        "char_count": 0,
        "created_at": now_naive(),
    }
    return _ctx.set(state)


def bind_request_unit(unit_type, unit_id, user_id=None, feature=None):
    """在 Flask request 裡開始一個單位；request 結束時（teardown）自動收尾。
    任何錯誤都只寫 log，不影響呼叫端。"""
    if _app is None:
        # 沒有呼叫 init_app（例如單元測試自己組的 app）就沒有 teardown 收尾，
        # 不開單位，避免單位殘留到同一條 thread 的下一個 request。
        return
    try:
        from flask import g

        previous = g.pop("_ai_usage_unit_token", None)
        if previous is not None:
            finish_unit(previous)
        g._ai_usage_unit_token = begin_unit(unit_type, unit_id, user_id=user_id, feature=feature)
    except Exception:  # noqa: BLE001
        logger.warning("AI usage: bind_request_unit failed", exc_info=True)


def add_items(count, chars):
    """目前的單位加上「送進 AI 分析的回覆筆數與字數」。沒有單位時不做事。"""
    state = _ctx.get()
    if not state:
        return
    try:
        state["item_count"] += max(0, int(count or 0))
        state["char_count"] += max(0, int(chars or 0))
    except Exception:  # noqa: BLE001
        logger.warning("AI usage: add_items failed", exc_info=True)


def current_unit():
    return _ctx.get()


def finish_unit(token, status="completed"):
    """收尾：寫入一筆 AI_Usage_Unit（同一單位重複收尾時更新筆數），並還原 ContextVar。"""
    state = _ctx.get()
    try:
        _ctx.reset(token)
    except Exception:  # noqa: BLE001  token 不屬於這個 context（例如換了 thread）
        pass
    if not state or not state.get("unit_id"):
        return
    try:
        _write_unit(state, status)
    except Exception:  # noqa: BLE001
        logger.warning("AI usage: writing unit failed (ignored)", exc_info=True)


@contextmanager
def unit_scope(unit_type, unit_id, user_id=None, feature=None):
    """背景工作用：with ai_usage.unit_scope(...) 包住整段工作。"""
    token = begin_unit(unit_type, unit_id, user_id=user_id, feature=feature)
    status = {"value": "completed"}
    try:
        yield status
    except Exception:
        status["value"] = "failed"
        raise
    finally:
        finish_unit(token, status=status["value"])


@contextmanager
def feature_scope(feature):
    """暫時指定這段程式裡 AI 呼叫的功能代碼（例如問卷 AI 修改）。"""
    state = _ctx.get()
    if state is None:
        token = _ctx.set({"unit_type": None, "unit_id": None, "user_id": None, "feature": feature,
                          "item_count": 0, "char_count": 0, "created_at": now_naive()})
        try:
            yield
        finally:
            _ctx.reset(token)
        return
    previous = state.get("feature")
    state["feature"] = feature
    try:
        yield
    finally:
        state["feature"] = previous


def current_feature(default="other"):
    state = _ctx.get()
    return (state or {}).get("feature") or default


# ── 每次 AI 呼叫 ─────────────────────────────────────────────

def classify_error(exc):
    """回傳 (outcome, error_code)。只取狀態碼，不保留錯誤訊息內容。"""
    text = f"{type(exc).__name__} {exc}"
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    code = str(code) if isinstance(code, int) else None
    if not code:
        match = _STATUS_RE.search(text)
        code = match.group(1) if match else None
    if code == "429" or "RESOURCE_EXHAUSTED" in text:
        return OUTCOME_QUOTA, code or "429"
    if code == "503" or "UNAVAILABLE" in text or "overloaded" in text.lower():
        return OUTCOME_UNAVAILABLE, code or "503"
    return OUTCOME_ERROR, code


def _int(value):
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def extract_tokens(response):
    """從 Gemini 回應的 usage_metadata 取 (輸入, 輸出, 思考) token 數；沒有就是 0。"""
    meta = getattr(response, "usage_metadata", None)
    if meta is None:
        return 0, 0, 0
    get = (lambda k: meta.get(k)) if isinstance(meta, dict) else (lambda k: getattr(meta, k, None))
    return (
        _int(get("prompt_token_count")),
        _int(get("candidates_token_count")),
        _int(get("thoughts_token_count")),
    )


def record_call(feature, requested_model, actual_model, response=None, error=None, started=None):
    """記一筆 AI 呼叫。response 與 error 擇一：成功給 response，失敗給 error。
    started 是 time.monotonic() 的開始時間（可省略）。不會拋出任何例外。"""
    try:
        state = _ctx.get() or {}
        if error is not None:
            outcome, error_code = classify_error(error)
            tokens = (0, 0, 0)
        else:
            outcome, error_code = OUTCOME_SUCCESS, None
            tokens = extract_tokens(response)
        latency = int((time.monotonic() - started) * 1000) if started is not None else None
        row = {
            "created_at": now_naive(),
            "feature": (feature or state.get("feature") or "other")[:40],
            "requested_model": _model(requested_model),
            "actual_model": _model(actual_model) or "unknown",
            "outcome": outcome,
            "error_code": error_code,
            "input_tokens": tokens[0],
            "output_tokens": tokens[1],
            "thinking_tokens": tokens[2],
            "latency_ms": latency,
            "unit_type": state.get("unit_type"),
            "unit_id": state.get("unit_id"),
            "user_id": state.get("user_id"),
        }
        _insert_log(row)
    except Exception:  # noqa: BLE001
        logger.warning("AI usage: recording call failed (ignored)", exc_info=True)


def _model(name):
    name = (name or "").strip()
    if name.startswith("models/"):
        name = name[len("models/"):]
    return name[:64] or None


# ── 寫入（獨立連線、獨立交易）──────────────────────────────

def _run_with_app(fn):
    from flask import has_app_context

    if has_app_context():
        return fn()
    if _app is None:
        logger.debug("AI usage: no app registered, skip recording")
        return None
    with _app.app_context():
        return fn()


def _insert_log(row):
    from ai_usage_models import AI_Usage_Log

    def write():
        with db.engine.begin() as conn:
            conn.execute(AI_Usage_Log.__table__.insert().values(**row))

    _run_with_app(write)


def _write_unit(state, status):
    from sqlalchemy import select

    from ai_usage_models import AI_Usage_Unit

    table = AI_Usage_Unit.__table__

    def write():
        with db.engine.begin() as conn:
            existing = conn.execute(
                select(table.c.unit_pk).where(
                    table.c.unit_type == state["unit_type"], table.c.unit_id == state["unit_id"]
                )
            ).first()
            values = {
                "user_id": state.get("user_id"),
                "item_count": state.get("item_count") or 0,
                "char_count": state.get("char_count") or 0,
                "status": status,
                "finished_at": now_naive(),
            }
            if existing:
                conn.execute(table.update().where(table.c.unit_pk == existing[0]).values(**values))
            else:
                conn.execute(table.insert().values(
                    unit_type=state["unit_type"], unit_id=state["unit_id"],
                    created_at=state.get("created_at") or now_naive(), **values,
                ))

    _run_with_app(write)


# ── 保留期限：明細彙總成每日一筆後刪除 ───────────────────────

def retention_days():
    try:
        return max(30, int(os.getenv("AI_USAGE_RETENTION_DAYS", DEFAULT_RETENTION_DAYS)))
    except ValueError:
        return DEFAULT_RETENTION_DAYS


def rollup_and_purge(now=None, days=None):
    """把超過保留期限的明細彙總進 AI_Usage_Daily，再刪除那些明細。
    重複執行安全：已刪除的明細不會再被彙總一次。回傳彙總的明細筆數。"""
    from sqlalchemy import and_, func, select

    from ai_usage_models import AI_Usage_Daily, AI_Usage_Log, AI_Usage_Unit

    now = now or now_naive()
    cutoff = (now - timedelta(days=days or retention_days())).replace(hour=0, minute=0, second=0, microsecond=0)
    log, daily = AI_Usage_Log.__table__, AI_Usage_Daily.__table__
    day_expr = func.date(log.c.created_at)

    with db.engine.begin() as conn:
        groups = conn.execute(
            select(
                day_expr.label("day"), log.c.feature, log.c.actual_model, log.c.outcome,
                func.count().label("calls"),
                func.coalesce(func.sum(log.c.input_tokens), 0).label("inp"),
                func.coalesce(func.sum(log.c.output_tokens), 0).label("out"),
                func.coalesce(func.sum(log.c.thinking_tokens), 0).label("think"),
            ).where(log.c.created_at < cutoff)
            .group_by(day_expr, log.c.feature, log.c.actual_model, log.c.outcome)
        ).all()
        moved = 0
        for g in groups:
            day = date.fromisoformat(g.day) if isinstance(g.day, str) else g.day
            key = and_(daily.c.day == day, daily.c.feature == g.feature,
                       daily.c.actual_model == g.actual_model, daily.c.outcome == g.outcome)
            existing = conn.execute(select(daily.c.daily_id).where(key)).first()
            if existing:
                conn.execute(daily.update().where(daily.c.daily_id == existing[0]).values(
                    calls=daily.c.calls + g.calls,
                    input_tokens=daily.c.input_tokens + g.inp,
                    output_tokens=daily.c.output_tokens + g.out,
                    thinking_tokens=daily.c.thinking_tokens + g.think,
                ))
            else:
                conn.execute(daily.insert().values(
                    day=day, feature=g.feature, actual_model=g.actual_model, outcome=g.outcome,
                    calls=g.calls, input_tokens=g.inp, output_tokens=g.out, thinking_tokens=g.think,
                ))
            moved += g.calls
        conn.execute(log.delete().where(log.c.created_at < cutoff))
        conn.execute(AI_Usage_Unit.__table__.delete().where(AI_Usage_Unit.__table__.c.created_at < cutoff))
    return moved


def scheduled_rollup(app):
    """APScheduler 每天執行一次（見 routes/workspaces/trash.py 的 start_scheduler）。"""
    with app.app_context():
        try:
            moved = rollup_and_purge()
            if moved:
                logger.info("AI usage: rolled up %s old log rows", moved)
        except Exception:  # noqa: BLE001
            logger.exception("AI usage: scheduled rollup failed")
