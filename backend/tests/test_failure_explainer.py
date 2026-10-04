#!/usr/bin/env python
"""
AI 服務失敗的顯示說明（services/failure_explainer.py）＋ Admin API 帶出中文原因。

涵蓋：
    1. 額度不足（429 / RESOURCE_EXHAUSTED）-> AI_QUOTA_EXCEEDED、中文說明
    2. 模型過載（503 / UNAVAILABLE / high demand）-> AI_SERVICE_BUSY
    3. 逾時 / 金鑰 / 個資遮罩 / 格式錯誤 / 未知錯誤各自有中文說明，原始錯誤保留在 raw
    4. 不會把 id 之類的數字誤判成 HTTP 狀態碼
    5. Admin 審查清單、未分類頁的 failed 列都帶 failure（中文 message）
    6. 重新處理時 AI 服務失敗：API 錯誤碼 / 訊息是中文說明，raw_error 保留原始錯誤

執行方式：
    cd backend
    python3 tests/test_failure_explainer.py
"""

from admin_test_support import (
    GEMINI_QUEUE, admin_header, check, create_app, finish, q, seed_classification, seed_people,
    seed_topic, seed_upload_batch,
)
from services.failure_explainer import explain_failure, routing_failure

QUOTA = "BATCH_CLASSIFICATION_FAILED: 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your current quota'}}"
BUSY = "BATCH_CLASSIFICATION_FAILED: 503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently experiencing high demand.'}}"

print("========== 1~4. explain_failure ==========")
e = explain_failure(QUOTA)
check("額度不足 -> AI_QUOTA_EXCEEDED", e["code"] == "AI_QUOTA_EXCEEDED")
check("額度不足有中文說明", "額度不足" in e["message"] and "重新處理" in e["message"])
check("原始錯誤保留在 raw", e["raw"] == QUOTA)
check("模型過載 -> AI_SERVICE_BUSY 中文", explain_failure(BUSY)["code"] == "AI_SERVICE_BUSY" and "使用量過高" in explain_failure(BUSY)["message"])
check("逾時 -> AI_TIMEOUT", explain_failure("GEMINI_API_FAILED: Deadline exceeded / timed out")["code"] == "AI_TIMEOUT")
check("金鑰 -> AI_AUTH_FAILED", explain_failure("ValueError: No API key was provided")["code"] == "AI_AUTH_FAILED")
check("個資遮罩 -> PII_MASKING_FAILED", explain_failure("PII_MASKING_FAILED: boom")["code"] == "PII_MASKING_FAILED")
check("格式錯誤 -> AI_RESPONSE_INVALID", explain_failure("JSONDecodeError('Expecting value')")["code"] == "AI_RESPONSE_INVALID")
unknown = explain_failure("something odd")
check("未知錯誤 -> CLASSIFICATION_FAILED_UNKNOWN 且仍是中文", unknown["code"] == "CLASSIFICATION_FAILED_UNKNOWN" and "原因不明" in unknown["message"])
check("classification_id=4031 之類的數字不會被當成 403", explain_failure("row classification_id=4031 odd")["code"] == "CLASSIFICATION_FAILED_UNKNOWN")
check("沒有錯誤文字 -> None", explain_failure(None) is None and explain_failure("") is None)
check("routing API 失敗有中文說明", routing_failure("routing_failed", "routing_reason=api_failure")["code"] == "ROUTING_SERVICE_FAILED")
check("unrouted（不是失敗）沒有 failure", routing_failure("unrouted", "routing_reason=undetermined") is None)

print("\n========== 5. Admin API 帶出中文原因 ==========")
app = create_app()
client = app.test_client()
with app.app_context():
    seed_people()
    version_id = seed_topic()
    ids = seed_upload_batch("batch-fail", ["額度不足的回答", "過載的回答"])
    c_quota = seed_classification(ids[0], "batch-fail", "額度不足的回答", None, None, version_id=version_id,
                                  status="failed")
    c_busy = seed_classification(ids[1], "batch-fail", "過載的回答", None, None, version_id=version_id,
                                 status="failed")
    import models as m
    from extensions import db
    from admin_test_support import seed_failed_retry
    # 「無法分類」清單只列自動重試仍失敗的資料：補上失敗的重試紀錄
    seed_failed_retry(ids[0])
    seed_failed_retry(ids[1])
    db.session.get(m.Response_Classification, c_quota).reasoning = QUOTA
    db.session.get(m.Response_Classification, c_busy).reasoning = BUSY
    db.session.commit()

rows = {r["classification_id"]: r for r in client.get(
    "/api/admin/ai/classifications?state=failed", headers=admin_header(1)).get_json()["classifications"]}
check("審查清單 failed 列：額度不足中文說明", rows[c_quota]["failure"]["code"] == "AI_QUOTA_EXCEEDED" and "額度不足" in rows[c_quota]["failure"]["message"])
check("審查清單 failed 列：過載中文說明", rows[c_busy]["failure"]["code"] == "AI_SERVICE_BUSY")
items = {i["classification_id"]: i for i in client.get(
    "/api/admin/ai/unassigned?kind=failed", headers=admin_header(1)).get_json()["items"]}
check("未分類頁 failed 列同樣帶中文說明", items[c_quota]["failure"]["code"] == "AI_QUOTA_EXCEEDED")

print("\n========== 6. 重新處理時 AI 服務失敗 ==========")
GEMINI_QUEUE.clear()
q(RuntimeError(QUOTA), RuntimeError(QUOTA), RuntimeError(QUOTA), RuntimeError(QUOTA))
resp = client.post(f"/api/admin/ai/classifications/{c_quota}/retry", headers=admin_header(1))
body = resp.get_json()
check("重新處理回應是 200（失敗結果）或具體錯誤碼", resp.status_code in (200, 502))
if resp.status_code == 200:
    check("回傳 failure：額度不足中文說明", body["succeeded"] is False and body["failure"]["code"] == "AI_QUOTA_EXCEEDED")
else:
    check("錯誤碼 AI_QUOTA_EXCEEDED、訊息為中文、raw_error 保留", body["code"] == "AI_QUOTA_EXCEEDED" and "額度不足" in body["message"] and body["raw_error"])
GEMINI_QUEUE.clear()

finish()
