#!/usr/bin/env python
"""備援模型：主要模型 503 / 429 時換另一個模型，不要卡在同一個模型上。

假的 client，不打真實 API。執行：cd backend && python3 tests/test_gemini_model_fallback.py
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.pop("GEMINI_FALLBACK_MODEL", None)

import services.gemini_client as gc  # noqa: E402

FAILED = []


def check(label, ok):
    print(("[PASS] " if ok else "[FAIL] ") + label)
    if not ok:
        FAILED.append(label)


class Resp:
    def __init__(self, text):
        self.text = text


class FakeClient:
    """behavior: {模型名稱: 例外或回應文字}；calls 記錄實際打了哪些模型"""
    def __init__(self, behavior):
        self.behavior = behavior
        self.calls = []
        self.models = self

    def generate_content(self, model, contents, config):
        self.calls.append(model)
        result = self.behavior[model]
        if isinstance(result, Exception):
            raise result
        return Resp(result)


class Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


def run(model_name, behavior):
    client = FakeClient(behavior)
    gc._create_client = lambda: client
    cap = Capture()
    log = logging.getLogger("services.gemini_client")
    log.addHandler(cap)
    log.setLevel(logging.DEBUG)
    try:
        out = gc.GenerativeModel(model_name).generate_content("hi")
        err = None
    except Exception as exc:  # noqa: BLE001
        out, err = None, exc
    log.removeHandler(cap)
    return client.calls, out, err, cap.records


E503 = RuntimeError("503 UNAVAILABLE. This model is currently experiencing high demand.")
E429 = RuntimeError("429 RESOURCE_EXHAUSTED. You exceeded your current quota")
E400 = RuntimeError("400 INVALID_ARGUMENT. bad request")

print("== 1. 主要模型 503 → 換備援模型成功 ==")
calls, out, err, logs = run("gemini-3.1-flash-lite", {"gemini-3.1-flash-lite": E503, "gemini-3.5-flash-lite": "ok-fallback"})
check("依序打主要、第一個備援模型（gemini-3.5-flash-lite）", calls == ["gemini-3.1-flash-lite", "gemini-3.5-flash-lite"])
check("拿到備援模型的回應", err is None and out.text == "ok-fallback")
check("備援成功時沒有 ERROR 紀錄（不會污染後台錯誤紀錄）", not any(r.levelno >= logging.ERROR for r in logs))

print("== 2. 主要模型 429 額度用完 → 換備援模型 ==")
calls, out, err, logs = run("gemini-3.1-flash-lite", {"gemini-3.1-flash-lite": E429, "gemini-3.5-flash-lite": "ok2"})
check("429 也會換備援", calls == ["gemini-3.1-flash-lite", "gemini-3.5-flash-lite"] and out.text == "ok2")

print("== 3. 兩個模型都失敗 → 拋出主要模型的原始錯誤，並記一筆 ERROR ==")
calls, out, err, logs = run("gemini-3.1-flash-lite", {"gemini-3.1-flash-lite": E429, "gemini-3.5-flash-lite": E503, "gemini-3.6-flash": E503, "gemini-3.8-flash": E503})
check("主要 + 三個備援模型都試過（依序）", calls == ["gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.8-flash"])
check("拋出的是主要模型的錯誤（呼叫端原本的 429 等待邏輯照舊）", err is E429)
check("有一筆 ERROR 紀錄", sum(1 for r in logs if r.levelno >= logging.ERROR) == 1)

print("== 4. 其他錯誤（參數錯誤）不換模型 ==")
calls, out, err, logs = run("gemini-3.1-flash-lite", {"gemini-3.1-flash-lite": E400, "gemini-3.5-flash-lite": "x"})
check("只打主要模型一次、錯誤原樣拋出", calls == ["gemini-3.1-flash-lite"] and err is E400)

print("== 5. 沒有備援的模型（AI 再確認用的較強模型）不換模型 ==")
calls, out, err, logs = run("gemini-3.5-flash", {"gemini-3.5-flash": E503})
check("較強模型失敗不會退回弱模型", calls == ["gemini-3.5-flash"] and err is E503)

print("== 5b. 第一個備援也不可用 → 接著試第二個備援 ==")
calls, out, err, logs = run("gemini-3.1-flash-lite", {"gemini-3.1-flash-lite": E503, "gemini-3.5-flash-lite": RuntimeError("404 NOT_FOUND model"), "gemini-3.6-flash": "third"})
check("第一個備援失敗後改用第二個", calls == ["gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-3.6-flash"] and out.text == "third")

print("== 6. 主要模型成功時不會打備援 ==")
calls, out, err, logs = run("gemini-3.1-flash-lite", {"gemini-3.1-flash-lite": "fine"})
check("只打一次", calls == ["gemini-3.1-flash-lite"] and out.text == "fine")

print("== 7. 環境變數 ==")
os.environ["GEMINI_FALLBACK_MODEL"] = ""
calls, out, err, logs = run("gemini-3.1-flash-lite", {"gemini-3.1-flash-lite": E503})
check("GEMINI_FALLBACK_MODEL 設成空字串 → 關閉備援，維持原行為", calls == ["gemini-3.1-flash-lite"] and err is E503)
os.environ["GEMINI_FALLBACK_MODEL"] = "gemini-x-custom"
calls, out, err, logs = run("models/gemini-3.1-flash-lite", {"gemini-3.1-flash-lite": E503, "gemini-x-custom": "custom"})
check("可指定其他備援模型（也相容 models/ 前綴）", calls == ["gemini-3.1-flash-lite", "gemini-x-custom"] and out.text == "custom")
os.environ.pop("GEMINI_FALLBACK_MODEL")

print("\n" + "=" * 50)
if FAILED:
    print(f"共 {len(FAILED)} 項失敗：", *FAILED, sep="\n  - ")
    sys.exit(1)
print("全部測試通過！")
