#!/usr/bin/env python
"""
次要分類（secondary classifications）必須完整保存與使用。

AI 回傳的真實結構：
    舊格式："secondary_sub_category": "..."（只有子類別、最多一個）
    新格式："secondary_categories": [{"main_category", "sub_category"}, ...]
兩種都要能保存；大類別以分類架構為準；支援多個。

涵蓋（對應需求 1~6，加上相容性）：
    1. AI 回傳兩個次要分類皆能保存（子表、taxonomy identity、舊欄位鏡像）
    2. 重新開 DB session 後仍存在
    3. Workspace 顯示正確（上傳回應、即時彙整都含次要分類分組，標示次要）
    4. Report / Export 納入正確
    5. 人工修改後使用 final secondary results（AI 原始的保留）
    6. re-analysis 不遺失歷史次要分類
    另外：舊格式相容、AI 大類別寫錯會被校正、不在分類架構的次要分類保留但
    不計入、舊欄位資料在清理 SQL 執行前能完整搬進子表、回填冪等。

執行方式：
    cd backend
    python3 tests/test_secondary_classifications.py
"""

import base64
import io
import os

import openpyxl
import pandas as pd

from admin_test_support import (
    GEMINI_QUEUE, admin_header, check, create_app, finish, q, seed_people, seed_topic,
    seed_workspace_chat, user_header,
)
import models as m
from extensions import db
from services.privacy_service import mask_pii

os.environ.pop("OPEN_CLASSIFICATION_ENABLED", None)
app = create_app()
client = app.test_client()

with app.app_context():
    seed_people()
    VID = seed_topic("career", categories=[
        ("職涯發展", "A1 教育訓練", "Method A1", "Cite A1"),
        ("職涯發展", "A2 升遷制度", "Method A2", "Cite A2"),
        ("薪酬福利", "C1 薪資", "Method C1", "Cite C1"),
        ("工作環境", "E1 設施", "Method E1", "Cite E1"),
    ])
    CAT_ID = {c.sub_category: c.category_id for c in m.Taxonomy_Category.query.all()}


def upload(column, texts):
    df = pd.DataFrame({column: texts})
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    buf.seek(0)
    resp = client.post("/api/classification/upload", data={"file": (buf, "u.xlsx"), "text_column": column},
                       headers=user_header(1), content_type="multipart/form-data")
    return resp.get_json()


TEXTS = ["薪水太低也沒有訓練課程", "升遷不透明", "冷氣太冷"]
GEMINI_QUEUE.clear()
q({"question_type": "career"})
# 回答 0：新格式，兩個次要分類（其中一個 AI 大類別寫錯 -> 以分類架構校正）
q({"segments": [mask_pii(TEXTS[0])]})
q({"classifications": [{"index": 0, "main_category": "薪酬福利", "sub_category": "C1 薪資",
                         "secondary_categories": [
                             {"main_category": "職涯發展", "sub_category": "A1 教育訓練"},
                             {"main_category": "寫錯的大類", "sub_category": "E1 設施"},
                             {"main_category": "自創", "sub_category": "不存在的子類"},
                         ],
                         "reasoning": "r0", "summary": "s0", "confidence": 0.9}]})
# 回答 1：舊格式（只有 secondary_sub_category）
q({"segments": [mask_pii(TEXTS[1])]})
q({"classifications": [{"index": 0, "main_category": "職涯發展", "sub_category": "A2 升遷制度",
                         "secondary_sub_category": "C1 薪資", "reasoning": "r1", "summary": "s1", "confidence": 0.9}]})
# 回答 2：沒有次要分類
q({"segments": [mask_pii(TEXTS[2])]})
q({"classifications": [{"index": 0, "main_category": "工作環境", "sub_category": "E1 設施",
                         "secondary_categories": [], "reasoning": "r2", "summary": "s2", "confidence": 0.9}]})
data = upload("意見", TEXTS)
BATCH = data["upload_batch_id"]
check("上傳 201、3 則都分類", data["classified_count"] == 3)

print("\n========== 1. 兩個次要分類皆能保存 ==========")
with app.app_context():
    rows = m.Response_Classification.query.filter_by(upload_batch_id=BATCH).order_by(
        m.Response_Classification.classification_id).all()
    R0, R1, R2 = [r.classification_id for r in rows]
    children = m.Response_Classification_Secondary.query.filter_by(classification_id=R0, kind="ai").order_by(
        m.Response_Classification_Secondary.position).all()
    check("回答 0：子表 3 列（2 個在分類架構內 + 1 個不在）", len(children) == 3)
    check("第 1 個：職涯發展 / A1 教育訓練 + category identity",
          (children[0].main_category, children[0].sub_category) == ("職涯發展", "A1 教育訓練")
          and children[0].taxonomy_category_id == CAT_ID["A1 教育訓練"] and children[0].taxonomy_version_id == VID
          and children[0].in_taxonomy and children[0].methodology == "Method A1")
    check("第 2 個：AI 大類別寫錯 -> 以分類架構校正為 工作環境",
          (children[1].main_category, children[1].sub_category) == ("工作環境", "E1 設施") and children[1].in_taxonomy)
    check("第 3 個：不在分類架構 -> in_taxonomy=False、保留紀錄", children[2].sub_category == "不存在的子類"
          and not children[2].in_taxonomy and children[2].taxonomy_category_id is None)
    r0 = db.session.get(m.Response_Classification, R0)
    r0d = r0.to_dict()
    check("API 相容 key 取第一個次要分類（含大類別）",
          (r0d["secondary_main_category"], r0d["secondary_sub_category"], r0d["secondary_methodology"]) == ("職涯發展", "A1 教育訓練", "Method A1"))
    c1 = m.Response_Classification_Secondary.query.filter_by(classification_id=R1).all()
    check("回答 1（舊格式）：1 列、大類別由分類架構補上",
          len(c1) == 1 and (c1[0].main_category, c1[0].sub_category) == ("薪酬福利", "C1 薪資") and c1[0].in_taxonomy)
    check("回答 2：沒有次要分類", m.Response_Classification_Secondary.query.filter_by(classification_id=R2).count() == 0)

print("\n========== 2. 重新開 DB session 後仍存在 ==========")
with app.app_context():
    db.session.remove()
with app.app_context():
    r0 = db.session.get(m.Response_Classification, R0)
    d = r0.to_dict()
    check("to_dict 的 secondary_categories 3 個（順序保留）",
          [s["sub_category"] for s in d["secondary_categories"]] == ["A1 教育訓練", "E1 設施", "不存在的子類"])
    from services.effective_classification_service import effective_view
    view = effective_view(r0, include_methodology=True)
    check("effective 次要分類只含分類架構內的 2 個",
          [(s["main_category"], s["sub_category"]) for s in view["secondary_categories"]]
          == [("職涯發展", "A1 教育訓練"), ("工作環境", "E1 設施")])
    check("effective 次要分類帶 methodology", [s["methodology"] for s in view["secondary_categories"]] == ["Method A1", "Method E1"])

print("\n========== 3. Workspace 顯示正確 ==========")
groups = {g["sub_category"]: g for g in data["aggregated_groups"]}


def find_group(groups_by_sub, keyword):
    return next((g for sub, g in groups_by_sub.items() if keyword in sub), None)


a1 = find_group(groups, "教育訓練")
check("上傳回應：A1 教育訓練分組出現（來自回答 0 的次要分類）", a1 is not None and a1["secondary_count"] == 1
      and "（次要分類）" in a1["respondent_text"])
e1 = find_group(groups, "設施")
check("E1 設施：回答 2（主要）+ 回答 0（次要）", e1 is not None and e1["respondent_count"] == 2 and e1["secondary_count"] == 1)
c1g = find_group(groups, "薪資")
check("C1 薪資：回答 0（主要）+ 回答 1（舊格式次要）", c1g is not None and c1g["respondent_count"] == 2 and c1g["secondary_count"] == 1)
check("不在分類架構的次要分類沒有變成分組", find_group(groups, "不存在") is None)
with app.app_context():
    from services.workspace_result_service import build_live_groups
    live = {g["sub_category"]: g for g in build_live_groups({"source_type": "user_upload", "upload_batch_id": BATCH})}
    check("Workspace 即時彙整與上傳回應一致（次要分組相同）",
          {s: (g["respondent_count"], g["secondary_count"]) for s, g in live.items()}
          == {s: (g["respondent_count"], g["secondary_count"]) for s, g in groups.items()})

print("\n========== 5. 人工修改後使用 final secondary ==========")
resp = client.post(f"/api/classification/{R1}/review/confirm-manual", headers=admin_header(1), json={
    "sub_category": "A2 升遷制度", "secondary_sub_categories": ["A1 教育訓練", "E1 設施", "A2 升遷制度"],
})
check("confirm-manual（兩個次要分類）200", resp.status_code == 200)
body = resp.get_json()
check("回應的 final_secondary_categories = A1、E1（跟主要相同的自動略過）",
      [s["sub_category"] for s in body["final_secondary_categories"]] == ["A1 教育訓練", "E1 設施"])
check("AI 原始次要分類保留（C1 薪資）", [s["sub_category"] for s in body["secondary_categories"]] == ["C1 薪資"])
resp = client.post(f"/api/classification/{R2}/review/confirm-manual", headers=admin_header(1),
                   json={"sub_category": "E1 設施", "secondary_sub_categories": ["不存在"]})
check("清單外的次要分類 -> 400", resp.status_code == 400 and resp.get_json()["code"] == "INVALID_CATEGORY")
client.post(f"/api/classification/{R0}/review/confirm-original", headers=admin_header(1))
client.post(f"/api/classification/{R2}/review/confirm-original", headers=admin_header(1))
with app.app_context():
    r1 = db.session.get(m.Response_Classification, R1)
    finals = [c for c in r1.secondaries if c.kind == "final"]
    check("final 子表：2 列、created_by_admin_id、category identity",
          len(finals) == 2 and all(c.created_by_admin_id == 1 and c.in_taxonomy for c in finals)
          and finals[0].taxonomy_category_id == CAT_ID["A1 教育訓練"])
    r1d = r1.to_dict()
    check("API 相容 key final_secondary_* 取第一個", (r1d["final_secondary_main_category"], r1d["final_secondary_sub_category"]) == ("職涯發展", "A1 教育訓練"))
    view = effective_view(r1)
    check("effective 用人工 final（A1、E1），不是 AI 的 C1",
          [s["sub_category"] for s in view["secondary_categories"]] == ["A1 教育訓練", "E1 設施"])
    audit = m.Admin_Audit_Log.query.filter_by(entity_id=str(R1), action="modify").order_by(m.Admin_Audit_Log.audit_id.desc()).first()
    check("audit 記錄 final 次要分類清單", audit is not None and "E1 設施" in str(audit.after_state.get("final_secondary_categories")))

print("\n========== 4. Report / Export 納入正確 ==========")
GEMINI_QUEUE.clear()
q(*[{"summary": "報告摘要"}] * 4)  # C1、A1、E1、A2 四個分組
resp = client.post(f"/api/admin/ai/reports/user_upload/{BATCH}/generate", headers=admin_header(1))
check("report 201", resp.status_code == 201)
detail = client.get(f"/api/admin/ai/reports/detail/{resp.get_json()['report']['report_id']}", headers=admin_header(1)).get_json()
agg = {a["sub_category"]: a for a in detail["aggregations"]}
check("report 分組：C1、A1、E1、A2", set(agg) == {"C1 薪資", "A1 教育訓練", "E1 設施", "A2 升遷制度"})
check("report C1 只有回答 0（回答 1 被人工改成沒有 C1）", [i["classification_id"] for i in agg["C1 薪資"]["items"]] == [R0])
check("report A1：回答 0（AI 次要）+ 回答 1（人工 final 次要）",
      sorted(i["classification_id"] for i in agg["A1 教育訓練"]["items"]) == sorted([R0, R1]))
check("report E1：回答 2（主要）+ 回答 0、1（次要）", agg["E1 設施"]["segment_count"] == 3)
check("report 次要分組的 methodology 來自分類架構", agg["A1 教育訓練"]["methodology"] == "Method A1")
check("不在分類架構的次要分類不進報告", "不存在的子類" not in agg)

with app.app_context():
    chat_id = seed_workspace_chat(BATCH)
resp = client.post("/api/exports", headers=user_header(1), json={
    "chat_id": chat_id, "filename": "o.xlsx", "export_type": "xlsx",
    "rows": [{"main_category": "舊", "sub_category": "舊快照", "respondent_text": "old"}],  # 前端送來的舊快照
})
check("export 使用後端結果（次要分類改變 -> 快照過期重建）", resp.status_code == 201 and resp.get_json()["rows_source"] == "server")
with app.app_context():
    export = db.session.get(m.Export_File, resp.get_json()["export_id"])
    wb = openpyxl.load_workbook(io.BytesIO(base64.b64decode(export.content)))
    cells = " ".join(str(c.value) for ws in wb.worksheets for r in ws.iter_rows() for c in r if c.value)
check("export 含次要分組與標示、不含前端舊快照", "教育訓練" in cells and "（次要分類）" in cells and "舊快照" not in cells)

print("\n========== 6. re-analysis 不遺失歷史次要分類 ==========")
with app.app_context():
    tpl = m.Survey_Template(user_id=1, title="問卷", access_code="SEC1", question_json={"items": [
        {"id": "q1", "type": "short", "title": "建議", "question_type": "career"}]})
    db.session.add(tpl)
    db.session.flush()
    resp_row = m.Survey_Response(template_id=tpl.template_id, answer_json={"answers": {"q1": "訓練不夠。薪水低"}})
    db.session.add(resp_row)
    db.session.flush()
    db.session.add(m.Response_Segmentation_Status(response_id=resp_row.response_id, question_id="q1",
                                                  source_type="survey", segmentation_status="partial_failed"))
    old = m.Response_Classification(response_id=resp_row.response_id, source_type="survey", question_id="q1",
                                    answer_text="訓練不夠。薪水低", segment_start=0, segment_end=4,
                                    main_category="職涯發展", sub_category="A1 教育訓練", status="completed",
                                    review_status="pending_review", taxonomy_version_id=VID)
    old.secondaries.append(m.Response_Classification_Secondary(kind="ai", position=0, main_category="薪酬福利",
                                                               sub_category="C1 薪資", in_taxonomy=True, taxonomy_version_id=VID))
    db.session.add(old)
    failed = m.Response_Classification(response_id=resp_row.response_id, source_type="survey", question_id="q1",
                                       answer_text="訓練不夠。薪水低", segment_start=5, segment_end=8,
                                       status="failed", review_status="pending_review", taxonomy_version_id=VID)
    db.session.add(failed)
    db.session.commit()
    OLD_ID = old.classification_id
GEMINI_QUEUE.clear()
q({"segments": [mask_pii("訓練不夠。薪水低")]})
q({"classifications": [{"index": 0, "main_category": "職涯發展", "sub_category": "A1 教育訓練",
                         "secondary_categories": [{"main_category": "職涯發展", "sub_category": "A2 升遷制度"}],
                         "reasoning": "r", "summary": "s", "confidence": 0.9}]})
resp = client.post("/api/surveys/SEC1/analyze", headers=user_header(1))
check("重新分析 200、生效 1 則", resp.status_code == 200 and resp.get_json()["newly_classified_count"] == 1)
with app.app_context():
    old = db.session.get(m.Response_Classification, OLD_ID)
    check("舊 attempt superseded，但它的次要分類仍在（歷史）", old.status == "superseded"
          and [c.sub_category for c in old.secondaries] == ["C1 薪資"])
    new = m.Response_Classification.query.filter_by(response_id=old.response_id, attempt_no=2).one()
    check("新 attempt 有自己的次要分類", [c.sub_category for c in new.secondaries] == ["A2 升遷制度"])

print("\n========== 舊欄位回填（清理 SQL 執行前的正式資料庫）==========")
with app.app_context():
    from sqlalchemy import text
    from services.secondary_classification_service import (
        LEGACY_SECONDARY_COLUMNS, backfill_legacy_secondaries, count_unmigrated_legacy_secondaries,
    )

    check("舊欄位不存在時回填直接略過", backfill_legacy_secondaries().get("skipped") is True)

    # 模擬還沒執行清理 SQL 的舊資料庫：舊欄位仍在，舊資料只有舊欄位、沒有子表列
    for col in LEGACY_SECONDARY_COLUMNS:
        db.session.execute(text(f"ALTER TABLE Response_Classification ADD COLUMN {col} TEXT"))
    legacy = m.Response_Classification(
        source_type="user_upload", upload_batch_id=BATCH, uploaded_answer_id=rows[0].uploaded_answer_id,
        question_id="legacy", answer_text="舊資料", segment_start=0, segment_end=3,
        main_category="職涯發展", sub_category="A2 升遷制度",
        status="completed", review_status="confirmed", taxonomy_version_id=VID,
    )
    legacy_final = m.Response_Classification(
        source_type="user_upload", upload_batch_id=BATCH, uploaded_answer_id=rows[0].uploaded_answer_id,
        question_id="legacy2", answer_text="舊資料二", segment_start=0, segment_end=4,
        main_category="職涯發展", sub_category="A2 升遷制度", status="completed", review_status="modified",
        final_main_category="職涯發展", final_sub_category="A1 教育訓練",
        taxonomy_version_id=VID,
    )
    db.session.add_all([legacy, legacy_final])
    db.session.commit()
    db.session.execute(text("UPDATE Response_Classification SET secondary_sub_category = 'C1 薪資' "
                            "WHERE classification_id = :id"), {"id": legacy.classification_id})
    db.session.execute(text("UPDATE Response_Classification SET final_secondary_sub_category = 'E1 設施' "
                            "WHERE classification_id = :id"), {"id": legacy_final.classification_id})
    db.session.commit()
    check("前置：2 筆舊資料尚未搬到子表", count_unmigrated_legacy_secondaries() == 2)

    first = backfill_legacy_secondaries()
    second = backfill_legacy_secondaries()
    check("回填：ai 1 列、final 1 列", first["ai"] == 1 and first["final"] == 1)
    check("回填冪等：第二次 0 列", second["ai"] == 0 and second["final"] == 0)
    check("回填後沒有未搬移的資料（可以安全執行清理 SQL）", count_unmigrated_legacy_secondaries() == 0)
    db.session.expire_all()
    legacy = db.session.get(m.Response_Classification, legacy.classification_id)
    legacy_final = db.session.get(m.Response_Classification, legacy_final.classification_id)
    view = effective_view(legacy, include_methodology=True)
    check("回填後由分類架構補出大類別與方法（可以進彙整）",
          [(s["main_category"], s["sub_category"], s["methodology"]) for s in view["secondary_categories"]]
          == [("薪酬福利", "C1 薪資", "Method C1")])
    check("舊 modified 的 final 次要分類也搬過來", [s["sub_category"] for s in effective_view(legacy_final)["secondary_categories"]] == ["E1 設施"])
    from services.aggregation_service import build_aggregation
    agg = {(g["main_category"], g["sub_category"]): g for g in build_aggregation("user_upload", upload_batch_id=BATCH)}
    check("舊資料的次要分類進入 report 彙整", legacy.classification_id in [i["classification_id"] for i in agg[("薪酬福利", "C1 薪資")]["items"]])

finish()
