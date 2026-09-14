"""

自動判斷一段文字（問卷題目 title，或 Excel 欄位名稱＋範例內容）
屬於 leadership_and_dept 還是 career_and_feedback 哪一個分析框架。

呼叫時機是「題目建立時」「上傳當下」各一次，不是每則回答一次，
不會隨回答數量增加呼叫次數；下面的重試機制也一樣——重試只發生在
「同一次判斷」內部，不會讓呼叫次數隨回答數量或重試而線性增加。

回傳 None 只會是以下三種情況之一，彼此意義不同，不能混為一談：

    1) 輸入是空字串 / 空白字串 —— 不會呼叫 Gemini，直接回傳 None。
    2)「內容真的判斷不出來」：Gemini 有成功回應，只是判斷結果本來
       就是 null，或回傳了不在合法清單裡的值。這種情況不需要重試，
       直接回傳 None。
    3)「Gemini API 暫時性故障」：呼叫本身失敗，例如 429 / quota
       exceeded / rate limit / 5xx / 逾時。這種情況會先重試，重試
       仍失敗才回傳 None。

【修正】原本任何 Exception（不管是暫時性的 429 quota，還是真正的
程式邏輯錯誤）都直接 fail-safe 成 None，沒有重試機制，等於把「暫時性
故障」跟「內容真的判斷不出來」用完全相同的方式處理、也完全相同的
log（一律印 `[ROUTING ERROR]`），事後從 log 完全無法分辨。

現在的作法：
    - 只有「暫時性」錯誤（429 / quota / rate limit / 5xx）才會重試，
      重試次數固定、不高（最多 2 次重試，含第一次共 3 次 Gemini
      呼叫），避免一直燒 API 額度；等待秒數優先讀 Gemini 錯誤訊息裡
      自己附的建議秒數（retry-after 概念），讀不到才用固定預設值。
      這個重試策略比照 services/classify_v2.py、
      services/segmentation_service.py、
      services/aggregated_summary_service.py 已經在用、驗證過的作法，
      不是這次新發明一套。
    - 非暫時性錯誤（prompt 有問題、JSON 解析失敗等）不重試，維持
      原本「立刻 fail-safe 成 None」的行為。
    - 不論最終是哪一種原因回傳 None，呼叫端（question_routing_service
      的所有呼叫端）都應該一致 fallback 成 QUESTION_OTHER / 動態分類，
      而不是直接跳過這筆資料——這件事是呼叫端的責任，這裡只確保
      「回傳 None」本身的判斷邏輯是正確、可分辨原因的。

log 分成四種，方便從後端 log 分辨原因（不再全部只印
`[ROUTING ERROR]`）：
    [ROUTING_RATE_LIMIT]   偵測到 429 / quota / 限流，準備重試，
                           或重試已用盡
    [ROUTING_API_ERROR]    非限流的其他呼叫 / 解析錯誤，不重試
    [ROUTING_UNDETERMINED] Gemini 正常回應，但判斷結果是「無法歸類」
    [ROUTING_FALLBACK]     這次呼叫最終回傳 None（不論上面哪個原因），
                           提醒呼叫端這裡會需要 fallback 處理
"""

import json
import os
import re
import time
from typing import Optional

import google.generativeai as genai

from services.subcategory_methodology import QUESTION_LEADERSHIP, QUESTION_CAREER

genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

_ALLOWED_QUESTION_TYPES = {QUESTION_LEADERSHIP, QUESTION_CAREER}


_RETRY_DELAY_PATTERNS = (
    re.compile(r"[Rr]etry in ([\d.]+)s"),
    re.compile(r'"retryDelay"\s*:\s*"([\d.]+)s"'),
)


_MAX_ATTEMPTS = 3
_DEFAULT_RETRY_DELAY_SECONDS = 20.0


def _extract_retry_delay_seconds(exc: Exception) -> Optional[float]:
    """從例外訊息裡解析 Gemini 建議的等待秒數；解析不到就回傳 None，
    呼叫端會改用固定預設值。"""
    text = str(exc)
    for pattern in _RETRY_DELAY_PATTERNS:
        match = pattern.search(text)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                continue
    return None


def _is_rate_limit_error(exc: Exception) -> bool:
    """判斷是不是「暫時性」限流 / quota 錯誤（值得重試），而不是
    prompt 有問題、回應格式跑掉之類「重試也沒用」的錯誤。"""
    text = str(exc)
    return (
        "429" in text
        or "ResourceExhausted" in type(exc).__name__
        or "RESOURCE_EXHAUSTED" in text
        or "quota" in text.lower()
    )


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

    最多呼叫 Gemini _MAX_ATTEMPTS 次，只有真的撞到限流才會重試；
    其餘情況（內容判斷不出來、非限流錯誤）都只呼叫一次就回傳。
    """
    if not context_text or not context_text.strip():
        return None

    last_error: Optional[Exception] = None

    for attempt in range(_MAX_ATTEMPTS):
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

            # Gemini 有成功回應，只是判斷結果是 null、或不在合法清單裡
            # ——這是「內容真的判斷不出來」，不是 API 錯誤，不重試。
            print("[ROUTING_UNDETERMINED]", f"raw_result={result!r}")
            print("[ROUTING_FALLBACK]", "reason=undetermined")
            return None

        except Exception as e:
            last_error = e

            if _is_rate_limit_error(e):
                remaining_attempts = _MAX_ATTEMPTS - attempt - 1
                if remaining_attempts > 0:
                    delay = _extract_retry_delay_seconds(e) or _DEFAULT_RETRY_DELAY_SECONDS
                    print(
                        "[ROUTING_RATE_LIMIT]",
                        f"attempt={attempt + 1}/{_MAX_ATTEMPTS}",
                        f"retry_in={delay}s",
                        repr(e),
                    )
                    time.sleep(delay + 1.0)
                    continue
                print(
                    "[ROUTING_RATE_LIMIT]",
                    f"attempt={attempt + 1}/{_MAX_ATTEMPTS}",
                    "retries_exhausted",
                    repr(e),
                )
                break

            # 非限流錯誤（prompt 有問題、JSON 解析失敗等）：維持原本
            # 行為，不重試，直接視為這次判斷失敗。
            print("[ROUTING_API_ERROR]", f"attempt={attempt + 1}", repr(e))
            break

    print("[ROUTING_FALLBACK]", "reason=api_failure", repr(last_error))
    return None