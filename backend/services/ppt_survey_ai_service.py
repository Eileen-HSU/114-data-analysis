import json
import logging
import mimetypes
import os
import re
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
DEFAULT_MODEL = "gemini-2.5-flash"
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_EXTRACTED_CHARS = 18000


def _get_api_key():
    api_key = os.getenv("PPT_SURVEY_AI_API_KEY", "").strip()
    if not api_key:
        logger.error("PPT_SURVEY_AI_API_KEY is missing")
        raise PptSurveyAiError("The AI survey API key is not configured.", 503)
    return api_key


def _load_genai_client():
    try:
        from google import genai
        from google.genai import types
    except Exception as exc:
        logger.exception("google-genai import failed")
        raise PptSurveyAiError("The AI service is unavailable. Please contact the administrator.", 503) from exc

    return genai.Client(api_key=_get_api_key()), types


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
        raise PptSurveyAiError("Please upload a PPT or PDF file.", 400)

    ext = _extension(file_storage.filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise PptSurveyAiError("Unsupported file format. Upload a .ppt, .pptx, or .pdf file.", 400)

    file_bytes = file_storage.read()
    if not file_bytes:
        raise PptSurveyAiError("The file is empty. Please upload another file.", 400)
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise PptSurveyAiError("The file is too large. Upload a PPT or PDF no larger than 25 MB.", 413)

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
    except Exception:
        logger.exception("pypdf import failed")
        return ""

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
            raise PptSurveyAiError("The AI response was not valid JSON. Please generate again.", 502)
        return json.loads(match.group(0))


def normalize_survey_draft(raw, fallback_title="AI-generated survey"):
    if not isinstance(raw, dict):
        raise PptSurveyAiError("The AI response format was invalid. Unable to create a survey draft.", 502)

    questions = raw.get("questions") or raw.get("items") or []
    normalized_questions = []
    for index, question in enumerate(questions):
        if not isinstance(question, dict):
            continue
        q_type = question.get("type") if question.get("type") in ALLOWED_TYPES else "short"
        title = str(question.get("title") or question.get("question") or "").strip()
        if not title:
            title = f"Question {index + 1}"
        normalized_questions.append({
            "id": str(question.get("id") or f"ai-q-{index + 1}"),
            "type": q_type,
            "title": title,
            "required": question.get("required") is not False,
            "options": [],
        })

    if not normalized_questions:
        raise PptSurveyAiError("No valid questions were generated. Adjust your priorities and try again.", 502)

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
Return only JSON, without Markdown or explanation. Write the survey title, description, and all questions in English. Use this exact structure:
{{
  "title": "Survey title",
  "description": "Survey description",
  "identity_mode": "anonymous",
  "deadline_at": "",
  "questions": [
    {{
      "id": "q1",
      "type": "short or rating",
      "title": "Question text",
      "required": true,
      "options": []
    }}
  ]
}}
Generate {question_count} questions. Allowed types: {type_text}.
short means an open-ended question; rating means a rating from 0 to 5.
Keep options as an empty array for compatibility with the survey schema.
"""


def _handle_ai_exception(exc):
    message = str(exc)
    lower_message = message.lower()
    logger.exception("Gemini API call failed: %s", message)
    if "quota" in lower_message or "429" in message:
        raise PptSurveyAiError("The AI usage or rate limit has been reached. Please try again later.", 429) from exc
    if "deadline" in lower_message or "timeout" in lower_message:
        raise PptSurveyAiError("AI analysis timed out. Try again later or use a smaller file.", 504) from exc
    if "unauthenticated" in lower_message or "api key" in lower_message or "401" in message:
        raise PptSurveyAiError("AI authentication failed. Please contact the administrator.", 401) from exc
    raise PptSurveyAiError("The AI service cannot complete the analysis right now. Please try again later.", 502) from exc


def _call_gemini(contents):
    client, types = _load_genai_client()
    model = os.getenv("PPT_SURVEY_AI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
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
        raise PptSurveyAiError("The AI returned no content. Please try again later.", 502)
    return _parse_json_response(text)


def generate_survey_from_material(filename, file_bytes, config):
    question_count = normalize_question_count(config.get("questionCount"))
    allowed_types = normalize_type_limits(config.get("typeLimits"))
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
            raise PptSurveyAiError("Unable to read the file text. Use a .pptx or a PDF with selectable text.", 400)

    fallback_title = f"{os.path.splitext(filename)[0]} survey"
    return normalize_survey_draft(raw, fallback_title=fallback_title)


def revise_survey_with_ai(draft, message):
    if not isinstance(draft, dict):
        raise PptSurveyAiError("No survey draft is available to edit.", 400)
    if not str(message or "").strip():
        raise PptSurveyAiError("Please enter editing instructions.", 400)

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
