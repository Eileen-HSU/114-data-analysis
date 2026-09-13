"""
測試腳本：驗證 backend/services/classify_v2.py 的多意義單元分類流程
（classify_response_multi_segment），以及確認舊版 _run_classification()
／classify_response_v2() 沒有被破壞。

用假的 google.generativeai 模組取代真實 API。

執行方式：
    cd backend
    python3 test_classify_v2_multi_segment.py
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


_call_log = []
_queued_responses = []


class _FakeResp:
    def __init__(self, text):
        self.text = text


class _FakeModel:
    def __init__(self, system_instruction=None, **kwargs):
        self.system_instruction = system_instruction

    def generate_content(self, prompt, **kwargs):
        _call_log.append({"system_instruction": self.system_instruction, "prompt": prompt})
        return _FakeResp(_queued_responses.pop(0))


_fake_genai = types.ModuleType("google.generativeai")
_fake_genai.GenerativeModel = _FakeModel
_fake_genai.configure = lambda **kwargs: None
_fake_google = types.ModuleType("google")
_fake_google.generativeai = _fake_genai
sys.modules["google"] = _fake_google
sys.modules["google.generativeai"] = _fake_genai

import services.classify_v2 as cv2


def queue(text):
    _queued_responses.append(text)


def queue_json(obj):
    queue(json.dumps(obj, ensure_ascii=False))


ORIGINAL = "王小明覺得主管很願意聽取意見，但工作量太大，希望增加人力"


print("========== 情境 1：固定 2 次 Gemini 呼叫，index 對應正確（含亂序）==========")
_call_log.clear()
queue_json({"segments": ["【姓名】覺得主管很願意聽取意見", "工作量太大，希望增加人力"]})
queue_json({"classifications": [
    {"index": 1, "main_category": "部門合作", "sub_category": "B2 支援協作",
     "secondary_sub_category": None, "reasoning": "r2", "summary": "s2", "confidence": "high"},
    {"index": 0, "main_category": "主管領導", "sub_category": "A2 回饋與溝通",
     "secondary_sub_category": None, "reasoning": "r1", "summary": "s1", "confidence": "high"},
]})
result = cv2.classify_response_multi_segment(ORIGINAL, cv2.DEFAULT_PROMPT_LEADERSHIP, "leadership_and_dept")
check("固定呼叫 2 次", len(_call_log) == 2)
check("segmentation_status 為 completed", result["segmentation_status"] == "completed")
check("2 個 segment 都有分類結果", len(result["segments"]) == 2)
check("index 0 正確對應第一段", result["segments"][0]["sub_category"] == "A2 回饋與溝通")
check("index 1 正確對應第二段（即使 Gemini 回傳順序相反）", result["segments"][1]["sub_category"] == "B2 支援協作")
check(
    "orig_start/orig_end 正確指向原文",
    ORIGINAL[result["segments"][0]["orig_start"]:result["segments"][0]["orig_end"]] == "王小明覺得主管很願意聽取意見",
)


print("\n========== 情境 2：system_instruction 沿用 prompt_content，附加 override，不重複分類規則 ==========")
si = _call_log[1]["system_instruction"]
check("system_instruction 含原始分類規則", "A1 工作與生活邊界" in si)
check("system_instruction 含原本單筆 JSON 指示（未被刪除/改寫）", '"main_category": "大類別名稱"' in si)
check("system_instruction 含批次輸出格式覆蓋說明", "本次輸出格式覆蓋" in si)
check("user message 不重複 JSON 格式規則", "classifications" not in _call_log[1]["prompt"])


print("\n========== 情境 3：index 集合不完整，整批 fail-closed ==========")
queue_json({"segments": ["【姓名】覺得主管很願意聽取意見", "工作量太大，希望增加人力"]})
queue_json({"classifications": [
    {"index": 0, "main_category": "x", "sub_category": "y", "reasoning": "r", "summary": "s"},
]})  # 缺 index 1
result = cv2.classify_response_multi_segment(ORIGINAL, cv2.DEFAULT_PROMPT_LEADERSHIP, "leadership_and_dept")
check("兩個 segment 都標記失敗（不採信部分結果）", all(s["status"] == "failed" for s in result["segments"]))
check(
    "錯誤標籤為 BATCH_CLASSIFICATION_FAILED",
    all("BATCH_CLASSIFICATION_FAILED" in s["error_detail"] for s in result["segments"]),
)


print("\n========== 情境 4：PII masking 失敗，fail-closed，不呼叫 Gemini ==========")
_call_log.clear()
import services.privacy_service as ps

_orig_get_engines = ps._get_engines
ps._get_engines = lambda: (_ for _ in ()).throw(RuntimeError("simulated crash"))
result = cv2.classify_response_multi_segment(ORIGINAL, cv2.DEFAULT_PROMPT_LEADERSHIP, "leadership_and_dept")
ps._get_engines = _orig_get_engines
check("PII masking 失敗時完全不呼叫 Gemini", len(_call_log) == 0)
check("segmentation_status 為 failed", result["segmentation_status"] == "failed")
check("segments 為空清單", result["segments"] == [])
check("error_detail 標記 PII_MASKING_FAILED", "PII_MASKING_FAILED" in result["segmentation_error_detail"])


print("\n========== 情境 5：舊版 _run_classification() / classify_response_v2() 不受影響 ==========")
_call_log.clear()
queue_json({"main_category": "主管領導", "sub_category": "A2 回饋與溝通",
            "secondary_sub_category": None, "reasoning": "r", "summary": "s", "confidence": "high"})
old_result = cv2._run_classification("王小明的信箱是abc@gmail.com", cv2.DEFAULT_PROMPT_LEADERSHIP, "leadership_and_dept")
check("舊路徑只呼叫 1 次 Gemini", len(_call_log) == 1)
check("舊路徑依然自動遮罩（送出內容不含明文 PII）", "王小明" not in _call_log[0]["prompt"] and "abc@gmail.com" not in _call_log[0]["prompt"])
check("舊路徑分類成功", old_result["status"] == "completed")

_call_log.clear()
queue("not valid json")
old_fail = cv2._run_classification("測試", cv2.DEFAULT_PROMPT_LEADERSHIP, "leadership_and_dept")
check("舊路徑錯誤標籤仍是 GEMINI_API_FAILED（不是 BATCH_CLASSIFICATION_FAILED）", "GEMINI_API_FAILED" in old_fail["error_detail"])


print("\n" + "=" * 50)
if FAILED:
    print(f"共 {len(FAILED)} 項測試失敗：")
    for f in FAILED:
        print("  -", f)
    sys.exit(1)
else:
    print("全部測試通過！")