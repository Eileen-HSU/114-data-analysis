#!/usr/bin/env python
"""
測試腳本：_build_aggregated_groups()（分類完成當下的即時彙整，供
Excel 上傳／問卷 /analyze 的回應與 /api/exports 使用）正確反映 Human
Review 結果。

背景：這個函式原本無條件讀 AI 原始欄位，不管 review_status 是什麼都
一樣處理，導致「不納入分析」（excluded）跟「採用候選」（modified 用
final_*）這兩個 Human Review 動作實際上對彙整結果沒有任何效果。

【產品定案】這裡不是 services/aggregation_service.py 那個嚴格只收
confirmed/modified 的 Report 產生管線，是「分類完成當下」要馬上顯示
給使用者看的即時彙整——pending_review（不論 needs_human_review 是
True 或 False）都跟 confirmed 一樣沿用 AI 原始欄位，不會被排除，也
不會有任何 auto-eligible 的特殊處理；只有 excluded 會被跳過、
modified 會改用 final_*。

涵蓋：
    1. review_status=excluded 的列完全不出現在彙整結果裡
    2. review_status=modified 的列使用 final_main_category /
       final_sub_category / final_reasoning，不是 AI 原始欄位
    3. review_status=confirmed 的列使用 AI 原始欄位
    4. review_status=pending_review 且 needs_human_review=True 的列
       仍然正常出現、使用 AI 原始欄位（不會被排除，不是
       auto-eligible，只是單純沒有被排除）
    5. review_status=pending_review 且 needs_human_review=False 的列
       同樣正常出現、使用 AI 原始欄位
    6. 混合以上多種 review_status 時，分組跟受試者片段合併都正確

執行方式：
    cd backend
    python3 tests/test_aggregated_groups_review_status.py
"""

import os
import sys
from types import SimpleNamespace

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

FAILED = []


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    if status == "FAIL":
        FAILED.append(label)
    print(f"[{status}] {label}")


from routes.classifications.classification import _build_aggregated_groups


def make_row(
    response_id, main_category, sub_category, reasoning, review_status,
    needs_human_review=False,
    final_main_category=None, final_sub_category=None, final_reasoning=None,
    text="意見內容",
):
    return SimpleNamespace(
        response_id=response_id,
        main_category=main_category,
        sub_category=sub_category,
        reasoning=reasoning,
        summary="summary",
        segment_start=None,
        segment_end=None,
        answer_text=text,
        review_status=review_status,
        needs_human_review=needs_human_review,
        final_main_category=final_main_category,
        final_sub_category=final_sub_category,
        final_reasoning=final_reasoning,
    )


# ═══════════════════════════════════════════════════════════════
# 測試 1：excluded 完全不出現在彙整結果裡
# ═══════════════════════════════════════════════════════════════
print("========== 測試 1：excluded 不進彙整 ==========")
rows_1 = [
    make_row(1, "部門合作", "B2 支援協作", "reasoning A", "excluded", text="受試者1的意見"),
    make_row(2, "部門合作", "B2 支援協作", "reasoning B", "pending_review", text="受試者2的意見"),
]
groups_1 = _build_aggregated_groups(rows_1, {1: 0, 2: 1}, question_type="career_and_feedback", id_field="response_id")
check("只有 1 組（excluded 那筆完全不算進去）", len(groups_1) == 1)
if groups_1:
    check("excluded 那位受試者不在 respondent_text 裡", "受試者1" not in groups_1[0]["respondent_text"])
    check("pending_review 那位受試者正常在裡面", "受試者2" in groups_1[0]["respondent_text"])


# ═══════════════════════════════════════════════════════════════
# 測試 2：modified 使用 final_*，不是 AI 原始欄位
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 2：modified 用 final_*，AI original 完全不使用 ==========")
rows_2 = [
    make_row(
        3, "部門合作", "B2 支援協作", "AI 原始 reasoning", "modified",
        final_main_category="工作表現的回饋及職涯發展",
        final_sub_category="A5 教育訓練",
        final_reasoning="人工修正後的 reasoning",
        text="受試者3的意見",
    ),
]
groups_2 = _build_aggregated_groups(rows_2, {3: 0}, question_type="career_and_feedback", id_field="response_id")
check("分組用的是 final_main_category（不是 AI 原始的「部門合作」）", len(groups_2) == 1 and groups_2[0]["main_category"] == "工作表現的回饋及職涯發展")
if groups_2:
    check("reasoning 用的是人工修正後的版本", "人工修正後的 reasoning" in groups_2[0]["aggregated_reasoning"] or "人工修正後的 reasoning" in str(groups_2[0]))


# ═══════════════════════════════════════════════════════════════
# 測試 3：confirmed 使用 AI 原始欄位
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 3：confirmed 用 AI 原始欄位 ==========")
rows_3 = [
    make_row(4, "主管領導", "A1 決策透明度", "AI reasoning", "confirmed", text="受試者4的意見"),
]
groups_3 = _build_aggregated_groups(rows_3, {4: 0}, question_type="leadership_and_dept", id_field="response_id")
check("confirmed 分組用 AI 原始的 main_category", len(groups_3) == 1 and groups_3[0]["main_category"] == "主管領導")


# ═══════════════════════════════════════════════════════════════
# 測試 4：pending_review + needs_human_review=True 仍正常出現（不排除、非 auto-eligible）
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 4：pending_review 且 needs_human_review=True 仍正常出現 ==========")
rows_4 = [
    make_row(5, "部門合作", "B2 支援協作", "AI reasoning", "pending_review", needs_human_review=True, text="受試者5的意見"),
]
groups_4 = _build_aggregated_groups(rows_4, {5: 0}, question_type="career_and_feedback", id_field="response_id")
check(
    "needs_human_review=True 的 pending_review 沒有被排除，仍用 AI 原始欄位分組",
    len(groups_4) == 1 and groups_4[0]["main_category"] == "部門合作",
)


# ═══════════════════════════════════════════════════════════════
# 測試 5：pending_review + needs_human_review=False 一樣正常出現（沒有特殊 auto-eligible 分支）
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 5：pending_review 且 needs_human_review=False 一樣正常出現 ==========")
rows_5 = [
    make_row(6, "部門合作", "B2 支援協作", "AI reasoning", "pending_review", needs_human_review=False, text="受試者6的意見"),
]
groups_5 = _build_aggregated_groups(rows_5, {6: 0}, question_type="career_and_feedback", id_field="response_id")
check(
    "needs_human_review=False 的 pending_review 一樣正常出現、用 AI 原始欄位（沒有跟 confirmed 或任何狀態做不同處理）",
    len(groups_5) == 1 and groups_5[0]["main_category"] == "部門合作",
)


# ═══════════════════════════════════════════════════════════════
# 測試 6：混合多種 review_status，分組與合併正確
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 6：混合多種 review_status ==========")
rows_6 = [
    make_row(10, "部門合作", "B2 支援協作", "r1", "confirmed", text="受試者A的意見"),
    make_row(11, "部門合作", "B2 支援協作", "r2", "pending_review", needs_human_review=True, text="受試者B的意見"),
    make_row(
        12, "部門合作", "B1 溝通與協調機制", "r3", "modified",
        final_main_category="部門合作", final_sub_category="B2 支援協作", final_reasoning="r3 modified",
        text="受試者C的意見",
    ),
    make_row(13, "部門合作", "B2 支援協作", "r4", "excluded", text="受試者D的意見"),
]
groups_6 = _build_aggregated_groups(
    rows_6, {10: 0, 11: 1, 12: 2, 13: 3}, question_type="career_and_feedback", id_field="response_id",
)
check("只有 1 組（B2 支援協作），因為 modified 的那筆 final_sub_category 也是 B2", len(groups_6) == 1)
if groups_6:
    text_blob = groups_6[0]["respondent_text"]
    check("受試者A（confirmed）在裡面", "受試者A" in text_blob)
    check("受試者B（pending_review, needs_human_review=True）在裡面", "受試者B" in text_blob)
    check("受試者C（modified，用 final_sub_category 正確合併進同一組）在裡面", "受試者C" in text_blob)
    check("受試者D（excluded）不在裡面", "受試者D" not in text_blob)


print("\n" + "=" * 50)
if FAILED:
    print(f"共 {len(FAILED)} 項測試失敗：")
    for f in FAILED:
        print("  -", f)
    sys.exit(1)
else:
    print("全部測試通過！")
