#!/usr/bin/env python
"""
測試腳本：驗證 Confidence Gate 在 production persistence 路徑
（routes/classifications/classification.py 的 _persist_segmentation_result()）
的實際落地行為。

這裡直接單元測試 _persist_segmentation_result()（純函式，只
db.session.add()，不呼叫 commit()），用手動組出的
classify_response_multi_segment() 風格 result dict 當輸入，涵蓋：

    1. 一則回答兩個 segment，一個高信心一個低信心 -> 各自獨立寫入
       對應的 needs_human_review，互不影響
    2. methodology_not_found 的 segment -> needs_human_review=True，
       不受 confidence 高低影響
    3. 正常高信心分類 -> needs_human_review=False，
       review_flag_reason=None，confidence 正確存為 float
    4. confidence 型別異常（字串殘留）-> 不會讓 INSERT 失敗，
       DB 裡的 confidence 欄位存 NULL，但 needs_human_review 仍正確
       標記為 True / invalid_confidence
    5. 人工確認後（review_status 變成 confirmed），confidence /
       needs_human_review / review_flag_reason 三個欄位不會被清除

執行方式：
    cd backend
    python3 test_confidence_gate_persistence.py
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


from flask import Flask
from extensions import db
import models as m
from routes.classifications.classification import _persist_segmentation_result

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
app.config["TESTING"] = True
db.init_app(app)

with app.app_context():
    tables = [
        m.Survey_Template.__table__,
        m.Survey_Response.__table__,
        m.Response_Classification.__table__,
        m.Response_Segmentation_Status.__table__,
    ]
    db.metadata.create_all(bind=db.engine, tables=tables)

    template = m.Survey_Template(title="t", access_code="ABCDE", question_json={"items": []})
    db.session.add(template)
    db.session.commit()
    survey_response = m.Survey_Response(template_id=template.template_id, answer_json={"answers": {}})
    db.session.add(survey_response)
    db.session.commit()
    response_id = survey_response.response_id


def make_segment(**overrides):
    seg = {
        "orig_start": 0, "orig_end": 5,
        "main_category": "M", "sub_category": "S",
        "secondary_sub_category": None, "reasoning": "r", "summary": "s",
        "methodology": "meth", "citation": "cite",
        "secondary_methodology": None, "secondary_citation": None,
        "status": "completed", "error_detail": None,
        "confidence": 0.9,
    }
    seg.update(overrides)
    return seg


print("========== 測試 1：同一回答內多個 segment 各自獨立判斷 ==========")

with app.app_context():
    result = {
        "segmentation_status": "completed",
        "segmentation_error_detail": None,
        "segments": [
            make_segment(orig_start=0, orig_end=5, confidence=0.9),
            make_segment(orig_start=5, orig_end=10, confidence=0.3),
        ],
    }
    _, rows = _persist_segmentation_result(
        result, source_type="survey", answer_text="測試回答內容ＡＢ",
        question_id="q1", response_id=response_id,
    )
    db.session.commit()

    check("高信心 segment：confidence 正確存為 0.9", rows[0].confidence == 0.9)
    check("高信心 segment：needs_human_review=False", rows[0].needs_human_review is False)
    check("高信心 segment：review_flag_reason=None", rows[0].review_flag_reason is None)

    check("低信心 segment：confidence 正確存為 0.3", rows[1].confidence == 0.3)
    check("低信心 segment：needs_human_review=True", rows[1].needs_human_review is True)
    check("低信心 segment：review_flag_reason=low_confidence", rows[1].review_flag_reason == "low_confidence")

    check("兩個 segment 互不影響", rows[0].needs_human_review is False and rows[1].needs_human_review is True)


print("\n========== 測試 2：methodology_not_found 不受 confidence 影響 ==========")

with app.app_context():
    result = {
        "segmentation_status": "completed",
        "segmentation_error_detail": None,
        "segments": [make_segment(status="methodology_not_found", confidence=0.99, sub_category="不存在的子類別")],
    }
    _, rows = _persist_segmentation_result(
        result, source_type="survey", answer_text="測試",
        question_id="q2", response_id=response_id,
    )
    db.session.commit()
    check("methodology_not_found + 高信心 -> needs_human_review=True", rows[0].needs_human_review is True)
    check("review_flag_reason=methodology_not_found", rows[0].review_flag_reason == "methodology_not_found")
    check("confidence 仍正確存下來（0.99）", rows[0].confidence == 0.99)


print("\n========== 測試 3：正常高信心分類 ==========")

with app.app_context():
    result = {
        "segmentation_status": "completed",
        "segmentation_error_detail": None,
        "segments": [make_segment(confidence=0.88)],
    }
    _, rows = _persist_segmentation_result(
        result, source_type="survey", answer_text="測試",
        question_id="q3", response_id=response_id,
    )
    db.session.commit()
    check("confidence 正確存為 float 0.88", rows[0].confidence == 0.88 and isinstance(rows[0].confidence, float))
    check("needs_human_review=False", rows[0].needs_human_review is False)
    check("review_flag_reason=None", rows[0].review_flag_reason is None)


print("\n========== 測試 4：confidence 型別異常時的安全寫入 ==========")

with app.app_context():
    result = {
        "segmentation_status": "completed",
        "segmentation_error_detail": None,
        "segments": [make_segment(confidence="high")],
    }
    _, rows = _persist_segmentation_result(
        result, source_type="survey", answer_text="測試",
        question_id="q4", response_id=response_id,
    )
    db.session.commit()
    check("confidence 型別異常時，DB 欄位安全存為 NULL", rows[0].confidence is None)
    check("confidence 型別異常仍正確標記 needs_human_review=True", rows[0].needs_human_review is True)
    check("review_flag_reason=invalid_confidence", rows[0].review_flag_reason == "invalid_confidence")


print("\n========== 測試 5：人工確認後三個欄位保留不變 ==========")

with app.app_context():
    result = {
        "segmentation_status": "completed",
        "segmentation_error_detail": None,
        "segments": [make_segment(confidence=0.4)],
    }
    _, rows = _persist_segmentation_result(
        result, source_type="survey", answer_text="測試",
        question_id="q5", response_id=response_id,
    )
    db.session.commit()
    classification_id = rows[0].classification_id

    row = m.Response_Classification.query.get(classification_id)
    row.review_status = "confirmed"
    db.session.commit()

    row_after = m.Response_Classification.query.get(classification_id)
    check("review_status 已變成 confirmed", row_after.review_status == "confirmed")
    check("confidence 沒有被清除（仍是 0.4）", row_after.confidence == 0.4)
    check("needs_human_review 沒有被清除（仍是 True）", row_after.needs_human_review is True)
    check("review_flag_reason 沒有被清除（仍是 low_confidence）", row_after.review_flag_reason == "low_confidence")


print("\n" + "=" * 50)
if FAILED:
    print(f"共 {len(FAILED)} 項測試失敗：")
    for f in FAILED:
        print("  -", f)
    sys.exit(1)
else:
    print("全部測試通過！")
