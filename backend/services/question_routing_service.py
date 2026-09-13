"""

自動判斷一段文字（問卷題目 title，或 Excel 欄位名稱＋範例內容）
屬於 leadership_and_dept 還是 career_and_feedback 哪一個分析框架。

呼叫時機是「題目建立時」「上傳當下」各一次，不是每則回答一次，
不會隨回答數量增加呼叫次數。

Fail-safe：任何無法可靠判斷的情況（Gemini 回傳不合法值、呼叫失敗、
輸入是空字串）一律回傳 None，不猜測、不預設某一個框架。
"""

import json
import os
import re
from typing import Optional

import google.generativeai as genai

from services.subcategory_methodology import QUESTION_LEADERSHIP, QUESTION_CAREER

genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

_ALLOWED_QUESTION_TYPES = {QUESTION_LEADERSHIP, QUESTION_CAREER}

ROUTING_PROMPT = f"""你是問卷內容的分類 routing 判斷助手。系統有兩個固定的分析框架：

- {QUESTION_LEADERSHIP}：主管領導風格、主管與部屬互動、部門之間合作、溝通協調相關內容。
- {QUESTION_CAREER}：工作表現回饋、績效回饋、職涯發展、培訓需求相關內容。

請判斷輸入內容（可能是題目名稱，也可能包含實際回答範例）整體上比較
屬於哪一個框架。如果內容跟兩者都無關、內容過於模糊、或無法可靠判斷，
請回傳 null，不要用猜的、不要強行歸類。

只回傳以下 JSON 格式，不要加任何其他文字：
{{"question_type": "{QUESTION_LEADERSHIP}" 或 "{QUESTION_CAREER}" 或 null}}"""


def route_question_type(context_text: str) -> Optional[str]:
    """
    對外主要介面。輸入已經組好的判斷用文字（呼叫端負責組裝、
    以及必要的 PII masking，這裡不做遮罩），回傳判斷結果或 None。
    """
    if not context_text or not context_text.strip():
        return None

    try:
        model = genai.GenerativeModel(
            model_name="gemini-3.1-flash-lite",
            system_instruction=ROUTING_PROMPT,
        )
        response = model.generate_content(
            context_text,
            generation_config={"temperature": 0},
        )
        cleaned = re.sub(r"```json|```", "", response.text).strip()
        parsed = json.loads(cleaned)
        result = parsed.get("question_type")

        if result in _ALLOWED_QUESTION_TYPES:
            return result
        return None  # 包含 Gemini 回傳 null、或任何不在合法清單裡的值

    except Exception as e:
        print("[ROUTING ERROR]", repr(e))
        return None