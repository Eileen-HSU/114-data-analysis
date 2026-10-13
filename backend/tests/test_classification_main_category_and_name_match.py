#!/usr/bin/env python
"""
驗證分類查表的兩項修正（全程 mock，不呼叫真實 AI）：
  1. AI 回的大類別和分類架構不符 -> 以架構為準、標記 main_category_mismatch、進人工審查（不自動通過）
  2. AI 回的子類別只差空白／全形半形／編號前綴 -> 視為既有類別（存標準名稱），不是新類別
  3. 真的不在清單 -> 仍是新類別（開放式）／methodology_not_found（封閉式）
  4. 正規化後有歧義 -> 不猜
執行：cd backend && JWT_SECRET_KEY=t python3 tests/test_classification_main_category_and_name_match.py
"""
import json
import os
import sys
from types import SimpleNamespace

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

FAILED = []


def check(label, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        FAILED.append(label)


import services.gemini_client as gc

_queue = []


class _R:
    def __init__(self, t):
        self.text = t


class _M:
    def __init__(self, *a, **k):
        pass

    def generate_content(self, c, **k):
        return _R(_queue.pop(0))


gc.GenerativeModel = _M
gc.configure = lambda **k: None

from services.classify_v2 import classify_response_multi_segment
from services.confidence_gate import evaluate_confidence_gate
from services.taxonomy_service import methodology_lookup_for_taxonomy_version, normalize_category_name


def cat(i, main, sub):
    return SimpleNamespace(category_id=i, main_category=main, sub_category=sub, methodology=f"m{i}", citation=f"c{i}")


version = SimpleNamespace(categories=[
    cat(1, "工作環境", "A1 工作與生活邊界"),
    cat(2, "制度", "B1 薪資福利"),
    cat(3, "制度", "B2 薪資"),     # 與 B1 正規化後不同（福利 vs 空）
    cat(4, "甲", "C1 溝通"),
    cat(5, "乙", "C2 溝通"),       # 與 C1 正規化後相同 -> 有歧義
])
lookup = methodology_lookup_for_taxonomy_version(version)


def run(main, sub, open_mode=True, confidence=0.9):
    os.environ["OPEN_CLASSIFICATION_ENABLED"] = "1" if open_mode else "0"
    _queue.clear()
    _queue.append(json.dumps({"segments": ["加班太多沒時間陪家人"]}, ensure_ascii=False))
    _queue.append(json.dumps({"classifications": [{
        "index": 0, "main_category": main, "sub_category": sub,
        "reasoning": "r", "summary": "s", "confidence": confidence}]}, ensure_ascii=False))
    seg = classify_response_multi_segment("加班太多沒時間陪家人", "P", "t", category_lookup=lookup)["segments"][0]
    return seg, evaluate_confidence_gate(seg)


seg, gate = run("工作環境", "A1 工作與生活邊界")
check("正確配對：completed、不進人工審查", seg["status"] == "completed" and gate == (False, None))

seg, gate = run("制度", "A1 工作與生活邊界")
check("大類別不符：改用架構的大類別", seg["main_category"] == "工作環境")
check("大類別不符：保留 AI 原本回的大類別", seg.get("ai_main_category") == "制度")
check("大類別不符：進人工審查（即使信心 0.9）", gate == (True, "main_category_mismatch"))

for label, sub in [("尾端空白", "A1 工作與生活邊界 "), ("少了編號前綴", "工作與生活邊界"), ("全形編號", "Ａ１　工作與生活邊界")]:
    seg, gate = run("工作環境", sub)
    check(f"{label}：視為既有類別、存標準名稱", seg["status"] == "completed" and seg["sub_category"] == "A1 工作與生活邊界")
    check(f"{label}：不進新類別候選、高信心不進人工審查", gate == (False, None))

seg, gate = run("工作環境", "完全不存在的類別")
check("真的不在清單（開放式）：仍是新類別", seg["status"] == "new_category" and gate == (True, "new_category_proposed"))
seg, gate = run("工作環境", "完全不存在的類別", open_mode=False)
check("真的不在清單（封閉式）：methodology_not_found", seg["status"] == "methodology_not_found")

seg, gate = run("甲", "溝通")
check("正規化後有兩個類別對得上：不猜，維持新類別", seg["status"] == "new_category")

check("正規化函式：NFKC／空白／前綴", normalize_category_name("Ａ１　工作 與生活邊界 ") == normalize_category_name("工作與生活邊界"))
check("低信心 + 正確配對仍是 low_confidence", run("工作環境", "A1 工作與生活邊界", confidence=0.5)[1] == (True, "low_confidence"))

print()
if FAILED:
    print(f"共 {len(FAILED)} 項失敗：", FAILED)
    sys.exit(1)
print("全部測試通過！")
