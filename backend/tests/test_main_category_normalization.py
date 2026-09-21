#!/usr/bin/env python
"""
測試腳本：main_category normalization（修正同一個大類別被拆成多組的
問題）。

背景：實際發現同一個 main_category 在 Response_Classification 裡至少
以三種不同字串寫法存在：

    1. "工作表現的回饋及職涯發展"          （乾淨版本）
    2. "工作表現的回饋及職涯發展 "         （尾端多一個空白）
    3. "大類別：工作表現的回饋及職涯發展"  （Gemini 把 prompt 參考清單
                                          裡的「大類別：」前綴一起吐
                                          回來——classify_v2.py／
                                          taxonomy_service.py 組 prompt
                                          時，可用類別清單本來就是用
                                          「大類別：{name}」這個格式
                                          條列給 Gemini 參考，Gemini
                                          在少數回應裡沒有把前綴拆掉，
                                          直接整段回填進 JSON 的
                                          main_category 欄位）

三種字串在人眼看起來「都是同一個大類別」，但拿去當 dict key 分組會
變成三組，也會讓「大類別」欄位在 Excel/Word/Chat 上重複出現好幾次。

涵蓋範圍：
    Part A - normalize_main_category() 單元測試
    Part B - _build_aggregated_groups()：三種 raw 寫法必須合併成 1 組，
             且輸出的 main_category 是 canonical 值
    Part C - _persist_segmentation_result()：新寫入的 Response_Classification
             一律套用 normalize，之後不會再產生新的髒資料

執行方式：
    cd backend
    python3 test_main_category_normalization.py
"""

import os
import sys
from types import SimpleNamespace

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only")
sys.path.insert(0, os.path.dirname(__file__))

FAILED = []


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    if status == "FAIL":
        FAILED.append(label)
    print(f"[{status}] {label}")


from routes.classifications.classification import (
    normalize_main_category,
    _build_aggregated_groups,
    _persist_segmentation_result,
)

# ═══════════════════════════════════════════════════════════════
# 實際發現造成分組的三種 raw main_category
# ═══════════════════════════════════════════════════════════════
RAW_VARIANTS = [
    "工作表現的回饋及職涯發展",
    "工作表現的回饋及職涯發展 ",
    "大類別：工作表現的回饋及職涯發展",
]
CANONICAL = "工作表現的回饋及職涯發展"

print("========== 實際發現的三種 raw main_category ==========")
for raw in RAW_VARIANTS:
    print(f"  raw={raw!r}  ->  normalize_main_category(raw)={normalize_main_category(raw)!r}")


# ═══════════════════════════════════════════════════════════════
# Part A：normalize_main_category() 單元測試
# ═══════════════════════════════════════════════════════════════
print("\n========== Part A：normalize_main_category() ==========")

for raw in RAW_VARIANTS:
    check(f"raw={raw!r} 正規化後等於 canonical 值", normalize_main_category(raw) == CANONICAL)

check("None -> 空字串（跟既有 `main_category or \"\"` 行為相容）", normalize_main_category(None) == "")
check("空字串 -> 空字串", normalize_main_category("") == "")
check(
    "全形冒號「：」跟半形冒號「:」的前綴都會被移除",
    normalize_main_category("大類別:工作表現的回饋及職涯發展") == CANONICAL
    and normalize_main_category("大類別：工作表現的回饋及職涯發展") == CANONICAL,
)
check(
    "換行、tab 這類空白字元會被壓成單一空白（不是被整個移除，避免中間有意義的分詞黏在一起）",
    normalize_main_category("工作表現的回饋及\n職涯發展") == "工作表現的回饋及 職涯發展"
    and normalize_main_category("工作表現的回饋及\t\t職涯發展") == "工作表現的回饋及 職涯發展",
)
check(
    "前綴後面還帶空白時，收尾的 strip 會清掉殘留的前導空白",
    normalize_main_category("大類別：  工作表現的回饋及職涯發展") == CANONICAL,
)
check(
    "NFKC 正規化：全形英數字會轉成半形（例如全形驚嘆號、全形字母），不影響中文本身",
    normalize_main_category("ＯＫＲ執行進度") == "OKR執行進度",
)
check("不是「大類別」開頭的正常字串不會被誤刪內容", normalize_main_category("主管領導與部門合作") == "主管領導與部門合作")
check(
    "「大類別」三個字如果是內容本身的一部分（沒有接冒號）不會被誤判成前綴而刪掉",
    normalize_main_category("大類別命名原則討論") == "大類別命名原則討論",
)


# ═══════════════════════════════════════════════════════════════
# Part B：_build_aggregated_groups() —— 三種寫法必須合併成 1 組
# ═══════════════════════════════════════════════════════════════
print("\n========== Part B：_build_aggregated_groups() 分組 regression ==========")


def make_row(main_category, sub_category, response_id, text="意見內容"):
    return SimpleNamespace(
        main_category=main_category,
        sub_category=sub_category,
        segment_start=None,
        segment_end=None,
        answer_text=text,
        response_id=response_id,
        reasoning="reasoning",
        summary="summary",
    )


# 模擬「舊 DB 裡已經存在的髒資料」：同一個大類別、同一個子類別，但
# main_category 是三種不同的字串寫法，分別來自不同受試者的回答。
dirty_rows = [
    make_row(RAW_VARIANTS[0], "A1 職涯規劃", response_id=1, text="受試者1的意見"),
    make_row(RAW_VARIANTS[1], "A1 職涯規劃", response_id=2, text="受試者2的意見"),
    make_row(RAW_VARIANTS[2], "A1 職涯規劃", response_id=3, text="受試者3的意見"),
]
id_to_row_index = {1: 0, 2: 1, 3: 2}

groups = _build_aggregated_groups(dirty_rows, id_to_row_index, question_type="career_and_feedback", id_field="response_id")

check("舊 DB 裡三種不同寫法的髒資料，合併後只產生 1 個 main_category 分組", len(groups) == 1)
if groups:
    check("分組輸出的 main_category 是 canonical 值（不是三種寫法的任何一種原始寫法）", groups[0]["main_category"] == CANONICAL)
    check(
        "三筆資料都被正確合併進同一組（respondent_text 裡三位受試者都在）",
        all(f"受試者{i}" in groups[0]["respondent_text"] for i in (1, 2, 3)),
    )

print("\n--- B2：不同大類別仍然正確分開，不會被 normalization 誤合併 ---")
distinct_rows = [
    make_row("主管領導", "B1 溝通", response_id=10, text="A"),
    make_row("部門合作", "C1 協作", response_id=11, text="B"),
]
distinct_groups = _build_aggregated_groups(distinct_rows, {10: 0, 11: 1}, question_type="leadership_and_dept", id_field="response_id")
check("語意不同的兩個大類別仍然是 2 組，normalization 不會過度合併", len(distinct_groups) == 2)


# ═══════════════════════════════════════════════════════════════
# Part C：_persist_segmentation_result() —— 新寫入前也套用 normalization
# ═══════════════════════════════════════════════════════════════
print("\n========== Part C：_persist_segmentation_result() 寫入前 normalization ==========")

from extensions import db
import models as m
from flask import Flask
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.ext.compiler import compiles


@compiles(MEDIUMTEXT, "sqlite")
def _compile_mediumtext_sqlite(element, compiler, **kw):
    return "TEXT"


app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
app.config["TESTING"] = True
db.init_app(app)

with app.app_context():
    db.metadata.create_all(
        bind=db.engine,
        tables=[m.Response_Classification.__table__, m.Response_Segmentation_Status.__table__],
    )

    for i, raw_main_category in enumerate(RAW_VARIANTS, start=1):
        result = {
            "segmentation_status": "completed",
            "segmentation_error_detail": None,
            "segments": [
                {
                    "reasoning": "r",
                    "status": "completed",
                    "error_detail": None,
                    "orig_start": 0,
                    "orig_end": 2,
                    "main_category": raw_main_category,
                    "sub_category": "A1 職涯規劃",
                    "secondary_sub_category": None,
                    "summary": "s",
                    "methodology": "m",
                    "citation": "c",
                    "secondary_methodology": None,
                    "secondary_citation": None,
                    "confidence": "high",
                }
            ],
        }
        _persist_segmentation_result(
            result,
            source_type="survey",
            answer_text="意見內容",
            question_id=f"q_persist_{i}",
            response_id=100 + i,
        )
    db.session.commit()

    persisted_rows = m.Response_Classification.query.filter(
        m.Response_Classification.question_id.like("q_persist_%")
    ).all()
    persisted_main_categories = {row.main_category for row in persisted_rows}

    check("三筆分別用三種不同 raw 寫法寫入，DB 裡實際只存在 1 種 main_category 字串", len(persisted_main_categories) == 1)
    check("DB 裡存的就是 canonical 值，不是三種寫法的任何一種原始寫法", persisted_main_categories == {CANONICAL})


# ═══════════════════════════════════════════════════════════════
# 總結
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試總結 ==========")
if FAILED:
    print(f"共有 {len(FAILED)} 項測試失敗：")
    for label in FAILED:
        print(f"  - {label}")
    sys.exit(1)
else:
    print("全部測試通過！")
