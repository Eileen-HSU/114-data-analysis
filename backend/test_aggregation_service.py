#!/usr/bin/env python
"""
測試腳本：Aggregation Readiness + Aggregation（Phase 4）。

涵蓋需求文件第二十七節測試項目 13~22：
    13. pending_review 不納入
    14. excluded 不納入
    15. confirmed 使用 AI original
    16. modified 使用 final
    17. primary + secondary 都會 aggregation
    18. same primary/secondary 不 duplicate
    19. 同 response 多 segment 同 category：response_count=1, segment_count>1
    20. Survey 不會跟別的 Survey 混
    21. upload batch 不會跟別的 batch 混
    22. Survey / upload 不混

執行方式：
    cd backend
    python3 test_aggregation_service.py
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
from services.aggregation_readiness_service import get_readiness
from services.aggregation_service import build_aggregation
from services.effective_classification_service import (
    get_effective_classification, EffectiveClassificationError,
)

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
app.config["TESTING"] = True
db.init_app(app)

with app.app_context():
    tables = [
        m.User.__table__,
        m.Survey_Template.__table__,
        m.Survey_Response.__table__,
        m.Response_Classification.__table__,
        m.Uploaded_Answer.__table__,
    ]
    db.metadata.create_all(bind=db.engine, tables=tables)

    db.session.add(m.User(user_id=1, user_name="owner", email="owner@example.com", password_hash="x"))
    db.session.commit()

    # ── Survey A：主要測試場景 ──
    template_a = m.Survey_Template(
        title="Survey A", access_code="AAAAA", user_id=1,
        question_json={"items": [
            {"id": "q1", "type": "short", "title": "t", "question_type": "leadership_and_dept"},
        ]},
    )
    db.session.add(template_a)
    db.session.commit()
    template_a_id = template_a.template_id

    # r1：同一份回答拆成 2 個 segment，都落在同一個 group（B2 支援協作）
    r1 = m.Survey_Response(template_id=template_a_id, answer_json={"answers": {"q1": "希望增加人力，也希望多補位"}})
    db.session.add(r1)
    db.session.commit()
    r1_id = r1.response_id

    rc1a = m.Response_Classification(
        response_id=r1_id, source_type="survey", question_id="q1",
        answer_text="希望增加人力，也希望多補位", segment_start=0, segment_end=6,
        main_category="部門合作", sub_category="B2 支援協作",
        reasoning="reasoning 1a", summary="s", methodology="互惠與責任承擔分析", citation="cite-b2",
        status="completed", review_status="confirmed",
    )
    rc1b = m.Response_Classification(
        response_id=r1_id, source_type="survey", question_id="q1",
        answer_text="希望增加人力，也希望多補位", segment_start=7, segment_end=14,
        main_category="部門合作", sub_category="B2 支援協作",
        reasoning="reasoning 1b", summary="s", methodology="互惠與責任承擔分析", citation="cite-b2",
        status="completed", review_status="confirmed",
    )
    db.session.add_all([rc1a, rc1b])

    # r2：primary=A2 回饋與溝通, secondary=B2 支援協作（不同 response，也要進 B2 群組）
    r2 = m.Survey_Response(template_id=template_a_id, answer_json={"answers": {"q1": "主管應多給回饋，也要注意部門支援"}})
    db.session.add(r2)
    db.session.commit()
    r2_id = r2.response_id

    rc2 = m.Response_Classification(
        response_id=r2_id, source_type="survey", question_id="q1",
        answer_text="主管應多給回饋，也要注意部門支援", segment_start=0, segment_end=16,
        main_category="主管領導", sub_category="A2 回饋與溝通",
        secondary_main_category="部門合作", secondary_sub_category="B2 支援協作",
        reasoning="reasoning 2", summary="s",
        methodology="互動與溝通需求分析", citation="cite-a2",
        secondary_methodology="互惠與責任承擔分析", secondary_citation="cite-b2",
        status="completed", review_status="confirmed",
    )
    db.session.add(rc2)

    # r3：modified，AI original 是 B1，final 是 B2（驗證 modified 用 final 不用 original）
    r3 = m.Survey_Response(template_id=template_a_id, answer_json={"answers": {"q1": "溝通不太順暢"}})
    db.session.add(r3)
    db.session.commit()
    r3_id = r3.response_id

    rc3 = m.Response_Classification(
        response_id=r3_id, source_type="survey", question_id="q1",
        answer_text="溝通不太順暢", segment_start=0, segment_end=6,
        main_category="部門合作", sub_category="B1 溝通與協調機制",
        reasoning="ai original reasoning", summary="s",
        methodology="流程瓶頸分析", citation="cite-b1",
        status="completed", review_status="modified",
        final_main_category="部門合作", final_sub_category="B2 支援協作",
        final_reasoning="human confirmed: 其實是支援不足",
    )
    db.session.add(rc3)

    # r4：pending_review，不應該出現在 aggregation 或 eligible
    r4 = m.Survey_Response(template_id=template_a_id, answer_json={"answers": {"q1": "還沒審核"}})
    db.session.add(r4)
    db.session.commit()
    rc4 = m.Response_Classification(
        response_id=r4.response_id, source_type="survey", question_id="q1",
        answer_text="還沒審核", segment_start=0, segment_end=4,
        main_category="部門合作", sub_category="B2 支援協作",
        status="completed", review_status="pending_review",
    )
    db.session.add(rc4)

    # r5：excluded，不應該出現在 aggregation 或 eligible
    r5 = m.Survey_Response(template_id=template_a_id, answer_json={"answers": {"q1": "已排除"}})
    db.session.add(r5)
    db.session.commit()
    rc5 = m.Response_Classification(
        response_id=r5.response_id, source_type="survey", question_id="q1",
        answer_text="已排除", segment_start=0, segment_end=3,
        main_category="部門合作", sub_category="B2 支援協作",
        status="completed", review_status="excluded",
    )
    db.session.add(rc5)
    db.session.commit()

    # ── Survey B：驗證不同 survey 不會混 ──
    template_b = m.Survey_Template(
        title="Survey B", access_code="BBBBB", user_id=1,
        question_json={"items": [
            {"id": "q1", "type": "short", "title": "t", "question_type": "leadership_and_dept"},
        ]},
    )
    db.session.add(template_b)
    db.session.commit()
    template_b_id = template_b.template_id

    rb = m.Survey_Response(template_id=template_b_id, answer_json={"answers": {"q1": "Survey B 的意見"}})
    db.session.add(rb)
    db.session.commit()
    rc_b = m.Response_Classification(
        response_id=rb.response_id, source_type="survey", question_id="q1",
        answer_text="Survey B 的意見", segment_start=0, segment_end=6,
        main_category="部門合作", sub_category="B2 支援協作",
        reasoning="b", summary="s", methodology="互惠與責任承擔分析", citation="cite-b2",
        status="completed", review_status="confirmed",
    )
    db.session.add(rc_b)
    db.session.commit()

    # ── Upload batch X / Y：驗證 upload 之間、以及跟 survey 不會混 ──
    ua_x = m.Uploaded_Answer(
        upload_batch_id="batch-X", user_id=1, source_column="意見", row_index=0,
        answer_text="Upload batch X 的意見", question_type="career_and_feedback",
    )
    db.session.add(ua_x)
    db.session.commit()
    rc_x = m.Response_Classification(
        upload_batch_id="batch-X", uploaded_answer_id=ua_x.id,
        source_type="user_upload", question_id="意見_row0",
        answer_text="Upload batch X 的意見", segment_start=0, segment_end=6,
        main_category="工作表現的回饋及職涯發展", sub_category="A5 教育訓練",
        reasoning="x", summary="s", methodology="知識賦能與趨勢接軌分析", citation="cite-a5",
        status="completed", review_status="confirmed",
    )
    db.session.add(rc_x)

    ua_y = m.Uploaded_Answer(
        upload_batch_id="batch-Y", user_id=1, source_column="意見", row_index=0,
        answer_text="Upload batch Y 的意見", question_type="career_and_feedback",
    )
    db.session.add(ua_y)
    db.session.commit()
    rc_y = m.Response_Classification(
        upload_batch_id="batch-Y", uploaded_answer_id=ua_y.id,
        source_type="user_upload", question_id="意見_row0",
        answer_text="Upload batch Y 的意見", segment_start=0, segment_end=6,
        main_category="工作表現的回饋及職涯發展", sub_category="A5 教育訓練",
        reasoning="y", summary="s", methodology="知識賦能與趨勢接軌分析", citation="cite-a5",
        status="completed", review_status="confirmed",
    )
    db.session.add(rc_y)
    db.session.commit()

    rc1a_id, rc3_id, rc5_id = rc1a.classification_id, rc3.classification_id, rc5.classification_id
    r4_id, r5_id, rb_id = r4.response_id, r5.response_id, rb.response_id


# ═══════════════════════════════════════════════════════════════
# 測試：Readiness（Survey A：3 confirmed + 1 modified + 1 pending + 1 excluded = total 6）
# ═══════════════════════════════════════════════════════════════
print("========== Readiness：Survey A ==========")
with app.app_context():
    readiness_a = get_readiness("survey", template_id=template_a_id)
check("total 為 6", readiness_a["total"] == 6)
check("confirmed 為 3（rc1a, rc1b, rc2）", readiness_a["confirmed"] == 3)
check("modified 為 1（rc3）", readiness_a["modified"] == 1)
check("pending_review 為 1（rc4）", readiness_a["pending_review"] == 1)
check("excluded 為 1（rc5）", readiness_a["excluded"] == 1)
check("eligible 為 4（confirmed+modified）", readiness_a["eligible"] == 4)
check("has_pending 為 True", readiness_a["has_pending"] is True)
check("can_generate 為 True（eligible>0）", readiness_a["can_generate"] is True)


# ═══════════════════════════════════════════════════════════════
# 測試 15/16：get_effective_classification 直接單元測試
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 15/16：effective classification ==========")
with app.app_context():
    rc1a_fresh = m.Response_Classification.query.get(rc1a_id)
    eff_confirmed = get_effective_classification(rc1a_fresh)
    check("confirmed 使用 AI original 的 sub_category", eff_confirmed["sub_category"] == "B2 支援協作")
    check("confirmed 使用 AI original 的 methodology（直接讀欄位，不重新查表）", eff_confirmed["methodology"] == "互惠與責任承擔分析")

    rc3_fresh = m.Response_Classification.query.get(rc3_id)
    eff_modified = get_effective_classification(rc3_fresh)
    check("modified 使用 final_sub_category（B2），不是 AI original（B1）", eff_modified["sub_category"] == "B2 支援協作")
    check("modified 的 methodology 是重新查表得到、對應 final_sub_category", eff_modified["methodology"] == "互惠與責任承擔分析")
    check("modified 的 reasoning 是 final_reasoning，不是 AI original reasoning", eff_modified["reasoning"] == "human confirmed: 其實是支援不足")

    rc5_fresh = m.Response_Classification.query.get(rc5_id)
    try:
        get_effective_classification(rc5_fresh)
        check("excluded 呼叫 get_effective_classification 應該拋例外", False)
    except EffectiveClassificationError:
        check("excluded 呼叫 get_effective_classification 應該拋例外", True)


# ═══════════════════════════════════════════════════════════════
# 測試：build_aggregation（Survey A）
# ═══════════════════════════════════════════════════════════════
print("\n========== Aggregation：Survey A ==========")
with app.app_context():
    agg_a = build_aggregation("survey", template_id=template_a_id)

by_key_a = {(g["main_category"], g["sub_category"]): g for g in agg_a}

check("13. pending_review 不納入：group 裡完全找不到 r4 的 classification_id", not any(
    item["response_id"] == r4_id for g in agg_a for item in g["items"]
))
check("14. excluded 不納入：group 裡完全找不到 r5 的 classification_id", not any(
    item["response_id"] == r5_id for g in agg_a for item in g["items"]
))

check("17. Primary 分組存在（A2 回饋與溝通）", ("主管領導", "A2 回饋與溝通") in by_key_a)
check("17. Secondary 分組也存在（B2 支援協作，來自 r2 的 secondary）", any(
    item["response_id"] == r2_id for item in by_key_a[("部門合作", "B2 支援協作")]["items"]
))

check("18. 只有一個 (部門合作, B2 支援協作) 分組，沒有因為多來源被拆成重複分組", len(
    [g for g in agg_a if g["main_category"] == "部門合作" and g["sub_category"] == "B2 支援協作"]
) == 1)

b2_group = by_key_a[("部門合作", "B2 支援協作")]
check(
    "19. 同一 response（r1）拆 2 個 segment，落在同一 group：segment_count 對這個 response 貢獻 2 筆 item",
    len([item for item in b2_group["items"] if item["response_id"] == r1_id]) == 2,
)
check(
    "19. B2 這個 group 的 response_count 正確去重（r1/r2/r3 三份不同回答 = 3，不是 4 筆 segment 的數量）",
    b2_group["response_count"] == 3,
)
check(
    "19. B2 這個 group 的 segment_count 是實際 item 數（r1 兩筆 + r2 一筆 + r3 一筆 = 4）",
    b2_group["segment_count"] == 4,
)
check("B2 group 的 methodology/citation 是查表結果，不是 None", b2_group["methodology"] == "互惠與責任承擔分析" and b2_group["citation"] == "cite-b2")

check(
    "20. Survey A 的 aggregation 完全不包含 Survey B 的資料",
    not any(item["response_id"] == rb_id for g in agg_a for item in g["items"]),
)


# ═══════════════════════════════════════════════════════════════
# 測試 20：Survey B 自己的 aggregation 也正確、且跟 A 分開
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 20：Survey B 獨立 aggregation ==========")
with app.app_context():
    agg_b = build_aggregation("survey", template_id=template_b_id)
check("Survey B 的 aggregation 只有 Survey B 自己的資料", all(
    item["response_id"] == rb_id for g in agg_b for item in g["items"]
))
check("Survey B 的 group 數量是 1", len(agg_b) == 1)


# ═══════════════════════════════════════════════════════════════
# 測試 21/22：upload batch 互相不混、也不跟 survey 混
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 21/22：upload batch 隔離 ==========")
with app.app_context():
    agg_x = build_aggregation("user_upload", upload_batch_id="batch-X")
    agg_y = build_aggregation("user_upload", upload_batch_id="batch-Y")

check("batch-X 的 aggregation 只包含 batch-X 自己的 item", all(
    item["upload_batch_id"] == "batch-X" for g in agg_x for item in g["items"]
))
check("batch-Y 的 aggregation 只包含 batch-Y 自己的 item", all(
    item["upload_batch_id"] == "batch-Y" for g in agg_y for item in g["items"]
))
check("21. batch-X 跟 batch-Y 彼此獨立，各自 response_count 都是 1（不會互相加總）", (
    agg_x[0]["response_count"] == 1 and agg_y[0]["response_count"] == 1
))
check(
    "22. Survey 的 aggregation 完全不會出現 upload_batch_id 有值的 item（Survey/upload 不混）",
    not any(item["upload_batch_id"] is not None for g in agg_a for item in g["items"]),
)
check(
    "22. Upload 的 aggregation 完全不會出現 response_id 有值的 item（Survey/upload 不混）",
    not any(item["response_id"] is not None for g in agg_x for item in g["items"]),
)


print("\n" + "=" * 50)
if FAILED:
    print(f"共 {len(FAILED)} 項測試失敗：")
    for f in FAILED:
        print("  -", f)
    sys.exit(1)
else:
    print("全部測試通過！")
