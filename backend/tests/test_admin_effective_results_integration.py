#!/usr/bin/env python
"""
P0-1 integration：Admin 人工審核結果真正進入 Workspace / Report / Export /
Chat 追問，而且是 DB persistence（重新載入後仍存在），不是前端 state。

情境（同一個上傳批次，3 位受試者）：
    r0：AI=A1，Admin modified -> B1（final_*）
    r1：AI=A1，Admin excluded
    r2：AI=A1，confirmed
    r3：AI=A1，status=failed（永遠不算）
    r4：legacy（taxonomy_version_id=NULL）AI=A1，modified -> legacy 表裡的子類別

驗證：
    1. Workspace 訊息 freshness 判定過期 -> refresh 後 rows 顯示 B1，原 A1
       不再計入 r0，excluded / failed 不出現。
    2. refresh 結果寫回 Chat_History：重新讀 /api/chat/history 仍是新結果。
    3. 匯出（/api/exports）不信任前端舊 rows，使用後端 effective 結果。
    4. Report 使用人工結果（B1 分組、無 excluded / failed / pending）。
    5. Chat 追問 context（_collect_items）與畫面同一套規則。
    6. legacy 分類 modified 仍能查到 methodology（legacy 表），動態 taxonomy
       modified 用該版 Taxonomy_Category。
    7. 單純 confirm 不會讓 Workspace 判定需要重建（只看畫面指紋）。

執行方式：
    cd backend
    python3 tests/test_admin_effective_results_integration.py
"""

import base64
import io

import openpyxl

from admin_test_support import (
    admin_header, check, create_app, finish, q, seed_classification, seed_people, seed_topic,
    seed_upload_batch, seed_workspace_chat, user_header,
)
import models as m
from extensions import db

app = create_app()
client = app.test_client()
BATCH = "batch-eff"

with app.app_context():
    seed_people()
    version_id = seed_topic()
    texts = ["受試者零的意見", "受試者一的意見", "受試者二的意見", "受試者三的意見", "受試者四的意見"]
    answer_ids = seed_upload_batch(BATCH, texts)
    cids = [
        seed_classification(answer_ids[0], BATCH, texts[0], "Main A", "A1 Original", version_id=version_id,
                            review_status="modified", final_main_category="Main B",
                            final_sub_category="B1 Candidate", final_reasoning="人工修正理由"),
        seed_classification(answer_ids[1], BATCH, texts[1], "Main A", "A1 Original", version_id=version_id,
                            review_status="excluded"),
        seed_classification(answer_ids[2], BATCH, texts[2], "Main A", "A1 Original", version_id=version_id,
                            review_status="confirmed"),
        seed_classification(answer_ids[3], BATCH, texts[3], "Main A", "A1 Original", version_id=version_id,
                            status="failed"),
        seed_classification(answer_ids[4], BATCH, texts[4], "工作表現的回饋及職涯發展", "A5 教育訓練",
                            version_id=None, review_status="modified",
                            final_main_category="部門合作", final_sub_category="B2 支援協作",
                            final_reasoning="legacy 人工修正"),
    ]
    # 分析當下（review 之前）存進 Chat_History 的舊快照：全部 A1
    stale_rows = [{"main_category": "Main A", "sub_category": "A1", "respondent_text": "受試者1：受試者零的意見\n受試者2：受試者一的意見",
                   "aggregated_reasoning": "old", "aggregated_summary": "old"}]
    chat_id = seed_workspace_chat(BATCH, rows=stale_rows)


def all_text(rows):
    return "\n".join(f"{r['main_category']}|{r['sub_category']}|{r['respondent_text']}|{r['aggregated_reasoning']}" for r in rows)


print("========== 1. Workspace freshness / refresh ==========")
resp = client.get(f"/api/chat/{chat_id}/classification-result/freshness", headers=user_header(1))
check("freshness 200", resp.status_code == 200)
check("舊快照（沒有 review_revision）被判定過期", resp.get_json()["stale"] is True and resp.get_json()["has_source"] is True)
check("非 owner 不能讀 freshness", client.get(f"/api/chat/{chat_id}/classification-result/freshness").status_code == 401)

resp = client.post(f"/api/chat/{chat_id}/classification-result/refresh", headers=user_header(1))
check("refresh 200", resp.status_code == 200)
rows = resp.get_json()["rows"]
blob = all_text(rows)
check("modified 的 r0 出現在 B1（Main B）", any(r["main_category"] == "Main B" and "受試者零" in r["respondent_text"] for r in rows))
check("r0 不再被計入原本的 A1 分組",
      not any(r["main_category"] == "Main A" and "受試者零" in r["respondent_text"] for r in rows))
check("excluded 的 r1 完全不出現", "受試者一" not in blob)
check("confirmed 的 r2 仍在 A1（Main A）", any(r["main_category"] == "Main A" and "受試者二" in r["respondent_text"] for r in rows))
check("failed 的 r3 不出現", "受試者三" not in blob)
check("legacy modified 的 r4 用 final_*（部門合作）", any(r["main_category"] == "部門合作" and "受試者四" in r["respondent_text"] for r in rows))
check("彙整理由使用人工 final_reasoning（fallback 文字）", "人工修正理由" in blob)
check("refresh 後 meta 帶 review_revision", bool(resp.get_json()["meta"].get("review_revision")))


print("\n========== 2. 重新載入（新 request）後結果仍在 ==========")
with app.app_context():
    db.session.remove()
resp = client.get("/api/chat/history/1", headers=user_header(1))
history_text = str(resp.get_json())
check("chat history 200", resp.status_code == 200)
check("重新讀取的 Chat_History 已是新結果（含 Main B）", "Main B" in history_text and "受試者一的意見" not in history_text)
resp = client.get(f"/api/chat/{chat_id}/classification-result/freshness", headers=user_header(1))
check("refresh 後 freshness=not stale", resp.get_json()["stale"] is False)


print("\n========== 3. 匯出使用後端 effective 結果 ==========")
resp = client.post("/api/exports", headers=user_header(1), json={
    "chat_id": chat_id, "filename": "out.xlsx", "export_type": "xlsx",
    "rows": stale_rows,  # 前端送來的是舊快照
})
check("export 201", resp.status_code == 201)
check("rows_source=server", resp.get_json()["rows_source"] == "server")
with app.app_context():
    export = db.session.get(m.Export_File, resp.get_json()["export_id"])
    wb = openpyxl.load_workbook(io.BytesIO(base64.b64decode(export.content)))
    cells = " ".join(str(c.value) for ws in wb.worksheets for r in ws.iter_rows() for c in r if c.value)
check("匯出檔含人工分類 Main B", "Main B" in cells)
check("匯出檔不含 excluded 的回答", "受試者一的意見" not in cells)
check("匯出檔不含 failed 的回答", "受試者三的意見" not in cells)
check("匯出檔不含前端舊快照文字 old", "old" not in cells.split())


print("\n========== 4. Report 使用人工結果 ==========")
q(*[{"summary": "報告摘要"}] * 3)  # 3 個 group 各一次 aggregated summary
resp = client.post(f"/api/admin/ai/reports/user_upload/{BATCH}/generate", headers=admin_header(1))
check("admin generate 201", resp.status_code == 201)
report_id = resp.get_json()["report"]["report_id"]
detail = client.get(f"/api/admin/ai/reports/detail/{report_id}", headers=admin_header(1)).get_json()
groups = {(a["main_category"], a["sub_category"]): [i["uploaded_answer_id"] for i in a["items"]] for a in detail["aggregations"]}
check("B1 分組包含 r0", answer_ids[0] in groups.get(("Main B", "B1 Candidate"), []))
check("A1 分組只有 confirmed 的 r2", groups.get(("Main A", "A1 Original")) == [answer_ids[2]])
flat = [i for ids in groups.values() for i in ids]
check("report 不含 excluded / failed", answer_ids[1] not in flat and answer_ids[3] not in flat)
b1 = next(a for a in detail["aggregations"] if a["sub_category"] == "B1 Candidate")
check("modified 動態 taxonomy 的 methodology 來自該版 category", b1["methodology"] == "Method B1")
legacy = next(a for a in detail["aggregations"] if a["sub_category"] == "B2 支援協作")
check("legacy modified 的 methodology 來自 legacy 表（非 None）", legacy["methodology"] is not None)
check("report 記錄 taxonomy versions（含 legacy）",
      str(version_id) in detail["taxonomy_version_ids"] and "legacy" in detail["taxonomy_version_ids"])
resp = client.get(f"/api/admin/ai/reports/detail/{report_id}/export?format=xlsx", headers=admin_header(1))
wb = openpyxl.load_workbook(io.BytesIO(resp.data))
cells = " ".join(str(c.value) for ws in wb.worksheets for r in ws.iter_rows() for c in r if c.value)
check("報告匯出 200 且含 B1、不含 excluded", resp.status_code == 200 and "B1 Candidate" in cells and "受試者一的意見" not in cells)


print("\n========== 5. Chat 追問 context 同一套規則 ==========")
with app.app_context():
    from services.chat_ask_service import _collect_items
    items = _collect_items({"source_type": "user_upload", "upload_batch_id": BATCH})
    excerpts = " ".join(i["excerpt"] for i in items)
    check("追問 context 不含 excluded / failed", "受試者一" not in excerpts and "受試者三" not in excerpts)
    r0 = next(i for i in items if "受試者零" in i["excerpt"])
    check("追問 context 的 r0 是 Main B + 對應 methodology", r0["main_category"] == "Main B" and r0["methodology"] == "Method B1")


print("\n========== 6. 單純 confirm 不觸發 Workspace 重建 ==========")
with app.app_context():
    extra = seed_classification(seed_upload_batch(BATCH, ["受試者五的意見"])[0], BATCH, "受試者五的意見",
                                "Main A", "A1 Original", version_id=version_id)
client.post(f"/api/chat/{chat_id}/classification-result/refresh", headers=user_header(1))
check("新增 pending 列 refresh 後 not stale",
      client.get(f"/api/chat/{chat_id}/classification-result/freshness", headers=user_header(1)).get_json()["stale"] is False)
client.post(f"/api/classification/{extra}/review/confirm-original", headers=admin_header(1))
check("confirm（畫面不變）不會讓快照過期",
      client.get(f"/api/chat/{chat_id}/classification-result/freshness", headers=user_header(1)).get_json()["stale"] is False)
client.post(f"/api/classification/{extra}/review/reopen", headers=admin_header(1))
client.post(f"/api/classification/{extra}/review/exclude", headers=admin_header(1))
check("exclude（畫面改變）讓快照過期",
      client.get(f"/api/chat/{chat_id}/classification-result/freshness", headers=user_header(1)).get_json()["stale"] is True)

finish()
