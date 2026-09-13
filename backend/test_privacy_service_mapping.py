#!/usr/bin/env python
"""
測試腳本：驗證 privacy_service.py 的 mask_pii_with_mapping()（位置對照功能）

執行方式：
    cd backend
    python3 test_privacy_service_mapping.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from services.privacy_service import mask_pii_with_mapping, PlaceholderBoundaryError

FAILED = []


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    if status == "FAIL":
        FAILED.append(label)
    print(f"[{status}] {label}")


print("========== mask_pii() 行為不受影響（回歸測試）==========")
from services.privacy_service import mask_pii
check(
    "mask_pii() 既有行為不變",
    mask_pii("王小明覺得主管回饋不夠即時") == "【姓名】覺得主管回饋不夠即時",
)

print("\n========== 基本情境：找出片段並換算回原文 ==========")
original = "王小明覺得主管很願意聽取意見，但工作量太大，希望可以增加人力，我的信箱是abc@gmail.com"
masked, pmap = mask_pii_with_mapping(original)
print(f"masked: {masked!r}")

seg1 = "主管很願意聽取意見"
s = masked.index(seg1)
e = s + len(seg1)
orig_s, orig_e = pmap.to_original_range(s, e)
check("片段 1 換算回原文正確", original[orig_s:orig_e] == seg1)

seg2 = "工作量太大，希望可以增加人力"
s2 = masked.index(seg2)
e2 = s2 + len(seg2)
orig_s2, orig_e2 = pmap.to_original_range(s2, e2)
check("片段 2 換算回原文正確", original[orig_s2:orig_e2] == seg2)

print("\n========== 片段完整包含遮罩標籤 ==========")
seg3 = "【姓名】覺得主管很願意聽取意見"
s3 = masked.index(seg3)
e3 = s3 + len(seg3)
orig_s3, orig_e3 = pmap.to_original_range(s3, e3)
check(
    "片段包含完整標籤時換算正確",
    original[orig_s3:orig_e3] == "王小明覺得主管很願意聽取意見",
)

print("\n========== 相鄰兩個 PII 被同一個片段涵蓋 ==========")
original4 = "陳怡君A123456789王小明abc@gmail.com"
masked4, pmap4 = mask_pii_with_mapping(original4)
seg4 = "【身分證字號】【姓名】"
s4 = masked4.index(seg4)
e4 = s4 + len(seg4)
orig_s4, orig_e4 = pmap4.to_original_range(s4, e4)
check(
    "相鄰 PII 換算正確（含 replacement 區塊邊界長度差異）",
    original4[orig_s4:orig_e4] == "A123456789王小明",
)

print("\n========== 切在標籤中間必須被拒絕 ==========")
original5 = "王小明覺得好"
masked5, pmap5 = mask_pii_with_mapping(original5)
try:
    pmap5.to_original_range(1, 3)
    check("切在標籤中間應該拋出例外", False)
except PlaceholderBoundaryError:
    check("切在標籤中間正確拋出 PlaceholderBoundaryError", True)

print("\n========== 邊界情況 ==========")
check("完全沒有 PII 時 masked == 原文", mask_pii_with_mapping("主管很願意聽取意見")[0] == "主管很願意聽取意見")

masked6, pmap6 = mask_pii_with_mapping("王小明覺得很好")
os6, oe6 = pmap6.to_original_range(0, len(masked6))
check("PII 在開頭，完整範圍還原正確", "王小明覺得很好"[os6:oe6] == "王小明覺得很好")

masked7, pmap7 = mask_pii_with_mapping("請聯絡我0912345678")
os7, oe7 = pmap7.to_original_range(0, len(masked7))
check("PII 在結尾，完整範圍還原正確", "請聯絡我0912345678"[os7:oe7] == "請聯絡我0912345678")

masked8, pmap8 = mask_pii_with_mapping("abc@gmail.com")
os8, oe8 = pmap8.to_original_range(0, len(masked8))
check("整份文字都是 PII，完整範圍還原正確", "abc@gmail.com"[os8:oe8] == "abc@gmail.com")

masked9, pmap9 = mask_pii_with_mapping("")
check("空字串輸入正常處理", masked9 == "")

print("\n========== 依序切分多個片段，拼回去要等於完整原文 ==========")
original10 = "王小明覺得主管很願意聽取意見，但工作量太大，希望增加人力，信箱是abc@gmail.com，謝謝"
masked10, pmap10 = mask_pii_with_mapping(original10)
boundaries = [(0, 6), (6, 15), (15, 29), (29, len(masked10))]
reconstructed = ""
for s, e in boundaries:
    os_, oe_ = pmap10.to_original_range(s, e)
    reconstructed += original10[os_:oe_]
check("依序片段重建結果等於完整原文", reconstructed == original10)

print("\n" + "=" * 50)
if FAILED:
    print(f"共 {len(FAILED)} 項測試失敗：")
    for f in FAILED:
        print("  -", f)
    sys.exit(1)
else:
    print("全部測試通過！")