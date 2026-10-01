#!/usr/bin/env python
"""
問卷重新分析「只重新分類失敗片段」（classify_existing_segments）也要帶入
同一個 taxonomy version 的人工審核範例，且範例要經過 PII 遮罩；新列記錄的
taxonomy version 必須是這次實際用來分類的版本。

情境：
    R1 partial_failed：A confirmed + B failed -> 只重新分類 B（retry_segments）
    RX（同題、已完成）：人工 modified，原文含姓名 -> 應成為範例（遮罩後）
    舊版本 v1 的 modified 列 -> 不可被當成範例

執行方式：
    cd backend
    python3 tests/test_retry_segments_feedback.py
"""

import os

from admin_test_support import GEMINI_CALLS, GEMINI_QUEUE, check, create_app, finish, q, seed_people, seed_topic, user_header
import models as m
from extensions import db, taiwan_now

os.environ.pop("OPEN_CLASSIFICATION_ENABLED", None)
app = create_app()
client = app.test_client()

FEEDBACK_MARKER = "已通過人工審核的分類範例"
R1_TEXT = "薪水三年沒有調整。希望公司多開教育訓練課程"
RX_TEXT = "王小明說主管很少給回饋"
OLD_TEXT = "舊版本的人工修正範例"

with app.app_context():
    seed_people()
    old_vid = seed_topic("career", categories=[("職涯發展", "A1 教育訓練", "m", "c")], status="archived")
    vid = seed_topic("career", categories=[
        ("職涯發展", "A1 教育訓練", "m", "c"), ("職涯發展", "A2 升遷制度", "m", "c"), ("薪酬福利", "C1 薪資", "m", "c"),
    ], version_number=2)
    tpl = m.Survey_Template(user_id=1, title="回饋", access_code="FBK01", question_json={"items": [
        {"id": "q1", "type": "short", "title": "建議", "question_type": "career"},
    ]})
    db.session.add(tpl)
    db.session.flush()
    r1 = m.Survey_Response(template_id=tpl.template_id, answer_json={"answers": {"q1": R1_TEXT}})
    rx = m.Survey_Response(template_id=tpl.template_id, answer_json={"answers": {"q1": RX_TEXT}})
    db.session.add_all([r1, rx])
    db.session.flush()
    now = taiwan_now()

    def row(resp, text, part, main, sub, version, **extra):
        start = text.index(part)
        r = m.Response_Classification(
            response_id=resp.response_id, source_type="survey", question_id="q1", answer_text=text,
            segment_start=start, segment_end=start + len(part), main_category=main, sub_category=sub,
            reasoning="AI 理由", summary="s", taxonomy_version_id=version, confidence=0.9, **extra,
        )
        db.session.add(r)
        db.session.flush()
        return r.classification_id

    db.session.add(m.Response_Segmentation_Status(response_id=r1.response_id, question_id="q1", source_type="survey",
                                                  segmentation_status="partial_failed", error_detail="503"))
    row(r1, R1_TEXT, "薪水三年沒有調整", "薪酬福利", "C1 薪資", vid, status="completed", review_status="confirmed",
        reviewed_by_admin_id=1, reviewed_at=now)
    FAILED_ID = row(r1, R1_TEXT, "希望公司多開教育訓練課程", None, None, old_vid, status="failed", review_status="pending_review")

    db.session.add(m.Response_Segmentation_Status(response_id=rx.response_id, question_id="q1", source_type="survey",
                                                  segmentation_status="completed"))
    row(rx, RX_TEXT, RX_TEXT, "職涯發展", "A1 教育訓練", vid, status="completed", review_status="modified",
        final_main_category="職涯發展", final_sub_category="A2 升遷制度", final_reasoning="人工：其實在講回饋與升遷",
        reviewed_by_admin_id=1, reviewed_at=now)
    # 另一個（舊）版本的人工修正：不可以混進這一版的範例
    other = m.Survey_Response(template_id=tpl.template_id, answer_json={"answers": {"q2": OLD_TEXT}})
    db.session.add(other)
    db.session.flush()
    db.session.add(m.Response_Classification(
        response_id=other.response_id, source_type="survey", question_id="q2", answer_text=OLD_TEXT,
        segment_start=0, segment_end=len(OLD_TEXT), main_category="職涯發展", sub_category="A1 教育訓練",
        status="completed", review_status="modified", final_main_category="職涯發展", final_sub_category="A1 教育訓練",
        taxonomy_version_id=old_vid, reviewed_by_admin_id=1, reviewed_at=now,
    ))
    db.session.commit()

GEMINI_QUEUE.clear()
GEMINI_CALLS.clear()
q({"classifications": [{"index": 0, "main_category": "職涯發展", "sub_category": "A1 教育訓練",
                         "secondary_sub_category": None, "reasoning": "新理由", "summary": "s", "confidence": 0.9}]})
resp = client.post("/api/surveys/FBK01/analyze", headers=user_header(1))
body = resp.get_json()
check("analyze 200", resp.status_code == 200)
check("走 retry_segments（只重新分類失敗片段）", body["diagnostic"]["per_question"]["q1"]["segment_retries"] == 1)
classify_calls = [c for c in GEMINI_CALLS if "量化前彙整助手" not in (c["system_instruction"] or "")]
check("只有 1 次分類呼叫（不重新拆分）", len(classify_calls) == 1)
instruction = classify_calls[0]["system_instruction"] if classify_calls else ""
check("片段重試的分類 prompt 帶入人工審核範例", FEEDBACK_MARKER in instruction)
check("範例使用人工定案的類別（final_*）", "A2 升遷制度" in instruction and "人工：其實在講回饋與升遷" in instruction)
check("範例經過 PII 遮罩（不含原始姓名）", "王小明" not in instruction and "說主管很少給回饋" in instruction)
check("只用同一個 taxonomy version 的範例", OLD_TEXT not in instruction)

with app.app_context():
    old = db.session.get(m.Response_Classification, FAILED_ID)
    new = m.Response_Classification.query.filter_by(response_id=old.response_id, attempt_no=2).one()
    check("失敗片段被取代（superseded，保留歷史）", old.status == "superseded")
    check("新列記錄實際使用的 taxonomy version", new.taxonomy_version_id == vid and new.sub_category == "A1 教育訓練")
    confirmed = m.Response_Classification.query.filter_by(
        response_id=old.response_id, review_status="confirmed", auto_confirmed=False,
    ).one()
    check("人工 confirmed 片段不動", confirmed.status == "completed" and confirmed.review_status == "confirmed" and confirmed.attempt_no in (None, 1))
    check("重試成功的新片段（高信心）自動通過", new.review_status == "confirmed" and new.auto_confirmed is True)

finish()
