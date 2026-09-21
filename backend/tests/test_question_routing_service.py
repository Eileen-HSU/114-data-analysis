"""
測試腳本：驗證 backend/services/question_routing_service.py。

執行方式：
    cd backend
    python3 tests/test_question_routing_service.py
"""

import sys
import os
import time
import types
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

FAILED = []


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    if status == "FAIL":
        FAILED.append(label)
    print(f"[{status}] {label}")


_queued_responses = []


class _FakeResp:
    def __init__(self, text):
        self.text = text


class _FakeModel:
    def __init__(self, **kwargs):
        pass

    def generate_content(self, prompt, **kwargs):
        # 佇列裡的元素除了「成功回應的文字」以外，也可以放一個
        # Exception instance，代表這次呼叫要模擬失敗（例如 429），
        # 讓下面可以測試重試機制，而不需要真的打 Gemini API。
        item = _queued_responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return _FakeResp(item)


_fake_genai = types.ModuleType("google.generativeai")
_fake_genai.GenerativeModel = _FakeModel
_fake_genai.configure = lambda **kwargs: None
_fake_google = types.ModuleType("google")
_fake_google.generativeai = _fake_genai
sys.modules["google"] = _fake_google
sys.modules["google.generativeai"] = _fake_genai

from services.question_routing_service import route_question_type


def queue_json(obj):
    _queued_responses.append(json.dumps(obj, ensure_ascii=False))


print("========== 情境 1：正常判斷出 leadership_and_dept ==========")
queue_json({"question_type": "leadership_and_dept"})
check("正確判斷", route_question_type("主管領導與部門合作建議") == "leadership_and_dept")

print("\n========== 情境 2：正常判斷出 career_and_feedback ==========")
queue_json({"question_type": "career_and_feedback"})
check("正確判斷", route_question_type("對於職涯發展的建議") == "career_and_feedback")

print("\n========== 情境 3：Gemini 主動判斷不出來（回傳 null）==========")
queue_json({"question_type": None})
check("Gemini 回傳 null 時對外回傳 None", route_question_type("今天天氣如何") is None)

print("\n========== 情境 4：Gemini 回傳不在合法清單內的值，fail-safe 成 None ==========")
queue_json({"question_type": "not_a_real_type"})
check("不合法值 fail-safe 成 None", route_question_type("亂七八糟") is None)

print("\n========== 情境 5：Gemini 呼叫/解析失敗，fail-safe 成 None ==========")
_queued_responses.append("not valid json")
check("呼叫失敗 fail-safe 成 None", route_question_type("測試") is None)

print("\n========== 情境 6：空字串/None 輸入，不呼叫 Gemini 直接回傳 None ==========")
check("空字串輸入直接 None", route_question_type("") is None)
check("None 輸入直接 None", route_question_type(None) is None)
check("純空白字串直接 None", route_question_type("   ") is None)

print("\n========== 情境 7：撞到限流（429），重試後成功判斷（不會永久變成 None）==========")
# 用很短的 "retry in 0.01s" 讓測試不用真的等 20 秒；只是驗證重試邏輯
# 本身有正確運作、有從錯誤訊息讀建議秒數，不是在測真正的等待時間。
_queued_responses.append(
    Exception("429 Resource has been exhausted (e.g. check quota). Please retry in 0.01s")
)
queue_json({"question_type": "career_and_feedback"})
_start = time.time()
_result = route_question_type("績效面談與職涯發展建議")
_elapsed = time.time() - _start
check("限流後重試成功，不會直接放棄變成 None", _result == "career_and_feedback")
check("有讀到訊息裡建議的等待秒數，不是傻等固定 20 秒", _elapsed < 5)

print("\n========== 情境 8：連續撞到限流，重試用盡後才 fallback 成 None ==========")
for _ in range(3):  # 對應 _MAX_ATTEMPTS = 3，三次都失敗才會真的放棄
    _queued_responses.append(
        Exception("429 RESOURCE_EXHAUSTED. Please retry in 0.01s")
    )
check("重試用盡才 fallback 成 None（且不會無限重試）", route_question_type("測試連續限流") is None)

print("\n========== 情境 9：非限流錯誤（例如回應不是合法 JSON）不重試，只呼叫一次 ==========")
_queued_responses.append("not valid json")
# 如果程式誤把這種錯誤也拿去重試，就會把下面這筆本來要留給「下一次
# 呼叫」的資料誤吃掉，用佇列剩餘長度可以驗證「真的沒有重試」。
queue_json({"question_type": "leadership_and_dept"})
check("非限流錯誤 fail-safe 成 None，不重試", route_question_type("測試非限流錯誤") is None)
check("非限流錯誤沒有誤觸發重試，佇列裡的下一筆資料還在", len(_queued_responses) == 1)
_queued_responses.pop(0)  # 清掉，避免影響後面（如果之後又加測試）

print("\n" + "=" * 50)
if FAILED:
    print(f"共 {len(FAILED)} 項測試失敗：")
    for f in FAILED:
        print("  -", f)
    sys.exit(1)
else:
    print("全部測試通過！")