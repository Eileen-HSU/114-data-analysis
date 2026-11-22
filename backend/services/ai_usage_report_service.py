"""
Admin「AI 用量與成本」頁的統計與設定。

金額一律是「依後台設定的單價估算的參考成本」，不是實際帳單：
目前使用免費額度時實際花費為 0，這裡算的是「若改用付費方案」的金額。

單位平均（每份問卷生成、每 100 筆回覆、每 1,000 字）：
    - 只看最近 UNIT_WINDOW_DAYS 天、有 token 紀錄的單位。
    - 至少有 1 個單位就顯示；少於 RELIABLE_UNITS 個時前端標示「樣本少，僅供參考」。
      完全沒有紀錄時回傳 None（前端顯示「尚無資料」）。
    - 同時回傳平均值與第 90 百分位數（偏高情況）。
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import func

from ai_usage_models import AI_Model_Price, AI_Usage_Daily, AI_Usage_Log, AI_Usage_Setting, AI_Usage_Unit
from extensions import db
from services import ai_usage_service as usage

UNIT_WINDOW_DAYS = 90
MIN_UNITS = 1
RELIABLE_UNITS = 3  # 少於這個數量，前端標示「樣本少，僅供參考」
QUOTA_WARN_RATIO = 0.8
FX_KEY = "fx_usd_twd"

# 系統目前程式裡用到的模型：設定頁一定會列出來，方便填單價（實際用到的其他模型也會列出）
KNOWN_MODELS = (
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash-lite",
    "gemini-3.5-flash",
    "gemini-3.6-flash",
    "gemini-3.8-flash",
)

_MODEL_NAME_RE = re.compile(r"^[A-Za-z0-9._\-]{1,64}$")
MAX_PRICE_USD_PER_MTOK = Decimal("1000")
MAX_LIMIT = 1_000_000_000
MAX_FX = Decimal("1000")


class SettingsError(ValueError):
    pass


# ── 設定 ─────────────────────────────────────────────────────

def _dec(value):
    return float(value) if value is not None else None


def load_prices():
    return {row.model_name: row for row in AI_Model_Price.query.all()}


def load_fx():
    row = db.session.get(AI_Usage_Setting, FX_KEY)
    if not row or not row.value:
        return None, None
    try:
        rate = float(Decimal(row.value))
    except (InvalidOperation, ValueError):
        return None, None
    return rate, row.reference_date


def price_to_dict(name, row):
    return {
        "model_name": name,
        "input_usd_per_mtok": _dec(row.input_usd_per_mtok) if row else None,
        "output_usd_per_mtok": _dec(row.output_usd_per_mtok) if row else None,
        "rpm_limit": row.rpm_limit if row else None,
        "tpm_limit": row.tpm_limit if row else None,
        "rpd_limit": row.rpd_limit if row else None,
        "reference_date": row.reference_date.isoformat() if row and row.reference_date else None,
        "updated_at": row.updated_at.isoformat() if row and row.updated_at else None,
    }


def get_settings():
    prices = load_prices()
    seen = [r[0] for r in db.session.query(AI_Usage_Log.actual_model).distinct().all() if r[0]]
    names = list(dict.fromkeys([*KNOWN_MODELS, *sorted(prices), *sorted(seen)]))
    rate, ref = load_fx()
    return {
        "models": [price_to_dict(n, prices.get(n)) for n in names],
        "fx": {"usd_twd": rate, "reference_date": ref.isoformat() if ref else None},
    }


def _parse_price(value, label):
    if value in (None, ""):
        return None
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise SettingsError(f"{label} 必須是數字")
    if not d.is_finite() or d < 0 or d > MAX_PRICE_USD_PER_MTOK:
        raise SettingsError(f"{label} 必須介於 0 到 {MAX_PRICE_USD_PER_MTOK}")
    return d.quantize(Decimal("0.000001"))


def _parse_limit(value, label):
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise SettingsError(f"{label} 必須是整數")
    try:
        n = int(str(value))
    except ValueError:
        raise SettingsError(f"{label} 必須是整數")
    if n < 0 or n > MAX_LIMIT:
        raise SettingsError(f"{label} 必須介於 0 到 {MAX_LIMIT}")
    return n


def _parse_date(value, label):
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise SettingsError(f"{label} 日期格式必須是 YYYY-MM-DD")


def update_settings(payload, admin_id):
    """驗證並寫入單價、配額、匯率；每一項變更都寫進 Admin 操作紀錄。
    任何一項驗證失敗就整批不寫入（拋 SettingsError）。不 commit，由呼叫端 commit。"""
    from services import audit_service

    if not isinstance(payload, dict):
        raise SettingsError("格式錯誤")
    models = payload.get("models") or []
    if not isinstance(models, list) or len(models) > 50:
        raise SettingsError("models 格式錯誤")

    now = usage.now_naive()
    parsed = []
    for item in models:
        if not isinstance(item, dict):
            raise SettingsError("models 格式錯誤")
        name = str(item.get("model_name") or "").strip()
        if not _MODEL_NAME_RE.match(name):
            raise SettingsError(f"模型名稱不正確：{name[:64]}")
        parsed.append((name, {
            "input_usd_per_mtok": _parse_price(item.get("input_usd_per_mtok"), f"{name} 輸入單價"),
            "output_usd_per_mtok": _parse_price(item.get("output_usd_per_mtok"), f"{name} 輸出單價"),
            "rpm_limit": _parse_limit(item.get("rpm_limit"), f"{name} RPM"),
            "tpm_limit": _parse_limit(item.get("tpm_limit"), f"{name} TPM"),
            "rpd_limit": _parse_limit(item.get("rpd_limit"), f"{name} RPD"),
            "reference_date": _parse_date(item.get("reference_date"), f"{name} 參考日期"),
        }))

    fx_payload = payload.get("fx")
    fx_value = fx_ref = None
    if fx_payload is not None:
        if not isinstance(fx_payload, dict):
            raise SettingsError("fx 格式錯誤")
        raw = fx_payload.get("usd_twd")
        if raw not in (None, ""):
            try:
                fx_value = Decimal(str(raw))
            except (InvalidOperation, ValueError):
                raise SettingsError("匯率必須是數字")
            if not fx_value.is_finite() or fx_value <= 0 or fx_value > MAX_FX:
                raise SettingsError(f"匯率必須大於 0 且不超過 {MAX_FX}")
        fx_ref = _parse_date(fx_payload.get("reference_date"), "匯率參考日期")

    changed = 0
    for name, values in parsed:
        row = db.session.get(AI_Model_Price, name)
        before = price_to_dict(name, row) if row else None
        if row is None:
            if all(v is None for v in values.values()):
                continue
            row = AI_Model_Price(model_name=name)
            db.session.add(row)
        if before and all(_same(getattr(row, k), v) for k, v in values.items()):
            continue
        for key, value in values.items():
            setattr(row, key, value)
        row.updated_at = now
        row.updated_by_admin_id = admin_id
        db.session.flush()
        audit_service.record(
            "ai_pricing_update", "ai_model_price", name, admin_id,
            before=before, after=price_to_dict(name, row),
        )
        changed += 1

    if fx_payload is not None:
        row = db.session.get(AI_Usage_Setting, FX_KEY)
        before = {"usd_twd": row.value, "reference_date": row.reference_date.isoformat() if row and row.reference_date else None} if row else None
        new_value = str(fx_value) if fx_value is not None else None
        if not (row and row.value == new_value and row.reference_date == fx_ref) and not (row is None and new_value is None and fx_ref is None):
            if row is None:
                row = AI_Usage_Setting(key=FX_KEY)
                db.session.add(row)
            row.value = new_value
            row.reference_date = fx_ref
            row.updated_at = now
            row.updated_by_admin_id = admin_id
            audit_service.record(
                "ai_pricing_update", "ai_usage_setting", FX_KEY, admin_id,
                before=before, after={"usd_twd": new_value, "reference_date": fx_ref.isoformat() if fx_ref else None},
            )
            changed += 1
    return changed


def _same(current, new):
    if current is None or new is None:
        return current is None and new is None
    if isinstance(current, Decimal) or isinstance(new, Decimal):
        return Decimal(str(current)) == Decimal(str(new))
    return current == new


# ── 成本計算 ─────────────────────────────────────────────────

def cost_usd(prices, model, input_tokens, output_tokens, thinking_tokens):
    """依單價算美金；這個模型沒有設定單價時回傳 None（不估算，避免顯示錯誤的 0）。"""
    row = prices.get(model)
    if not row or row.input_usd_per_mtok is None or row.output_usd_per_mtok is None:
        return None
    return (
        input_tokens * float(row.input_usd_per_mtok)
        + (output_tokens + thinking_tokens) * float(row.output_usd_per_mtok)
    ) / 1_000_000


def _blank():
    return {"calls": 0, "success": 0, "failed": 0, "input_tokens": 0, "output_tokens": 0,
            "thinking_tokens": 0, "total_tokens": 0, "cost_usd": 0.0, "cost_complete": True}


def _add(bucket, prices, model, outcome, calls, inp, out, think):
    bucket["calls"] += calls
    if outcome == usage.OUTCOME_SUCCESS:
        bucket["success"] += calls
    else:
        bucket["failed"] += calls
    bucket["input_tokens"] += inp
    bucket["output_tokens"] += out
    bucket["thinking_tokens"] += think
    bucket["total_tokens"] += inp + out + think
    if inp or out or think:
        c = cost_usd(prices, model, inp, out, think)
        if c is None:
            bucket["cost_complete"] = False
        else:
            bucket["cost_usd"] += c


def _grouped(start, end):
    """[start, end) 期間，依 功能 × 實際模型 × 結果 加總：明細 + 已彙總的每日資料。"""
    log = AI_Usage_Log
    rows = db.session.query(
        log.feature, log.actual_model, log.outcome, func.count(),
        func.coalesce(func.sum(log.input_tokens), 0),
        func.coalesce(func.sum(log.output_tokens), 0),
        func.coalesce(func.sum(log.thinking_tokens), 0),
    ).filter(log.created_at >= start, log.created_at < end).group_by(
        log.feature, log.actual_model, log.outcome
    ).all()
    d = AI_Usage_Daily
    rolled = db.session.query(
        d.feature, d.actual_model, d.outcome, func.coalesce(func.sum(d.calls), 0),
        func.coalesce(func.sum(d.input_tokens), 0),
        func.coalesce(func.sum(d.output_tokens), 0),
        func.coalesce(func.sum(d.thinking_tokens), 0),
    ).filter(d.day >= start.date(), d.day < end.date()).group_by(
        d.feature, d.actual_model, d.outcome
    ).all()
    return [tuple(int(x) if i >= 3 else x for i, x in enumerate(r)) for r in [*rows, *rolled]]


def _period_summary(prices, start, end):
    total = _blank()
    by_feature = defaultdict(_blank)
    by_model = defaultdict(_blank)
    for feature, model, outcome, calls, inp, out, think in _grouped(start, end):
        for bucket in (total, by_feature[feature], by_model[model]):
            _add(bucket, prices, model, outcome, calls, inp, out, think)
    grand = total["total_tokens"] or 0

    def listing(groups, key):
        items = []
        for name, b in groups.items():
            items.append({key: name, **_finish(b), "share": (b["total_tokens"] / grand) if grand else 0.0})
        return sorted(items, key=lambda x: (-x["total_tokens"], -x["calls"]))

    return _finish(total), listing(by_feature, "feature"), listing(by_model, "model")


def _finish(bucket):
    out = dict(bucket)
    if not out.pop("cost_complete"):
        out["cost_usd_partial"] = True
    out["cost_usd"] = round(out["cost_usd"], 6)
    return out


# ── 單位平均 ─────────────────────────────────────────────────

def percentile(values, pct):
    """最近排名法（nearest-rank）。"""
    if not values:
        return None
    ordered = sorted(values)
    k = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[k - 1]


def _stat(values):
    if len(values) < MIN_UNITS:
        return None
    return {"avg": sum(values) / len(values), "p90": percentile(values, 90), "n": len(values)}


def _unit_tokens(prices, unit_type, since):
    """每個單位的 token 與成本：{unit_id: {"tokens", "cost_usd", "cost_complete", "by_feature"}}。"""
    log = AI_Usage_Log
    rows = db.session.query(
        log.unit_id, log.feature, log.actual_model,
        func.coalesce(func.sum(log.input_tokens), 0),
        func.coalesce(func.sum(log.output_tokens), 0),
        func.coalesce(func.sum(log.thinking_tokens), 0),
    ).filter(
        log.unit_type == unit_type, log.unit_id.isnot(None), log.created_at >= since,
        log.outcome == usage.OUTCOME_SUCCESS,
    ).group_by(log.unit_id, log.feature, log.actual_model).all()
    units = {}
    for unit_id, feature, model, inp, out, think in rows:
        inp, out, think = int(inp), int(out), int(think)
        u = units.setdefault(unit_id, {"tokens": 0, "cost_usd": 0.0, "cost_complete": True,
                                       "by_feature": defaultdict(int)})
        u["tokens"] += inp + out + think
        u["by_feature"][feature] += inp + out + think
        c = cost_usd(prices, model, inp, out, think)
        if c is None:
            u["cost_complete"] = False
        else:
            u["cost_usd"] += c
    return {k: v for k, v in units.items() if v["tokens"] > 0}


def _metric(token_values, cost_values):
    tokens = _stat(token_values)
    if tokens is None:
        return None
    return {
        "tokens": tokens,
        "cost_usd": _stat(cost_values) if len(cost_values) == len(token_values) else None,
    }


def unit_metrics(prices, now):
    since = now - timedelta(days=UNIT_WINDOW_DAYS)
    unit = AI_Usage_Unit

    # 每份問卷生成：只算成功完成的生成
    gen_tokens = _unit_tokens(prices, usage.UNIT_SURVEY_GENERATION, since)
    done = {r[0] for r in db.session.query(unit.unit_id).filter(
        unit.unit_type == usage.UNIT_SURVEY_GENERATION, unit.status == "completed", unit.created_at >= since,
    ).all()}
    gen = [v for k, v in gen_tokens.items() if k in done]
    per_survey = _metric([u["tokens"] for u in gen], [u["cost_usd"] for u in gen if u["cost_complete"]])

    # 分析批次：每 100 筆回覆、每 1,000 字
    batch_tokens = _unit_tokens(prices, usage.UNIT_ANALYSIS_BATCH, since)
    batches = db.session.query(unit.unit_id, unit.item_count, unit.char_count).filter(
        unit.unit_type == usage.UNIT_ANALYSIS_BATCH, unit.created_at >= since, unit.item_count > 0,
    ).all()
    per100_t, per100_c, per1k_t, per1k_c = [], [], [], []
    feature_tokens, feature_items = defaultdict(int), 0
    for unit_id, items, chars in batches:
        u = batch_tokens.get(unit_id)
        if not u:
            continue
        per100_t.append(u["tokens"] / items * 100)
        if u["cost_complete"]:
            per100_c.append(u["cost_usd"] / items * 100)
        if chars:
            per1k_t.append(u["tokens"] / chars * 1000)
            if u["cost_complete"]:
                per1k_c.append(u["cost_usd"] / chars * 1000)
        feature_items += items
        for feature, tokens in u["by_feature"].items():
            feature_tokens[feature] += tokens

    per100 = _metric(per100_t, per100_c)
    if per100 is not None:
        per100["by_feature"] = sorted(
            ({"feature": f, "tokens_per_100": t / feature_items * 100} for f, t in feature_tokens.items()),
            key=lambda x: -x["tokens_per_100"],
        )
    per1k = _metric(per1k_t, per1k_c)

    # 診斷：試算器沒有數字時，讓畫面說明是哪一步被排除（不用猜）
    all_batches = db.session.query(unit.unit_id, unit.item_count).filter(
        unit.unit_type == usage.UNIT_ANALYSIS_BATCH, unit.created_at >= since).all()
    all_gens = db.session.query(unit.unit_id, unit.status).filter(
        unit.unit_type == usage.UNIT_SURVEY_GENERATION, unit.created_at >= since).all()
    diagnostics = {
        "analysis_units": len(all_batches),
        "analysis_no_items": sum(1 for _, n in all_batches if not n),
        "analysis_no_tokens": sum(1 for uid, n in all_batches if n and uid not in batch_tokens),
        "generation_units": len(all_gens),
        "generation_not_completed": sum(1 for _, st in all_gens if st != "completed"),
        "generation_no_tokens": sum(1 for uid, st in all_gens if st == "completed" and uid not in gen_tokens),
    }

    return {
        "diagnostics": diagnostics,
        "window_days": UNIT_WINDOW_DAYS,
        "min_units": MIN_UNITS,
        "reliable_units": RELIABLE_UNITS,
        "per_survey_generation": per_survey,
        "per_100_responses": per100,
        "per_1000_chars": per1k,
        "sample_sizes": {"survey_generation": len(gen), "analysis_batches": len(per100_t)},
    }


# ── 用量／配額監控 ───────────────────────────────────────────

def quota_monitor(prices, now):
    """各模型今日請求數（對照 RPD）、今日每分鐘尖峰請求數與 token（對照 RPM／TPM）、
    最近一分鐘的用量、今日 429 次數。配額由 Admin 依官方公告填入；沒填就只顯示用量。"""
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    log = AI_Usage_Log
    rows = db.session.query(
        log.actual_model, log.created_at, log.outcome, log.input_tokens, log.output_tokens, log.thinking_tokens,
    ).filter(log.created_at >= start).all()
    per_model = {}
    last_minute_start = now - timedelta(minutes=1)
    for model, created, outcome, inp, out, think in rows:
        m = per_model.setdefault(model, {"requests_today": 0, "quota_errors_today": 0,
                                         "per_minute": defaultdict(lambda: [0, 0]),
                                         "last_minute_requests": 0, "last_minute_tokens": 0})
        tokens = (inp or 0) + (out or 0) + (think or 0)
        m["requests_today"] += 1
        if outcome == usage.OUTCOME_QUOTA:
            m["quota_errors_today"] += 1
        minute = created.replace(second=0, microsecond=0)
        m["per_minute"][minute][0] += 1
        m["per_minute"][minute][1] += tokens
        if created >= last_minute_start:
            m["last_minute_requests"] += 1
            m["last_minute_tokens"] += tokens

    result = []
    for model in sorted(set(per_model) | {n for n, p in prices.items() if p.rpd_limit or p.rpm_limit or p.tpm_limit}):
        m = per_model.get(model) or {"requests_today": 0, "quota_errors_today": 0, "per_minute": {},
                                     "last_minute_requests": 0, "last_minute_tokens": 0}
        p = prices.get(model)
        peaks = list(m["per_minute"].values())
        item = {
            "model": model,
            "requests_today": m["requests_today"],
            "quota_errors_today": m["quota_errors_today"],
            "peak_rpm_today": max((x[0] for x in peaks), default=0),
            "peak_tpm_today": max((x[1] for x in peaks), default=0),
            "last_minute_requests": m["last_minute_requests"],
            "last_minute_tokens": m["last_minute_tokens"],
            "rpd_limit": p.rpd_limit if p else None,
            "rpm_limit": p.rpm_limit if p else None,
            "tpm_limit": p.tpm_limit if p else None,
            "reference_date": p.reference_date.isoformat() if p and p.reference_date else None,
        }
        warnings = []
        if item["quota_errors_today"]:
            warnings.append("quota_errors")
        for used, limit, key in (
            (item["requests_today"], item["rpd_limit"], "rpd"),
            (item["peak_rpm_today"], item["rpm_limit"], "rpm"),
            (item["peak_tpm_today"], item["tpm_limit"], "tpm"),
        ):
            if limit and used >= limit * QUOTA_WARN_RATIO:
                warnings.append(f"near_{key}")
        item["warnings"] = warnings
        result.append(item)
    return result


# ── 對外：整頁資料 ───────────────────────────────────────────

RECENT_UNITS_LIMIT = 30
UNIT_LABELS = {usage.UNIT_SURVEY_GENERATION: "問卷生成", usage.UNIT_ANALYSIS_BATCH: "回覆分析"}


def recent_units(prices, limit=RECENT_UNITS_LIMIT):
    """最近每一次「問卷生成」「回覆分析」各自用了多少 token 與參考成本（單份明細）。"""
    from models import User

    units = (AI_Usage_Unit.query.order_by(AI_Usage_Unit.created_at.desc(), AI_Usage_Unit.unit_pk.desc())
             .limit(limit).all())
    if not units:
        return []
    ids = [u.unit_id for u in units]
    log = AI_Usage_Log
    rows = db.session.query(
        log.unit_id, log.actual_model, log.outcome,
        func.count(log.log_id),
        func.coalesce(func.sum(log.input_tokens), 0),
        func.coalesce(func.sum(log.output_tokens), 0),
        func.coalesce(func.sum(log.thinking_tokens), 0),
    ).filter(log.unit_id.in_(ids)).group_by(log.unit_id, log.actual_model, log.outcome).all()
    agg = {}
    for unit_id, model, outcome, calls, inp, out, think in rows:
        a = agg.setdefault(unit_id, {"calls": 0, "failed": 0, "input_tokens": 0, "output_tokens": 0,
                                     "thinking_tokens": 0, "cost_usd": 0.0, "cost_complete": True, "models": set()})
        a["calls"] += int(calls)
        if outcome != usage.OUTCOME_SUCCESS:
            a["failed"] += int(calls)
            continue
        inp, out, think = int(inp), int(out), int(think)
        a["input_tokens"] += inp
        a["output_tokens"] += out
        a["thinking_tokens"] += think
        a["models"].add(model)
        c = cost_usd(prices, model, inp, out, think)
        if c is None:
            a["cost_complete"] = False
        else:
            a["cost_usd"] += c
    user_ids = {u.user_id for u in units if u.user_id}
    names = dict(db.session.query(User.user_id, User.user_name).filter(User.user_id.in_(user_ids)).all()) if user_ids else {}
    result = []
    for u in units:
        a = agg.get(u.unit_id, {"calls": 0, "failed": 0, "input_tokens": 0, "output_tokens": 0,
                                "thinking_tokens": 0, "cost_usd": 0.0, "cost_complete": True, "models": set()})
        total = a["input_tokens"] + a["output_tokens"] + a["thinking_tokens"]
        result.append({
            "unit_type": u.unit_type,
            "type_label": UNIT_LABELS.get(u.unit_type, u.unit_type),
            "label": u.label or "",
            "user_name": names.get(u.user_id, ""),
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "status": u.status,
            "item_count": u.item_count or 0,
            "response_total": u.response_total,
            "char_count": u.char_count or 0,
            "calls": a["calls"],
            "failed_calls": a["failed"],
            "input_tokens": a["input_tokens"],
            "output_tokens": a["output_tokens"],
            "thinking_tokens": a["thinking_tokens"],
            "total_tokens": total,
            "cost_usd": round(a["cost_usd"], 6) if (a["cost_complete"] and total) else (0.0 if not total else None),
            "models": sorted(a["models"]),
        })
    return result


def build_summary(now=None, month=None):
    """month：'YYYY-MM'，預設本月。"""
    now = now or usage.now_naive()
    prices = load_prices()
    rate, fx_ref = load_fx()

    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if month:
        try:
            month_start = datetime.strptime(month, "%Y-%m")
        except ValueError:
            raise SettingsError("month 格式必須是 YYYY-MM")
    else:
        month_start = today_start.replace(day=1)
    month_end = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)

    today_total, _, _ = _period_summary(prices, today_start, today_start + timedelta(days=1))
    month_total, by_feature, by_model = _period_summary(prices, month_start, month_end)
    missing_prices = sorted(
        m["model"] for m in by_model
        if m["total_tokens"] and (m["model"] not in prices
                                  or prices[m["model"]].input_usd_per_mtok is None
                                  or prices[m["model"]].output_usd_per_mtok is None)
    )
    return {
        "generated_at": now.isoformat(),
        "currency": {"usd_twd": rate, "reference_date": fx_ref.isoformat() if fx_ref else None},
        "today": today_total,
        "month": {"month": month_start.strftime("%Y-%m"), **month_total},
        "by_feature": by_feature,
        "by_model": by_model,
        "unit_metrics": unit_metrics(prices, now),
        "quota": quota_monitor(prices, now),
        "recent_units": recent_units(prices),
        "missing_price_models": missing_prices,
        "price_reference_dates": sorted({p.reference_date.isoformat() for p in prices.values() if p.reference_date}),
        "retention_days": usage.retention_days(),
    }
