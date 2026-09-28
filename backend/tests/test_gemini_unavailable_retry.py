#!/usr/bin/env python
"""
Gemini 暫時過載（503 UNAVAILABLE）自動重試。

背景：分類時 Gemini 回傳
    503 UNAVAILABLE ... "This model is currently experiencing high demand"
原本只有 429 會重試，503 直接失敗，整批 segment 被標成
BATCH_CLASSIFICATION_FAILED，需要 Admin 手動重新處理。

涵蓋：
    1. 批次分類（classify_v2._generate_with_retry）：503 兩次後成功 -> 回傳結果，
       依 2、4 秒退避
    2. 拆分（segmentation_service._call_gemini_segmentation）：503 一次後成功
    3. 503 持續發生：重試 3 次（2、4、8 秒）後仍往上拋，不無限重試
    4. 非暫時性錯誤（例如 400 INVALID_ARGUMENT）不重試
    5. 429 限流行為不變（照建議秒數等待）

執行方式：
    cd backend
    python3 tests/test_gemini_unavailable_retry.py
"""

import json

from admin_test_support import check, finish
import services.classify_v2 as classify_v2
import services.gemini_client as gemini_client
import services.segmentation_service as segmentation_service

UNAVAILABLE = RuntimeError(
    "503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently experiencing high demand. "
    "Spikes in demand are usually temporary. Please try again later.', 'status': 'UNAVAILABLE'}}"
)
INVALID = RuntimeError("400 INVALID_ARGUMENT. {'error': {'code': 400, 'status': 'INVALID_ARGUMENT'}}")
RATE_LIMIT = RuntimeError("429 RESOURCE_EXHAUSTED. Please retry in 7s.")

sleeps = []


class _Clock:
    @staticmethod
    def sleep(seconds):
        sleeps.append(seconds)


classify_v2.time = _Clock
segmentation_service.time = _Clock


class _Resp:
    def __init__(self, text):
        self.text = text


class ScriptedModel:
    """依序丟出例外或回傳內容。"""

    script = []
    calls = 0

    def __init__(self, *args, **kwargs):
        pass

    def generate_content(self, *args, **kwargs):
        ScriptedModel.calls += 1
        item = ScriptedModel.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return _Resp(item)


def run(script, fn):
    ScriptedModel.script = list(script)
    ScriptedModel.calls = 0
    sleeps.clear()
    try:
        return fn(), None
    except Exception as exc:  # noqa: BLE001
        return None, exc


gemini_client.GenerativeModel = ScriptedModel

print("========== 0. 錯誤判斷 ==========")
check("503 UNAVAILABLE 視為暫時性錯誤", gemini_client.is_transient_unavailable_error(UNAVAILABLE))
check("400 INVALID_ARGUMENT 不是暫時性錯誤", not gemini_client.is_transient_unavailable_error(INVALID))

print("\n========== 1. 批次分類：503 兩次後成功 ==========")
result, err = run(
    [UNAVAILABLE, UNAVAILABLE, "ok"],
    lambda: classify_v2._generate_with_retry(ScriptedModel(), "msg").text,
)
check("最後成功回傳", result == "ok" and err is None)
check("共呼叫 3 次", ScriptedModel.calls == 3)
check("依序等待 2、4 秒", sleeps == [2.0, 4.0])

print("\n========== 2. 拆分：503 一次後成功 ==========")
result, err = run(
    [UNAVAILABLE, json.dumps({"segments": ["內容很好，", "但時間太趕。"]}, ensure_ascii=False)],
    lambda: segmentation_service._call_gemini_segmentation("內容很好，但時間太趕。"),
)
check("拆分成功", result == ["內容很好，", "但時間太趕。"] and err is None)
check("等待 2 秒後重試", sleeps == [2.0])

print("\n========== 3. 503 持續發生：有上限 ==========")
result, err = run([UNAVAILABLE] * 5, lambda: classify_v2._generate_with_retry(ScriptedModel(), "msg"))
check("最後仍往上拋 503", err is UNAVAILABLE)
check("總共 4 次呼叫（1 + 3 次重試）", ScriptedModel.calls == 4)
check("等待 2、4、8 秒", sleeps == [2.0, 4.0, 8.0])
result, err = run([UNAVAILABLE] * 5, lambda: segmentation_service._call_gemini_segmentation("x"))
check("拆分同樣有上限（4 次呼叫）", err is UNAVAILABLE and ScriptedModel.calls == 4)

print("\n========== 4. 非暫時性錯誤不重試 ==========")
result, err = run([INVALID, "ok"], lambda: classify_v2._generate_with_retry(ScriptedModel(), "msg"))
check("400 直接往上拋、只呼叫 1 次、沒有等待", err is INVALID and ScriptedModel.calls == 1 and sleeps == [])

print("\n========== 5. 429 行為不變 ==========")
result, err = run([RATE_LIMIT, "ok"], lambda: classify_v2._generate_with_retry(ScriptedModel(), "msg").text)
check("429 照建議秒數（7+1）等待後成功", result == "ok" and sleeps == [8.0])

print("\n========== 6. 整體流程：503 後成功不會變成 failed ==========")
ScriptedModel.script = [
    UNAVAILABLE,
    json.dumps({"segments": ["希望增加教育訓練"]}, ensure_ascii=False),
    UNAVAILABLE,
    json.dumps({"classifications": [{
        "index": 0, "main_category": "M", "sub_category": "S", "secondary_sub_category": None,
        "reasoning": "r", "summary": "s", "confidence": 0.9,
    }]}, ensure_ascii=False),
]
sleeps.clear()
out = classify_v2.classify_response_multi_segment(
    "希望增加教育訓練", "prompt", "custom_topic",
    category_lookup=lambda sub: {"main_category": "M", "methodology": "m", "citation": "c"} if sub == "S" else None,
)
check("segmentation_status=completed", out["segmentation_status"] == "completed")
check("segment 沒有 failed", all(seg["status"] != "failed" for seg in out["segments"]))
check("拆分與分類各等待一次 2 秒", sleeps == [2.0, 2.0])

finish()
