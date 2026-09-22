import json
import logging
import mimetypes
import os
import re
import time
import zipfile
from io import BytesIO
from xml.etree import ElementTree


logger = logging.getLogger(__name__)


class PptSurveyAiError(Exception):
    def __init__(self, message, status_code=502):
        super().__init__(message)
        self.status_code = status_code


ALLOWED_EXTENSIONS = {".ppt", ".pptx", ".pdf"}
ALLOWED_TYPES = {"short", "rating"}
GEMINI_MODEL = "gemini-3.5-flash"
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_EXTRACTED_CHARS = 18000
# One initial request plus at most one retry keeps failover responsive while
# retaining a small recovery window for brief Gemini overloads.
PPT_SURVEY_GEMINI_RETRY_ATTEMPTS = 2
PPT_SURVEY_GEMINI_RETRY_DELAYS_SECONDS = (1,)
PPT_SURVEY_GEMINI_MODELS = (GEMINI_MODEL, "gemini-2.5-flash")
# google-genai HttpOptions.timeout uses milliseconds.  The generation endpoint
# runs in a background task, so allow a full two minutes for a binary document
# to be processed before treating an individual model request as timed out.
PPT_SURVEY_GEMINI_TIMEOUT_MILLISECONDS = 120_000


def _get_api_key():
    api_key = _get_ppt_survey_api_keys()[0][1]
    if not api_key:
        logger.error("PPT_SURVEY_AI_API_KEY is missing")
        raise PptSurveyAiError("PPT/PDF 問卷 AI API key 尚未設定。", 503)
    return api_key


def _load_genai_client():
    try:
        from google import genai
        from google.genai import types
    except Exception as exc:
        logger.exception("google-genai import failed")
        raise PptSurveyAiError("後端缺少 google-genai 套件，請確認 requirements.txt。", 503) from exc

    return genai.Client(api_key=_get_api_key()), types


def _get_ppt_survey_api_keys():
    """Read the two keys dedicated exclusively to PPT survey generation."""
    primary_key = (
        os.getenv("PPT_SURVEY_AI_PRIMARY_API_KEY", "").strip()
        or os.getenv("PPT_SURVEY_AI_API_KEY", "").strip()
        or os.getenv("GEMINI_API_KEY", "").strip()
    )
    fallback_key = os.getenv("PPT_SURVEY_AI_FALLBACK_API_KEY", "").strip()
    if not primary_key or not fallback_key:
        logger.error(
            "PPT survey API key configuration is incomplete: primary=%s fallback=%s",
            bool(primary_key),
            bool(fallback_key),
        )
        raise PptSurveyAiError("PPT survey AI key configuration is incomplete.", 503)
    return (("primary", primary_key), ("fallback", fallback_key))


def _load_genai_types():
    try:
        from google import genai
        from google.genai import types
    except Exception as exc:
        logger.exception("google-genai import failed")
        raise PptSurveyAiError("google-genai is unavailable.", 503) from exc
    return genai, types


def _extension(filename):
    return os.path.splitext(filename or "")[1].lower()


def _guess_mime(filename):
    ext = _extension(filename)
    if ext == ".ppt":
        return "application/vnd.ms-powerpoint"
    if ext == ".pptx":
        return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    if ext == ".pdf":
        return "application/pdf"
    return mimetypes.guess_type(filename or "")[0] or "application/octet-stream"


def validate_upload(file_storage):
    if not file_storage or not file_storage.filename:
        raise PptSurveyAiError("請上傳 PPT 或 PDF 檔案。", 400)

    ext = _extension(file_storage.filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise PptSurveyAiError("檔案格式不支援，請上傳 .ppt、.pptx 或 .pdf。", 400)

    file_bytes = file_storage.read()
    if not file_bytes:
        raise PptSurveyAiError("檔案內容是空的，請重新上傳。", 400)
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise PptSurveyAiError("檔案太大，請上傳 25MB 以下的 PPT/PDF。", 413)

    logger.info(
        "PPT survey upload accepted: filename=%s ext=%s size=%s",
        file_storage.filename,
        ext,
        len(file_bytes),
    )
    return file_storage.filename, file_bytes


def _extract_pptx_text(file_bytes):
    texts = []
    try:
        with zipfile.ZipFile(BytesIO(file_bytes)) as archive:
            slide_names = sorted(
                name for name in archive.namelist()
                if name.startswith("ppt/slides/slide") and name.endswith(".xml")
            )
            for slide_name in slide_names:
                root = ElementTree.fromstring(archive.read(slide_name))
                for node in root.iter():
                    if node.tag.endswith("}t") and node.text:
                        texts.append(node.text.strip())
    except Exception:
        logger.exception("PPTX text extraction failed")
        return ""

    text = "\n".join(text for text in texts if text)[:MAX_EXTRACTED_CHARS]
    logger.info("PPTX text extracted: chars=%s", len(text))
    return text


def _extract_pdf_text(file_bytes):
    try:
        from pypdf import PdfReader
    except Exception as exc:
        logger.exception("pypdf import failed")
        raise PptSurveyAiError("後端缺少 pypdf 套件，請確認 requirements.txt 與新平台安裝流程。", 503) from exc

    try:
        reader = PdfReader(BytesIO(file_bytes))
        pages = []
        for page in reader.pages[:80]:
            text = page.extract_text() or ""
            if text.strip():
                pages.append(text.strip())
        extracted = "\n\n".join(pages)[:MAX_EXTRACTED_CHARS]
        logger.info("PDF text extracted: pages=%s chars=%s", len(reader.pages), len(extracted))
        return extracted
    except Exception:
        logger.exception("PDF text extraction failed")
        return ""


def extract_document_text(filename, file_bytes):
    ext = _extension(filename)
    if ext == ".pptx":
        return _extract_pptx_text(file_bytes)
    if ext == ".pdf":
        return _extract_pdf_text(file_bytes)
    logger.warning("Text extraction is not available for extension: %s", ext)
    return ""


def normalize_type_limits(raw_limits):
    if isinstance(raw_limits, str):
        try:
            raw_limits = json.loads(raw_limits)
        except json.JSONDecodeError:
            raw_limits = {}

    if not isinstance(raw_limits, dict):
        raw_limits = {}

    allowed = []
    if raw_limits.get("short") is not False:
        allowed.append("short")
    if raw_limits.get("rating") is not False:
        allowed.append("rating")
    return allowed or ["short", "rating"]


def normalize_question_count(value):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 5
    return max(1, min(20, parsed))


def normalize_type_counts(raw_counts):
    if not isinstance(raw_counts, dict):
        raw_counts = {}

    def normalize(value, fallback):
        try:
            return max(0, min(20, int(value)))
        except (TypeError, ValueError):
            return fallback

    short_count = normalize(raw_counts.get("short"), 0)
    rating_count = normalize(raw_counts.get("rating"), 0)
    return {"short": short_count, "rating": rating_count}


def _strip_code_fence(text):
    return re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.MULTILINE).strip()


def _parse_json_response(text):
    cleaned = _strip_code_fence(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            logger.error("AI response is not JSON: %s", cleaned[:1000])
            raise PptSurveyAiError("AI 回傳格式不是 JSON，請重新生成。", 502)
        return json.loads(match.group(0))


def normalize_survey_draft(raw, fallback_title="AI 生成問卷"):
    if not isinstance(raw, dict):
        raise PptSurveyAiError("AI 回傳格式不正確，無法建立問卷草稿。", 502)

    questions = raw.get("questions") or raw.get("items") or []
    normalized_questions = []
    for index, question in enumerate(questions):
        if not isinstance(question, dict):
            continue
        q_type = question.get("type") if question.get("type") in ALLOWED_TYPES else "short"
        title = str(question.get("title") or question.get("question") or "").strip()
        if not title:
            title = f"第 {index + 1} 題"
        normalized_questions.append({
            "id": str(question.get("id") or f"ai-q-{index + 1}"),
            "type": q_type,
            "title": title,
            "required": question.get("required") is not False,
            "options": [],
        })

    if not normalized_questions:
        raise PptSurveyAiError("AI 沒有產生有效題目，請調整生成重點後再試。", 502)

    return {
        "title": str(raw.get("title") or fallback_title).strip()[:100],
        "description": str(raw.get("description") or "").strip()[:500],
        "identity_mode": "identified" if raw.get("identity_mode") == "identified" else "anonymous",
        "deadline_at": raw.get("deadline_at") or "",
        "questions": normalized_questions[:20],
    }


def _survey_json_instruction(allowed_types, question_count):
    type_text = ", ".join(allowed_types)
    return f"""
請只回傳 JSON，不要加 Markdown 或說明文字。格式必須完全符合：
{{
  "title": "問卷標題",
  "description": "問卷說明",
  "identity_mode": "anonymous",
  "deadline_at": "",
  "questions": [
    {{
      "id": "q1",
      "type": "short 或 rating",
      "title": "題目文字",
      "required": true,
      "options": []
    }}
  ]
}}
請產生 {question_count} 題。題型只能使用：{type_text}。
short 代表問答題，rating 代表 0 到 5 評分題。
options 必須維持空陣列，才能相容系統原本問卷資料結構。
"""


def _handle_ai_exception(exc):
    message = str(exc)
    lower_message = message.lower()
    logger.exception("Gemini API call failed: %s", message)
    if "quota" in lower_message or "429" in message:
        raise PptSurveyAiError("AI API 額度或頻率限制已達上限，請稍後再試。", 429) from exc
    if "deadline" in lower_message or "timeout" in lower_message:
        raise PptSurveyAiError("AI 分析逾時，請稍後再試或改用較小的檔案。", 504) from exc
    if "unauthenticated" in lower_message or "api key" in lower_message or "401" in message:
        raise PptSurveyAiError("AI API key 驗證失敗，請確認 PPT_SURVEY_AI_API_KEY。", 401) from exc
    raise PptSurveyAiError("AI 服務暫時無法完成分析，請稍後再試。", 502) from exc


def _call_gemini_legacy_unused(contents):
    client, types = _load_genai_client()
    model = GEMINI_MODEL
    logger.info("Calling Gemini model=%s", model)
    try:
        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(
                temperature=0.25,
                response_mime_type="application/json",
            ),
        )
    except Exception as exc:
        _handle_ai_exception(exc)

    text = getattr(response, "text", "") or ""
    logger.info("Gemini response received: chars=%s", len(text))
    if not text.strip():
        raise PptSurveyAiError("AI 沒有回傳內容，請稍後再試。", 502)
    return _parse_json_response(text)


def _gemini_error_status_code(exc):
    """Best-effort extraction across google-genai exception versions."""
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if callable(code):
        try:
            code = code()
        except Exception:
            code = None
    if hasattr(code, "value"):
        code = code.value
    try:
        return int(code)
    except (TypeError, ValueError):
        match = re.search(r"\\b([1-5]\\d{2})\\b", str(exc))
        return int(match.group(1)) if match else None


def _is_gemini_unavailable_error(exc):
    message = str(exc)
    lower_message = message.lower()
    code = _gemini_error_status_code(exc)
    status = str(getattr(exc, "status", "") or getattr(exc, "reason", "")).lower()
    return (
        code == 503
        or "503" in message
        or "unavailable" in lower_message
        or "service unavailable" in lower_message
        or status == "unavailable"
    )


def _is_transient_gemini_error(exc):
    """Return whether an error is worth retrying with the same PPT API key."""
    status_code = _gemini_error_status_code(exc)
    if _is_gemini_unavailable_error(exc) or status_code in {500, 502, 503, 504}:
        return True

    message = str(exc).lower()
    error_type = type(exc).__name__.lower()
    return (
        isinstance(exc, (TimeoutError, ConnectionError))
        or "servererror" in error_type
        or "server error" in message
        or "overload" in message
        or "timeout" in message
        or "timed out" in message
        or "connection" in message
        or "network" in message
    )


def _ppt_survey_retry_delay_seconds(attempt_number):
    """Delay before the next attempt; attempts are one-indexed."""
    return PPT_SURVEY_GEMINI_RETRY_DELAYS_SECONDS[min(
        attempt_number - 1,
        len(PPT_SURVEY_GEMINI_RETRY_DELAYS_SECONDS) - 1,
    )]


def _is_model_not_found_error(exc):
    message = str(exc)
    lower_message = message.lower()
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    return (
        code == 404
        or "404" in message
        or "not_found" in lower_message
        or "not found" in lower_message
    ) and "model" in lower_message


def _retry_delay_seconds(attempt_number):
    return min(
        GEMINI_RETRY_MAX_DELAY_SECONDS,
        GEMINI_RETRY_INITIAL_DELAY_SECONDS * (2 ** max(0, attempt_number - 1)),
    )


def _normalize_gemini_model_name(model):
    normalized = (model or "").strip()
    if normalized.startswith("models/"):
        normalized = normalized.removeprefix("models/")
    return normalized


def _normalize_fallback_model_name(model):
    normalized = _normalize_gemini_model_name(model)
    replacement = RETIRED_FALLBACK_MODEL_REPLACEMENTS.get(normalized)
    if replacement:
        replacement = _normalize_gemini_model_name(replacement)
        logger.warning(
            "Replacing retired Gemini fallback model: old=%s new=%s",
            normalized,
            replacement,
        )
        return replacement
    return normalized


def _model_sequence(primary_model):
    primary_model = _normalize_gemini_model_name(primary_model)
    raw_fallbacks = os.getenv("PPT_SURVEY_AI_FALLBACK_MODELS", "").strip()
    fallback_models = [
        _normalize_fallback_model_name(model)
        for model in (raw_fallbacks.split(",") if raw_fallbacks else DEFAULT_FALLBACK_MODELS)
        if _normalize_gemini_model_name(model)
    ]
    models = []
    for model in [primary_model, *fallback_models]:
        if model and model not in models:
            models.append(model)
    return models


def _call_gemini_model(client, types, model, contents):
    try:
        return client.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(
                temperature=0.25,
                response_mime_type="application/json",
            ),
        )
    except Exception as exc:
        logger.exception(
            "Gemini generate_content failed: model=%s error_type=%s error=%r",
            model,
            type(exc).__name__,
            exc,
        )
        traceback.print_exc()
        if _is_gemini_unavailable_error(exc) or _is_model_not_found_error(exc):
            raise
        _handle_ai_exception(exc)


def _call_gemini_with_model_fallback_legacy_unused(contents):
    client, types = _load_genai_client()
    primary_model = GEMINI_MODEL
    models = _model_sequence(primary_model)
    last_unavailable_error = None

    for model in models:
        logger.info("Calling Gemini model=%s", model)
        skip_model = False
        for attempt in range(1, GEMINI_RETRY_ATTEMPTS + 1):
            try:
                response = _call_gemini_model(client, types, model, contents)
                logger.info("Gemini model succeeded: model=%s attempt=%s", model, attempt)
                break
            except Exception as exc:
                if _is_model_not_found_error(exc):
                    last_unavailable_error = exc
                    skip_model = True
                    logger.warning(
                        "Gemini model not found, skipping to next model: model=%s error=%s",
                        model,
                        str(exc),
                        exc_info=True,
                    )
                    break

                if not _is_gemini_unavailable_error(exc):
                    _handle_ai_exception(exc)

                last_unavailable_error = exc
                logger.warning(
                    "Gemini model unavailable: model=%s attempt=%s/%s error=%s",
                    model,
                    attempt,
                    GEMINI_RETRY_ATTEMPTS,
                    str(exc),
                    exc_info=True,
                )

                if attempt < GEMINI_RETRY_ATTEMPTS:
                    delay_seconds = _retry_delay_seconds(attempt)
                    logger.info(
                        "Retrying Gemini model after backoff: model=%s delay_seconds=%s",
                        model,
                        delay_seconds,
                    )
                    time.sleep(delay_seconds)
                else:
                    logger.warning(
                        "Gemini model exhausted after retries, trying fallback if available: model=%s",
                        model,
                    )
        else:
            continue

        if skip_model:
            continue

        text = getattr(response, "text", "") or ""
        logger.info("Gemini response received: model=%s chars=%s", model, len(text))
        if not text.strip():
            raise PptSurveyAiError("AI 沒有回傳內容，請稍後再試。", 502)
        return _parse_json_response(text)

    logger.error(
        "All Gemini models unavailable after retries: models=%s last_error=%s",
        models,
        str(last_unavailable_error) if last_unavailable_error else "",
    )
    raise PptSurveyAiError(
        "Gemini 服務目前忙碌或暫時不可用，已自動重試並切換備援模型但仍失敗，請稍後再試。",
        503,
    ) from last_unavailable_error


def _call_gemini(contents):
    """Call PPT Gemini with transient-error retry, key, and model failover.

    A key is never passed to shared Gemini helpers, so this failover cannot
    affect any other AI feature.
    """
    genai, types = _load_genai_types()
    last_error = None

    for model in PPT_SURVEY_GEMINI_MODELS:
        for key_role, api_key in _get_ppt_survey_api_keys():
            client = genai.Client(
                api_key=api_key,
                http_options={"timeout": PPT_SURVEY_GEMINI_TIMEOUT_MILLISECONDS},
            )
            response = None
            transient_failure = False
            for attempt in range(1, PPT_SURVEY_GEMINI_RETRY_ATTEMPTS + 1):
                logger.info(
                    "Calling PPT survey Gemini: model=%s key_role=%s attempt=%s/%s",
                    model,
                    key_role,
                    attempt,
                    PPT_SURVEY_GEMINI_RETRY_ATTEMPTS,
                )
                try:
                    response = client.models.generate_content(
                        model=model,
                        contents=contents,
                        config=types.GenerateContentConfig(
                            temperature=0.25,
                            response_mime_type="application/json",
                        ),
                    )
                    break
                except Exception as exc:
                    last_error = exc
                    transient_failure = _is_transient_gemini_error(exc)
                    if not transient_failure:
                        logger.warning(
                            "PPT survey Gemini non-transient failure: model=%s key_role=%s "
                            "error_type=%s error=%s",
                            model,
                            key_role,
                            type(exc).__name__,
                            str(exc),
                            exc_info=True,
                        )
                        break

                    if attempt < PPT_SURVEY_GEMINI_RETRY_ATTEMPTS:
                        delay_seconds = _ppt_survey_retry_delay_seconds(attempt)
                        logger.warning(
                            "PPT survey Gemini transient failure; retrying same key: "
                            "model=%s key_role=%s attempt=%s/%s delay_seconds=%s "
                            "error_type=%s error=%s",
                            model,
                            key_role,
                            attempt,
                            PPT_SURVEY_GEMINI_RETRY_ATTEMPTS,
                            delay_seconds,
                            type(exc).__name__,
                            str(exc),
                            exc_info=True,
                        )
                        time.sleep(delay_seconds)
                        continue

                    logger.warning(
                        "PPT survey Gemini retries exhausted; switching key or model: "
                        "model=%s key_role=%s attempts=%s error_type=%s error=%s",
                        model,
                        key_role,
                        PPT_SURVEY_GEMINI_RETRY_ATTEMPTS,
                        type(exc).__name__,
                        str(exc),
                        exc_info=True,
                    )
                    break

            if response is not None:
                text = getattr(response, "text", "") or ""
                logger.info(
                    "PPT survey Gemini response received: model=%s key_role=%s chars=%s",
                    model,
                    key_role,
                    len(text),
                )
                if not text.strip():
                    raise PptSurveyAiError("PPT survey AI returned an empty response.", 502)
                return _parse_json_response(text)

            if not transient_failure:
                # A different key can recover from authentication or quota errors,
                # but a model downgrade is only useful for temporary model overload.
                if key_role == "primary":
                    continue
                _handle_ai_exception(last_error or RuntimeError("PPT survey Gemini call failed"))

        logger.warning(
            "PPT survey Gemini model unavailable after both keys; trying next model: model=%s",
            model,
        )

    raise PptSurveyAiError(
        "PPT survey Gemini is temporarily overloaded after retrying all models and keys.",
        503,
    ) from last_error


def generate_survey_from_material(filename, file_bytes, config):
    type_counts = normalize_type_counts(config.get("typeCounts"))
    question_count = type_counts["short"] + type_counts["rating"]
    allowed_types = [name for name, count in type_counts.items() if count > 0]
    direction = str(config.get("direction") or "").strip()
    focus = str(config.get("focus") or "").strip()
    extracted_text = extract_document_text(filename, file_bytes)

    logger.info(
        "Generating PPT survey: filename=%s question_count=%s allowed_types=%s direction=%s focus=%s extracted_chars=%s",
        filename,
        question_count,
        allowed_types,
        direction,
        focus,
        len(extracted_text),
    )

    prompt = f"""
你是教學問卷設計助理。請根據上傳的 PPT/PDF 內容產生一份可直接儲存的問卷草稿。
檔名：{filename}
題目方向：{direction or "學習成效"}
生成重點：{focus or "課程內容"}
{_survey_json_instruction(allowed_types, question_count)}
Return exactly {type_counts['short']} questions with type "short" and exactly {type_counts['rating']} questions with type "rating".
"""

    if extracted_text:
        prompt += f"\n以下是從檔案擷取出的文字內容：\n{extracted_text}"
        raw = _call_gemini([prompt])
    else:
        ext = _extension(filename)
        if ext in {".ppt", ".pptx", ".pdf"}:
            logger.warning("No text extracted; falling back to binary upload for filename=%s", filename)
            _, types = _load_genai_client()
            raw = _call_gemini([
                types.Part.from_bytes(data=file_bytes, mime_type=_guess_mime(filename)),
                prompt,
            ])
        else:
            raise PptSurveyAiError("無法讀取檔案文字，請改用 .pptx 或可選取文字的 .pdf。", 400)

    fallback_title = f"{os.path.splitext(filename)[0]} 問卷"
    return normalize_survey_draft(raw, fallback_title=fallback_title)


def revise_survey_with_ai(draft, message):
    if not isinstance(draft, dict):
        raise PptSurveyAiError("缺少目前問卷草稿，無法修改。", 400)
    if not str(message or "").strip():
        raise PptSurveyAiError("請輸入修改指令。", 400)

    current_draft = normalize_survey_draft(draft)
    question_count = len(current_draft["questions"])
    allowed_types = sorted({q["type"] for q in current_draft["questions"]} | {"short", "rating"})
    prompt = f"""
你是問卷編修助理。請依照講師指令修改問卷，並保持系統相容的 JSON 格式。
講師指令：{message}
目前問卷 JSON：{json.dumps(current_draft, ensure_ascii=False)}
{_survey_json_instruction(allowed_types, question_count)}
請盡量保留原本題數、題型與問卷結構，只修改講師要求的部分。
"""
    raw = _call_gemini([prompt])
    return normalize_survey_draft(raw, fallback_title=current_draft["title"])
