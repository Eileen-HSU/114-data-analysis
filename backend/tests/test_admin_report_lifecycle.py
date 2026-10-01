#!/usr/bin/env python
"""
P0-4：Admin Report lifecycle（後端 + DB 依據，不靠前端猜）。

涵蓋：
    1. GET /api/admin/ai/reports：列出所有有分類結果的分析單位，含
       readiness、最新報告、needs_regeneration + 原因
    2. 尚未產生報告 -> needs_regeneration（no_completed_report）；readiness 不足
       -> 全部被排除、沒有可納入的結果時，產生回 400 REPORT_NOT_READY
    3. 產生 -> completed、version、taxonomy_version_ids、updated_at、audit
    4. 下列事件都讓報告 outdated，且 outdated_reason 寫進 DB：
       classification modified / excluded / reopened / rerun / bulk review / taxonomy publish
    5. 重新產生 -> 新 version、舊版保留、needs_regeneration 解除
    6. 產生失敗（AI 摘要失敗）-> status=failed + error_detail，API 回具體訊息，
       needs_regeneration=last_generation_failed
    7. 匯出：completed 才能匯出；失敗版本 409 REPORT_NOT_COMPLETED

執行方式：
    cd backend
    python3 tests/test_admin_report_lifecycle.py
"""

from admin_test_support import (
    GEMINI_QUEUE, admin_header, check, create_app, finish, q, seed_classification, seed_people,
    seed_topic, seed_upload_batch,
)
import models as m
from extensions import db

app = create_app()
client = app.test_client()
BATCH = "batch-report"

with app.app_context():
    seed_people()
    version_id = seed_topic("report_topic")
    ids = seed_upload_batch(BATCH, [f"回答{i}" for i in range(4)], question_type="report_topic")
    cids = [seed_classification(a, BATCH, f"回答{i}", "Main A", "A1 Original", version_id=version_id)
            for i, a in enumerate(ids)]


def unit():
    return client.get(f"/api/admin/ai/reports/user_upload/{BATCH}", headers=admin_header(1)).get_json()


def latest():
    with app.app_context():
        r = m.Report.query.filter_by(upload_batch_id=BATCH, status="completed").order_by(m.Report.version.desc()).first()
        return (r.is_outdated, r.outdated_reason) if r else None


def generate(summaries=1):
    q(*[{"summary": "摘要"}] * summaries)
    return client.post(f"/api/admin/ai/reports/user_upload/{BATCH}/generate", headers=admin_header(1))


print("========== 1/2. 列表與 readiness ==========")
resp = client.get("/api/admin/ai/reports", headers=admin_header(1))
check("reports 200", resp.status_code == 200)
item = next(i for i in resp.get_json()["items"] if i["upload_batch_id"] == BATCH)
# 報告不等人工審核：4 筆待審的結果直接可以產生報告
check("readiness：4 pending、eligible 4（待審也算）",
      item["readiness"]["pending_review"] == 4 and item["readiness"]["eligible"] == 4
      and item["readiness"]["can_generate"] is True)
check("沒有報告、但已經可以產生 -> needs_regeneration（no_completed_report）",
      item["needs_regeneration"] is True and item["regeneration_reason"] == "no_completed_report"
      and item["latest_report"] is None)
GEMINI_QUEUE.clear()
client.post("/api/classification/review/batch-confirm", headers=admin_header(1), json={"classification_ids": cids[:3]})
check("確認之後仍然需要產生第一份報告（no_completed_report）",
      unit()["needs_regeneration"] is True and unit()["regeneration_reason"] == "no_completed_report")
check("非 admin 不能存取", client.get("/api/admin/ai/reports").status_code == 401)

# 全部都被人工排除：沒有任何可以納入報告的結果 -> 不能產生
with app.app_context():
    empty_ids = seed_upload_batch("batch-all-excluded", ["不相關"], question_type="report_topic")
    seed_classification(empty_ids[0], "batch-all-excluded", "不相關", "Main A", "A1 Original",
                        version_id=version_id, review_status="excluded")
resp = client.post("/api/admin/ai/reports/user_upload/batch-all-excluded/generate", headers=admin_header(1))
check("全部排除 -> 400 REPORT_NOT_READY", resp.status_code == 400 and resp.get_json()["code"] == "REPORT_NOT_READY")


print("\n========== 3. 產生 ==========")
resp = generate()
check("generate 201", resp.status_code == 201)
rep = resp.get_json()["report"]
check("completed、version=1、taxonomy_version_ids、updated_at",
      rep["status"] == "completed" and rep["version"] == 1 and rep["taxonomy_version_ids"] == [str(version_id)] and rep["updated_at"])
check("產生後 needs_regeneration=False", unit()["needs_regeneration"] is False)
with app.app_context():
    check("report_regenerate audit", m.Admin_Audit_Log.query.filter_by(action="report_regenerate").count() == 1)


print("\n========== 4. 各種事件讓報告 outdated（DB 依據）==========")


def regenerate_fresh():
    generate()
    check("  重新產生後回到 not outdated", latest() == (False, None))


# modified
client.post(f"/api/classification/{cids[3]}/review/start", headers=admin_header(1))
q({"reply": "改 B", "candidate_sub_category": "B1 Candidate", "candidate_secondary_sub_category": None, "candidate_reasoning": "x"})
client.post(f"/api/classification/{cids[3]}/review/message", headers=admin_header(1), json={"message": "改"})
client.post(f"/api/classification/{cids[3]}/review/confirm-candidate", headers=admin_header(1))
check("modified -> outdated（classification_modified）", latest() == (True, "classification_modified"))
check("unit 顯示需要重新產生與原因 label",
      unit()["needs_regeneration"] is True and unit()["regeneration_reason_label"] == "有分類結果被人工修改")
q({"summary": "摘要"})
regenerate_fresh()

client.post(f"/api/classification/{cids[3]}/review/reopen", headers=admin_header(1))
check("reopened -> outdated（classification_reopened）", latest() == (True, "classification_reopened"))
client.post(f"/api/classification/{cids[3]}/review/exclude", headers=admin_header(1))
check("excluded -> outdated（classification_excluded）", latest() == (True, "classification_excluded"))
regenerate_fresh()

client.post(f"/api/classification/{cids[3]}/review/reopen", headers=admin_header(1))
client.post(f"/api/classification/{cids[3]}/review/exclude", headers=admin_header(1))
regenerate_fresh()
with app.app_context():
    new_ids = seed_upload_batch(BATCH, ["legacy bulk"], question_type=None)
    seed_classification(new_ids[0], BATCH, "legacy bulk", "M", "S", confidence=None)
client.post("/api/classification/review/exclude-legacy", headers=admin_header(1))
check("bulk review action -> outdated（bulk_review_action）", latest() == (True, "bulk_review_action"))
regenerate_fresh()

# taxonomy publish（同一 Topic 的新版本）
with app.app_context():
    draft = seed_topic("report_topic", status="draft", version_number=2)
resp = client.post(f"/api/admin/ai/topics/report_topic/taxonomy/{draft}/publish", headers=admin_header(1))
check("publish 200", resp.status_code == 200)
check("taxonomy publish -> outdated（taxonomy_published）", latest() == (True, "taxonomy_published"))
regenerate_fresh()

# rerun（retry failed）
with app.app_context():
    fid = seed_upload_batch(BATCH, ["失敗重跑"], question_type="report_topic")[0]
    failed_cid = seed_classification(fid, BATCH, "失敗重跑", None, None, version_id=version_id, status="failed")
from services.privacy_service import mask_pii  # noqa: E402
q({"segments": [mask_pii("失敗重跑")]},
  {"classifications": [{"index": 0, "main_category": "Main A", "sub_category": "A1 Original",
                        "secondary_sub_category": None, "reasoning": "r", "summary": "s", "confidence": 0.9}]})
resp = client.post(f"/api/admin/ai/classifications/{failed_cid}/retry", headers=admin_header(1))
check("retry 200", resp.status_code == 200)
check("rerun -> outdated（classification_rerun）", latest() == (True, "classification_rerun"))


print("\n========== 5. 版本保留 ==========")
versions = unit()["versions"]
check("每次重新產生都是新 version，舊版保留", [v["version"] for v in versions] == sorted([v["version"] for v in versions], reverse=True) and len(versions) >= 6)


print("\n========== 6. 產生失敗 ==========")
GEMINI_QUEUE.clear()  # 沒有摘要回應 -> AI 摘要失敗
resp = client.post(f"/api/admin/ai/reports/user_upload/{BATCH}/generate", headers=admin_header(1))
check("失敗 -> 500 REPORT_GENERATION_FAILED 且帶具體原因",
      resp.status_code == 500 and resp.get_json()["code"] == "REPORT_GENERATION_FAILED"
      and resp.get_json()["message"].startswith("報告產生失敗：") and resp.get_json()["failure"]["raw"])
check("失敗原因有中文說明，原始錯誤保留在 failure.raw",
      "摘要產生失敗" in resp.get_json()["failure"]["raw"] and resp.get_json()["failure"]["message"])
failed_report = resp.get_json()["report"]
check("DB 記錄 status=failed + error_detail", failed_report["status"] == "failed" and failed_report["error_detail"])
check("unit：needs_regeneration=last_generation_failed", unit()["regeneration_reason"] == "last_generation_failed")
check("unit：latest_failure 帶中文說明", bool(unit()["latest_failure"]["message"]))


print("\n========== 7. 匯出 ==========")
resp = client.get(f"/api/admin/ai/reports/detail/{failed_report['report_id']}/export?format=xlsx", headers=admin_header(1))
check("failed 版本匯出 -> 409 REPORT_NOT_COMPLETED", resp.status_code == 409 and resp.get_json()["code"] == "REPORT_NOT_COMPLETED")
completed_id = next(v["report_id"] for v in unit()["versions"] if v["status"] == "completed")
resp = client.get(f"/api/admin/ai/reports/detail/{completed_id}/export?format=docx", headers=admin_header(1))
check("completed 版本匯出 docx 200", resp.status_code == 200 and resp.data[:2] == b"PK")
check("format 不合法 -> 400 INVALID_FORMAT",
      client.get(f"/api/admin/ai/reports/detail/{completed_id}/export?format=pdf", headers=admin_header(1)).get_json()["code"] == "INVALID_FORMAT")
check("needs_regeneration 篩選", any(i["upload_batch_id"] == BATCH for i in client.get(
    "/api/admin/ai/reports?needs_regeneration=true", headers=admin_header(1)).get_json()["items"]))

finish()
