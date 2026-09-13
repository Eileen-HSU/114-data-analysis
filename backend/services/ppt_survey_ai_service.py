import json
import mimetypes
import os
import re
import zipfile
from io import BytesIO
from xml.etree import ElementTree


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
        raise PptSurveyAiError("PPT/PDF 問卷 AI API key 尚未設定。", 503)
    return api_key


def _load_genai_client():
    try:
        from google import genai
        from google.genai import types
    except Exception as exc:
        raise PptSurveyAiError("後端缺少 google-genai 套件，請先安裝 requirements。", 503) from exc

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
        raise PptSurveyAiError("請上傳 PPT 或 PDF 檔案。", 400)

    ext = _extension(file_storage.filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise PptSurveyAiError("檔案格式不支援，請上傳 .ppt、.pptx 或 .pdf。", 400)

    file_bytes = file_storage.read()
    if not file_bytes:
        raise PptSurveyAiError("檔案內容是空的。", 400)
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise PptSurveyAiError("檔案過大，請上傳 25MB 以下的教材檔案。", 413)

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
        return ""
    return "\n".join(text for text in texts if text)[:MAX_EXTRACTED_CHARS]


def _extract_pdf_text(file_bytes):
    try:
        from pypdf import PdfReader
    except Exception:
        return ""

    try:
        reader = PdfReader(BytesIO(file_bytes))
        pages = []
        for page in reader.pages[:80]:
            text = page.extract_text() or ""
            if text.strip():
                pages.append(text.strip())
        return "\n\n".join(pages)[:MAX_EXTRACTED_CHARS]
    except Exception:
        return ""


def extract_document_text(filename, file_bytes):
    ext = _extension(filename)
    if ext == ".pptx":
        return _extract_pptx_text(file_bytes)
    if ext == ".pdf":
        return _extract_pdf_text(file_bytes)
    return ""


def normalize_type_limits(raw_limits):
    if isinstance(raw_limits, str):
        try:
            raw_limits = json.loads(raw_limits)
        except json.JSONDecodeError:
            raw_limits = {}

    allowed = []
    if not isinstance(raw_limits, dict):
        raw_limits = {}
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
            raise
        return json.loads(match.group(0))


def normalize_survey_draft(raw, fallback_title="AI 生成問卷"):
    if not isinstance(raw, dict):
        raise PptSurveyAiError("AI 回傳格式錯誤，請重新生成。", 502)

    questions = raw.get("questions") or raw.get("items") or []
    normalized_questions = []
    for index, question in enumerate(questions):
        if not isinstance(question, dict):
            continue
        q_type = question.get("type") if question.get("type") in ALLOWED_TYPES else "short"
        title = str(question.get("title") or question.get("question") or "").strip()
        if not title:
            title = f"請分享第 {index + 1} 題的回饋"
        normalized_questions.append({
            "id": str(question.get("id") or f"ai-q-{index + 1}"),
            "type": q_type,
            "title": title,
            "required": question.get("required") is not False,
            "options": [],
        })

    if not normalized_questions:
        raise PptSurveyAiError("AI 未產生任何題目，請調整參數後再試。", 502)

    return {
        "title": str(raw.get("title") or fallback_title).strip()[:100],
        "description": str(raw.get("description") or "").strip()[:500],
        "identity_mode": "identified" if raw.get("identity_mode") == "identified" else "anonymous",
        "deadline_at": raw.get("deadline_at") or "",
        "questions": normalized_questions[:20],
    }


def _survey_json_instruction(allowed_types, question_count):
    return f"""
請只輸出 JSON，不要加 Markdown。
JSON 必須符合：
{{
  "title": "100 字以內的問卷標題",
  "description": "500 字以內的問卷說明",
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
題目數量必須是 {question_count} 題。
題型只能使用：{", ".join(allowed_types)}。
short 代表問答題，rating 代表 0 到 5 分評分題。
所有 options 請固定輸出空陣列，避免破壞既有問卷格式。
"""


def _call_gemini(contents):
    client, types = _load_genai_client()
    model = os.getenv("PPT_SURVEY_AI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
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
        message = str(exc)
        if "quota" in message.lower() or "429" in message:
            raise PptSurveyAiError("AI 額度或速率限制不足，請稍後再試。", 429) from exc
        if "deadline" in message.lower() or "timeout" in message.lower():
            raise PptSurveyAiError("AI 連線逾時，請稍後再試。", 504) from exc
        if "unauthenticated" in message.lower() or "api key" in message.lower() or "401" in message:
            raise PptSurveyAiError("AI API key 驗證失敗，請確認 PPT_SURVEY_AI_API_KEY。", 401) from exc
        raise PptSurveyAiError("AI 生成服務暫時無法使用。", 502) from exc

    text = getattr(response, "text", "") or ""
    if not text.strip():
        raise PptSurveyAiError("AI 沒有回傳內容，請重新生成。", 502)
    return _parse_json_response(text)


def generate_survey_from_material(filename, file_bytes, config):
    question_count = normalize_question_count(config.get("questionCount"))
    allowed_types = normalize_type_limits(config.get("typeLimits"))
    direction = str(config.get("direction") or "").strip()
    focus = str(config.get("focus") or "").strip()
    extracted_text = extract_document_text(filename, file_bytes)
    mime_type = _guess_mime(filename)
    client, types = _load_genai_client()
    model = os.getenv("PPT_SURVEY_AI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL

    prompt = f"""
你是企業培訓課後問卷設計助理。請根據使用者上傳的 PPT/PDF 教材建立問卷草稿。
檔名：{filename}
題目方向：{direction or "課後回饋與學習成效"}
生成重點：{focus or "課程內容理解、講師表達、實務應用與改善建議"}
{_survey_json_instruction(allowed_types, question_count)}
"""
    if extracted_text:
        prompt += f"\n以下是從檔案擷取的文字內容：\n{extracted_text}"

    contents = [
        types.Part.from_bytes(data=file_bytes, mime_type=mime_type),
        prompt,
    ]

    try:
        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(
                temperature=0.25,
                response_mime_type="application/json",
            ),
        )
        raw = _parse_json_response(getattr(response, "text", "") or "")
    except PptSurveyAiError:
        raise
    except Exception as exc:
        # Some providers reject PPT binary input. Retry with extracted text when possible.
        if extracted_text:
            raw = _call_gemini([prompt])
        else:
            message = str(exc)
            if "quota" in message.lower() or "429" in message:
                raise PptSurveyAiError("AI 額度或速率限制不足，請稍後再試。", 429) from exc
            if "unauthenticated" in message.lower() or "401" in message:
                raise PptSurveyAiError("AI API key 驗證失敗，請確認 PPT_SURVEY_AI_API_KEY。", 401) from exc
            raise PptSurveyAiError("AI 無法讀取此檔案，請改用 .pptx 或 .pdf 後再試。", 502) from exc

    return normalize_survey_draft(raw, fallback_title=f"{os.path.splitext(filename)[0]} 課後回饋問卷")


def revise_survey_with_ai(draft, message):
    if not isinstance(draft, dict):
        raise PptSurveyAiError("缺少可修改的問卷草稿。", 400)
    if not str(message or "").strip():
        raise PptSurveyAiError("請輸入修改指令。", 400)

    current_draft = normalize_survey_draft(draft)
    question_count = len(current_draft["questions"])
    allowed_types = sorted({q["type"] for q in current_draft["questions"]} | {"short", "rating"})
    prompt = f"""
你是企業培訓問卷編修助理。請依講師指令修改既有問卷草稿。
講師指令：{message}
目前問卷 JSON：
{json.dumps(current_draft, ensure_ascii=False)}
{_survey_json_instruction(allowed_types, question_count)}
可以依指令調整題目文字、題型、必填與題數；但輸出仍必須符合既有問卷資料結構。
"""
    raw = _call_gemini([prompt])
    return normalize_survey_draft(raw, fallback_title=current_draft["title"])
