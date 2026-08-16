#!/usr/bin/env python
"""
測試腳本：驗證 privacy_service.py 的 PII 遮罩邏輯。

沿用專案既有的 test_*.py 風格（例如 test_survey.py、test_gemini.py）：
直接用 assert 驗證，不依賴 pytest。

執行方式：
    cd backend
    python3 test_privacy_service.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from services.privacy_service import mask_pii, PiiMaskingError

FAILED = []


def check(label, input_text, actual, expected):
    status = "PASS" if actual == expected else "FAIL"
    if status == "FAIL":
        FAILED.append(label)
    print(f"[{status}] {label}")
    print(f"       input   : {input_text!r}")
    print(f"       output  : {actual!r}")
    print(f"       expected: {expected!r}")


def check_true(label, condition):
    status = "PASS" if condition else "FAIL"
    if status == "FAIL":
        FAILED.append(label)
    print(f"[{status}] {label}")


print("========== Test 1：中文姓名 + Email ==========")
actual_input = "王小明的Email是abc@gmail.com"
check("Test1 姓名與 Email 都被遮罩", actual_input, mask_pii(actual_input), "【姓名】的Email是【EMAIL】")

print("\n========== Test 2：台灣手機 ==========")
actual_input = "可以打0912-345-678給我"
result = mask_pii(actual_input)
check_true("Test2 手機被遮罩、原始數字消失", "【手機號碼】" in result and "0912" not in result)

print("\n========== Test 3：台灣市內電話 ==========")
actual_input = "公司電話是02-2345-6789"
result = mask_pii(actual_input)
check_true("Test3 市話被遮罩、原始數字消失", "【電話】" in result and "2345" not in result)

print("\n========== Test 4：身分證字號（合法格式，checksum 需通過）==========")
actual_input = "我的身分證是A123456789"
result = mask_pii(actual_input)
check_true("Test4 合法身分證格式可以被辨識並遮罩", "【身分證字號】" in result and "A123456789" not in result)

print("\n========== Test 4b：身分證字號（格式對但 checksum 沒過，附近有「身分證」context → 仍應遮罩）==========")
# Privacy-first：checksum 沒過不代表「一定不是敏感資料」。這句話裡緊接著
# 出現「身分證」，代表使用者很可能就是在講身分證字號（例如打錯一碼），
# 即使 checksum 沒過也應該遮罩，避免把很可能是身分證字號的敏感資訊
# 原封不動送去 Gemini。
actual_input = "我的身分證是A111111111"
result = mask_pii(actual_input)
check_true(
    "Test4b checksum 沒過但有身分證 context，仍應遮罩",
    "【身分證字號】" in result and "A111111111" not in result,
)

print("\n========== Test 4c：checksum 錯誤，但附近有身分證 context（另一種寫法）→ 仍應遮罩 ==========")
actual_input = "身分證字號：B222222222，麻煩協助更新"
result = mask_pii(actual_input)
check_true(
    "Test4c checksum 沒過但有「身分證字號」context，仍應遮罩",
    "【身分證字號】" in result and "B222222222" not in result,
)

print("\n========== Test 4d：隨機英文字母＋9碼數字，checksum 錯且無身分證 context → 不應遮罩 ==========")
actual_input = "追蹤碼X999999999已經產生"
result = mask_pii(actual_input)
check_true(
    "Test4d checksum 沒過、也沒有身分證 context，不應被誤判成身分證",
    result == actual_input,
)

print("\n========== Test 5：一般詞彙不得被中文姓名 recognizer 誤遮罩 ==========")
actual_input = "希望主管改善教育訓練與職涯發展制度"
check("Test5 不得誤遮罩正常詞彙", actual_input, mask_pii(actual_input), actual_input)

print("\n========== Test 6：完整資料流情境（Gemini input vs DB answer_text）==========")
actual_input = "王小明覺得主管回饋不夠即時"
gemini_input = mask_pii(actual_input)
check("Test6 Gemini 應收到的 masked_text", actual_input, gemini_input, "【姓名】覺得主管回饋不夠即時")
# DB 端不會呼叫 mask_pii，answer_text 本來就是這個原始字串，這裡只是
# 明確驗證 mask_pii 不會「修改」傳入的原始字串本身（沒有 side effect）。
check_true("Test6 DB 應保留的 answer_text 不受影響", actual_input == "王小明覺得主管回饋不夠即時")

print("\n========== Test 7：姓氏開頭但不是姓名的 hard cases ==========")
hard_cases = [
    "林場管理是這次會議的重點",
    "高興的心情持續了一整天",
    "請提供更完整的解決方案方法",
    "陳列在架上的商品需要盤點",
    "這次活動的方向還沒確定",
    "馬路上的標線需要重新規劃",
]
for text in hard_cases:
    check(f"Test7 不應誤判「{text}」", text, mask_pii(text), text)

print("\n========== 額外：不同手機/市話格式 ==========")
for text, label_should_appear in [
    ("0912345678", "【手機號碼】"),
    ("0912 345 678", "【手機號碼】"),
    ("(02)23456789", "【電話】"),
    ("02 2345 6789", "【電話】"),
]:
    result = mask_pii(text)
    check_true(f"格式變化「{text}」應被遮罩為 {label_should_appear}", label_should_appear in result)

print("\n========== 額外：fail-closed 行為 ==========")
try:
    mask_pii(None)
    check_true("mask_pii(None) 應該要拋出例外", False)
except PiiMaskingError:
    check_true("mask_pii(None) 正確拋出 PiiMaskingError（fail-closed）", True)

try:
    mask_pii(12345)
    check_true("mask_pii(非 str) 應該要拋出例外", False)
except PiiMaskingError:
    check_true("mask_pii(非 str) 正確拋出 PiiMaskingError（fail-closed）", True)

print("\n========== 額外：空字串不應報錯，直接原樣回傳 ==========")
check("空字串輸入", "", mask_pii(""), "")

print("\n" + "=" * 50)
if FAILED:
    print(f"共 {len(FAILED)} 項測試失敗：")
    for f in FAILED:
        print("  -", f)
    sys.exit(1)
else:
    print("全部測試通過！")