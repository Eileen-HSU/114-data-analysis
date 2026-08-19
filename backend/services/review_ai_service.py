"""

Human Review Conversation 專用的 Gemini 呼叫層。

跟 services/classify_v2.py 的分工是：
    classify_v2.py      ：AI original 分類（segmentation + 批次分類）
    review_ai_service.py：Human Review 對話中，針對「單一一筆已存在的
                           classification」跟 User 來回討論、重新判斷

【taxonomy 限制的實作方式，對應本次需求文件第六、七節與使用者的
Phase 1 修正】
    Gemini 在這裡只允許輸出 sub_category / secondary_sub_category
    （跟 classify_v2.py 的正式分類輸出格式一致），main_category /
    secondary_main_category / methodology / citation 一律由後端呼叫
    services/subcategory_methodology.get_methodology() 查表取得，
    不讓 Gemini 自己輸出或發明這些欄位。

    Gemini 回傳的 sub_category 如果不在
    subcategory_methodology.all_subcategories(question_type) 允許清單
    裡（Gemini 自創或打字不一致），視為「這輪沒有提出有效 candidate」
    ——不寫入 candidate_* 欄位（維持 None），但仍然保留 Gemini 的
    自然語言回覆文字，讓對話可以繼續、User 可以再澄清一次
    （對應測試項目 9：AI 回傳不存在 taxonomy → reject / retry-safe）。
"""

import json
import os
import re

import google.generativeai as genai

from services.privacy_service import mask_pii, PiiMaskingError
from services.subcategory_methodology import all_subcategories, get_methodology

genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))


REVIEW_SYSTEM_INSTRUCTION_TEMPLATE = """你是問卷開放式回覆的人工複核助手，正在陪同一位審核人員（User）針對
「已經由 AI 判斷過一次」的一小段回覆內容，重新討論分類是否正確。

【絕對規則，不可違反】
1. 你只能從下面「目前正式存在的子類別清單」裡選擇，不可以自創、
   修改或合併類別名稱。
2. 如果 User 提出的分類需求不在清單內，你必須在回覆裡說明目前分類
   架構沒有這個類別，並從清單中選出語意最接近的既有子類別供參考，
   不可以假裝新增了一個類別。
3. 你不能修改 methodology、citation，那些不是你的職責，完全不要
   在輸出裡提到或發明這些內容。
4. 除非你有足夠把握要更新候選分類，否則 candidate_sub_category /
   candidate_secondary_sub_category 可以維持跟目前候選一致或回傳
   null（代表這輪只是討論、不變更候選）。
5. secondary_sub_category 是可選的，只有在內容明確同時涉及另一個
   獨立主題時才需要提出；不要為了填欄位而勉強生成。

【這一題目前正式存在的子類別清單（只能從這裡選）】
{taxonomy_list}

【這段回覆的原始 AI 判斷】
main_category: {ai_main_category}
sub_category: {ai_sub_category}
secondary_sub_category: {ai_secondary_sub_category}
reasoning: {ai_reasoning}

【目前的候選分類（尚未確認，可能等於 AI 原始判斷，也可能是前幾輪
討論後的結果）】
candidate_sub_category: {candidate_sub_category}
candidate_secondary_sub_category: {candidate_secondary_sub_category}

只回傳以下 JSON 格式，不要加任何其他文字說明：

{{
  "reply": "給 User 看的自然語言回覆，1-3 句話",
  "candidate_sub_category": "子類別完整名稱，或維持不變、或 null",
  "candidate_secondary_sub_category": "次要子類別完整名稱，或 null",
  "candidate_reasoning": "這個候選分類的判斷原因，1-2 句話，或 null"
}}"""


class ReviewAIError(RuntimeError):
    """Gemini 呼叫或回傳格式有問題時使用（呼叫端應該 fail-safe，
    不讓整個 review 對話中斷，但也不能假裝有 candidate）。"""


def _parse_json(raw_text: str) -> dict:
    cleaned = re.sub(r"```json|```", "", raw_text).strip()
    return json.loads(cleaned)


def _build_taxonomy_list_text(question_type: str) -> str:
    subs = all_subcategories(question_type)
    return "\n".join(f"- {s}" for s in subs) if subs else "（目前查無這個題目的子類別清單）"


def _build_history_text(conversation_history: list) -> str:
    if not conversation_history:
        return "（尚無對話紀錄，這是第一輪）"
    lines = []
    for msg in conversation_history:
        speaker = "User" if msg["role"] == "user" else "AI"
        lines.append(f"{speaker}：{msg['content']}")
    return "\n".join(lines)


def build_review_reply(
    *,
    question_type: str,
    segment_text: str,
    ai_main_category: str,
    ai_sub_category: str,
    ai_secondary_sub_category: str,
    ai_reasoning: str,
    candidate_sub_category: str,
    candidate_secondary_sub_category: str,
    conversation_history: list,
    user_message: str,
) -> dict:
    """
    對外主要介面。呼叫 Gemini、驗證 taxonomy、補上 main_category /
    secondary_main_category（查表結果，不是 Gemini 輸出），套用
    Primary==Secondary 正規化規則。

    Args:
        segment_text: 這個 segment 的原文（未遮罩）。這裡負責在送
            進 Gemini 前呼叫 mask_pii()，呼叫端不需要自己遮罩。
        conversation_history: [{"role": "user"/"assistant", "content": str}, ...]，
            依時間順序、不含這一輪剛送出的 user_message。

    Returns:
        {
            "reply": str,
            "candidate_main_category": str or None,   # 查表結果
            "candidate_sub_category": str or None,     # Gemini 輸出，已驗證存在於 taxonomy
            "candidate_secondary_main_category": str or None,  # 查表結果
            "candidate_secondary_sub_category": str or None,   # Gemini 輸出，已驗證
            "candidate_reasoning": str or None,
            "taxonomy_rejected": bool,  # True 代表 Gemini 這輪回傳的子類別不在允許清單裡，
                                         # 已經被拒絕採用，只保留自然語言回覆
        }

    Gemini 呼叫失敗或回傳格式錯誤時，不拋出例外中斷對話：回傳一個
    fail-safe 的 dict，reply 是固定的錯誤說明文字，candidate_* 全部
    是 None（不採用任何候選變更），讓呼叫端可以照常把這輪對話存
    下來、User 可以重新再問一次。
    """
    try:
        masked_segment = mask_pii(segment_text)
    except PiiMaskingError as e:
        return {
            "reply": "系統暫時無法處理這段內容（個資遮罩失敗），請稍後再試一次。",
            "candidate_main_category": None,
            "candidate_sub_category": None,
            "candidate_secondary_main_category": None,
            "candidate_secondary_sub_category": None,
            "candidate_reasoning": None,
            "taxonomy_rejected": False,
            "error_detail": f"PII_MASKING_FAILED: {str(e)[:180]}",
        }

    system_instruction = REVIEW_SYSTEM_INSTRUCTION_TEMPLATE.format(
        taxonomy_list=_build_taxonomy_list_text(question_type),
        ai_main_category=ai_main_category,
        ai_sub_category=ai_sub_category,
        ai_secondary_sub_category=ai_secondary_sub_category or "無",
        ai_reasoning=ai_reasoning or "（無）",
        candidate_sub_category=candidate_sub_category or ai_sub_category,
        candidate_secondary_sub_category=candidate_secondary_sub_category or "無",
    )

    user_content = (
        f"這段回覆原文（已遮罩個資）：\n{masked_segment}\n\n"
        f"對話紀錄：\n{_build_history_text(conversation_history)}\n\n"
        f"User 這一輪的意見：\n{user_message}"
    )

    try:
        model = genai.GenerativeModel(
            model_name="gemini-3.1-flash-lite",
            system_instruction=system_instruction,
        )
        response = model.generate_content(
            user_content,
            generation_config={"temperature": 0},
        )
        parsed = _parse_json(response.text)
    except Exception as e:
        print("[REVIEW AI ERROR][CALL_OR_PARSE_FAILED]", repr(e))
        return {
            "reply": "系統暫時無法處理這則訊息，請稍後再試一次。",
            "candidate_main_category": None,
            "candidate_sub_category": None,
            "candidate_secondary_main_category": None,
            "candidate_secondary_sub_category": None,
            "candidate_reasoning": None,
            "taxonomy_rejected": False,
            "error_detail": f"REVIEW_CALL_FAILED: {str(e)[:180]}",
        }

    reply_text = parsed.get("reply") or ""
    raw_sub = parsed.get("candidate_sub_category")
    raw_secondary_sub = parsed.get("candidate_secondary_sub_category")
    raw_reasoning = parsed.get("candidate_reasoning")

    allowed = set(all_subcategories(question_type))

    taxonomy_rejected = False

    resolved_sub = None
    resolved_main = None
    if raw_sub:
        if raw_sub in allowed:
            resolved_sub = raw_sub
            resolved_main = get_methodology(question_type, raw_sub)["main_category"]
        else:
            taxonomy_rejected = True
            print(f"[REVIEW AI WARNING] Gemini 回傳不在 taxonomy 裡的 sub_category: {raw_sub!r}")

    resolved_secondary_sub = None
    resolved_secondary_main = None
    if raw_secondary_sub:
        if raw_secondary_sub in allowed:
            resolved_secondary_sub = raw_secondary_sub
            resolved_secondary_main = get_methodology(question_type, raw_secondary_sub)["main_category"]
        else:
            taxonomy_rejected = True
            print(f"[REVIEW AI WARNING] Gemini 回傳不在 taxonomy 裡的 secondary_sub_category: {raw_secondary_sub!r}")

    # Primary == Secondary 正規化：跟 classify_v2._build_classification_result()
    # 概念一致，只是這裡比較的是「這一輪 candidate」而非正式 AI original。
    if resolved_sub is not None and resolved_sub == resolved_secondary_sub:
        resolved_secondary_sub = None
        resolved_secondary_main = None

    return {
        "reply": reply_text,
        "candidate_main_category": resolved_main,
        "candidate_sub_category": resolved_sub,
        "candidate_secondary_main_category": resolved_secondary_main,
        "candidate_secondary_sub_category": resolved_secondary_sub,
        "candidate_reasoning": raw_reasoning if resolved_sub else None,
        "taxonomy_rejected": taxonomy_rejected,
        "error_detail": None,
    }
