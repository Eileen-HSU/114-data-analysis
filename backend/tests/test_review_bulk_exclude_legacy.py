#!/usr/bin/env python
"""
測試腳本：Human Review「排除舊版資料」批次功能
（services.review_service.exclude_legacy_pending_classifications() +
POST /api/classification/review/exclude-legacy）。

涵蓋：
    1. 只排除同時符合 taxonomy_version_id IS NULL AND confidence IS
       NULL AND review_status = 'pending_review' 三個條件的列
    2. confirmed / modified / excluded 的列完全不動（即使同時符合
       taxonomy_version_id IS NULL 跟 confidence IS NULL）
    3. 有 confidence（含 confidence=0.0 這個容易跟 NULL 搞混的邊界
       值）的列不動
    4. 有 taxonomy_version_id 的列不動（即使 confidence 剛好是 NULL）
    5. affected_count 精確等於實際被更新的筆數
    6. 除了 review_status 以外，main_category / sub_category /
       reasoning / confidence / taxonomy_version_id 等欄位完全沒有
       被改動（不刪除資料、不覆寫其他欄位）
    7. 重複呼叫（idempotent）：第二次呼叫時，已經被排除過的列不會
       再被算進 affected_count
    8. HTTP endpoint 串接：POST /api/classification/review/exclude-legacy
       —— Admin token 正常回 200 + 正確 affected_count；沒帶 token
       回 401

執行方式：
    cd backend
    export JWT_SECRET_KEY=test-secret-key-for-testing-only
    python3 tests/test_review_bulk_exclude_legacy.py
"""

import os
import sys

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

FAILED = []


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    if status == "FAIL":
        FAILED.append(label)
    print(f"[{status}] {label}")


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
from routes.auth.admin_guard import build_admin_token
from routes.classifications.review import review_bp
from services import review_service


app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
app.config["TESTING"] = True
app.register_blueprint(review_bp)
db.init_app(app)

with app.app_context():
    tables = [
        m.Admin.__table__,
        m.Response_Classification.__table__,
    ]
    db.metadata.create_all(bind=db.engine, tables=tables)
    db.session.add(m.Admin(admin_id=1, admin_name="測試管理員", email="admin@example.com", password_hash="x"))
    db.session.commit()

client = app.test_client()
_next_response_id = [5000]


def _fresh_response_id():
    _next_response_id[0] += 1
    return _next_response_id[0]


def make_row(
    review_status,
    taxonomy_version_id,
    confidence,
    main_category="M",
    sub_category="S",
    reasoning="R",
):
    row = m.Response_Classification(
        response_id=_fresh_response_id(),
        source_type=SOURCE_TYPE_SURVEY,
        question_id="q1",
        answer_text="這是一段測試用的完整回答內容",
        segment_start=0,
        segment_end=5,
        main_category=main_category,
        sub_category=sub_category,
        reasoning=reasoning,
        status="completed",
        review_status=review_status,
        taxonomy_version_id=taxonomy_version_id,
        confidence=confidence,
    )
    db.session.add(row)
    db.session.commit()
    return row.classification_id


with app.app_context():

    print("========== 建立測試資料 ==========")

    # ── 應該被排除的：taxonomy_version_id=NULL + confidence=NULL + pending_review ──
    cid_legacy_1 = make_row(REVIEW_STATUS_PENDING, None, None, main_category="LEGACY1_MAIN", sub_category="LEGACY1_SUB", reasoning="LEGACY1_REASON")
    cid_legacy_2 = make_row(REVIEW_STATUS_PENDING, None, None, main_category="LEGACY2_MAIN", sub_category="LEGACY2_SUB", reasoning="LEGACY2_REASON")

    # ── 不應該被排除：review_status 不是 pending_review（即使同時符合另外兩個條件）──
    cid_confirmed = make_row(REVIEW_STATUS_CONFIRMED, None, None)
    cid_modified = make_row(REVIEW_STATUS_MODIFIED, None, None)
    cid_already_excluded = make_row(REVIEW_STATUS_EXCLUDED, None, None)

    # ── 不應該被排除：有 confidence（不是 NULL）──
    cid_has_confidence = make_row(REVIEW_STATUS_PENDING, None, 0.55)
    # 邊界情況：confidence=0.0 是合法數值，不是 NULL，不該被當成
    # 「沒有信心分數」誤判排除。
    cid_confidence_zero = make_row(REVIEW_STATUS_PENDING, None, 0.0)

    # ── 不應該被排除：有 taxonomy_version_id（即使 confidence 剛好是 NULL）──
    cid_has_taxonomy_version = make_row(REVIEW_STATUS_PENDING, 999, None)

    should_be_excluded_ids = {cid_legacy_1, cid_legacy_2}
    should_be_untouched_ids = {
        cid_confirmed, cid_modified, cid_already_excluded,
        cid_has_confidence, cid_confidence_zero, cid_has_taxonomy_version,
    }

    # 排除前先拍一份「除了 review_status 以外」欄位的快照，之後比對
    # 這些欄位完全沒有被動過。
    def _snapshot(classification_id):
        row = m.Response_Classification.query.get(classification_id)
        return {
            "main_category": row.main_category,
            "sub_category": row.sub_category,
            "reasoning": row.reasoning,
            "confidence": row.confidence,
            "taxonomy_version_id": row.taxonomy_version_id,
            "answer_text": row.answer_text,
            "segment_start": row.segment_start,
            "segment_end": row.segment_end,
        }

    before_snapshots = {
        cid: _snapshot(cid) for cid in (should_be_excluded_ids | should_be_untouched_ids)
    }
    before_review_status = {
        cid: m.Response_Classification.query.get(cid).review_status
        for cid in should_be_untouched_ids
    }


    print("\n========== 1~4. 篩選條件：只排除三條件同時成立的列 ==========")

    affected_count = review_service.exclude_legacy_pending_classifications(admin_id=1)

    check("affected_count 精確等於 2（只有 2 筆同時符合三個條件）", affected_count == 2)

    for cid in should_be_excluded_ids:
        row = m.Response_Classification.query.get(cid)
        check(f"classification_id={cid}（舊版 pending）review_status 變成 excluded", row.review_status == REVIEW_STATUS_EXCLUDED)

    check(
        "confirmed 的列 review_status 不變",
        m.Response_Classification.query.get(cid_confirmed).review_status == REVIEW_STATUS_CONFIRMED,
    )
    check(
        "modified 的列 review_status 不變",
        m.Response_Classification.query.get(cid_modified).review_status == REVIEW_STATUS_MODIFIED,
    )
    check(
        "已經是 excluded 的列 review_status 不變（還是 excluded，不影響冪等性判斷）",
        m.Response_Classification.query.get(cid_already_excluded).review_status == REVIEW_STATUS_EXCLUDED,
    )
    check(
        "有 confidence=0.55 的列 review_status 不變（仍是 pending_review）",
        m.Response_Classification.query.get(cid_has_confidence).review_status == REVIEW_STATUS_PENDING,
    )
    check(
        "confidence=0.0（不是 NULL）的列 review_status 不變（仍是 pending_review）",
        m.Response_Classification.query.get(cid_confidence_zero).review_status == REVIEW_STATUS_PENDING,
    )
    check(
        "有 taxonomy_version_id 的列 review_status 不變（仍是 pending_review）",
        m.Response_Classification.query.get(cid_has_taxonomy_version).review_status == REVIEW_STATUS_PENDING,
    )


    print("\n========== 6. 除了 review_status，其餘欄位完全沒被改動 ==========")

    for cid in should_be_excluded_ids | should_be_untouched_ids:
        after = _snapshot(cid)
        check(
            f"classification_id={cid}：main_category/sub_category/reasoning/confidence/"
            "taxonomy_version_id/answer_text/segment_start/segment_end 全部不變",
            after == before_snapshots[cid],
        )


    print("\n========== 7. 冪等性：再跑一次，已排除的不會重複計入 ==========")

    affected_count_second_run = review_service.exclude_legacy_pending_classifications(admin_id=1)
    check("第二次呼叫 affected_count 為 0（沒有剩下符合條件的舊版 pending 資料）", affected_count_second_run == 0)


print(f"\n服務層測試累計失敗：{len(FAILED)} 項")


print("\n========== 8. HTTP endpoint 串接 ==========")

with app.app_context():
    # 再放一筆新的舊版 pending 資料，驗證走 HTTP endpoint 也能正確排除。
    cid_via_http = make_row(REVIEW_STATUS_PENDING, None, None, main_category="HTTP_MAIN", sub_category="HTTP_SUB")

admin_token = build_admin_token(admin_id=1)

resp_no_auth = client.post("/api/classification/review/exclude-legacy")
check("沒帶 token 呼叫 endpoint 回 401", resp_no_auth.status_code == 401)

resp = client.post(
    "/api/classification/review/exclude-legacy",
    headers={"Authorization": f"Bearer {admin_token}"},
)
check("帶合法 Admin token 呼叫 endpoint 回 200", resp.status_code == 200)
body = resp.get_json()
check("endpoint 回應包含 affected_count 欄位", "affected_count" in body)
check("這次透過 endpoint 排除的筆數正確（只有剛放進去那 1 筆）", body["affected_count"] == 1)

with app.app_context():
    check(
        "透過 endpoint 排除後，該筆 review_status 確實變成 excluded",
        m.Response_Classification.query.get(cid_via_http).review_status == REVIEW_STATUS_EXCLUDED,
    )

resp_again = client.post(
    "/api/classification/review/exclude-legacy",
    headers={"Authorization": f"Bearer {admin_token}"},
)
check("endpoint 再呼叫一次，affected_count 為 0（沒有新的舊版 pending 資料了）", resp_again.get_json()["affected_count"] == 0)


print("\n" + "=" * 50)
if FAILED:
    print(f"共 {len(FAILED)} 項測試失敗：")
    for label in FAILED:
        print(f"  - {label}")
    sys.exit(1)
else:
    print("全部測試通過！")