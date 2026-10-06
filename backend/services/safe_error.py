"""
安全的錯誤摘要：寫進 DB（routing_detail / error_detail）或回傳給前端之前，
把可能夾帶的 API key / token / 授權標頭遮掉，並截斷長度。

AI SDK 的例外訊息有時會帶出請求 URL（含 ?key=...）或設定值；這些字串
不可以原樣存進資料庫、也不可以回傳給前端。
"""

import os
import re

_PATTERNS = (
    # URL 裡的帳密：scheme://user:password@host
    (re.compile(r"(?i)([a-z][a-z0-9+.\-]*://)[^\s/@:]+:[^\s/@]+@"), r"\1[REDACTED]@"),
    # Google API key（AIza 開頭）
    (re.compile(r"AIza[0-9A-Za-z_\-]{20,}"), "[REDACTED_KEY]"),
    # Brevo API key（xkeysib- 開頭）
    (re.compile(r"xkeysib-[0-9A-Za-z\-]{20,}"), "[REDACTED_KEY]"),
    # Authorization: Bearer xxx / bearer xxx
    (re.compile(r"(?i)(bearer)\s+[A-Za-z0-9._\-~+/=]{8,}"), r"\1 [REDACTED]"),
    # key=xxx / api_key: xxx / token=xxx / secret=xxx / password=xxx（URL query 或 log 格式）
    (re.compile(r"(?i)\b(api[_-]?key|x-goog-api-key|key|token|access_token|secret|password)(\s*[=:]\s*)([^\s&,;'\"]+)"),
     r"\1\2[REDACTED]"),
)

MAX_SUMMARY_CHARS = 300


_SECRET_ENV_NAMES = (
    "GEMINI_API_KEY", "GOOGLE_API_KEY", "ADMIN_GEMINI_API_KEY", "JWT_SECRET_KEY", "BREVO_API_KEY",
    "PPT_SURVEY_AI_API_KEY", "PPT_SURVEY_AI_PRIMARY_API_KEY", "PPT_SURVEY_AI_FALLBACK_API_KEY",
    "CUTTLY_API_KEY", "ADMIN_PASSWORD",
)


def redact(text: str) -> str:
    """去除敏感資訊，但保留換行與排版（給 stack trace 用）。"""
    if not text:
        return ""
    for env_name in _SECRET_ENV_NAMES:
        secret = os.environ.get(env_name)
        if secret and len(secret) >= 8:
            text = text.replace(secret, "[REDACTED]")
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def safe_error_summary(value, limit=MAX_SUMMARY_CHARS) -> str:
    """例外或文字 -> 去除敏感資訊、截斷後的摘要（永遠回傳字串）。"""
    if value is None:
        return ""
    text = value if isinstance(value, str) else f"{type(value).__name__}: {value}"
    text = " ".join(redact(text).split())
    return text[:limit]
