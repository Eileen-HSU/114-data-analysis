"""

分析追問（Chat Ask）服務：workspace 聊天室裡「一般文字追問」的後端實作。

對應 routes/chats/chat.py 的 POST /api/chat/<project_id>/ask。

【設計原則】
    - 後端自己依 project_id 從 DB 撈目前的分類結果組 context，不相信前端
      傳來的任何分類內容（前端這次只送 message，沒有、也不需要送分類
      資料本身）。
    - 每次呼叫最多打 1 次 Gemini：不重新跑 segmentation / classification /
      routing，也不呼叫 aggregated_summary_service（那個服務本身就會為了
      彙整摘要而呼叫 Gemini，這裡刻意不用，避免一次追問變成好幾次
      Gemini 呼叫）。彙整用的統計、分組全部在這個檔案裡用純 Python
      字串/字典處理，不呼叫任何會打 Gemini 的其他 service。
    - 送給 Gemini 的所有原始文字（受訪者原文片段、AI 判斷原因、建議摘要）
      一律先用 services/privacy_service.mask_pii() 遮罩過，遮罩失敗的
      項目直接整筆捨棄，不送出原始未遮罩內容，比照
      services/question_routing_service.py 對 routing 樣本的處理方式。

【project_id 與「chat」的對應關係】
    這個專案裡 Chat_History.chat_id 其實是「一則訊息」的 PK，不是一個
    對話/session 的 ID；真正代表「使用者這個 workspace 裡目前這個
    對話」的是 project_id（前端 UI 上的「session」也是用 project_id
    當 id）。這裡的 project_id 就是使用者在聊天室裡看到的「這個對話」。

【怎麼從 project_id 找到目前的分類結果，且不用改資料庫 schema】
    這個專案目前沒有任何一張表把 project_id 直接關聯到
    upload_batch_id（Excel 上傳）；survey 來源則是靠
    Chat_History.template_id（送出分析當下就已經存在這個欄位上）。
    這裡選擇「不新增欄位」的做法，改成從這個 project 底下的
    Chat_History 訊息本身回推：
        - 有任何一則訊息的 template_id 不是 None -> survey 來源，
          直接用那個 template_id。
        - 否則找「內容是分類結果表格」的訊息（用跟前端
          buildClassificationMessageContent() 完全相同的 marker 字串
          判斷），從裡面存的 meta.upload_batch_id 拿到 Excel 上傳來源。
    依訊息時間新到舊掃過去，第一個掃到的當作「目前」的分析上下文，
    這樣同一個對話裡先後分析過多份資料時，永遠對應到最新一次。
"""

import json
import os
import re

from models import Chat_History, Response_Classification, Survey_Response, Uploaded_Answer
from response_classification import (
    SOURCE_TYPE_SURVEY,
    SOURCE_TYPE_USER_UPLOAD,
    REVIEW_STATUS_EXCLUDED,
    REVIEW_STATUS_MODIFIED,
)
from services.source_lookup_service import fetch_classifications_in_scope
from services.effective_classification_service import get_effective_classification
from services.privacy_service import mask_pii, PiiMaskingError

# 跟 frontend/src/pages/workspace/page.jsx 的 CLASSIFICATION_TABLE_MARKER
# 必須逐字一致——這是判斷「這則訊息是不是分類結果表格」唯一的依據。
# 前端如果之後改了這個字串，這裡也要跟著改，兩邊目前沒有共用設定檔
# 可以避免這種重複定義。
CLASSIFICATION_TABLE_MARKER = "[[CLASSIFICATION_TABLE]]"

# 一次最多送幾筆「受試者片段」進 Gemini prompt，避免使用者的分析資料
# 量很大時，單次追問的 prompt 大到不合理（拖慢速度、浪費 token）。
_MAX_CONTEXT_ITEMS = 60
_MAX_EXCERPT_CHARS = 300

_ASK_MODEL = os.getenv("CHAT_ASK_AI_MODEL", "gemini-3.1-flash-lite")

_CODE_PATTERN = re.compile(r"\b([A-Za-z]{1,3}\d{1,2})\b")
_RESPONDENT_PATTERN = re.compile(r"受試者\s*0*([0-9]+)")


class ChatAskError(Exception):
    """呼叫端（routes/chats/chat.py）直接用 e.status_code 當 HTTP status
    回給前端，訊息（str(e)）直接當 error 欄位回傳，不需要再轉譯一次。"""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


SYSTEM_PROMPT = """你是「深度資料分析」平台裡，針對「已經產生的分類結果」提供解釋與問答的助手。

你收到的內容分兩段：
1.【目前這個 chat 已出現過的所有子類別】：這是目前唯一合法的分類清單。
2.【符合使用者問題的詳細分類與原始回答片段】：跟使用者這次問題最相關的
   實際分類結果，包含受試者編號、大類別、子類別、原始回答片段、分類
   原因、建議摘要。

嚴格規則，務必遵守：
1. 只能根據上面兩段內容回答，不可以捏造清單裡沒有出現過的大類別、
   子類別，也不可以杜撰不存在的原始回答內容或受試者編號。
2. 如果使用者問到的代碼（例如 A9、B2）不在清單裡，要明確告訴使用者
   「目前這個對話裡沒有這個子類別」，不要硬掰一個聽起來合理的答案。
3. 如果使用者問「為什麼這樣分類」，請優先解釋：
   (a) 這個子類別屬於哪個大類別、大致代表什麼意涵；
   (b) 有哪些原始回答片段被歸進這一類（用受試者編號指出來）；
   (c) 分類原因欄位實際寫的內容是什麼。
   不要重新對這些回答重新跑一次分類判斷，你只是在解釋既有結果。
4. 如果某個片段標註「此片段分類狀態不是 completed」，要明確說明這一段
   目前沒有完整的分類原因、原因可能是什麼，不要假裝有完整原因。
5. 這是既有分類結果的解釋與問答，不是人工複核（Human Review）流程。
   你的回答不會、也不能修改資料庫裡任何分類結果，不要用「我幫你改成
   ...」這種語氣，也不要建議使用者「已經幫你調整」。
6. 找不到使用者問題提到的受試者編號或子類別代碼時，明確說「目前資料
   裡找不到你提到的內容」，不要用猜測的內容硬回答。
7. 一律使用繁體中文回答。
8. 直接輸出自然語言說明文字即可，不要輸出 JSON、不要用程式碼區塊，也
   不需要用 Markdown 表格。"""


def _extract_mentioned_codes(message: str) -> set:
    return {m.group(1).upper() for m in _CODE_PATTERN.finditer(message)}


def _extract_mentioned_respondents(message: str) -> set:
    return {int(m.group(1)) for m in _RESPONDENT_PATTERN.finditer(message)}


def _parse_classification_message(content: str):
    try:
        return json.loads(content[len(CLASSIFICATION_TABLE_MARKER):])
    except (ValueError, TypeError):
        return None


def _resolve_chat_analysis_source(project_id: int):
    """依 project_id 找目前這個對話最新一次分析對應的來源。
    回傳 {"source_type": ..., "template_id": ...} 或
    {"source_type": ..., "upload_batch_id": ...}；找不到回傳 None。"""
    history_rows = (
        Chat_History.query
        .filter_by(project_id=project_id)
        .order_by(Chat_History.created_at.desc(), Chat_History.chat_id.desc())
        .all()
    )

    for h in history_rows:
        if h.template_id:
            return {"source_type": SOURCE_TYPE_SURVEY, "template_id": h.template_id}

        content = h.message_content or ""
        if content.startswith(CLASSIFICATION_TABLE_MARKER):
            parsed = _parse_classification_message(content)
            upload_batch_id = ((parsed or {}).get("meta") or {}).get("upload_batch_id")
            if upload_batch_id:
                return {"source_type": SOURCE_TYPE_USER_UPLOAD, "upload_batch_id": upload_batch_id}

    return None


def _row_effective_view(row):
    """回傳這筆 classification 目前該用的 main_category / sub_category /
    reasoning（尊重 Human Review 的結果，比照
    effective_classification_service.get_effective_classification() 的
    判斷規則）。review_status = excluded 代表人工決定不採用這筆，回傳
    None，呼叫端要整筆跳過，不納入追問的上下文；pending_review 目前
    還沒有人工複核過，跟 confirmed 一樣直接用 AI original 結果——
    「還沒有人確認」不代表這個分類結果不存在，使用者當然可以針對它
    追問。secondary_* 這裡不需要，追問不需要用到次要分類。"""
    if row.review_status == REVIEW_STATUS_EXCLUDED:
        return None

    if row.review_status == REVIEW_STATUS_MODIFIED:
        effective = get_effective_classification(row)
        return {
            "main_category": effective["main_category"],
            "sub_category": effective["sub_category"],
            "reasoning": effective["reasoning"],
        }

    # pending_review / confirmed 都还没有被 Human Review 覆寫過，直接用
    # AI original 欄位。
    return {
        "main_category": row.main_category,
        "sub_category": row.sub_category,
        "reasoning": row.reasoning,
    }


def _safe_mask(text):
    """遮罩失敗就回傳 None，讓呼叫端決定要不要整筆捨棄——絕對不會
    回傳未遮罩的原文。"""
    if not text:
        return ""
    try:
        return mask_pii(text)
    except PiiMaskingError:
        return None


def _collect_items(source):
    """依 source 撈出所有 Response_Classification，組成純 Python dict
    清單（respondent_number / main_category / sub_category / status /
    excerpt / reasoning / summary，全部已遮罩），不呼叫任何 Gemini。"""
    if source["source_type"] == SOURCE_TYPE_SURVEY:
        template_id = source["template_id"]
        rows = fetch_classifications_in_scope(SOURCE_TYPE_SURVEY, template_id=template_id)
        responses = (
            Survey_Response.query
            .filter_by(template_id=template_id)
            .order_by(Survey_Response.response_id.asc())
            .all()
        )
        respondent_number_by_key = {r.response_id: i + 1 for i, r in enumerate(responses)}

        def get_respondent_number(row):
            return respondent_number_by_key.get(row.response_id)
    else:
        upload_batch_id = source["upload_batch_id"]
        rows = fetch_classifications_in_scope(SOURCE_TYPE_USER_UPLOAD, upload_batch_id=upload_batch_id)
        uploaded_answers = Uploaded_Answer.query.filter_by(upload_batch_id=upload_batch_id).all()
        row_index_by_id = {ua.id: ua.row_index for ua in uploaded_answers}

        def get_respondent_number(row):
            row_index = row_index_by_id.get(row.uploaded_answer_id)
            return row_index + 1 if row_index is not None else None

    items = []
    for row in rows:
        view = _row_effective_view(row)
        if view is None:
            continue

        excerpt = row.answer_text or ""
        if (
            isinstance(row.segment_start, int)
            and isinstance(row.segment_end, int)
            and 0 <= row.segment_start < row.segment_end <= len(excerpt)
        ):
            excerpt = excerpt[row.segment_start:row.segment_end]

        masked_excerpt = _safe_mask(excerpt)
        masked_reasoning = _safe_mask(view.get("reasoning"))
        masked_summary = _safe_mask(row.summary)
        if masked_excerpt is None or masked_reasoning is None or masked_summary is None:
            print("[CHAT_ASK][PII_MASKING_FAILED]", f"classification_id={row.classification_id}")
            continue

        items.append({
            "respondent_number": get_respondent_number(row),
            "main_category": view.get("main_category") or "（無）",
            "sub_category": view.get("sub_category") or "（無）",
            "status": row.status,
            "excerpt": masked_excerpt,
            "reasoning": masked_reasoning,
            "summary": masked_summary,
        })

    return items


def _build_context_text(items, user_message: str) -> str:
    """把 _collect_items() 撈到的資料，依使用者這次問題（有沒有提到
    A9/B2 這種代碼、有沒有提到「受試者N」）篩出最相關的片段，組成純
    文字 context。沒有比對到任何代碼/受試者編號時，回傳全部（受
    _MAX_CONTEXT_ITEMS 上限保護）。"""
    seen_keys = set()
    category_index_lines = []
    for it in items:
        key = (it["main_category"], it["sub_category"])
        if key not in seen_keys:
            seen_keys.add(key)
            category_index_lines.append(f"- {it['main_category']}／{it['sub_category']}")

    mentioned_codes = _extract_mentioned_codes(user_message)
    mentioned_respondents = _extract_mentioned_respondents(user_message)

    def matches(it):
        code_match = bool(mentioned_codes) and any(
            it["sub_category"].upper().startswith(code) for code in mentioned_codes
        )
        respondent_match = (
            it["respondent_number"] is not None
            and it["respondent_number"] in mentioned_respondents
        )
        return code_match or respondent_match

    if mentioned_codes or mentioned_respondents:
        focused_items = [it for it in items if matches(it)]
        # 使用者明確提到代碼/受試者編號、卻完全比對不到時，退回顯示
        # 全部片段——讓 Gemini 自己依規則 6 明確告知「找不到」，而不是
        # 完全沒有任何 context 可以判斷。
        if not focused_items:
            focused_items = items
    else:
        focused_items = items

    focused_items = focused_items[:_MAX_CONTEXT_ITEMS]

    detail_lines = []
    for it in focused_items:
        respondent_label = (
            f"受試者{it['respondent_number']}" if it["respondent_number"] is not None else "（受試者編號不明）"
        )
        status_note = (
            "" if it["status"] == "completed"
            else f"（此片段分類狀態不是 completed，目前是「{it['status']}」，可能沒有完整的分類原因）"
        )
        detail_lines.append(
            f"[{respondent_label}] 大類別：{it['main_category']}／子類別：{it['sub_category']}{status_note}\n"
            f"  原文片段：{it['excerpt'][:_MAX_EXCERPT_CHARS]}\n"
            f"  分類原因：{it['reasoning'] or '（無）'}\n"
            f"  建議摘要：{it['summary'] or '（無）'}"
        )

    return (
        "【目前這個 chat 已出現過的所有子類別】\n"
        + ("\n".join(category_index_lines) if category_index_lines else "（無）")
        + "\n\n【符合使用者問題的詳細分類與原始回答片段】\n"
        + ("\n\n".join(detail_lines) if detail_lines else "（沒有找到符合的片段）")
    )


def _map_gemini_exception(exc: Exception) -> ChatAskError:
    message = str(exc)
    lower = message.lower()
    if "429" in message or "resourceexhausted" in type(exc).__name__.lower() or "quota" in lower or "rate limit" in lower:
        return ChatAskError("AI 額度或頻率限制已達上限，請稍後再試。", 429)
    if "deadline" in lower or "timeout" in lower:
        return ChatAskError("AI 回覆逾時，請稍後再試。", 504)
    return ChatAskError("AI 服務暫時無法完成回覆，請稍後再試。", 502)


def _call_gemini(context_text: str, user_message: str) -> str:
    """這支追問功能唯一會呼叫 Gemini 的地方，每次呼叫最多執行一次
    （不重試——撞到限流時直接讓使用者知道，而不是同步卡住這次 HTTP
    請求等 20 秒重試，追問是即時互動功能，不是背景批次工作）。"""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ChatAskError("後端缺少 GEMINI_API_KEY 設定，無法呼叫 AI。", 503)

    try:
        from google import genai
        from google.genai import types
    except Exception as exc:
        raise ChatAskError("後端缺少 google-genai 套件，請確認 requirements.txt。", 503) from exc

    client = genai.Client(api_key=api_key)
    contents = f"{context_text}\n\n【使用者問題】\n{user_message}"

    try:
        response = client.models.generate_content(
            model=_ASK_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=0.2,
            ),
        )
    except Exception as exc:
        print("[CHAT_ASK][GEMINI_API_FAILED]", repr(exc))
        raise _map_gemini_exception(exc) from exc

    text = (getattr(response, "text", "") or "").strip()
    if not text:
        raise ChatAskError("AI 沒有回傳內容，請稍後再試。", 502)
    return text


def answer_chat_question(project_id: int, user_message: str) -> str:
    """對外主要介面。呼叫端（routes/chats/chat.py）已經驗證過 project_id
    存在且屬於目前使用者，這裡只負責「找 context、組 prompt、呼叫
    Gemini 一次、回傳答案」，不再做任何權限判斷。"""
    source = _resolve_chat_analysis_source(project_id)
    if source is None:
        raise ChatAskError("目前沒有可供追問的分類結果", 422)

    items = _collect_items(source)
    if not items:
        raise ChatAskError("目前沒有可供追問的分類結果", 422)

    context_text = _build_context_text(items, user_message)
    return _call_gemini(context_text, user_message)