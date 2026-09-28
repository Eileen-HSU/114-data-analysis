#!/usr/bin/env python
"""
taxonomy bootstrap 的可觀察性：失敗不阻止網站啟動，但要被記錄、Admin 看得到。

涵蓋：
    1. 失敗 / lock_timeout / 成功 / 停用 的結果寫進 System_Health_Status
    2. Admin API 回傳狀態、失敗時間、安全錯誤摘要（不含 API key、沒有 stack trace）
    3. 一般使用者不能讀
    4. bootstrap 失敗（沒有任何分類架構）時：
       - 固定分類模式 fail-closed：不分類、NO_PUBLISHED_TAXONOMY、不呼叫 AI
       - 開放式分類：AI 歸納失敗 -> 不分類（OPEN_CLASSIFICATION_FAILED）；
         AI 歸納成功 -> 才分析
       - 任何情況都不使用程式內建的 legacy 分類規則

執行方式：
    cd backend
    python3 tests/test_bootstrap_health.py
"""

import io
import os

import pandas as pd

from admin_test_support import (
    GEMINI_CALLS, GEMINI_QUEUE, admin_header, check, create_app, finish, q, seed_people, seed_topic, user_header,
)
import models as m
from extensions import db
from services.privacy_service import mask_pii
from services.subcategory_methodology import SUBCATEGORY_METHODOLOGY
from services.system_health_service import record_bootstrap_result, taxonomy_bootstrap_health

os.environ.pop("OPEN_CLASSIFICATION_ENABLED", None)
app = create_app()
client = app.test_client()
LEGACY_SUBS = [sub for table in SUBCATEGORY_METHODOLOGY.values() for sub in table]

with app.app_context():
    seed_people()


def upload(column, texts):
    df = pd.DataFrame({column: texts})
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    buf.seek(0)
    resp = client.post("/api/classification/upload", data={"file": (buf, "u.xlsx"), "text_column": column},
                       headers=user_header(1), content_type="multipart/form-data")
    return resp.get_json()


def legacy_rules_used():
    return any(sub in (c["system_instruction"] or "") for c in GEMINI_CALLS for sub in LEGACY_SUBS)


print("========== 1~3. 狀態記錄與 Admin API ==========")
with app.app_context():
    record_bootstrap_result(error=RuntimeError(
        "Can't connect to MySQL server; url=mysql://u:p@h/db?password=hunter2 key=AIzaSyBOOTSTRAP_leak_1234567890"))
    health = taxonomy_bootstrap_health()
check("失敗：status=failed、有失敗時間", health["status"] == "failed" and health["last_failure_at"])
check("錯誤摘要去除密碼 / URL 帳密 / API key", "hunter2" not in health["error_summary"] and "AIzaSy" not in health["error_summary"]
      and "u:p@" not in health["error_summary"]
      and "[REDACTED]" in health["error_summary"])
check("沒有任何分類架構：warning=bootstrap_failed", health["warning"] == "bootstrap_failed" and health["taxonomy_empty"])

resp = client.get("/api/admin/ai/system/health", headers=admin_header(1))
body = resp.get_json()
check("Admin API 200、回傳狀態", resp.status_code == 200 and body["taxonomy_bootstrap"]["status"] == "failed")
check("Admin API 不含 stack trace / 敏感資訊", "Traceback" not in str(body) and "hunter2" not in str(body))
check("一般使用者不能讀", client.get("/api/admin/ai/system/health", headers=user_header(1)).status_code in (401, 403))
check("未登入不能讀", client.get("/api/admin/ai/system/health").status_code == 401)

with app.app_context():
    record_bootstrap_result(result={"status": "lock_timeout", "created_topics": []})
    check("lock_timeout 也列為警告", taxonomy_bootstrap_health()["warning"] == "bootstrap_failed")
    record_bootstrap_result(disabled=True)
    check("停用：status=disabled，仍提醒沒有已發布分類架構",
          taxonomy_bootstrap_health()["status"] == "disabled" and taxonomy_bootstrap_health()["warning"] == "no_published_taxonomy")

print("\n========== 4. bootstrap 失敗時的分類行為 ==========")
with app.app_context():
    record_bootstrap_result(error=RuntimeError("seed failed"))

os.environ["OPEN_CLASSIFICATION_ENABLED"] = "0"
GEMINI_QUEUE.clear()
GEMINI_CALLS.clear()
data = upload("意見", ["希望多開訓練課程"])
check("固定模式 fail-closed：不分類、NO_PUBLISHED_TAXONOMY",
      data["classified_count"] == 0 and data["diagnostic_code"] == "NO_PUBLISHED_TAXONOMY" and data["failed_count"] == 1)
check("固定模式：完全沒有呼叫 AI（沒有 legacy fallback）", not GEMINI_CALLS)
with app.app_context():
    check("固定模式：沒有分類列", m.Response_Classification.query.filter_by(upload_batch_id=data["upload_batch_id"]).count() == 0)
os.environ.pop("OPEN_CLASSIFICATION_ENABLED", None)

GEMINI_QUEUE.clear()
GEMINI_CALLS.clear()
q("AI 歸納失敗：這不是 JSON")
data = upload("意見", ["希望多開訓練課程"])
check("開放式：AI 歸納失敗 -> 不分類、OPEN_CLASSIFICATION_FAILED",
      data["classified_count"] == 0 and data["diagnostic_code"] == "OPEN_CLASSIFICATION_FAILED")
check("開放式：沒有使用 legacy 分類規則", not legacy_rules_used())
with app.app_context():
    check("開放式失敗：沒有分類列", m.Response_Classification.query.filter_by(upload_batch_id=data["upload_batch_id"]).count() == 0)

GEMINI_QUEUE.clear()
GEMINI_CALLS.clear()
q({"categories": [{"main_category": "職涯", "sub_category": "訓練課程", "definition": "對訓練課程的需求"}]})
q({"segments": [mask_pii("希望多開訓練課程")]})
q({"classifications": [{"index": 0, "main_category": "職涯", "sub_category": "訓練課程", "secondary_categories": [],
                         "reasoning": "r", "summary": "s", "confidence": 0.9}]})
data = upload("意見", ["希望多開訓練課程"])
check("開放式：AI 歸納成功才分析（自動主題、暫定分類）",
      data["classified_count"] == 1 and data["columns"][0]["routing_status"] == "auto_topic" and data["provisional_taxonomy"])
check("開放式成功：沒有使用 legacy 分類規則", not legacy_rules_used())

with app.app_context():
    seed_topic("career")
    record_bootstrap_result(result={"status": "created", "created_topics": ["career"]})
    health = taxonomy_bootstrap_health()
check("成功後：status=created、有成功時間、沒有警告、錯誤摘要清除",
      health["status"] == "created" and health["last_success_at"] and health["warning"] is None and health["error_summary"] is None)

GEMINI_QUEUE.clear()
finish()
