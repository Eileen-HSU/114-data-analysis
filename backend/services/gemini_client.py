import contextvars
import logging
import os

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


# ── 備援模型：主要模型暫時過載或額度用完時，改用另一個模型 ─────────────────
# 503（模型過載）和 429（額度用完）都是「這個模型」的狀況；Gemini 的額度也是
# 每個模型各算各的。所以第一個模型失敗時，立刻換備援模型再試一次，不要在同一個
# 模型上一直等待重試。
#
# 只有「主要模型」會有備援（預設只有分類流程用的 gemini-3.1-flash-lite）。
# AI 再確認等刻意使用較強模型的呼叫不套用：如果它退回同一個弱模型，兩次判斷
# 一致就會被當成「雙重確認」自動通過，失去再確認的意義。
#
# 環境變數 GEMINI_FALLBACK_MODEL：備援模型名稱，可用逗號分隔多個，依序嘗試
# （預設 gemini-3.5-flash-lite,gemini-3.6-flash,gemini-3.8-flash）；設成空字串可完全關閉備援。
# 預設值依 Google 官方模型清單（ai.google.dev/gemini-api/docs/models）：舊預設的 gemini-3.5-flash 不在清單內
# （只有 gemini-3.5-flash-lite），gemini-2.5-flash 是 Legacy 且只開放給近期用過的帳號，兩者都可能整個備援失效。
# 模型停用 / 改名時可直接用環境變數覆蓋，不必改程式。
_PRIMARY_MODELS_WITH_FALLBACK = ("gemini-3.1-flash-lite",)
_DEFAULT_FALLBACK_MODELS = "gemini-3.5-flash-lite,gemini-3.6-flash,gemini-3.8-flash"


def fallback_models_for(model_name):
    """回傳這個模型依序要嘗試的備援模型清單；沒有備援（或已被關閉）回傳空清單。"""
    name = _normalize_model_name(model_name)
    if name not in _PRIMARY_MODELS_WITH_FALLBACK:
        return []
    raw = os.getenv("GEMINI_FALLBACK_MODEL")
    raw = _DEFAULT_FALLBACK_MODELS if raw is None else raw
    models = []
    for item in raw.split(","):
        item = _normalize_model_name(item)
        if item and item != name and item not in models:
            models.append(item)
    return models


def is_quota_error(exc: Exception) -> bool:
    """額度用完／被限流（HTTP 429 / RESOURCE_EXHAUSTED）。"""
    text = str(exc)
    return "429" in text or "RESOURCE_EXHAUSTED" in text


def should_switch_model(exc: Exception) -> bool:
    return is_transient_unavailable_error(exc) or is_quota_error(exc)


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


def translation_api_key():
    """類別名稱翻譯專用的 key（TRANSLATION_GEMINI_API_KEY）。沒設定時回傳 None（沿用原本的 key）。"""
    return os.getenv("TRANSLATION_GEMINI_API_KEY", "").strip() or None


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
        log = logging.getLogger(__name__)
        try:
            return self._call(client, self.model_name, contents, config)
        except Exception as exc:
            fallbacks = fallback_models_for(self.model_name) if should_switch_model(exc) else []
            for fallback in fallbacks:
                # 先不當成錯誤紀錄：備援成功的話，使用者端和後台都不該看到「失敗」。
                log.warning("Gemini 模型 %s 暫時無法使用（%s），改用備援模型 %s",
                            self.model_name, str(exc)[:120], fallback)
                try:
                    result = self._call(client, fallback, contents, config)
                    log.info("Gemini 備援模型 %s 呼叫成功", fallback)
                    return result
                except Exception as fallback_exc:  # noqa: BLE001
                    log.warning("Gemini 備援模型 %s 也失敗：%s", fallback, str(fallback_exc)[:120])
            # 寫進 log（也會進後台的系統錯誤紀錄；訊息裡帶錯誤內容，額度用完才會被
            # 歸類成 AI_QUOTA_EXCEEDED。數字不同的同一種錯誤會合併成一筆累加次數）
            # 一律拋出「主要模型」的原始錯誤，呼叫端原本依錯誤內容做的重試／等待照舊。
            log.error("Gemini 呼叫失敗（模型 %s）：%s", self.model_name, exc, exc_info=True)
            raise

    @staticmethod
    def _call(client, model_name, contents, config):
        return client.models.generate_content(
            model=_normalize_model_name(model_name),
            contents=contents,
            config=config,
        )
