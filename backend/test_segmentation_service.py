"""
測試腳本：驗證 backend/services/segmentation_service.py。

涵蓋：Gemini #1 呼叫結果的定位／驗證、placeholder 邊界檢查、
不重疊保證、orig_start/orig_end 換算正確性、部分失敗與整批失敗。

用假的 google.generativeai 模組取代真實 API，不需要真實
GEMINI_API_KEY 也能執行。

執行方式：
    cd backend
    python3 test_segmentation_service.py
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


# ── 在 import segmentation_service 之前，先把 google.generativeai 換成假的 ──
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

from services.privacy_service import mask_pii_with_mapping
from services.segmentation_service import segment_answer


def queue(response_dict):
    _queued_responses.append(json.dumps(response_dict, ensure_ascii=False))


ORIGINAL = "王小明覺得主管很願意聽取意見，但工作量太大，希望增加人力"
MASKED_TEXT, POSITION_MAP = mask_pii_with_mapping(ORIGINAL)
print(f"masked_text = {MASKED_TEXT!r}\n")


print("========== 情境 1：正常拆分兩段 ==========")
queue({"segments": ["【姓名】覺得主管很願意聽取意見", "工作量太大，希望增加人力"]})
result = segment_answer(MASKED_TEXT, POSITION_MAP)
check("segmentation_status 為 completed", result["segmentation_status"] == "completed")
check("拆出 2 個 segment", len(result["segments"]) == 2)
seg0, seg1 = result["segments"]
check("segment 0 含 masked_text", seg0["masked_text"] == "【姓名】覺得主管很願意聽取意見")
check(
    "segment 0 orig 座標正確換算回原文",
    ORIGINAL[seg0["orig_start"]:seg0["orig_end"]] == "王小明覺得主管很願意聽取意見",
)
check(
    "segment 1 orig 座標正確換算回原文",
    ORIGINAL[seg1["orig_start"]:seg1["orig_end"]] == "工作量太大，希望增加人力",
)


print("\n========== 情境 2：不拆分，單一片段 ==========")
queue({"segments": [MASKED_TEXT]})
result = segment_answer(MASKED_TEXT, POSITION_MAP)
check("單一片段 status 為 completed", result["segmentation_status"] == "completed")
check("單一片段數量為 1", len(result["segments"]) == 1)
check(
    "單一片段涵蓋完整原文",
    ORIGINAL[result["segments"][0]["orig_start"]:result["segments"][0]["orig_end"]] == ORIGINAL,
)


print("\n========== 情境 3：部分片段找不到（Gemini 編造內容）==========")
queue({"segments": ["【姓名】覺得主管很願意聽取意見", "這段是編出來的內容"]})
result = segment_answer(MASKED_TEXT, POSITION_MAP)
check("partial_failed 狀態正確", result["segmentation_status"] == "partial_failed")
check("只有 1 個 segment 驗證通過", len(result["segments"]) == 1)
check("error_detail 有記錄失敗原因", result["error_detail"] is not None)


print("\n========== 情境 4：切在遮罩標籤中間，應驗證失敗 ==========")
bad_masked = MASKED_TEXT[0:2]  # 只取「【姓」兩個字，不是完整標籤
queue({"segments": [bad_masked, MASKED_TEXT[2:]]})
result = segment_answer(MASKED_TEXT, POSITION_MAP)
check(
    "切在標籤中間的片段被拒絕（不是全部驗證通過）",
    result["segmentation_status"] in ("partial_failed", "failed"),
)


print("\n========== 情境 5：Gemini 呼叫本身失敗（例如回傳非 JSON）==========")
queue({})  # 會在下面直接塞一個非法字串
_queued_responses.pop()
_queued_responses.append("not valid json")
result = segment_answer(MASKED_TEXT, POSITION_MAP)
check("呼叫失敗時 segmentation_status 為 failed", result["segmentation_status"] == "failed")
check("失敗時 segments 為空清單", result["segments"] == [])
check("error_detail 標記 SEGMENTATION_CALL_FAILED", "SEGMENTATION_CALL_FAILED" in (result["error_detail"] or ""))


print("\n========== 情境 6：不重疊保證（依序定位，天然不會重疊）==========")
queue({"segments": ["【姓名】覺得主管很願意聽取意見", "工作量太大，希望增加人力"]})
result = segment_answer(MASKED_TEXT, POSITION_MAP)
segs = sorted(result["segments"], key=lambda s: s["orig_start"])
no_overlap = all(segs[i]["orig_end"] <= segs[i + 1]["orig_start"] for i in range(len(segs) - 1))
check("多個 segment 之間彼此不重疊", no_overlap)


print("\n" + "=" * 50)
if FAILED:
    print(f"共 {len(FAILED)} 項測試失敗：")
    for f in FAILED:
        print("  -", f)
    sys.exit(1)
else:
    print("全部測試通過！")