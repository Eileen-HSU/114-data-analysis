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


def _create_client():
    if _api_key:
        return genai.Client(api_key=_api_key)
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
