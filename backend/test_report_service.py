#!/usr/bin/env python
"""
測試腳本：Versioned Report Snapshot（Phase 5）端到端測試。

涵蓋需求文件第二十七節測試項目 23~29，以及使用者對 Phase 5 的十點
要求逐項驗證：
    23. v1 建立
    24. Review 改變後 v1 outdated
    25. regenerate → v2
    26. v1 仍可讀
    27. v1 snapshot 不因 classification 後續修改而改變
    28. pending 存在時仍可在明確允許後只使用 eligible records
    29. report generation failure 不產生 completed 半成品

執行方式：
    cd backend
    export JWT_SECRET_KEY=test-secret
    python3 test_report_service.py
"""

import sys
import os
import types
import json

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only")
sys.path.insert(0, os.path.dirname(__file__))

FAILED = []


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    if status == "FAIL":
        FAILED.append(label)
    print(f"[{status}] {label}")


# ── 假的 google.generativeai：依序從佇列吐出回應 ──
_queue = []


class _FakeResp:
    def __init__(self, text):
        self.text = text


class _FakeModel:
    def __init__(self, system_instruction=None, **kwargs):
        self.system_instruction = system_instruction

    def generate_content(self, prompt, **kwargs):
        return _FakeResp(_queue.pop(0))  # 佇列空了會丟 IndexError，模擬呼叫失敗


_fake_genai = types.ModuleType("google.generativeai")
_fake_genai.GenerativeModel = _FakeModel
_fake_genai.configure = lambda **kwargs: None
_fake_google = types.ModuleType("google")
_fake_google.generativeai = _fake_genai
sys.modules["google"] = _fake_google
sys.modules["google.generativeai"] = _fake_genai


def q(obj_or_text):
    _queue.append(obj_or_text if isinstance(obj_or_text, str) else json.dumps(obj_or_text, ensure_ascii=False))


import jwt
from flask import Flask
from extensions import db
import models as m
from routes.classifications.review import review_bp
from routes.classifications.report import report_bp

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
app.config["TESTING"] = True
app.register_blueprint(review_bp)
app.register_blueprint(report_bp)
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

    db.session.add(m.User(user_id=1, user_name="owner", email="owner@example.com", password_hash="x"))
    db.session.add(m.User(user_id=2, user_name="stranger", email="stranger@example.com", password_hash="x"))
    db.session.commit()

    template = m.Survey_Template(
        title="測試問卷", access_code="RPRT1", user_id=1,
        question_json={"items": [
            {"id": "q1", "type": "short", "title": "t", "question_type": "leadership_and_dept"},
        ]},
    )
    db.session.add(template)
    db.session.commit()
    template_id = template.template_id

    def _mk_response(text):
        r = m.Survey_Response(template_id=template_id, answer_json={"answers": {"q1": text}})
        db.session.add(r)
        db.session.commit()
        return r.response_id

    r1_id = _mk_response("希望增加人力支援")
    r2_id = _mk_response("希望主管多給回饋")

    rc1 = m.Response_Classification(
        response_id=r1_id, source_type="survey", question_id="q1",
        answer_text="希望增加人力支援", segment_start=0, segment_end=8,
        main_category="部門合作", sub_category="B2 支援協作",
        reasoning="reasoning 1", summary="s", methodology="互惠與責任承擔分析", citation="cite-b2",
        status="completed", review_status="confirmed",
    )
    rc2 = m.Response_Classification(
        response_id=r2_id, source_type="survey", question_id="q1",
        answer_text="希望主管多給回饋", segment_start=0, segment_end=8,
        main_category="主管領導", sub_category="A2 回饋與溝通",
        reasoning="reasoning 2", summary="s", methodology="互動與溝通需求分析", citation="cite-a2",
        status="completed", review_status="confirmed",
    )
    db.session.add_all([rc1, rc2])
    db.session.commit()
    rc1_id, rc2_id = rc1.classification_id, rc2.classification_id


client = app.test_client()


def auth_header(user_id):
    token = jwt.encode({"user_id": user_id}, os.environ["JWT_SECRET_KEY"], algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


# ═══════════════════════════════════════════════════════════════
# 測試 23：v1 建立
# ═══════════════════════════════════════════════════════════════
print("========== 測試 23：v1 建立 ==========")

resp_readiness = client.get(f"/api/reports/survey/{template_id}/readiness", headers=auth_header(1))
check("readiness HTTP 200", resp_readiness.status_code == 200)
readiness_data = resp_readiness.get_json()
check("readiness eligible 為 2", readiness_data["eligible"] == 2)
check("readiness can_generate 為 True", readiness_data["can_generate"] is True)

q({"summary": "受訪者希望部門間能有更多實質支援。"})
q({"summary": "受訪者希望主管能更主動給予回饋。"})

resp_gen1 = client.post(f"/api/reports/survey/{template_id}/generate", headers=auth_header(1))
check("generate HTTP 201", resp_gen1.status_code == 201)
v1_data = resp_gen1.get_json()
check("v1 version 為 1", v1_data["version"] == 1)
check("v1 status 為 completed", v1_data["status"] == "completed")
check("v1 is_outdated 為 False", v1_data["is_outdated"] is False)
check("v1 eligible_count_at_generation 為 2", v1_data["eligible_count_at_generation"] == 2)
v1_id = v1_data["report_id"]

resp_v1_detail = client.get(f"/api/reports/{v1_id}", headers=auth_header(1))
check("v1 detail HTTP 200", resp_v1_detail.status_code == 200)
v1_detail = resp_v1_detail.get_json()
check("v1 detail 有 2 個 aggregation group", len(v1_detail["aggregations"]) == 2)
b2_agg = next(a for a in v1_detail["aggregations"] if a["sub_category"] == "B2 支援協作")
check("v1 detail 的 aggregated_summary 正確存在", b2_agg["aggregated_summary"] == "受訪者希望部門間能有更多實質支援。")
check("v1 detail 的 methodology/citation 正確快照", b2_agg["methodology"] == "互惠與責任承擔分析" and b2_agg["citation"] == "cite-b2")
check("v1 detail 的 item 保留完整原文", b2_agg["items"][0]["original_answer_text"] == "希望增加人力支援")


# ═══════════════════════════════════════════════════════════════
# 測試 24：Review 改變後 v1 outdated（呼應 Phase 3 已接好的 report_outdated_service）
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 24：Review 改變後 v1 outdated ==========")

with app.app_context():
    check("尚未有任何 review 動作前，v1 不是 outdated", m.Report.query.get(v1_id).is_outdated is False)

with app.app_context():
    r3 = m.Survey_Response(template_id=template_id, answer_json={"answers": {"q1": "新回答"}})
    db.session.add(r3)
    db.session.commit()
    rc3 = m.Response_Classification(
        response_id=r3.response_id, source_type="survey", question_id="q1",
        answer_text="新回答的分工不清楚", segment_start=0, segment_end=8,
        main_category="部門合作", sub_category="B3 權責界定與規範落實",
        reasoning="r3", summary="s", methodology="角色界定與規範內化分析", citation="cite-b3",
        status="completed", review_status="pending_review",
    )
    db.session.add(rc3)
    db.session.commit()
    rc3_id = rc3.classification_id

resp_confirm = client.post(f"/api/classification/{rc3_id}/review/confirm-original", headers=auth_header(1))
check("confirm-original HTTP 200", resp_confirm.status_code == 200)

with app.app_context():
    check("confirm-original 後，v1 被標記為 outdated", m.Report.query.get(v1_id).is_outdated is True)


# ═══════════════════════════════════════════════════════════════
# 測試 25/26：regenerate → v2，v1 仍可讀
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 25/26：regenerate → v2，v1 仍可讀 ==========")

q({"summary": "受訪者希望部門間能有更多實質支援。"})
q({"summary": "受訪者希望主管能更主動給予回饋。"})
q({"summary": "受訪者反映分工與權責不夠清楚。"})

resp_gen2 = client.post(f"/api/reports/survey/{template_id}/generate", headers=auth_header(1))
check("regenerate HTTP 201", resp_gen2.status_code == 201)
v2_data = resp_gen2.get_json()
check("v2 version 為 2（不是又建一個 1）", v2_data["version"] == 2)
v2_id = v2_data["report_id"]

resp_versions = client.get(f"/api/reports/survey/{template_id}/versions", headers=auth_header(1))
version_list = resp_versions.get_json()["versions"]
check("versions 列表同時有 v1 + v2", {v["version"] for v in version_list} == {1, 2})

resp_v1_again = client.get(f"/api/reports/{v1_id}", headers=auth_header(1))
check("v1 仍然可以正常讀取（HTTP 200）", resp_v1_again.status_code == 200)
v1_again_data = resp_v1_again.get_json()
check("v1 仍然只有 2 個 group（沒有被 regenerate 混進第 3 個新分類）", len(v1_again_data["aggregations"]) == 2)


# ═══════════════════════════════════════════════════════════════
# 測試 27：v1 snapshot 不因 classification 後續修改而改變
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 27：v1 snapshot 不因 classification 後續修改而改變 ==========")

with app.app_context():
    rc1_live = m.Response_Classification.query.get(rc1_id)
    original_reasoning = rc1_live.reasoning
    rc1_live.reasoning = "被竄改後的 reasoning（不應該出現在 v1 snapshot 裡）"
    db.session.commit()

resp_v1_after_mutation = client.get(f"/api/reports/{v1_id}", headers=auth_header(1))
v1_after_mutation = resp_v1_after_mutation.get_json()
b2_item_after = next(
    a for a in v1_after_mutation["aggregations"] if a["sub_category"] == "B2 支援協作"
)["items"][0]
check(
    "v1 snapshot 的 effective_reasoning 仍是產生當下的值，沒有跟著被竄改的資料變",
    b2_item_after["effective_reasoning"] == "reasoning 1",
)
check(
    "v1 snapshot 完全沒有反映竄改後的文字",
    "竄改" not in b2_item_after["effective_reasoning"],
)

with app.app_context():
    rc1_live = m.Response_Classification.query.get(rc1_id)
    rc1_live.reasoning = original_reasoning
    db.session.commit()


# ═══════════════════════════════════════════════════════════════
# 測試 28：pending 存在時仍可在明確允許後只使用 eligible records
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 28：pending 存在時，eligible-only 產生 ==========")

with app.app_context():
    r_pending = m.Survey_Response(template_id=template_id, answer_json={"answers": {"q1": "還沒審核的意見"}})
    db.session.add(r_pending)
    db.session.commit()
    rc_pending = m.Response_Classification(
        response_id=r_pending.response_id, source_type="survey", question_id="q1",
        answer_text="還沒審核的意見", segment_start=0, segment_end=5,
        main_category="部門合作", sub_category="B2 支援協作",
        status="completed", review_status="pending_review",
    )
    db.session.add(rc_pending)
    db.session.commit()

resp_readiness2 = client.get(f"/api/reports/survey/{template_id}/readiness", headers=auth_header(1))
readiness2 = resp_readiness2.get_json()
check("readiness has_pending 為 True", readiness2["has_pending"] is True)
check("readiness eligible 沒有把 pending 算進去（仍是 3：rc1,rc2,rc3）", readiness2["eligible"] == 3)

q({"summary": "受訪者希望部門間能有更多實質支援。"})
q({"summary": "受訪者希望主管能更主動給予回饋。"})
q({"summary": "受訪者反映分工與權責不夠清楚。"})

resp_gen3 = client.post(f"/api/reports/survey/{template_id}/generate", headers=auth_header(1))
v3_data = resp_gen3.get_json()
check("generate HTTP 201（即使有 pending 也能明確產生）", resp_gen3.status_code == 201)
check("v3 pending_count_at_generation 正確記錄為 1", v3_data["pending_count_at_generation"] == 1)
check("v3 eligible_count_at_generation 為 3（不含 pending）", v3_data["eligible_count_at_generation"] == 3)

resp_v3_detail = client.get(f"/api/reports/{v3_data['report_id']}", headers=auth_header(1))
v3_detail = resp_v3_detail.get_json()
check(
    "v3 snapshot 完全不包含 pending 那筆的內容",
    not any(
        item["original_answer_text"] == "還沒審核的意見"
        for agg in v3_detail["aggregations"] for item in agg["items"]
    ),
)


# ═══════════════════════════════════════════════════════════════
# 測試 29：report generation failure 不產生 completed 半成品
# ═══════════════════════════════════════════════════════════════
print("\n========== 測試 29：generation failure 不產生 completed 半成品 ==========")

with app.app_context():
    before_report_count = m.Report.query.filter_by(source_type="survey", template_id=template_id).count()

resp_gen_fail = client.post(f"/api/reports/survey/{template_id}/generate", headers=auth_header(1))
check("generation 失敗時 HTTP 500", resp_gen_fail.status_code == 500)
fail_data = resp_gen_fail.get_json()
check("失敗的 report status 為 failed（不是 completed）", fail_data["status"] == "failed")
check("失敗的 report 有 error_detail", bool(fail_data.get("error_detail")))

with app.app_context():
    failed_report = m.Report.query.get(fail_data["report_id"])
    check("DB 裡這筆 report 真的是 failed，不是 completed", failed_report.status == "failed")
    check("失敗的 report 底下沒有任何 Report_Aggregation（沒有半成品資料）", len(failed_report.aggregations) == 0)

    after_report_count = m.Report.query.filter_by(source_type="survey", template_id=template_id).count()
    check("version 號碼有被消耗掉（claim 過但失敗），不會被下次 generate 重複使用", after_report_count == before_report_count + 1)

q({"summary": "s1"})
q({"summary": "s2"})
q({"summary": "s3"})
resp_gen_after_fail = client.post(f"/api/reports/survey/{template_id}/generate", headers=auth_header(1))
check("失敗後下一次 generate 仍然成功", resp_gen_after_fail.status_code == 201)
check(
    "失敗後下一次 generate 版本號正確遞增（跳過失敗那個 version 號碼，不重複也不卡住）",
    resp_gen_after_fail.get_json()["version"] == fail_data["version"] + 1,
)


# ═══════════════════════════════════════════════════════════════
# 額外：ownership authorization（Phase 5 要求第 10 點）
# ═══════════════════════════════════════════════════════════════
print("\n========== 額外：ownership authorization ==========")

resp_stranger_readiness = client.get(f"/api/reports/survey/{template_id}/readiness", headers=auth_header(2))
check("非 owner 呼叫 readiness 回 403", resp_stranger_readiness.status_code == 403)

resp_stranger_generate = client.post(f"/api/reports/survey/{template_id}/generate", headers=auth_header(2))
check("非 owner 呼叫 generate 回 403", resp_stranger_generate.status_code == 403)

resp_stranger_versions = client.get(f"/api/reports/survey/{template_id}/versions", headers=auth_header(2))
check("非 owner 呼叫 versions 回 403", resp_stranger_versions.status_code == 403)

resp_stranger_detail = client.get(f"/api/reports/{v1_id}", headers=auth_header(2))
check("非 owner 呼叫 report detail 回 403", resp_stranger_detail.status_code == 403)

resp_no_token = client.get(f"/api/reports/survey/{template_id}/readiness")
check("完全沒帶 token 回 401", resp_no_token.status_code == 401)

resp_not_found = client.get("/api/reports/999999", headers=auth_header(1))
check("不存在的 report_id 回 404", resp_not_found.status_code == 404)

resp_no_eligible = client.get("/api/reports/survey/999999/readiness", headers=auth_header(1))
check("不存在的 survey template_id 回 404", resp_no_eligible.status_code == 404)


# ═══════════════════════════════════════════════════════════════
# 額外：版本號 claim 的重試邏輯（模擬併發衝突）
# ═══════════════════════════════════════════════════════════════
print("\n========== 額外：version claim 重試邏輯 ==========")
with app.app_context():
    current_max = db.session.query(db.func.max(m.Report.version)).filter_by(
        source_type="survey", template_id=template_id, upload_batch_id=None,
    ).scalar()
    hijacked_version = current_max + 1
    hijack_report = m.Report(
        source_type="survey", template_id=template_id, version=hijacked_version,
        generated_by=1, status="completed",
        eligible_count_at_generation=0, pending_count_at_generation=0, excluded_count_at_generation=0,
    )
    db.session.add(hijack_report)
    db.session.commit()

q({"summary": "s1"})
q({"summary": "s2"})
q({"summary": "s3"})
resp_after_hijack = client.post(f"/api/reports/survey/{template_id}/generate", headers=auth_header(1))
check("version 號碼被搶先佔用時，generate 仍然成功（自動重試拿下一個號碼）", resp_after_hijack.status_code == 201)
check(
    "拿到的 version 正確跳過被佔用的號碼",
    resp_after_hijack.get_json()["version"] == hijacked_version + 1,
)


print("\n" + "=" * 50)
if FAILED:
    print(f"共 {len(FAILED)} 項測試失敗：")
    for f in FAILED:
        print("  -", f)
    sys.exit(1)
else:
    print("全部測試通過！")
