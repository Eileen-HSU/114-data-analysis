"""
把 AI 服務失敗的原始錯誤文字（例如
"BATCH_CLASSIFICATION_FAILED: 429 RESOURCE_EXHAUSTED ..." 或
"503 UNAVAILABLE ... high demand"）轉成 machine-readable code +
使用者看得懂的中英文說明。

原始錯誤仍然完整保留在 DB（reasoning / error_detail / routing_detail），
這裡只負責「顯示用的解釋」，Admin 畫面、API 錯誤訊息共用同一套判斷，
不在前端各自猜字串。
"""

import re

TRANSIENT_FAILURE_CODES = frozenset({"AI_QUOTA_EXCEEDED", "AI_SERVICE_BUSY", "AI_TIMEOUT"})
NON_HUMAN_FAILURE_CODES = TRANSIENT_FAILURE_CODES | frozenset({"AI_AUTH_FAILED"})

# (code, 判斷條件, 中文說明, English)
_RULES = (
    (
        "AI_QUOTA_EXCEEDED",
        re.compile(r"\b429\b|RESOURCE_EXHAUSTED|ResourceExhausted|quota|rate.?limit", re.I),
        "AI 服務額度不足（已超過使用上限或請求太頻繁），系統自動重試後仍失敗。請等額度恢復後（通常數分鐘，免費額度可能要到隔天）再按「重新處理」。",
        "AI quota exceeded (usage limit or too many requests). Retries failed; wait for the quota to reset, then use Retry.",
    ),
    (
        "AI_SERVICE_BUSY",
        re.compile(r"\b503\b|UNAVAILABLE|high demand|overloaded|ServiceUnavailable", re.I),
        "AI 模型目前使用量過高，暫時無法服務，系統自動重試後仍失敗。請稍後再按「重新處理」。",
        "The AI model is overloaded right now. Automatic retries failed; please retry later.",
    ),
    (
        "AI_TIMEOUT",
        re.compile(r"timeout|timed out|DEADLINE_EXCEEDED|\b504\b", re.I),
        "AI 服務回應逾時，請稍後再按「重新處理」。",
        "The AI service timed out. Please retry later.",
    ),
    (
        "AI_AUTH_FAILED",
        re.compile(r"API key|api_key|PERMISSION_DENIED|UNAUTHENTICATED|\b401\b|\b403\b", re.I),
        "AI 服務金鑰無效或未設定，請檢查後端的 GEMINI_API_KEY 設定。",
        "The AI API key is missing or invalid. Check GEMINI_API_KEY on the backend.",
    ),
    (
        "PII_MASKING_FAILED",
        re.compile(r"PII_MASKING_FAILED", re.I),
        "個資遮罩失敗，這段文字沒有送去分類（避免外洩個資）。",
        "PII masking failed, so the text was not sent for classification.",
    ),
    (
        "AI_RESPONSE_INVALID",
        re.compile(r"JSONDecodeError|Expecting value|KeyError|格式|parse", re.I),
        "AI 回傳的內容格式不正確，無法解析。可以再按「重新處理」試一次。",
        "The AI response could not be parsed. Retry may help.",
    ),
    (
        "SEGMENTATION_INVALID",
        re.compile(r"segment|片段|重疊|找不到", re.I),
        "AI 拆分出的片段跟原文對不上，驗證沒有通過。可以再按「重新處理」試一次。",
        "The AI's segmentation did not match the original text. Retry may help.",
    ),
)


def explain_failure(raw) -> dict | None:
    """Returns {"code", "message", "message_en", "raw"}；沒有錯誤文字時回傳 None。"""
    if not raw:
        return None
    from services.safe_error import safe_error_summary

    # raw 會回傳給前端：先去除可能夾帶的 API key / token（見 services/safe_error.py）
    text = safe_error_summary(raw, limit=2000)
    for code, pattern, zh, en in _RULES:
        if pattern.search(text):
            return {"code": code, "message": zh, "message_en": en, "raw": text[:500]}
    return {
        "code": "CLASSIFICATION_FAILED_UNKNOWN",
        "message": "分類處理失敗，原因不明（詳細錯誤見下方原始訊息）。可以再按「重新處理」試一次。",
        "message_en": "Classification failed for an unknown reason (see the raw message). Retry may help.",
        "raw": text[:500],
    }


def routing_failure(routing_status, routing_detail) -> dict | None:
    """Uploaded_Answer 的 routing 失敗說明（routing API 本身失敗時，原始例外
    沒有保存，只能給一般性說明）。"""
    if routing_status == "classification_failed":
        return explain_failure(routing_detail)
    if routing_status == "routing_failed":
        detail = routing_detail or ""
        kind = re.search(r"routing_error=(\w+)", detail)
        explained = explain_failure(detail) if (
            (kind and kind.group(1) != "unknown")
            or re.search(r"429|503|UNAVAILABLE|RESOURCE_EXHAUSTED", detail, re.I)
        ) else None
        return explained or {
            "code": "ROUTING_SERVICE_FAILED",
            "message": "判斷主題時 AI 服務呼叫失敗（常見原因是額度不足或模型忙碌）。可以按「重新判斷主題」或直接指派主題。",
            "message_en": "The AI call failed while determining the topic (often quota or overload). Re-route or assign a topic.",
            "raw": explain_failure(detail)["raw"] if detail else "",
        }
    return None
