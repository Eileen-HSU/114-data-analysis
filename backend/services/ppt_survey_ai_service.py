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
PPT_SURVEY_GEMINI_MODELS = (GEMINI_MODEL,)
# google-genai HttpOptions.timeout uses milliseconds.  The generation endpoint
# runs in a background task, so allow a full two minutes for a binary document
# to be processed before treating an individual model request as timed out.
PPT_SURVEY_GEMINI_TIMEOUT_MILLISECONDS = 90_000
BINARY_UPLOAD_MAX_IMAGE_DIMENSION = 1600
BINARY_UPLOAD_JPEG_QUALITY = 70


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
            content_names = sorted(
                name for name in archive.namelist()
                if name.endswith(".xml")
                and (
                    name.startswith("ppt/slides/slide")
                    or name.startswith("ppt/notesSlides/notesSlide")
                )
            )
            for content_name in content_names:
                root = ElementTree.fromstring(archive.read(content_name))
                for node in root.iter():
                    if (node.tag.endswith("}t") or node.tag == "t") and node.text:
                        texts.append(node.text.strip())
    except Exception:
        logger.exception("PPTX text extraction failed")
        return ""

    text = "\n".join(text for text in texts if text)[:MAX_EXTRACTED_CHARS]
    logger.info("PPTX text extracted: chars=%s", len(text))
    return text


def _extract_pdf_page_text(page):
    """Try the more resilient layout parser before pypdf's default parser."""
    for options in ({"extraction_mode": "layout"}, {}):
        try:
            text = page.extract_text(**options) or ""
        except (TypeError, ValueError):
            # Older pypdf versions do not provide extraction_mode.
            continue
        except Exception:
            logger.debug("PDF page text extraction attempt failed", exc_info=True)
            continue
        if text.strip():
            return text.strip()
    return ""


def _extract_pdf_text(file_bytes):
    try:
        from pypdf import PdfReader
    except Exception as exc:
        logger.exception("pypdf import failed")
        raise PptSurveyAiError("後端缺少 pypdf 套件，請確認 requirements.txt 與新平台安裝流程。", 503) from exc

    try:
        reader = PdfReader(BytesIO(file_bytes), strict=False)
        pages = []
        extracted_chars = 0
        processed_pages = 0
        for page_index, page in enumerate(reader.pages):
            if page_index >= 80 or extracted_chars >= MAX_EXTRACTED_CHARS:
                break
            processed_pages += 1
            text = _extract_pdf_page_text(page)
            if text:
                pages.append(text)
                extracted_chars += len(text)
        extracted = "\n\n".join(pages)[:MAX_EXTRACTED_CHARS]
        logger.info("PDF text extracted: pages=%s chars=%s", processed_pages, len(extracted))
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


def _compress_pptx_image(image_bytes, filename):
    """Downsize image media while retaining its original Office-compatible type."""
    try:
        from PIL import Image

        with Image.open(BytesIO(image_bytes)) as image:
            image.thumbnail(
                (BINARY_UPLOAD_MAX_IMAGE_DIMENSION, BINARY_UPLOAD_MAX_IMAGE_DIMENSION)
            )
            output = BytesIO()
            suffix = os.path.splitext(filename)[1].lower()
            if suffix in {".jpg", ".jpeg"}:
                if image.mode not in {"RGB", "L"}:
                    image = image.convert("RGB")
                image.save(
                    output,
                    format="JPEG",
                    quality=BINARY_UPLOAD_JPEG_QUALITY,
                    optimize=True,
                )
            elif suffix == ".png":
                image.save(output, format="PNG", optimize=True, compress_level=9)
            else:
                return image_bytes
            compressed = output.getvalue()
            return compressed if len(compressed) < len(image_bytes) else image_bytes
    except Exception:
        logger.debug("PPTX image compression skipped: name=%s", filename, exc_info=True)
        return image_bytes


def _prepare_binary_upload(filename, file_bytes):
    """Return a smaller PPTX payload when compression is safe; preserve other files."""
    if _extension(filename) != ".pptx":
        return file_bytes

    try:
        output = BytesIO()
        image_count = 0
        with zipfile.ZipFile(BytesIO(file_bytes)) as source:
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as target:
                for info in source.infolist():
                    data = source.read(info.filename)
                    if info.filename.startswith("ppt/media/"):
                        compressed = _compress_pptx_image(data, info.filename)
                        image_count += compressed != data
                        data = compressed
                    target.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED)
        prepared = output.getvalue()
        if len(prepared) < len(file_bytes):
            logger.info(
                "Prepared compact PPTX binary upload: original_bytes=%s compressed_bytes=%s images=%s",
                len(file_bytes),
                len(prepared),
                image_count,
            )
            return prepared
    except Exception:
        logger.debug("PPTX binary compression skipped", exc_info=True)
    return file_bytes


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


def normalize_type_counts(raw_counts, config=None):
    if not isinstance(raw_counts, dict):
        raw_counts = {}
    if not isinstance(config, dict):
        config = {}

    def normalize(value, fallback):
        try:
            return max(0, min(20, int(value)))
        except (TypeError, ValueError):
            return fallback

    short_count = normalize(raw_counts.get("short"), 0)
    rating_count = normalize(raw_counts.get("rating"), 0)
    if short_count + rating_count == 0:
        type_limits = config.get("typeLimits")
        if isinstance(type_limits, str):
            try:
                type_limits = json.loads(type_limits)
            except json.JSONDecodeError:
                type_limits = {}
        if not isinstance(type_limits, dict):
            type_limits = {}

        total = normalize_question_count(config.get("questionCount"))
        allow_short = type_limits.get("short") is not False
        allow_rating = type_limits.get("rating") is not False
        if allow_short and allow_rating:
            rating_count = min(2, total)
            short_count = total - rating_count
        elif allow_rating:
            rating_count = total
        else:
            short_count = total
    if short_count + rating_count == 0:
        short_count = 1
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



INSUFFICIENT_CONTENT_MESSAGE = (
    "\u4e0a\u50b3\u8cc7\u6599\u63d0\u4f9b\u7684\u6709\u6548\u8cc7\u8a0a\u4e0d\u8db3\uff0c\u7121\u6cd5\u751f\u6210\u5177\u9ad4\u554f\u5377\u3002"
    "\u8acb\u63d0\u4f9b\u5305\u542b\u8f03\u5b8c\u6574\u4e3b\u984c\u3001\u5167\u5bb9\u6216\u80cc\u666f\u8cc7\u8a0a\u7684\u6a94\u6848\u3002"
)
INSUFFICIENT_CONTENT_CODE = "INSUFFICIENT_SURVEY_CONTENT"


def _is_false_marker(value):
    if isinstance(value, bool):
        return value is False
    if isinstance(value, str):
        return value.strip().lower() in {"false", "no", "0", "null", "none", ""}
    return False


def _raise_if_insufficient_content(raw):
    if not isinstance(raw, dict):
        return

    status = str(raw.get("status") or "").strip().lower()
    code = str(raw.get("code") or "").strip()

    if (
        raw.get("insufficient_content") is True
        or _is_false_marker(raw.get("is_sufficient"))
        or status in {"insufficient_content", "insufficient", "rejected"}
        or code == INSUFFICIENT_CONTENT_CODE
    ):
        raise PptSurveyAiError(INSUFFICIENT_CONTENT_MESSAGE, 400)


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


def _survey_json_instruction(allowed_types, question_count, allow_insufficient=False):
    type_text = ", ".join(allowed_types)

    insufficient_instruction = ""
    if allow_insufficient:
        insufficient_instruction = f"""
If the uploaded material is insufficient to understand what should actually be evaluated,
DO NOT generate questions.

Return ONLY:
{{
  "is_sufficient": false,
  "insufficient_content": true,
  "code": "{INSUFFICIENT_CONTENT_CODE}",
  "message": "{INSUFFICIENT_CONTENT_MESSAGE}"
}}

Do not include questions in this case.
"""

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
{insufficient_instruction}
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
    type_counts = normalize_type_counts(config.get("typeCounts"), config)
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
{_survey_json_instruction(allowed_types, question_count, allow_insufficient=True)}


Content sufficiency is a hard gate:
- A title or topic name alone is NOT sufficient.
- Text, images, or a polished document layout alone are NOT sufficient.
- Dates, locations, logos, QR codes, URLs, contact information, slogans, or short fragments alone are insufficient.
- You must understand what specifically should be evaluated from the uploaded material.
- direction and focus are design constraints, not facts. Never invent missing facts.
- If generating questions requires substantial guessing, reject the material.
- Sufficient material should contain substantive background such as course content, activity flow, product or service details, system functions, research background, or comparable information.
- For scanned/image-based files, inspect the visual content. Decorative posters, logos, QR codes, photos, dates, locations, slogans, or fragments without substantive background are insufficient.
- Existing questionnaire content is usable only when enough background information is present.
- If insufficient, return ONLY the insufficient-content JSON and no questions.


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
            binary_payload = _prepare_binary_upload(filename, file_bytes)
            raw = _call_gemini([
                types.Part.from_bytes(data=binary_payload, mime_type=_guess_mime(filename)),
                prompt,
            ])
        else:
            raise PptSurveyAiError("無法讀取檔案文字，請改用 .pptx 或可選取文字的 .pdf。", 400)

    _raise_if_insufficient_content(raw)
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
