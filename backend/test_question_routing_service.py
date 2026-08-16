"""
測試腳本：驗證 backend/services/question_routing_service.py。

執行方式：
    cd backend
    python3 test_question_routing_service.py
"""

import sys
import os
import types
import json

sys.path.insert(0, os.path.dirname(__file__))

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
        return _FakeResp(_queued_responses.pop(0))


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

print("\n" + "=" * 50)
if FAILED:
    print(f"共 {len(FAILED)} 項測試失敗：")
    for f in FAILED:
        print("  -", f)
    sys.exit(1)
else:
    print("全部測試通過！")