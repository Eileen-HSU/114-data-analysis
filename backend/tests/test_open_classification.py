#!/usr/bin/env python
"""
開放式分類（services/open_classification.py）。

產品定案：既有分類只是參考值，遇到類似 / 新的資料系統仍然要能分析。

涵蓋：
    1. 既有主題：AI 提出清單外的新類別 -> status=new_category（不是失敗）、保留判斷原因、
       needs_human_review（new_category_proposed）、prompt 帶開放式規則、Workspace 標示新類別
    2. 判斷不出主題：建立「自動主題」、AI 依回答歸納暫定分類架構（draft，既有主題只當範例）、
       立即分類（不再是零結果），回應標示 provisional / auto_topic
    3. 之後遇到類似資料：routing 把自動主題列為候選 -> 沿用，不重新歸納
    4. AI 歸納失敗：不亂分類，維持未分類並寫明原因
    5. 新類別候選：Admin 列表、採用（加進可編輯草稿）、合併到既有類別
    6. 審核：新類別出現在可選清單；「維持 AI 原始分類」可用
    7. 正式報告只納入人工確認過的結果
    8. OPEN_CLASSIFICATION_ENABLED=0：回到封閉式行為

執行方式：
    cd backend
    python3 tests/test_open_classification.py
"""

import io
import os

import pandas as pd

from admin_test_support import (
    GEMINI_CALLS, GEMINI_QUEUE, admin_header, check, create_app, finish, q, seed_classification,
    seed_people, seed_topic, seed_upload_batch, user_header,
)
import models as m
from extensions import db
from services.open_classification import OPEN_SET_RULES, auto_topic_key
from services.privacy_service import mask_pii

os.environ.pop("OPEN_CLASSIFICATION_ENABLED", None)  # 預設開放模式

app = create_app()
client = app.test_client()

with app.app_context():
    seed_people()
    version_id = seed_topic("custom_topic")


def upload(column, texts):
    df = pd.DataFrame({column: texts})
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    buf.seek(0)
    resp = client.post("/api/classification/upload", data={"file": (buf, "u.xlsx"), "text_column": column},
                       headers=user_header(1), content_type="multipart/form-data")
    return resp.status_code, resp.get_json()


def classify_q(text, main, sub, confidence=0.9):
    q({"segments": [mask_pii(text)]})
    q({"classifications": [{"index": 0, "main_category": main, "sub_category": sub,
                            "secondary_sub_category": None, "reasoning": f"理由：{sub}",
                            "summary": f"摘要：{sub}", "confidence": confidence}]})


print("========== 1. 既有主題：AI 提出新類別 ==========")
GEMINI_QUEUE.clear()
GEMINI_CALLS.clear()
q({"question_type": "custom_topic"})
classify_q("希望公司提供寵物友善的辦公空間", "Main C", "寵物友善環境", confidence=0.7)
status, data = upload("意見", ["希望公司提供寵物友善的辦公空間"])
check("upload 201、分類 1 筆", status == 201 and data["classified_count"] == 1)
row = data["classifications"][0]
check("status=new_category（不是失敗、不是 methodology_not_found）", row["status"] == "new_category")
check("保留 AI 判斷原因", row["reasoning"] == "理由：寵物友善環境")
check("needs_human_review + new_category_proposed", row["needs_human_review"] and row["review_flag_reason"] == "new_category_proposed")
check("分類 prompt 帶開放式規則", any(OPEN_SET_RULES in (c["system_instruction"] or "") for c in GEMINI_CALLS))
check("Workspace 彙整標示新類別", any(g.get("is_new_category") and g["sub_category"] == "寵物友善環境" for g in data["aggregated_groups"]))
check("既有主題已發布 -> 不是暫定分類", data["provisional_taxonomy"] is False)
new_cat_cid = row["classification_id"]


print("\n========== 2. 判斷不出主題：自動主題 + AI 歸納 ==========")
GEMINI_QUEUE.clear()
GEMINI_CALLS.clear()
auto_key = auto_topic_key("雜項回饋")
q({"question_type": None})
q({"categories": [
    {"main_category": "工作環境", "sub_category": "辦公設備", "definition": "對辦公設備的意見"},
    {"main_category": "工作環境", "sub_category": "休息空間", "definition": "對休息空間的意見"},
]})
classify_q("椅子坐久了會腰痛", "工作環境", "辦公設備")
classify_q("茶水間太小常常很擠", "工作環境", "休息空間")
status, data = upload("雜項回饋", ["椅子坐久了會腰痛", "茶水間太小常常很擠"])
check("upload 201", status == 201)
check("不再是零結果：分類 2 筆", data["classified_count"] == 2)
col = data["columns"][0]
check("question_type=自動主題、routing_status=auto_topic", col["question_type"] == auto_key and col["routing_status"] == "auto_topic")
check("標示暫定分類（provisional）", col["provisional_taxonomy"] is True and data["provisional_taxonomy"] is True)
check("分類結果使用歸納出的類別", {r["sub_category"] for r in data["classifications"]} == {"辦公設備", "休息空間"})
gen_prompt = next((c["system_instruction"] for c in GEMINI_CALLS if "categories" in (c["system_instruction"] or "")), "") or ""
with app.app_context():
    versions = m.Taxonomy_Version.query.filter_by(topic_key=auto_key).all()
    check("建立 1 個 AI 歸納的 draft 版本", len(versions) == 1 and versions[0].status == "draft" and versions[0].source == "ai_generated")
    check("自動主題標題來自欄位名稱", m.Topic.query.get(auto_key).title.endswith("雜項回饋"))
    check("分類綁定該 draft 版本", all(r.taxonomy_version_id == versions[0].version_id for r in
                                       m.Response_Classification.query.filter_by(upload_batch_id=data["upload_batch_id"]).all()))
    answers = m.Uploaded_Answer.query.filter_by(upload_batch_id=data["upload_batch_id"]).all()
    check("Uploaded_Answer 記錄自動主題", all(a.question_type == auto_key and a.routing_status == "auto_topic" for a in answers))
body = client.get("/api/admin/ai/unassigned?kind=unrouted", headers=admin_header(1)).get_json()
check("自動分析過的回答不在未分類清單", not any(i["upload_batch_id"] == data["upload_batch_id"] for i in body["items"]))
topics = client.get("/api/admin/ai/taxonomy-topics", headers=admin_header(1)).get_json()["topics"]
check("Admin 主題列表看得到自動主題（草稿待審）", any(t["topic_key"] == auto_key and t["status"] == "draft" for t in topics))


print("\n========== 2b. 問卷題目沒有主題：同樣自動歸納 ==========")
with app.app_context():
    tpl = m.Survey_Template(user_id=1, title="新問卷", access_code="OPEN1", question_json={"items": [
        {"id": "q1", "type": "short", "title": "對餐廳的建議", "question_type": None},
    ]})
    db.session.add(tpl)
    db.session.flush()
    db.session.add(m.Survey_Response(template_id=tpl.template_id, answer_json={"answers": {"q1": "午餐選擇太少"}}))
    db.session.commit()
GEMINI_QUEUE.clear()
q({"categories": [{"main_category": "餐飲", "sub_category": "菜色選擇", "definition": "對菜色多樣性的意見"}]})
classify_q("午餐選擇太少", "餐飲", "菜色選擇")
resp = client.post("/api/surveys/OPEN1/analyze", headers=user_header(1))
body = resp.get_json()
check("問卷 analyze 200、分類 1 筆", resp.status_code == 200 and body["newly_classified_count"] == 1)
check("問卷標示暫定分類", body["provisional_taxonomy"] is True and body["provisional_question_ids"] == ["q1"])
check("問卷結果出現歸納出的類別", any(g["sub_category"] == "菜色選擇" for g in body["aggregated_groups"]))
with app.app_context():
    check("問卷題目對應的自動主題已建立", m.Topic.query.get(auto_topic_key("對餐廳的建議")) is not None)


print("\n========== 3. 類似資料沿用自動主題 ==========")
GEMINI_QUEUE.clear()
GEMINI_CALLS.clear()
q({"question_type": auto_key})  # routing 候選已包含自動主題
classify_q("螢幕太小看久眼睛很累", "工作環境", "辦公設備")
status, data = upload("其他意見", ["螢幕太小看久眼睛很累"])
check("routing 選到自動主題並分類", status == 201 and data["classified_count"] == 1 and data["columns"][0]["question_type"] == auto_key)
check("routing prompt 包含自動主題", any(auto_key in (c["system_instruction"] or "") for c in GEMINI_CALLS))
with app.app_context():
    check("沒有重新歸納（仍然只有 1 個版本）", m.Taxonomy_Version.query.filter_by(topic_key=auto_key).count() == 1)


print("\n========== 4. AI 歸納失敗：不亂分類 ==========")
GEMINI_QUEUE.clear()
q({"question_type": None}, "這不是 JSON")
status, data = upload("完全不同的欄位", ["一段無法歸納的內容"])
col = data["columns"][0]
check("upload 仍然 201、分類 0 筆", status == 201 and data["classified_count"] == 0)
check("維持未分類並寫明原因", col["routing_status"] == "unrouted" and col["question_type"] is None)
with app.app_context():
    answer = m.Uploaded_Answer.query.filter_by(upload_batch_id=data["upload_batch_id"]).one()
    check("routing_detail 寫明 AI 歸納失敗", "AI 自動歸納分類架構失敗" in (answer.routing_detail or ""))
    check("沒有留下半套的自動主題版本", m.Taxonomy_Version.query.filter_by(topic_key=auto_topic_key("完全不同的欄位")).count() == 0)
GEMINI_QUEUE.clear()


print("\n========== 5. 新類別候選：列表 / 採用 / 合併 ==========")
body = client.get("/api/admin/ai/new-categories", headers=admin_header(1)).get_json()
cand = next((i for i in body["items"] if i["sub_category"] == "寵物友善環境"), None)
check("列出新類別候選（主題、次數、範例）", cand is not None and cand["topic_key"] == "custom_topic" and cand["count"] == 1 and cand["examples"])
resp = client.post("/api/admin/ai/new-categories/adopt", headers=admin_header(1), json={
    "topic_key": "custom_topic", "main_category": "Main C", "sub_category": "寵物友善環境",
})
check("採用 201：建立可編輯草稿", resp.status_code == 201 and resp.get_json()["draft_created"] is True)
draft_id = resp.get_json()["taxonomy_version"]["version_id"]
with app.app_context():
    draft = db.session.get(m.Taxonomy_Version, draft_id)
    check("草稿包含原有類別 + 新類別", {c.sub_category for c in draft.categories} == {"A1 Original", "B1 Candidate", "寵物友善環境"})
    check("已發布版本不受影響", {c.sub_category for c in db.session.get(m.Taxonomy_Version, version_id).categories} == {"A1 Original", "B1 Candidate"})
    check("採用寫入 audit", m.Admin_Audit_Log.query.filter_by(action="adopt_new_category").count() == 1)
resp = client.post("/api/admin/ai/new-categories/adopt", headers=admin_header(1), json={
    "topic_key": "custom_topic", "main_category": "Main C", "sub_category": "寵物友善環境",
})
check("重複採用 -> 409 CATEGORY_EXISTS", resp.status_code == 409 and resp.get_json()["code"] == "CATEGORY_EXISTS")

with app.app_context():
    ids = seed_upload_batch("batch-merge", ["加班太多"], question_type="custom_topic")
    merge_cid = seed_classification(ids[0], "batch-merge", "加班太多", "Main A", "工時過長", version_id=version_id,
                                    status="new_category")
resp = client.post("/api/admin/ai/new-categories/merge", headers=admin_header(1), json={
    "topic_key": "custom_topic", "main_category": "Main A", "sub_category": "工時過長", "target_sub_category": "A1 Original",
})
check("合併 200", resp.status_code == 200 and resp.get_json()["merged_ids"] == [merge_cid])
with app.app_context():
    merged = db.session.get(m.Response_Classification, merge_cid)
    check("合併後 modified 到既有類別", merged.review_status == "modified" and merged.final_sub_category == "A1 Original")
check("合併後不再是候選", not any(i["sub_category"] == "工時過長" for i in client.get(
    "/api/admin/ai/new-categories", headers=admin_header(1)).get_json()["items"]))


print("\n========== 6. 審核：新類別可選、可維持 AI 原始分類 ==========")
state = client.get(f"/api/classification/{new_cat_cid}/review", headers=admin_header(1)).get_json()
check("可選清單包含 AI 提出的新類別（proposed）", any(o["sub_category"] == "寵物友善環境" and o["proposed"] for o in state["taxonomy_options"]))
resp = client.post(f"/api/classification/{new_cat_cid}/review/confirm-original", headers=admin_header(1))
check("維持 AI 原始分類（新類別）-> confirmed", resp.status_code == 200 and resp.get_json()["review_status"] == "confirmed")


print("\n========== 7. 正式報告只納入人工確認過的 ==========")
with app.app_context():
    from services.report_service import get_readiness
    batch = m.Response_Classification.query.get(new_cat_cid).upload_batch_id
    readiness = get_readiness("user_upload", upload_batch_id=batch)
    check("確認後的新類別計入 eligible", readiness["eligible"] == 1)
    auto_batch = m.Uploaded_Answer.query.filter_by(question_type=auto_key).first().upload_batch_id
    check("暫定分類未確認前 eligible=0", get_readiness("user_upload", upload_batch_id=auto_batch)["eligible"] == 0)


print("\n========== 8. 關閉開放模式 ==========")
os.environ["OPEN_CLASSIFICATION_ENABLED"] = "0"
GEMINI_QUEUE.clear()
GEMINI_CALLS.clear()
q({"question_type": None})
status, data = upload("封閉模式欄位", ["封閉模式下判斷不出主題"])
check("封閉模式：不自動歸納、分類 0 筆", data["classified_count"] == 0 and data["columns"][0]["routing_status"] == "unrouted")
with app.app_context():
    check("封閉模式：沒有建立自動主題", m.Topic.query.get(auto_topic_key("封閉模式欄位")) is None)
os.environ.pop("OPEN_CLASSIFICATION_ENABLED", None)
GEMINI_QUEUE.clear()

finish()
