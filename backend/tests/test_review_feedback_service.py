#!/usr/bin/env python
"""
測試腳本：Human Review feedback loop（services/review_feedback_service.py）
以及它跟 services/classify_v2.py 的插入點（Gemini #2 批次分類的
system_instruction 組裝）。

涵蓋（對應本次需求文件的測試清單）：
    第一部分（services/review_feedback_service.py 純邏輯，用真實
    SQLite in-memory DB + 假的 mask_pii spy，不呼叫任何 Gemini）：
        1. confirmed 用 AI original 欄位
        2. modified 用 final_* 欄位
        3. pending_review 不取
        4. excluded 不取
        5. 不同 taxonomy_version_id 不互相污染
        6. taxonomy_version_id=None 回傳 []
        7. modified 優先、最多 5 筆，總數 <= 8（confirmed 補滿剩餘額度）
        8. segment_text 正確依 segment_start/segment_end 從 answer_text 擷取
        9. mask_pii 有被呼叫（且是用擷取出來的 segment_text 呼叫）
        10. PiiMaskingError 時該筆單獨 skip，不影響其餘範例
        11. examples=[] 時 build_review_feedback_prompt() 回傳空字串 ""

    第二部分（services/classify_v2.py，用假的
    services.gemini_client.GenerativeModel，不打真實 Gemini API；
    mock get_reviewed_examples / build_review_feedback_prompt，不碰
    DB）：
        12. _call_gemini_batch_classification() 組出的
            system_instruction 順序精確等於
            prompt_content + reviewed_examples_block + BATCH_OUTPUT_FORMAT_OVERRIDE
        13. taxonomy_version_id=None 時完全不呼叫
            review_feedback_service.get_reviewed_examples()，
            system_instruction 跟這個 feedback loop 功能加入之前逐字元
            相同（舊行為不變）

不依賴真實 google.genai 網路呼叫：GenerativeModel 全程被假物件取代，
只驗證「傳進去的 system_instruction 內容」，不會真的打 API。

執行方式：
    cd backend
    export JWT_SECRET_KEY=test-secret-key-for-testing-only
    python3 tests/test_review_feedback_service.py
"""

import sys
import os
import json

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

FAILED = []


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    if status == "FAIL":
        FAILED.append(label)
    print(f"[{status}] {label}")


# ═══════════════════════════════════════════════════════════════
# 共用：Flask app + SQLite in-memory，只建立 Response_Classification
# 這一張表（其餘欄位的 FK 在 SQLite 預設不啟用外鍵檢查，不需要真的
# 建 Survey_Response / Uploaded_Answer 表）。
# ═══════════════════════════════════════════════════════════════

from flask import Flask
from extensions import db
import models as m
from classification_models import (
    SOURCE_TYPE_SURVEY,
    REVIEW_STATUS_PENDING,
    REVIEW_STATUS_CONFIRMED,
    REVIEW_STATUS_MODIFIED,
    REVIEW_STATUS_EXCLUDED,
)

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
app.config["TESTING"] = True
db.init_app(app)

with app.app_context():
    db.metadata.create_all(bind=db.engine, tables=[m.Response_Classification.__table__])

_next_response_id = [1000]


def _fresh_response_id():
    _next_response_id[0] += 1
    return _next_response_id[0]


def make_row(
    answer_text,
    segment_start,
    segment_end,
    review_status=REVIEW_STATUS_CONFIRMED,
    taxonomy_version_id=10,
    main_category="AI_MAIN",
    sub_category="AI_SUB",
    secondary_sub_category="AI_SECONDARY_SUB",
    reasoning="AI_REASONING",
    final_main_category=None,
    final_sub_category=None,
    final_secondary_sub_category=None,
    final_reasoning=None,
):
    """建立一筆 Response_Classification 並寫進 DB，回傳這筆的
    classification_id。預設 AI original 欄位跟 final_* 欄位刻意給
    「一看就不同」的值，方便測試斷言到底是哪一組欄位被拿去當範例。
    """
    row = m.Response_Classification(
        response_id=_fresh_response_id(),
        source_type=SOURCE_TYPE_SURVEY,
        question_id="q1",
        answer_text=answer_text,
        segment_start=segment_start,
        segment_end=segment_end,
        main_category=main_category,
        sub_category=sub_category,
        secondary_sub_category=secondary_sub_category,
        reasoning=reasoning,
        final_main_category=final_main_category,
        final_sub_category=final_sub_category,
        final_secondary_sub_category=final_secondary_sub_category,
        final_reasoning=final_reasoning,
        status="completed",
        review_status=review_status,
        taxonomy_version_id=taxonomy_version_id,
    )
    db.session.add(row)
    db.session.commit()
    return row.classification_id


import services.review_feedback_service as rfs


# ── mask_pii spy：記錄呼叫過的文字，並可設定哪些文字要 raise ──────
_mask_calls = []
_mask_should_fail_on = set()


def _fake_mask_pii(text):
    _mask_calls.append(text)
    if text in _mask_should_fail_on:
        raise rfs.PiiMaskingError(f"simulated masking failure for {text!r}")
    return f"MASKED[{text}]"


def reset_mask_spy(fail_on=()):
    _mask_calls.clear()
    _mask_should_fail_on.clear()
    _mask_should_fail_on.update(fail_on)


rfs.mask_pii = _fake_mask_pii


with app.app_context():

    print("========== 1. confirmed 用 AI original 欄位 ==========")
    reset_mask_spy()
    cid = make_row(
        "王小明的完整回答內容", 0, 4,  # segment_text = "王小明的"
        review_status=REVIEW_STATUS_CONFIRMED,
        taxonomy_version_id=10,
        main_category="ORIG_MAIN", sub_category="ORIG_SUB",
        secondary_sub_category="ORIG_SEC", reasoning="ORIG_REASON",
        final_main_category="SHOULD_NOT_BE_USED", final_sub_category="SHOULD_NOT_BE_USED",
    )
    examples = rfs.get_reviewed_examples(10)
    ex = next(e for e in examples if e["classification_id"] == cid)
    check("confirmed：main_category 用 AI original", ex["main_category"] == "ORIG_MAIN")
    check("confirmed：sub_category 用 AI original", ex["sub_category"] == "ORIG_SUB")
    check("confirmed：secondary_sub_category 用 AI original", ex["secondary_sub_category"] == "ORIG_SEC")
    check("confirmed：reasoning 用 AI original", ex["reasoning"] == "ORIG_REASON")
    check("confirmed：完全沒有混入 final_* 的值", "SHOULD_NOT_BE_USED" not in ex.values())


    print("\n========== 2. modified 用 final_* 欄位 ==========")
    reset_mask_spy()
    cid = make_row(
        "小華覺得部門合作要改善", 0, 2,  # segment_text = "小華"
        review_status=REVIEW_STATUS_MODIFIED,
        taxonomy_version_id=10,
        main_category="SHOULD_NOT_BE_USED_MAIN", sub_category="SHOULD_NOT_BE_USED_SUB",
        secondary_sub_category="SHOULD_NOT_BE_USED_SEC", reasoning="SHOULD_NOT_BE_USED_REASON",
        final_main_category="FINAL_MAIN", final_sub_category="FINAL_SUB",
        final_secondary_sub_category="FINAL_SEC", final_reasoning="FINAL_REASON",
    )
    examples = rfs.get_reviewed_examples(10)
    ex = next(e for e in examples if e["classification_id"] == cid)
    check("modified：main_category 用 final_main_category", ex["main_category"] == "FINAL_MAIN")
    check("modified：sub_category 用 final_sub_category", ex["sub_category"] == "FINAL_SUB")
    check("modified：secondary_sub_category 用 final_secondary_sub_category", ex["secondary_sub_category"] == "FINAL_SEC")
    check("modified：reasoning 用 final_reasoning", ex["reasoning"] == "FINAL_REASON")
    check(
        "modified：完全沒有混入 AI original 的值",
        "SHOULD_NOT_BE_USED_MAIN" not in ex.values() and "SHOULD_NOT_BE_USED_SUB" not in ex.values(),
    )


    print("\n========== 3. pending_review 不取 ==========")
    reset_mask_spy()
    taxonomy_v = 111
    cid_pending = make_row("這筆還沒人審核", 0, 3, review_status=REVIEW_STATUS_PENDING, taxonomy_version_id=taxonomy_v)
    examples = rfs.get_reviewed_examples(taxonomy_v)
    check("pending_review 不會出現在範例裡", all(e["classification_id"] != cid_pending for e in examples))
    check("pending_review：這個版本目前沒有任何合法範例，結果為空", examples == [])


    print("\n========== 4. excluded 不取 ==========")
    reset_mask_spy()
    taxonomy_v = 112
    cid_excluded = make_row("這筆被人工排除", 0, 3, review_status=REVIEW_STATUS_EXCLUDED, taxonomy_version_id=taxonomy_v)
    examples = rfs.get_reviewed_examples(taxonomy_v)
    check("excluded 不會出現在範例裡", all(e["classification_id"] != cid_excluded for e in examples))
    check("excluded：這個版本目前沒有任何合法範例，結果為空", examples == [])


    print("\n========== 5. 不同 taxonomy_version_id 不互相污染 ==========")
    reset_mask_spy()
    v_a, v_b = 201, 202
    cid_a = make_row("版本A的內容片段一二三四五", 0, 3, review_status=REVIEW_STATUS_CONFIRMED, taxonomy_version_id=v_a)
    cid_b = make_row("版本B的內容片段一二三四五", 0, 3, review_status=REVIEW_STATUS_CONFIRMED, taxonomy_version_id=v_b)
    examples_a = rfs.get_reviewed_examples(v_a)
    examples_b = rfs.get_reviewed_examples(v_b)
    check("查版本 A 只拿到版本 A 自己的範例", {e["classification_id"] for e in examples_a} == {cid_a})
    check("查版本 B 只拿到版本 B 自己的範例", {e["classification_id"] for e in examples_b} == {cid_b})
    check("版本 A 的結果裡完全沒有版本 B 的 id", cid_b not in {e["classification_id"] for e in examples_a})


    print("\n========== 6. taxonomy_version_id=None 回傳 [] ==========")
    reset_mask_spy()
    check("taxonomy_version_id=None 直接回傳空清單", rfs.get_reviewed_examples(None) == [])
    check("taxonomy_version_id=None 完全不會呼叫 mask_pii（沒有查詢、沒有候選）", _mask_calls == [])

    # NULL legacy 資料：taxonomy_version_id 欄位本身是 NULL 的舊資料，
    # 不應該被任何一次查詢撈出來（不只是查 None 的情境）。
    reset_mask_spy()
    v_legacy_check = 203
    cid_legacy = make_row(
        "舊資料沒有 taxonomy 版本", 0, 3,
        review_status=REVIEW_STATUS_CONFIRMED, taxonomy_version_id=None,
    )
    cid_normal = make_row(
        "新資料有 taxonomy 版本", 0, 3,
        review_status=REVIEW_STATUS_CONFIRMED, taxonomy_version_id=v_legacy_check,
    )
    examples_legacy_scope = rfs.get_reviewed_examples(v_legacy_check)
    check(
        "taxonomy_version_id=NULL 的舊資料不會被任何查詢誤撈出來",
        cid_legacy not in {e["classification_id"] for e in examples_legacy_scope},
    )
    check(
        "同一批裡 taxonomy_version_id 有值的新資料仍正常被撈到",
        cid_normal in {e["classification_id"] for e in examples_legacy_scope},
    )


    print("\n========== 7. modified 優先最多 5 筆，總數 <= 8 ==========")
    reset_mask_spy()
    v_priority = 301
    modified_ids = [
        make_row(f"modified 範例 {i}", 0, 2, review_status=REVIEW_STATUS_MODIFIED,
                 taxonomy_version_id=v_priority, final_main_category=f"FM{i}", final_sub_category=f"FS{i}")
        for i in range(6)  # 6 筆 modified，超過上限 5
    ]
    confirmed_ids = [
        make_row(f"confirmed 範例 {i}", 0, 2, review_status=REVIEW_STATUS_CONFIRMED, taxonomy_version_id=v_priority)
        for i in range(10)  # 10 筆 confirmed，遠超剩餘額度
    ]
    examples = rfs.get_reviewed_examples(v_priority)
    result_ids = [e["classification_id"] for e in examples]
    modified_in_result = [i for i in result_ids if i in modified_ids]
    confirmed_in_result = [i for i in result_ids if i in confirmed_ids]
    check("modified 最多只取 5 筆（即使有 6 筆可用）", len(modified_in_result) == 5)
    check("confirmed 補滿剩餘額度（8 - 5 = 3 筆）", len(confirmed_in_result) == 3)
    check("總數不超過 8 筆", len(examples) <= 8)
    check("總數剛好 8 筆（modified 5 + confirmed 3）", len(examples) == 8)

    # 反過來：modified 不足 5 筆時，confirmed 要補到總數 8（不會卡在
    # 「modified 不足就少給」）。
    v_priority2 = 302
    modified_ids2 = [
        make_row(f"modified2 範例 {i}", 0, 2, review_status=REVIEW_STATUS_MODIFIED,
                 taxonomy_version_id=v_priority2, final_main_category=f"FM2_{i}", final_sub_category=f"FS2_{i}")
        for i in range(2)  # 只有 2 筆 modified
    ]
    confirmed_ids2 = [
        make_row(f"confirmed2 範例 {i}", 0, 2, review_status=REVIEW_STATUS_CONFIRMED, taxonomy_version_id=v_priority2)
        for i in range(10)
    ]
    examples2 = rfs.get_reviewed_examples(v_priority2)
    result_ids2 = [e["classification_id"] for e in examples2]
    modified_in_result2 = [i for i in result_ids2 if i in modified_ids2]
    confirmed_in_result2 = [i for i in result_ids2 if i in confirmed_ids2]
    check("modified 不足 5 筆時，全部 2 筆都入選", len(modified_in_result2) == 2)
    check("confirmed 補滿到總數 8（6 筆）", len(confirmed_in_result2) == 6)
    check("總數仍是 8", len(examples2) == 8)

    # limit 參數本身也要生效（不是寫死 8）。
    examples_small_limit = rfs.get_reviewed_examples(v_priority, limit=3)
    check("limit=3 時最多只回傳 3 筆", len(examples_small_limit) <= 3)


    print("\n========== 8. segment_text 正確依 segment_start/segment_end 擷取 ==========")
    reset_mask_spy()
    v_seg = 401
    full_text = "0123456789ABCDEFGHIJ"
    cid = make_row(full_text, 3, 8, review_status=REVIEW_STATUS_CONFIRMED, taxonomy_version_id=v_seg)
    examples = rfs.get_reviewed_examples(v_seg)
    ex = next(e for e in examples if e["classification_id"] == cid)
    expected_segment = full_text[3:8]  # "34567"
    check(
        "segment_text 精確等於 answer_text[segment_start:segment_end]",
        ex["segment_text"] == f"MASKED[{expected_segment}]",
    )
    check("擷取出來的原文片段內容正確（未被多切或少切）", expected_segment == "34567")


    print("\n========== 9. mask_pii 有被呼叫 ==========")
    reset_mask_spy()
    v_mask = 501
    full_text = "測試遮罩呼叫的完整回答內容"
    make_row(full_text, 0, 6, review_status=REVIEW_STATUS_CONFIRMED, taxonomy_version_id=v_mask)
    rfs.get_reviewed_examples(v_mask)
    check("mask_pii 至少被呼叫一次", len(_mask_calls) >= 1)
    check("mask_pii 是用切出來的 segment_text（而不是整段 answer_text）呼叫", full_text[0:6] in _mask_calls)
    check("mask_pii 沒有被整段未切割的 answer_text 呼叫", full_text not in _mask_calls)


    print("\n========== 10. PiiMaskingError 單筆 skip，不影響整批 ==========")
    v_skip = 601
    ok_text_1 = "第一筆正常內容片段"
    fail_text = "第二筆會遮罩失敗的片段"
    ok_text_2 = "第三筆正常內容片段"
    cid_ok1 = make_row(ok_text_1, 0, 5, review_status=REVIEW_STATUS_CONFIRMED, taxonomy_version_id=v_skip)
    cid_fail = make_row(fail_text, 0, 6, review_status=REVIEW_STATUS_CONFIRMED, taxonomy_version_id=v_skip)
    cid_ok2 = make_row(ok_text_2, 0, 5, review_status=REVIEW_STATUS_CONFIRMED, taxonomy_version_id=v_skip)
    reset_mask_spy(fail_on={fail_text[0:6]})
    examples = rfs.get_reviewed_examples(v_skip)
    result_ids = {e["classification_id"] for e in examples}
    check("遮罩失敗的那一筆被排除", cid_fail not in result_ids)
    check("遮罩成功的其他筆仍然正常回傳（第一筆）", cid_ok1 in result_ids)
    check("遮罩成功的其他筆仍然正常回傳（第三筆）", cid_ok2 in result_ids)
    check("查詢本身不會因為單筆遮罩失敗而整批拋出例外", True)  # 走到這裡代表沒有 raise


    print("\n========== 11. examples=[] 時 build_review_feedback_prompt() 回傳空字串 ==========")
    check("空清單回傳空字串", rfs.build_review_feedback_prompt([]) == "")
    check("空字串型別正確", isinstance(rfs.build_review_feedback_prompt([]), str))

    non_empty_block = rfs.build_review_feedback_prompt([{
        "classification_id": 1, "review_status": "confirmed",
        "segment_text": "測試片段", "main_category": "M", "sub_category": "S",
        "secondary_sub_category": None, "reasoning": "R",
    }])
    check("非空清單時回傳非空字串", non_empty_block != "")
    check("非空清單時內容包含範例的 segment_text", "測試片段" in non_empty_block)


print(f"\n第一部分（review_feedback_service）目前累計失敗：{len(FAILED)} 項")


# ═══════════════════════════════════════════════════════════════
# 第二部分：services/classify_v2.py 的插入點
# 用假的 services.gemini_client.GenerativeModel（不是 sys.modules
# 層級去偽造 google 套件本身，避免跟 gemini_client.py 目前使用的
# 新版 google-genai SDK import 方式衝突），只攔截「送進去的
# system_instruction / contents」，不會真的打 Gemini API。
# ═══════════════════════════════════════════════════════════════

_call_log = []
_queued_responses = []


class _FakeResp:
    def __init__(self, text):
        self.text = text


class _FakeGenerativeModel:
    def __init__(self, model_name=None, system_instruction=None, **kwargs):
        self.model_name = model_name
        self.system_instruction = system_instruction

    def generate_content(self, contents, **kwargs):
        _call_log.append({"system_instruction": self.system_instruction, "contents": contents})
        return _FakeResp(_queued_responses.pop(0))


def queue_json(obj):
    _queued_responses.append(json.dumps(obj, ensure_ascii=False))


import services.gemini_client as gemini_client_module
gemini_client_module.GenerativeModel = _FakeGenerativeModel

import services.classify_v2 as cv2
import services.review_feedback_service as rfs2  # 同一個模組物件，monkeypatch 這裡即可影響 cv2 內的 lazy import


PROMPT_CONTENT = cv2.DEFAULT_PROMPT_LEADERSHIP
ANSWER_TEXT = "測試回答內容，沒有PII"


def _run_classify(taxonomy_version_id):
    """跑一次完整的 classify_response_multi_segment()（固定 2 次
    Gemini 呼叫：Gemini #1 拆分 + Gemini #2 批次分類），回傳
    (result, batch_call) 供斷言。batch_call 是 _call_log 裡對應
    Gemini #2 的那一筆（system_instruction / contents）。
    """
    _call_log.clear()
    _queued_responses.clear()
    queue_json({"segments": [ANSWER_TEXT]})
    queue_json({"classifications": [{
        "index": 0, "main_category": "主管領導", "sub_category": "A2 回饋與溝通",
        "secondary_sub_category": None, "reasoning": "r", "summary": "s", "confidence": "high",
    }]})
    result = cv2.classify_response_multi_segment(
        ANSWER_TEXT, PROMPT_CONTENT, "leadership_and_dept",
        taxonomy_version_id=taxonomy_version_id,
    )
    check("固定呼叫 2 次 Gemini（不因為加了 feedback loop 而變動）", len(_call_log) == 2)
    return result, _call_log[1]


print("\n========== 12. system_instruction 順序：prompt_content -> reviewed_examples_block -> BATCH_OUTPUT_FORMAT_OVERRIDE ==========")

_FAKE_EXAMPLES = [{"classification_id": 1, "review_status": "confirmed"}]
_FAKE_BLOCK = "\n\n【FAKE_REVIEWED_EXAMPLES_BLOCK_MARKER】這是假的已審核範例區塊\n"

_get_examples_calls = []


def _fake_get_reviewed_examples(taxonomy_version_id, limit=8):
    _get_examples_calls.append((taxonomy_version_id, limit))
    return _FAKE_EXAMPLES


def _fake_build_review_feedback_prompt(examples):
    check("build_review_feedback_prompt 收到的是 get_reviewed_examples 回傳的同一份 examples", examples is _FAKE_EXAMPLES)
    return _FAKE_BLOCK


rfs2.get_reviewed_examples = _fake_get_reviewed_examples
rfs2.build_review_feedback_prompt = _fake_build_review_feedback_prompt
_get_examples_calls.clear()

result, batch_call = _run_classify(taxonomy_version_id=777)

n = 1  # 這次只有 1 個 segment
expected_si = (
    PROMPT_CONTENT
    + _FAKE_BLOCK
    + cv2.BATCH_OUTPUT_FORMAT_OVERRIDE.format(n=n, n_minus_1=n - 1)
)
si = batch_call["system_instruction"]

check("有傳 taxonomy_version_id 時，get_reviewed_examples 被呼叫一次", len(_get_examples_calls) == 1)
check("get_reviewed_examples 收到正確的 taxonomy_version_id", _get_examples_calls[0][0] == 777)
check(
    "system_instruction 精確等於 prompt_content + reviewed_examples_block + BATCH_OUTPUT_FORMAT_OVERRIDE",
    si == expected_si,
)
idx_prompt = si.find(PROMPT_CONTENT)
idx_block = si.find("FAKE_REVIEWED_EXAMPLES_BLOCK_MARKER")
idx_override = si.find("本次輸出格式覆蓋")
check("prompt_content 在最前面（index 0）", idx_prompt == 0)
check("reviewed_examples_block 排在 prompt_content 之後", idx_block > idx_prompt)
check("BATCH_OUTPUT_FORMAT_OVERRIDE 排在 reviewed_examples_block 之後（維持最後）", idx_override > idx_block)
check("這次分類本身仍正常成功（feedback loop 不影響分類結果本身）", result["segments"][0]["status"] == "completed")


print("\n========== 13. taxonomy_version_id=None 時完全不查 feedback service，舊行為不變 ==========")

_get_examples_calls.clear()
result_none, batch_call_none = _run_classify(taxonomy_version_id=None)

check("taxonomy_version_id=None 時，get_reviewed_examples 完全不會被呼叫", len(_get_examples_calls) == 0)

si_none = batch_call_none["system_instruction"]
expected_si_old = PROMPT_CONTENT + cv2.BATCH_OUTPUT_FORMAT_OVERRIDE.format(n=n, n_minus_1=n - 1)
check(
    "taxonomy_version_id=None 時 system_instruction 逐字元等於「沒有這個功能時」的舊行為",
    si_none == expected_si_old,
)
check("system_instruction 不包含任何 reviewed_examples_block 的痕跡", "FAKE_REVIEWED_EXAMPLES_BLOCK_MARKER" not in si_none)
check("這次分類本身仍正常成功", result_none["segments"][0]["status"] == "completed")

# 額外：不傳 taxonomy_version_id 參數（用預設值）跟明確傳 None 效果
# 必須完全一致——確認預設值真的是 None，不是意外變成其他值。
_get_examples_calls.clear()
_call_log.clear()
_queued_responses.clear()
queue_json({"segments": [ANSWER_TEXT]})
queue_json({"classifications": [{
    "index": 0, "main_category": "主管領導", "sub_category": "A2 回饋與溝通",
    "secondary_sub_category": None, "reasoning": "r", "summary": "s", "confidence": "high",
}]})
result_default = cv2.classify_response_multi_segment(ANSWER_TEXT, PROMPT_CONTENT, "leadership_and_dept")
check("不傳 taxonomy_version_id（用預設值）時，同樣完全不呼叫 get_reviewed_examples", len(_get_examples_calls) == 0)
check("不傳 taxonomy_version_id 時 system_instruction 跟明確傳 None 完全相同", _call_log[1]["system_instruction"] == si_none)


print("\n" + "=" * 50)
if FAILED:
    print(f"共 {len(FAILED)} 項測試失敗：")
    for label in FAILED:
        print(f"  - {label}")
    sys.exit(1)
else:
    print("全部測試通過！")