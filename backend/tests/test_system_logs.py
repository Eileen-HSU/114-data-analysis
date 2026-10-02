#!/usr/bin/env python
"""
系統紀錄管理（手冊 4.3）：錯誤紀錄、操作紀錄、系統狀態。

涵蓋：
    1. 非預期的 500：瀏覽器只看到一般訊息和錯誤編號，內部細節不外洩；錯誤紀錄有
       路徑、方法、去敏的 stack trace
    2. 同一種錯誤合併累加次數（數字不同也算同一種）；AI 額度錯誤自動分類
    3. 程式裡的 logger.exception 也會被記錄；資料庫底層的 log 不記錄
    4. 請求被 rollback 時錯誤紀錄仍然保留
    5. 記錄錯誤本身不會造成錯誤（遞迴保護）
    6. Admin API：錯誤清單／篩選／明細／標記已處理、忽略、重新開啟；權限
    7. 操作紀錄總覽：依動作、人員（含系統）、日期篩選，顯示人員名稱
    8. 系統狀態：各部分狀態，不會回傳任何 key 的值
    9. 保留期限：舊紀錄自動清除

執行方式：
    cd backend
    python3 tests/test_system_logs.py
"""

import json
import logging
import os
from datetime import timedelta

from admin_test_support import admin_header, check, create_app, finish, seed_people, user_header
import models as m
from extensions import db, taiwan_now
from services import error_log_service as els

FAKE_KEY = "AIzaSyFAKEKEYFORTESTS_1234567890abcdef"
os.environ["GEMINI_API_KEY"] = FAKE_KEY
os.environ.pop("ADMIN_GEMINI_API_KEY", None)

app = create_app()
els.install(app)


@app.route("/test/boom")
def boom():
    raise RuntimeError(f"connection to db-internal.example:3306 failed (key={FAKE_KEY}) attempt 3")


@app.route("/test/boom-rollback")
def boom_rollback():
    db.session.add(m.Topic(topic_key="should_not_exist", title="不該存在"))
    db.session.flush()
    raise ValueError("寫入一半失敗")


@app.route("/test/logged")
def logged():
    try:
        raise KeyError("missing field")
    except KeyError:
        logging.getLogger("routes.auth.login").exception("Login error: 處理登入時發生錯誤")
    return {"ok": True}


client = app.test_client()
with app.app_context():
    seed_people()


def errors():
    with app.app_context():
        return [e.to_dict(include_detail=True) for e in m.System_Error_Log.query.order_by(m.System_Error_Log.error_id).all()]


print("========== 1. 非預期的 500 ==========")
resp = client.get("/test/boom")
body = resp.get_json()
check("回 500 與錯誤編號", resp.status_code == 500 and isinstance(body.get("error_id"), int))
check("瀏覽器看不到內部細節（主機名稱、key、例外內容）",
      "db-internal" not in json.dumps(body) and FAKE_KEY not in json.dumps(body) and "RuntimeError" not in json.dumps(body))
check("訊息是一般說明，附錯誤編號", body["message"].startswith("伺服器發生錯誤") and str(body["error_id"]) in body["message"])
row = errors()[0]
check("錯誤紀錄有路徑、方法、狀態碼、代碼",
      row["path"] == "/test/boom" and row["method"] == "GET" and row["status_code"] == 500 and row["code"] == "SERVER_ERROR")
check("錯誤紀錄有 stack trace，而且 key 被遮掉",
      "Traceback" in row["detail"] and FAKE_KEY not in row["detail"] and FAKE_KEY not in row["message"]
      and "[REDACTED" in row["message"])
check("stack trace 保留換行（看得懂）", "\n" in row["detail"])

import io  # noqa: E402

console = next(h for h in logging.getLogger().handlers if isinstance(h, logging.StreamHandler)
               and not isinstance(h, els.DatabaseErrorHandler))
captured, original_stream = io.StringIO(), console.stream
console.stream = captured
client.get("/test/boom")
console.stream = original_stream
printed = captured.getvalue()
check("印到主機 log 的內容也去除 key（但仍有 stack trace 可以除錯）",
      FAKE_KEY not in printed and "[REDACTED" in printed and "Traceback" in printed)


print("\n========== 2. 合併相同錯誤、AI 錯誤分類 ==========")
client.get("/test/boom")
rows = errors()
check("同一種錯誤合併成一筆、次數 3", len(rows) == 1 and rows[0]["occurrence_count"] == 3)
gemini_logger = logging.getLogger("services.gemini_client")
gemini_logger.error("Gemini 呼叫失敗（模型 m）：429 RESOURCE_EXHAUSTED. Please retry in 14.37s.")
gemini_logger.error("Gemini 呼叫失敗（模型 m）：429 RESOURCE_EXHAUSTED. Please retry in 58.62s.")
quota = [r for r in errors() if r["code"] == "AI_QUOTA_EXCEEDED"]
check("AI 額度用完自動分類為 AI_QUOTA_EXCEEDED", len(quota) == 1)
check("只差在秒數的額度錯誤合併成一筆、次數 2", quota and quota[0]["occurrence_count"] == 2)


print("\n========== 3. logger.exception 也會記錄；資料庫底層不記錄 ==========")
before = len(errors())
resp = client.get("/test/logged")
check("程式自己處理掉的錯誤，請求照常回應", resp.status_code == 200)
logged_rows = [r for r in errors() if r["source"] == "routes.auth.login"]
check("logger.exception 被記錄，含路徑與 stack trace",
      len(logged_rows) == 1 and logged_rows[0]["path"] == "/test/logged" and "KeyError" in logged_rows[0]["detail"])
logging.getLogger("sqlalchemy.engine").error("noisy driver error")
logging.getLogger("services.something").warning("只是警告")
check("資料庫底層的 log、WARNING 都不記錄", len(errors()) == before + 1)


print("\n========== 4. 請求 rollback 時錯誤紀錄仍保留 ==========")
resp = client.get("/test/boom-rollback")
with app.app_context():
    check("請求寫到一半的資料被 rollback", m.Topic.query.filter_by(topic_key="should_not_exist").count() == 0)
check("但錯誤紀錄留下來了", any(r["path"] == "/test/boom-rollback" for r in errors()))


print("\n========== 5. 記錄錯誤不會造成錯誤 ==========")
els._state.busy = True
with app.app_context():
    check("記錄中又遇到錯誤：直接略過、不遞迴", els.record_error(source="x", message="y") is None)
els._state.busy = False
original_engine_table = m.System_Error_Log.__table__
with app.app_context():
    db.session.execute(db.text("ALTER TABLE System_Error_Log RENAME TO System_Error_Log_tmp"))
    db.session.commit()
    check("錯誤紀錄表壞掉時不會往外拋例外", els.record_error(source="x", message="y") is None)
    db.session.execute(db.text("ALTER TABLE System_Error_Log_tmp RENAME TO System_Error_Log"))
    db.session.commit()


print("\n========== 6. Admin API：錯誤紀錄 ==========")
check("非管理員不能看", client.get("/api/admin/ai/system/errors", headers=user_header(1)).status_code in (401, 403))
body = client.get("/api/admin/ai/system/errors", headers=admin_header(1)).get_json()
check("清單依最近發生排序，附代碼清單", body["total"] == len(errors()) and "AI_QUOTA_EXCEEDED" in body["codes"]
      and "detail" not in body["errors"][0])
body = client.get("/api/admin/ai/system/errors?code=AI_QUOTA_EXCEEDED", headers=admin_header(1)).get_json()
check("依代碼篩選", body["total"] == 1 and body["errors"][0]["code"] == "AI_QUOTA_EXCEEDED")
body = client.get("/api/admin/ai/system/errors?q=boom-rollback", headers=admin_header(1)).get_json()
check("搜尋路徑", body["total"] == 1)
boom_id = errors()[0]["error_id"]
detail = client.get(f"/api/admin/ai/system/errors/{boom_id}", headers=admin_header(1)).get_json()
check("明細含 stack trace", "Traceback" in detail["detail"])
resp = client.post(f"/api/admin/ai/system/errors/{boom_id}/status", headers=admin_header(1),
                   json={"status": "resolved", "note": "資料庫連線設定已修正"})
check("標記已處理，記錄處理人與說明", resp.status_code == 200 and resp.get_json()["status"] == "resolved"
      and resp.get_json()["resolved_by_admin_id"] == 1 and resp.get_json()["resolution_note"] == "資料庫連線設定已修正")
client.get("/test/boom")
boom_rows = [r for r in errors() if r["path"] == "/test/boom"]
check("已處理後同一種錯誤再發生 -> 新的一筆（不會被藏在已處理裡）",
      len(boom_rows) == 2 and boom_rows[-1]["status"] == "open" and boom_rows[-1]["occurrence_count"] == 1)
body = client.get("/api/admin/ai/system/errors?status=resolved", headers=admin_header(1)).get_json()
check("依狀態篩選", body["total"] == 1)
resp = client.post(f"/api/admin/ai/system/errors/{boom_id}/status", headers=admin_header(1), json={"status": "open"})
check("可以重新開啟（清掉處理資訊）", resp.get_json()["status"] == "open" and resp.get_json()["resolved_at"] is None)
check("無效狀態 -> 400", client.post(f"/api/admin/ai/system/errors/{boom_id}/status", headers=admin_header(1),
                                   json={"status": "done"}).status_code == 400)
check("不存在 -> 404", client.get("/api/admin/ai/system/errors/99999", headers=admin_header(1)).status_code == 404)


print("\n========== 7. 操作紀錄總覽 ==========")
from audit import Admin_Audit_Log  # noqa: E402

with app.app_context():
    now = taiwan_now()
    db.session.add_all([
        Admin_Audit_Log(action="quick_confirm", entity_type="classification", entity_id="11", admin_id=1, created_at=now),
        Admin_Audit_Log(action="second_opinion", entity_type="classification", entity_id="12", admin_id=None, created_at=now),
        Admin_Audit_Log(action="bulk_exclude", entity_type="classification", entity_id="13", admin_id=0, created_at=now),
        Admin_Audit_Log(action="taxonomy_publish", entity_type="taxonomy_version", entity_id="3", admin_id=1,
                        created_at=now - timedelta(days=10)),
    ])
    db.session.commit()
    admin_name = db.session.get(m.Admin, 1).admin_name
    today = now.strftime("%Y-%m-%d")
    ten_days_ago = (now - timedelta(days=10)).strftime("%Y-%m-%d")
check("非管理員不能看", client.get("/api/admin/ai/audit-logs", headers=user_header(1)).status_code in (401, 403))
body = client.get("/api/admin/ai/audit-logs", headers=admin_header(1)).get_json()
check("列出全部、最新的在前，附動作清單與管理員清單",
      body["total"] == 4 and body["items"][-1]["action"] == "taxonomy_publish"
      and set(body["actions"]) == {"quick_confirm", "second_opinion", "bulk_exclude", "taxonomy_publish"}
      and any(a["admin_id"] == 1 for a in body["admins"]))
names = {i["action"]: i["admin_name"] for i in body["items"]}
check("顯示管理員名稱；系統自動的顯示「系統」",
      names["quick_confirm"] == admin_name and names["second_opinion"] == "系統" and names["bulk_exclude"] == "系統")
body = client.get("/api/admin/ai/audit-logs?action=quick_confirm", headers=admin_header(1)).get_json()
check("依動作篩選", body["total"] == 1)
body = client.get("/api/admin/ai/audit-logs?admin_id=system", headers=admin_header(1)).get_json()
check("篩選系統自動的", body["total"] == 2)
body = client.get(f"/api/admin/ai/audit-logs?date_from={today}&date_to={today}", headers=admin_header(1)).get_json()
check("依日期篩選（含當天）", body["total"] == 3)
body = client.get(f"/api/admin/ai/audit-logs?date_to={ten_days_ago}", headers=admin_header(1)).get_json()
check("只到某一天", body["total"] == 1 and body["items"][0]["action"] == "taxonomy_publish")
check("日期格式錯 -> 400", client.get("/api/admin/ai/audit-logs?date_from=10/01", headers=admin_header(1)).status_code == 400)
body = client.get("/api/admin/ai/audit-logs?page=2&page_size=3", headers=admin_header(1)).get_json()
check("分頁", body["total_pages"] == 2 and len(body["items"]) == 1)


print("\n========== 8. 系統狀態 ==========")
resp = client.get("/api/admin/ai/system/status", headers=admin_header(1))
status = resp.get_json()
check("系統狀態 200", resp.status_code == 200)
check("資料庫、AI、寄信、排程、背景工作、錯誤、分類架構初始化都有",
      status["database"]["ok"] is True and status["ai"]["user_key_configured"] is True
      and status["ai"]["admin_key_configured"] is False and "configured" in status["mail"]
      and "running" in status["scheduler"] and set(status["background_jobs"]) == {"retry", "second_opinion"}
      and status["errors"]["open"] >= 1 and "taxonomy_bootstrap" in status)
check("不會回傳任何 key 的值", FAKE_KEY not in resp.get_data(as_text=True))
check("非管理員不能看", client.get("/api/admin/ai/system/status", headers=user_header(1)).status_code in (401, 403))


print("\n========== 9. 保留期限 ==========")
with app.app_context():
    now = taiwan_now()
    old_closed = m.System_Error_Log(fingerprint="a", source="t", code="X", message="舊的已處理", status="resolved",
                                    first_seen_at=now - timedelta(days=100), last_seen_at=now - timedelta(days=100))
    old_open = m.System_Error_Log(fingerprint="b", source="t", code="X", message="很舊的未處理", status="open",
                                  first_seen_at=now - timedelta(days=200), last_seen_at=now - timedelta(days=200))
    recent_open = m.System_Error_Log(fingerprint="c", source="t", code="X", message="最近的未處理", status="open",
                                     first_seen_at=now - timedelta(days=100), last_seen_at=now - timedelta(days=100))
    db.session.add_all([old_closed, old_open, recent_open])
    db.session.commit()
    deleted = els.purge_old()
    remaining = {r.message for r in m.System_Error_Log.query.filter_by(code="X").all()}
check("已處理超過 90 天、未處理超過 180 天的刪除", deleted == 2 and remaining == {"最近的未處理"})

finish()
