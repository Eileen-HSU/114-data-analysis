"""
頻率限制（固定時間窗，計數存資料庫）。

- 一行 SQL 完成 atomic 計數（MySQL: ON DUPLICATE KEY UPDATE；SQLite 測試環境:
  ON CONFLICT DO UPDATE），不會有 read-modify-write 的 race condition。
- 用獨立連線（db.engine.begin()），不影響呼叫端目前的交易。
- 識別資料（email / IP）只存雜湊，不存明文。
- 計數資料庫寫入失敗時「放行」並寫 log（可用性優先，避免 DB 小問題讓全站無法登入）。
- 超過限制是「冷卻」：該時間窗結束後自動恢復，不永久鎖帳號。
- 所有門檻可用環境變數調整（見 LIMITS）。
"""

import hashlib
import logging
import os
import time
from datetime import datetime, timedelta

from flask import request
from sqlalchemy import text

from extensions import db

logger = logging.getLogger(__name__)

# (環境變數名, 預設次數, 預設時間窗秒數)
LIMITS = {
    "login_account": ("RL_LOGIN_ACCOUNT_MAX", 5, 10 * 60),
    "login_ip": ("RL_LOGIN_IP_MAX", 20, 10 * 60),
    "otp_email_min": ("RL_OTP_EMAIL_PER_MIN", 1, 60),
    "otp_email_hour": ("RL_OTP_EMAIL_PER_HOUR", 5, 3600),
    "otp_ip_hour": ("RL_OTP_IP_PER_HOUR", 20, 3600),
    "disable2fa_account": ("RL_DISABLE2FA_ACCOUNT_MAX", 5, 10 * 60),
    "disable2fa_ip": ("RL_DISABLE2FA_IP_MAX", 20, 10 * 60),
    "register_ip": ("RL_REGISTER_IP_PER_HOUR", 5, 3600),
    "survey_min": ("RL_SURVEY_PER_MIN", 60, 60),
    "survey_hour": ("RL_SURVEY_PER_HOUR", 150, 3600),
}


def limit_of(name):
    env, default_max, window = LIMITS[name]
    try:
        value = int(os.getenv(env, ""))
        if value < 1:
            raise ValueError
    except ValueError:
        value = default_max
    return value, window


def client_ip():
    """真實 IP：依賴 app.py 的 ProxyFix（層數由 PROXY_FIX_X_FOR 設定）。"""
    return request.remote_addr or "unknown"


def _ident_hash(value):
    return hashlib.sha256(str(value or "").strip().lower().encode("utf-8")).hexdigest()[:32]


def _window_start(window_seconds, now=None):
    now = int(now if now is not None else time.time())
    return now - (now % window_seconds)


def _key(scope, ident, window_seconds, now=None):
    start = _window_start(window_seconds, now)
    return f"{scope}:{_ident_hash(ident)}:{start}", start


def _expires_at(start, window_seconds):
    # 比時間窗多留一點，讓「剩餘冷卻秒數」可以算準；清除由排程處理
    return datetime.utcfromtimestamp(start + window_seconds + 60)


def _dialect():
    return db.engine.dialect.name


def _incr_sql():
    if _dialect() == "mysql":
        return text(
            "INSERT INTO `Rate_Limit_Counter` (counter_key, hit_count, expires_at) "
            "VALUES (:k, 1, :e) ON DUPLICATE KEY UPDATE hit_count = hit_count + 1"
        )
    return text(
        "INSERT INTO Rate_Limit_Counter (counter_key, hit_count, expires_at) "
        "VALUES (:k, 1, :e) ON CONFLICT(counter_key) DO UPDATE SET hit_count = hit_count + 1"
    )


def _retry_after(start, window_seconds, now=None):
    now = now if now is not None else time.time()
    return max(1, int(start + window_seconds - now))


def peek(scope, ident, limit, window_seconds, now=None):
    """只查詢、不計數。回傳 (是否仍可通過, 需等待秒數)。"""
    key, start = _key(scope, ident, window_seconds, now)
    try:
        with db.engine.connect() as conn:
            count = conn.execute(
                text("SELECT hit_count FROM Rate_Limit_Counter WHERE counter_key = :k"), {"k": key}
            ).scalar() or 0
    except Exception:
        logger.error("rate limit peek failed", exc_info=True)
        return True, 0
    if count >= limit:
        return False, _retry_after(start, window_seconds, now)
    return True, 0


def hit(scope, ident, limit, window_seconds, now=None):
    """計數 +1（atomic）。回傳 (是否仍可通過, 需等待秒數)。第 limit 次仍通過，第 limit+1 次起拒絕。"""
    key, start = _key(scope, ident, window_seconds, now)
    try:
        with db.engine.begin() as conn:
            conn.execute(_incr_sql(), {"k": key, "e": _expires_at(start, window_seconds)})
            count = conn.execute(
                text("SELECT hit_count FROM Rate_Limit_Counter WHERE counter_key = :k"), {"k": key}
            ).scalar() or 0
    except Exception:
        logger.error("rate limit hit failed", exc_info=True)
        return True, 0
    if count > limit:
        return False, _retry_after(start, window_seconds, now)
    return True, 0


def clear(scope, ident, window_seconds, now=None):
    key, _ = _key(scope, ident, window_seconds, now)
    try:
        with db.engine.begin() as conn:
            conn.execute(text("DELETE FROM Rate_Limit_Counter WHERE counter_key = :k"), {"k": key})
    except Exception:
        logger.error("rate limit clear failed", exc_info=True)


# ---- 高階 helper（讓路由程式碼短一點） ----

def blocked(name, ident, now=None):
    """失敗計數型（登入、關閉 2FA）：已達上限則回傳 (True, 等待秒數)。"""
    limit, window = limit_of(name)
    ok, wait = peek(name, ident, limit, window, now)
    return (not ok), wait


def record_failure(name, ident, now=None):
    limit, window = limit_of(name)
    hit(name, ident, limit, window, now)  # 只計數，回傳值不使用


def reset(name, ident, now=None):
    _, window = limit_of(name)
    clear(name, ident, window, now)


def allow(name, ident, now=None):
    """每次請求都計數型（驗證碼、註冊、問卷）：回傳 (可通過, 等待秒數)。"""
    limit, window = limit_of(name)
    return hit(name, ident, limit, window, now)


def purge_expired(now=None):
    cutoff = datetime.utcfromtimestamp(now if now is not None else time.time())
    try:
        with db.engine.begin() as conn:
            res = conn.execute(
                text("DELETE FROM Rate_Limit_Counter WHERE expires_at < :c"), {"c": cutoff}
            )
        return res.rowcount or 0
    except Exception:
        logger.error("rate limit purge failed", exc_info=True)
        return 0


def scheduled_purge(app):
    with app.app_context():
        n = purge_expired()
        if n:
            logger.info("rate limit counters purged: %s", n)


def check_otp_send(email):
    """寄送驗證碼限制：同 email 每 60 秒 1 次、每小時 5 次；同 IP 每小時 20 次。
    回傳 (可通過, 需等待秒數)。不論 email 是否存在都計數，避免從限制行為反推帳號是否存在。"""
    for name, ident in (("otp_email_min", email), ("otp_email_hour", email), ("otp_ip_hour", client_ip())):
        ok, wait = allow(name, ident)
        if not ok:
            return False, wait
    return True, 0
