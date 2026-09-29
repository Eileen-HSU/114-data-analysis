"""
測試腳本：驗證 backend/services/segmentation_service.py。

涵蓋：Gemini #1 呼叫結果的定位／驗證、placeholder 邊界檢查、
不重疊保證、orig_start/orig_end 換算正確性、部分失敗與整批失敗。

用假的 google.generativeai 模組取代真實 API，不需要真實
GEMINI_API_KEY 也能執行。

執行方式：
    cd backend
    python3 tests/test_segmentation_service.py
"""

import sys
import os
import types
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

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


# 直接替換 services.gemini_client（新版 google-genai SDK 的包裝層），
# 不再偽造 sys.modules["google"]——那會讓 `from google import genai` 失敗。
import services.gemini_client as _gemini_client
_gemini_client.GenerativeModel = _FakeModel
_gemini_client.configure = lambda **kwargs: None

from services.privacy_service import mask_pii_with_mapping
from services.segmentation_service import segment_answer


def queue(response_dict):
    _queued_responses.append(json.dumps(response_dict, ensure_ascii=False))


ORIGINAL = "王小明覺得主管很願意聽取意見，但工作量太大，希望增加人力"
MASKED_TEXT, POSITION_MAP = mask_pii_with_mapping(ORIGINAL)
print(f"masked_text = {MASKED_TEXT!r}\n")


print("========== 情境 1：正常拆分兩段（完整涵蓋，連接詞歸入後一段）==========")
queue({"segments": ["【姓名】覺得主管很願意聽取意見，", "但工作量太大，希望增加人力"]})
result = segment_answer(MASKED_TEXT, POSITION_MAP)
check("segmentation_status 為 completed", result["segmentation_status"] == "completed")
check("拆出 2 個 segment", len(result["segments"]) == 2)
seg0, seg1 = result["segments"]
check("segment 0 含 masked_text", seg0["masked_text"] == "【姓名】覺得主管很願意聽取意見，")
check(
    "segment 0 orig 座標正確換算回原文",
    ORIGINAL[seg0["orig_start"]:seg0["orig_end"]] == "王小明覺得主管很願意聽取意見，",
)
check(
    "segment 1 orig 座標正確換算回原文",
    ORIGINAL[seg1["orig_start"]:seg1["orig_end"]] == "但工作量太大，希望增加人力",
)
check("completed 時 error_detail 為 None", result["error_detail"] is None)


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
check("回退成 1 個整則片段", len(result["segments"]) == 1)
check(
    "回退片段涵蓋完整原文（找不到的片段不會讓原文消失）",
    ORIGINAL[result["segments"][0]["orig_start"]:result["segments"][0]["orig_end"]] == ORIGINAL,
)
check("error_detail 有記錄失敗原因", "這段是編出來的內容" in (result["error_detail"] or ""))


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


def _assert_whole_fallback(label, result, missing_snippet):
    check(f"{label}：不可標成 completed", result["segmentation_status"] == "partial_failed")
    check(f"{label}：回退成單一整則片段", len(result["segments"]) == 1)
    seg = result["segments"][0] if result["segments"] else {"orig_start": 0, "orig_end": 0, "masked_text": ""}
    check(f"{label}：片段涵蓋完整原文", ORIGINAL[seg["orig_start"]:seg["orig_end"]] == ORIGINAL)
    check(f"{label}：送分類的是完整遮罩文字（不含原始個資）", seg["masked_text"] == MASKED_TEXT and "王小明" not in seg["masked_text"])
    detail = result["error_detail"] or ""
    check(f"{label}：error_detail 標記 SEGMENTATION_COVERAGE_GAP", "SEGMENTATION_COVERAGE_GAP" in detail)
    check(f"{label}：error_detail 指出漏掉的內容", missing_snippet in detail)


print("\n========== 情境 7：首段漏字（原文開頭沒被涵蓋）==========")
queue({"segments": ["覺得主管很願意聽取意見，", "但工作量太大，希望增加人力"]})
_assert_whole_fallback("首段漏字", segment_answer(MASKED_TEXT, POSITION_MAP), "【姓名】")


print("\n========== 情境 8：中間漏字（片段之間有空隙）==========")
queue({"segments": ["【姓名】覺得主管很願意聽取意見", "工作量太大，希望增加人力"]})
_assert_whole_fallback("中間漏字", segment_answer(MASKED_TEXT, POSITION_MAP), "但")

queue({"segments": ["【姓名】覺得主管很願意聽取意見，", "希望增加人力"]})
_assert_whole_fallback("中間漏掉整個子句", segment_answer(MASKED_TEXT, POSITION_MAP), "但工作量太大")


print("\n========== 情境 9：尾段漏字（原文結尾沒被涵蓋）==========")
queue({"segments": ["【姓名】覺得主管很願意聽取意見，", "但工作量太大，"]})
_assert_whole_fallback("尾段漏字", segment_answer(MASKED_TEXT, POSITION_MAP), "希望增加人力")


print("\n========== 情境 10：AI 回傳空清單 ==========")
queue({"segments": []})
_assert_whole_fallback("空清單", segment_answer(MASKED_TEXT, POSITION_MAP), "【姓名】")


print("\n========== 情境 11：片段間只差標點 / 空白 -> 併入相鄰片段，completed ==========")
queue({"segments": ["【姓名】覺得主管很願意聽取意見", "但工作量太大", "希望增加人力"]})
result = segment_answer(MASKED_TEXT, POSITION_MAP)
check("標點空隙：completed", result["segmentation_status"] == "completed")
check("標點空隙：3 段", len(result["segments"]) == 3)
check(
    "標點空隙：片段依序接起來等於完整原文（無空隙）",
    "".join(ORIGINAL[s["orig_start"]:s["orig_end"]] for s in result["segments"]) == ORIGINAL,
)
check(
    "標點空隙：相鄰片段首尾相接",
    all(result["segments"][i]["orig_end"] == result["segments"][i + 1]["orig_start"] for i in range(2)),
)
check("標點空隙：逗號併入前一段", result["segments"][0]["masked_text"] == "【姓名】覺得主管很願意聽取意見，")

queue({"segments": ["  【姓名】覺得主管很願意聽取意見，但工作量太大，希望增加人力"[2:]]})
result = segment_answer("  " + MASKED_TEXT + "。", mask_pii_with_mapping("  " + ORIGINAL + "。")[1])
check("開頭空白 / 結尾句號：completed", result["segmentation_status"] == "completed")
check("開頭空白 / 結尾句號：片段涵蓋整則", result["segments"][0]["orig_start"] == 0 and result["segments"][0]["orig_end"] == len(ORIGINAL) + 3)


print("\n========== 情境 12：切在標籤中間的原因不會被誤記成「找不到」==========")
queue({"segments": [MASKED_TEXT[0:2], MASKED_TEXT[2:]]})
result = segment_answer(MASKED_TEXT, POSITION_MAP)
check("標籤邊界：回退整則", result["segmentation_status"] == "partial_failed" and len(result["segments"]) == 1)
check("標籤邊界：原因不是『找不到』", "找不到" not in (result["error_detail"] or "").split("|")[-1])


print("\n" + "=" * 50)
if FAILED:
    print(f"共 {len(FAILED)} 項測試失敗：")
    for f in FAILED:
        print("  -", f)
    sys.exit(1)
else:
    print("全部測試通過！")