import contextvars
import os
import traceback

from google import genai
from google.genai import types


_api_key = (
    os.getenv("PPT_SURVEY_AI_API_KEY")
    or os.getenv("GEMINI_API_KEY")
    or os.getenv("GOOGLE_API_KEY")
)


# Gemini 暫時過載（HTTP 503 / UNAVAILABLE，例如「This model is currently
# experiencing high demand」）時的自動重試間隔（秒）。這類錯誤通常幾秒內
# 就會恢復，跟 429 限流（要照 retryDelay 等待）是不同情況，分開處理。
UNAVAILABLE_RETRY_DELAYS_SECONDS = (2.0, 4.0, 8.0)


def is_transient_unavailable_error(exc: Exception) -> bool:
    """Gemini 伺服器端暫時不可用（503 / UNAVAILABLE / overloaded）。"""
    text = str(exc)
    return (
        "503" in text
        or "UNAVAILABLE" in text
        or "ServiceUnavailable" in type(exc).__name__
        or "overloaded" in text.lower()
    )


def configure(api_key=None, **_kwargs):
    global _api_key
    _api_key = api_key or _api_key


# ── 額度分流：Admin 觸發的 AI 呼叫改用另一個帳號的 key ─────────────────
# Gemini 額度以帳號／專案計算，所以 Admin 的操作（審核對話、重新處理、
# 全部重試、自動歸納分類架構、Admin 產生報告）用 ADMIN_GEMINI_API_KEY，
# 就不會跟使用者上傳、問卷分析搶同一份額度。沒有設定時沿用原本的 key。
#
# 用 ContextVar 而不是改全域 _api_key：同一個 process 同時處理多個請求
# （gunicorn gthread），只有這個請求／這條 thread 會切換，其他請求不受影響。
_key_override = contextvars.ContextVar("gemini_api_key_override", default=None)


def admin_api_key():
    return os.getenv("ADMIN_GEMINI_API_KEY", "").strip() or None


def use_api_key(api_key):
    """在目前的 context 改用 api_key（None 表示沿用預設）。回傳 token 給 reset_api_key。"""
    return _key_override.set(api_key or None)


def reset_api_key(token):
    _key_override.reset(token)


def current_api_key():
    return _key_override.get() or _api_key


def _create_client():
    api_key = current_api_key()
    if api_key:
        return genai.Client(api_key=api_key)
    return genai.Client()


def _normalize_model_name(model_name):
    model_name = (model_name or "").strip()
    if model_name.startswith("models/"):
        return model_name.removeprefix("models/")
    return model_name


class GenerativeModel:
    def __init__(self, model_name, system_instruction=None, **_kwargs):
        self.model_name = model_name
        self.system_instruction = system_instruction

    def generate_content(self, contents, generation_config=None, **_kwargs):
        config_data = dict(generation_config or {})
        if self.system_instruction:
            config_data["system_instruction"] = self.system_instruction
        config = types.GenerateContentConfig(**config_data) if config_data else None
        client = _create_client()
        try:
            return client.models.generate_content(
                model=_normalize_model_name(self.model_name),
                contents=contents,
                config=config,
            )
        except Exception:
            traceback.print_exc()
            raise
