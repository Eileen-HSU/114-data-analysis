#!/usr/bin/env python
"""
測試腳本：驗證 services/confidence_gate.evaluate_confidence_gate()。

涵蓋（對應需求討論的 11 個純函式案例）：
    1. 高信心、資料完整 -> (False, None)
    2. confidence < 0.75 -> low_confidence
    3. confidence == 0.75（等於門檻，不觸發）
    4. confidence 缺失（None）-> invalid_confidence
    5. confidence 是字串殘留（型別錯誤）-> invalid_confidence
    6. confidence 超出上界 -> invalid_confidence
    7. confidence 超出下界 -> invalid_confidence
    8. confidence 是 bool（陷阱）-> invalid_confidence
    9. status=methodology_not_found，即使 confidence 很高 -> 仍要 flag
    10. main_category 缺失 -> classification_incomplete（優先序最高）
    11. 同時符合多個原因 -> 依優先序回傳單一原因

執行方式：
    cd backend
    python3 test_confidence_gate.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

FAILED = []


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    if status == "FAIL":
        FAILED.append(label)
    print(f"[{status}] {label}")


from services.confidence_gate import (
    evaluate_confidence_gate,
    CONFIDENCE_THRESHOLD,
    REASON_CLASSIFICATION_INCOMPLETE,
    REASON_METHODOLOGY_NOT_FOUND,
    REASON_INVALID_CONFIDENCE,
    REASON_LOW_CONFIDENCE,
)


def base_segment(**overrides):
    seg = {
        "main_category": "M",
        "sub_category": "S",
        "status": "completed",
        "confidence": 0.9,
    }
    seg.update(overrides)
    return seg


print("========== evaluate_confidence_gate() 純函式測試 ==========")

check("CONFIDENCE_THRESHOLD 是 0.75", CONFIDENCE_THRESHOLD == 0.75)

# 1. 高信心、資料完整
needs, reason = evaluate_confidence_gate(base_segment(confidence=0.9))
check("高信心 + 資料完整 -> (False, None)", needs is False and reason is None)

# 2. confidence < threshold
needs, reason = evaluate_confidence_gate(base_segment(confidence=0.5))
check("confidence=0.5（<0.75） -> (True, low_confidence)", needs is True and reason == REASON_LOW_CONFIDENCE)

# 3. confidence == threshold（等於門檻，不觸發）
needs, reason = evaluate_confidence_gate(base_segment(confidence=0.75))
check("confidence=0.75（等於門檻） -> (False, None)", needs is False and reason is None)

# 4. confidence 缺失
needs, reason = evaluate_confidence_gate(base_segment(confidence=None))
check("confidence=None -> (True, invalid_confidence)", needs is True and reason == REASON_INVALID_CONFIDENCE)

# 5. confidence 是字串殘留
needs, reason = evaluate_confidence_gate(base_segment(confidence="high"))
check('confidence="high"（型別錯誤） -> (True, invalid_confidence)', needs is True and reason == REASON_INVALID_CONFIDENCE)

# 6. confidence 超出上界
needs, reason = evaluate_confidence_gate(base_segment(confidence=1.5))
check("confidence=1.5（超出上界） -> (True, invalid_confidence)", needs is True and reason == REASON_INVALID_CONFIDENCE)

# 7. confidence 超出下界
needs, reason = evaluate_confidence_gate(base_segment(confidence=-0.1))
check("confidence=-0.1（超出下界） -> (True, invalid_confidence)", needs is True and reason == REASON_INVALID_CONFIDENCE)

# 8. confidence 是 bool 陷阱
needs, reason = evaluate_confidence_gate(base_segment(confidence=True))
check("confidence=True（bool 陷阱） -> (True, invalid_confidence)", needs is True and reason == REASON_INVALID_CONFIDENCE)

# 9. methodology_not_found，即使 confidence 很高
needs, reason = evaluate_confidence_gate(base_segment(status="methodology_not_found", confidence=0.99))
check(
    "status=methodology_not_found + confidence=0.99 -> 仍要 flag (True, methodology_not_found)",
    needs is True and reason == REASON_METHODOLOGY_NOT_FOUND,
)

# 10. main_category 缺失（優先序最高）
needs, reason = evaluate_confidence_gate(base_segment(main_category=None))
check("main_category=None -> (True, classification_incomplete)", needs is True and reason == REASON_CLASSIFICATION_INCOMPLETE)

needs, reason = evaluate_confidence_gate(base_segment(sub_category=""))
check("sub_category=''（空字串） -> (True, classification_incomplete)", needs is True and reason == REASON_CLASSIFICATION_INCOMPLETE)

# 11. 同時符合多個原因 -> 依優先序回傳單一原因
needs, reason = evaluate_confidence_gate(base_segment(main_category=None, status="methodology_not_found", confidence="bad"))
check(
    "main_category 缺失 + methodology_not_found + invalid confidence 同時成立 -> 回傳優先序最高的 classification_incomplete",
    needs is True and reason == REASON_CLASSIFICATION_INCOMPLETE,
)

needs, reason = evaluate_confidence_gate(base_segment(status="methodology_not_found", confidence="bad"))
check(
    "methodology_not_found + invalid confidence 同時成立（main/sub 完整） -> 回傳優先序較高的 methodology_not_found",
    needs is True and reason == REASON_METHODOLOGY_NOT_FOUND,
)

needs, reason = evaluate_confidence_gate(base_segment(confidence="bad"))
check(
    "invalid confidence 單獨成立 -> invalid_confidence（不是 low_confidence）",
    needs is True and reason == REASON_INVALID_CONFIDENCE,
)

print("\n" + "=" * 50)
if FAILED:
    print(f"共 {len(FAILED)} 項測試失敗：")
    for f in FAILED:
        print("  -", f)
    sys.exit(1)
else:
    print("全部測試通過！")
