#!/usr/bin/env python
"""
測試腳本：驗證 Phase 2（Models + schema compatibility）本身，
不涉及 Human Review / Aggregation / Report generation 的業務邏輯
（那些屬於 Phase 3~5）。

涵蓋：
  1. Response_Classification 新欄位可以正常寫入/讀出，且不影響既有
     欄位與既有 CheckConstraint。
  2. Uploaded_Answer.user_id 可為 None（相容舊資料），但新資料可以
     正常帶入 authenticated user_id。
  3. 新表 Classification_Review / Classification_Review_Message /
     Report / Report_Aggregation / Report_Aggregation_Item 可以建立、
     寫入，FK cascade / SET NULL 行為符合設計。
  4. review_status 允許值集合已包含 modified / excluded，不再有
     removed。

執行方式：
    cd backend
    python3 test_phase2_schema.py
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
from sqlalchemy import event
from sqlalchemy.engine import Engine

from extensions import db
import models as m


# SQLite 預設不會真的執行 FK 的 ON DELETE 行為（CASCADE / SET NULL），
# 除非明確開啟 PRAGMA foreign_keys=ON。正式環境用 MySQL 本來就會強制
# 生效，這裡開啟 pragma 只是讓測試能在 SQLite 上如實驗證 ondelete
# 設定是否正確，不是新增行為。
@event.listens_for(Engine, "connect")
def _enable_sqlite_fk(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
from response_classification import (
    ALLOWED_REVIEW_STATUSES,
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
    tables = [
        m.User.__table__,
        m.Survey_Template.__table__,
        m.Survey_Response.__table__,
        m.Response_Classification.__table__,
        m.Uploaded_Answer.__table__,
        m.Classification_Review.__table__,
        m.Classification_Review_Message.__table__,
        m.Report.__table__,
        m.Report_Aggregation.__table__,
        m.Report_Aggregation_Item.__table__,
    ]
    db.metadata.create_all(bind=db.engine, tables=tables)

    user = m.User(user_id=1, user_name="tester", email="tester@example.com", password_hash="x")
    db.session.add(user)
    db.session.commit()


# ═══════════════════════════════════════════════════════════════
# 測試 1：review_status 允許值集合
# ═══════════════════════════════════════════════════════════════
print("========== review_status 允許值 ==========")
check("REVIEW_STATUS_MODIFIED 存在", REVIEW_STATUS_MODIFIED == "modified")
check("REVIEW_STATUS_EXCLUDED 存在", REVIEW_STATUS_EXCLUDED == "excluded")
check(
    "ALLOWED_REVIEW_STATUSES 不再包含 removed",
    "removed" not in ALLOWED_REVIEW_STATUSES,
)
check(
    "ALLOWED_REVIEW_STATUSES 剛好是 4 個合法值",
    ALLOWED_REVIEW_STATUSES == {
        REVIEW_STATUS_PENDING, REVIEW_STATUS_CONFIRMED,
        REVIEW_STATUS_MODIFIED, REVIEW_STATUS_EXCLUDED,
    },
)


# ═══════════════════════════════════════════════════════════════
# 測試 2：Response_Classification 新欄位（AI original / secondary_main / final_*）
# ═══════════════════════════════════════════════════════════════
print("\n========== Response_Classification 新欄位 ==========")

with app.app_context():
    template = m.Survey_Template(title="t", access_code="ABCDE", question_json={"items": []})
    db.session.add(template)
    db.session.commit()

    template_id = template.template_id

    survey_response = m.Survey_Response(template_id=template_id, answer_json={"answers": {}})
    db.session.add(survey_response)
    db.session.commit()
    survey_response_id = survey_response.response_id

    rc = m.Response_Classification(
        response_id=survey_response_id,
        source_type="survey",
        question_id="q1",
        answer_text="主要意見，次要意見",
        segment_start=0,
        segment_end=4,
        main_category="部門合作",
        sub_category="B2 支援協作",
        secondary_main_category="主管領導",
        secondary_sub_category="A2 回饋與溝通",
        reasoning="ai reasoning",
        summary="ai summary",
        methodology="互惠與責任承擔分析",
        citation="cite1",
        secondary_methodology="互動與溝通需求分析",
        secondary_citation="cite2",
        status="completed",
    )
    db.session.add(rc)
    db.session.commit()
    rc_id = rc.classification_id

    check("secondary_main_category 寫入成功", rc.secondary_main_category == "主管領導")
    check("final_* 欄位預設為 None（AI original 不受影響）", rc.final_main_category is None and rc.final_sub_category is None)
    check("review_status 預設為 pending_review", rc.review_status == REVIEW_STATUS_PENDING)

    # 模擬 Human Review 確認 candidate（Phase 3 才會真正這樣寫，這裡只驗證
    # DB 層允許 final_* 獨立於 AI original 被寫入，且 AI original 不會被覆寫）
    rc.review_status = REVIEW_STATUS_MODIFIED
    rc.final_main_category = "主管領導"
    rc.final_sub_category = "A4 領導風格"
    rc.final_secondary_main_category = None
    rc.final_secondary_sub_category = None
    rc.final_reasoning = "human confirmed reasoning"
    db.session.commit()

    reloaded = m.Response_Classification.query.get(rc_id)
    check("final_* 寫入後可正確讀回", reloaded.final_sub_category == "A4 領導風格")
    check(
        "AI original main_category/sub_category 完全沒被 Human Review 動到",
        reloaded.main_category == "部門合作" and reloaded.sub_category == "B2 支援協作",
    )
    check(
        "to_dict() 包含所有新欄位",
        set(["secondary_main_category", "final_main_category", "final_sub_category",
             "final_secondary_main_category", "final_secondary_sub_category", "final_reasoning"])
        <= set(reloaded.to_dict().keys()),
    )

    # 既有 CheckConstraint（source invariant）仍然有效，沒有被新欄位破壞
    try:
        bad = m.Response_Classification(
            response_id=survey_response_id,
            upload_batch_id="should-not-coexist",
            source_type="survey",
            answer_text="x", segment_start=0, segment_end=1,
        )
        db.session.add(bad)
        db.session.commit()
        check("既有 source invariant CheckConstraint 仍然擋下非法組合", False)
    except Exception:
        db.session.rollback()
        check("既有 source invariant CheckConstraint 仍然擋下非法組合", True)


# ═══════════════════════════════════════════════════════════════
# 測試 3：Uploaded_Answer.user_id（新資料 vs 舊資料相容）
# ═══════════════════════════════════════════════════════════════
print("\n========== Uploaded_Answer.user_id ==========")

with app.app_context():
    # 模擬「migration 前」就存在、沒有 owner 的舊資料列：user_id 仍可為 None
    legacy_ua = m.Uploaded_Answer(
        upload_batch_id="legacy-batch", source_column="意見", row_index=0,
        answer_text="舊資料，沒有 user_id", question_type=None,
    )
    db.session.add(legacy_ua)
    db.session.commit()
    check("舊資料列 user_id=None 仍可寫入（欄位相容）", legacy_ua.user_id is None)

    # 新資料應該正常帶入 user_id（route 層強制帶入，這裡驗證 model/DB 層不擋）
    new_ua = m.Uploaded_Answer(
        upload_batch_id="new-batch", user_id=1, source_column="意見", row_index=0,
        answer_text="新資料，有 user_id", question_type=None,
    )
    db.session.add(new_ua)
    db.session.commit()
    check("新資料列可正確帶入 user_id", new_ua.user_id == 1)
    check("to_dict() 包含 user_id", "user_id" in new_ua.to_dict())

    # 使用者被刪除時，Uploaded_Answer 不應該被 CASCADE 砍掉，只是 user_id 變 None。
    # 用 bulk delete（synchronize_session=False）繞過 ORM relationship
    # cascade 探測（User.profile/verifications/workspaces 這些關聯表
    # 不在本測試建立的表子集裡），直接測 DB 層 FK ondelete 行為本身。
    m.User.query.filter_by(user_id=1).delete(synchronize_session=False)
    db.session.commit()
    reloaded_ua = m.Uploaded_Answer.query.get(new_ua.id)
    check(
        "刪除 User 後 Uploaded_Answer 仍存在（SET NULL，不是 CASCADE 砍資料）",
        reloaded_ua is not None,
    )
    check("刪除 User 後 user_id 被設為 None", reloaded_ua.user_id is None)

    # 補回一個 user 供後面測試使用
    db.session.add(m.User(user_id=2, user_name="tester2", email="t2@example.com", password_hash="x"))
    db.session.commit()


# ═══════════════════════════════════════════════════════════════
# 測試 4：Classification_Review / Classification_Review_Message
# ═══════════════════════════════════════════════════════════════
print("\n========== Classification_Review 新表 ==========")

with app.app_context():
    review = m.Classification_Review(
        classification_id=rc_id, user_id=2, status="in_progress",
    )
    db.session.add(review)
    db.session.commit()
    review_id = review.review_id

    msg_user = m.Classification_Review_Message(
        review_id=review_id, role="user", content="我覺得這比較偏向講師的教學方式。",
    )
    msg_ai = m.Classification_Review_Message(
        review_id=review_id, role="assistant", content="根據你的說明，我重新判斷...",
        candidate_main_category="主管領導",
        candidate_sub_category="A4 領導風格",
        candidate_secondary_main_category=None,
        candidate_secondary_sub_category=None,
        candidate_reasoning="candidate reasoning",
    )
    db.session.add_all([msg_user, msg_ai])
    db.session.commit()

    check("Classification_Review 寫入成功", m.Classification_Review.query.count() == 1)
    check("Classification_Review_Message 寫入 2 筆", m.Classification_Review_Message.query.filter_by(review_id=review_id).count() == 2)

    reloaded_review = m.Classification_Review.query.get(review_id)
    check("relationship 可以撈到訊息（依 created_at 排序）", len(reloaded_review.messages) == 2)
    check("assistant 訊息保存了 candidate_*", reloaded_review.messages[1].candidate_sub_category == "A4 領導風格")

    check(
        "confirm 前，Response_Classification.final_sub_category 沒有被 candidate 影響（仍是上面手動設的 A4，不是這裡新的 candidate）",
        m.Response_Classification.query.get(rc_id).final_sub_category == "A4 領導風格",
    )

    # cascade：刪除 Response_Classification 應該連帶刪除 review + message
    db.session.delete(m.Response_Classification.query.get(rc_id))
    db.session.commit()
    check(
        "刪除 Response_Classification 後，Classification_Review 被 CASCADE 刪除",
        m.Classification_Review.query.get(review_id) is None,
    )
    check(
        "刪除 Response_Classification 後，Classification_Review_Message 也被連帶刪除",
        m.Classification_Review_Message.query.filter_by(review_id=review_id).count() == 0,
    )


# ═══════════════════════════════════════════════════════════════
# 測試 5：Report / Report_Aggregation / Report_Aggregation_Item
# ═══════════════════════════════════════════════════════════════
print("\n========== Report 系列新表 ==========")

with app.app_context():
    report_v1 = m.Report(
        source_type="survey", template_id=template_id, version=1,
        generated_by=2, status="completed",
        eligible_count_at_generation=10, pending_count_at_generation=0,
        excluded_count_at_generation=0,
    )
    db.session.add(report_v1)
    db.session.commit()

    agg = m.Report_Aggregation(
        report_id=report_v1.report_id, main_category="部門合作", sub_category="B2 支援協作",
        response_count=5, segment_count=7, aggregated_summary="摘要文字",
        methodology="互惠與責任承擔分析", citation="cite1",
    )
    db.session.add(agg)
    db.session.commit()

    item = m.Report_Aggregation_Item(
        aggregation_id=agg.aggregation_id,
        classification_id=None,  # 原始 classification 這裡已經在測試4被刪除，模擬「原始資料已不在但快照仍在」
        original_answer_text="完整原始回答", matched_segment_text="片段文字",
        effective_reasoning="有效 reasoning",
        response_id=survey_response_id,
    )
    db.session.add(item)
    db.session.commit()

    check("Report v1 寫入成功", m.Report.query.count() == 1)
    check("Report_Aggregation 寫入成功且掛在 Report 底下", len(m.Report.query.get(report_v1.report_id).aggregations) == 1)
    check(
        "Report_Aggregation_Item 即使 classification_id=None，snapshot 內容仍完整保留",
        m.Report_Aggregation_Item.query.get(item.item_id).original_answer_text == "完整原始回答",
    )

    # 建立 v2，驗證同一 source 下 version 可以遞增、且 v1 不會被覆蓋/刪除
    report_v2 = m.Report(
        source_type="survey", template_id=template_id, version=2,
        generated_by=2, status="completed",
        eligible_count_at_generation=12, pending_count_at_generation=0,
        excluded_count_at_generation=0,
    )
    db.session.add(report_v2)
    db.session.commit()

    check("v1 + v2 同時存在", m.Report.query.filter_by(template_id=template_id).count() == 2)
    check("v1 仍可正常讀取、內容未變", m.Report.query.get(report_v1.report_id).eligible_count_at_generation == 10)

    # UniqueConstraint：同一 source + 同一 version 不能重複
    try:
        dup_version = m.Report(
            source_type="survey", template_id=template_id, version=1,
            status="completed",
        )
        db.session.add(dup_version)
        db.session.commit()
        check("同一 source 下 version 不可重複（UniqueConstraint 生效）", False)
    except Exception:
        db.session.rollback()
        check("同一 source 下 version 不可重複（UniqueConstraint 生效）", True)

    # source invariant CheckConstraint：survey 不能同時有 upload_batch_id
    try:
        bad_report = m.Report(
            source_type="survey", template_id=template_id,
            upload_batch_id="should-not-coexist", version=99, status="completed",
        )
        db.session.add(bad_report)
        db.session.commit()
        check("Report source invariant CheckConstraint 擋下非法組合", False)
    except Exception:
        db.session.rollback()
        check("Report source invariant CheckConstraint 擋下非法組合", True)

    # cascade：刪除 Report 應該連帶刪除 Report_Aggregation + Report_Aggregation_Item
    db.session.delete(m.Report.query.get(report_v1.report_id))
    db.session.commit()
    check(
        "刪除 Report 後，Report_Aggregation 被 CASCADE 刪除",
        m.Report_Aggregation.query.get(agg.aggregation_id) is None,
    )
    check(
        "刪除 Report 後，Report_Aggregation_Item 也被連帶刪除",
        m.Report_Aggregation_Item.query.get(item.item_id) is None,
    )
    check("v2 不受 v1 被刪除影響，仍然存在", m.Report.query.get(report_v2.report_id) is not None)


print("\n" + "=" * 50)
if FAILED:
    print(f"共 {len(FAILED)} 項測試失敗：")
    for f in FAILED:
        print("  -", f)
    sys.exit(1)
else:
    print("全部測試通過！")
