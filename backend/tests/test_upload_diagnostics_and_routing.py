#!/usr/bin/env python
"""
上傳診斷（P1-3）、routing 失敗不建立自動主題（P1-4）、自動主題範圍（P1-5）、
計數（P2-6）。

涵蓋：
    A. routing 失敗（429 / 5xx / timeout / API key / 回應解析失敗）：
       routing_failed、原始回答保存、不建立自動主題、沒有假的分類、
       進 Admin 未分類頁、錯誤摘要不含 API key、稍後可以重新判斷
    B. 診斷 code 與計數：多欄上傳（成功欄 + 失敗欄）、部分成功、拆分失敗、
       分類失敗、沒有有意義的結果、固定分類模式（沒有已發布分類架構 /
       判斷不出主題）；saved = classified + failed，整批 = 各欄加總
    C. 通用欄位名：兩份「開放式回答」內容完全不同 -> 不同主題；同 workspace
       + 相近內容 -> 沿用；不同 workspace -> 不沿用；topic key 不含原文；
       routing 候選不含其他範圍的自動主題；別人的 project_id 不能用
    D. 問卷：建立時 routing 失敗 -> 分析時重新判斷；仍失敗 -> 跳過並回報，
       不建立自動主題

執行方式：
    cd backend
    python3 tests/test_upload_diagnostics_and_routing.py
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

os.environ.pop("OPEN_CLASSIFICATION_ENABLED", None)
os.environ["GEMINI_API_KEY"] = "AIzaSyTESTKEY_should_never_leak_1234567"
app = create_app()
from routes.surveys.survey import survey_bp  # noqa: E402  問卷建立 / 分析路由
app.register_blueprint(survey_bp)
client = app.test_client()

with app.app_context():
    seed_people()
    seed_topic("career", categories=[("職涯發展", "A1 教育訓練", "m", "c"), ("職涯發展", "A2 升遷制度", "m", "c")])
    db.session.add(m.User(user_id=2, user_name="other", email="other@example.com", password_hash="x"))
    db.session.add_all([
        m.Workspace(project_id=11, user_id=1, project_name="A"),
        m.Workspace(project_id=12, user_id=1, project_name="B"),
        m.Workspace(project_id=21, user_id=2, project_name="別人的"),
    ])
    db.session.commit()


def upload(columns, project_id=None, user_id=1):
    df = pd.DataFrame(columns)
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    buf.seek(0)
    form = {"file": (buf, "u.xlsx")}
    if project_id is not None:
        form["project_id"] = str(project_id)
    if len(columns) == 1:
        form["text_column"] = next(iter(columns))
    resp = client.post("/api/classification/upload", data=form, headers=user_header(user_id),
                       content_type="multipart/form-data")
    return resp.status_code, resp.get_json()


def classify(text, main="職涯發展", sub="A1 教育訓練"):
    q({"segments": [mask_pii(text)]})
    q({"classifications": [{"index": 0, "main_category": main, "sub_category": sub, "secondary_categories": [],
                             "reasoning": "r", "summary": "s", "confidence": 0.9}]})


def auto_topic_count():
    with app.app_context():
        return m.Topic.query.filter(m.Topic.topic_key.like("auto\\_%", escape="\\")).count()


def consistent(body):
    cols = body["columns"]
    return (
        body["saved_answer_count"] == body["classified_count"] + body["failed_count"]
        and all(c["saved_answer_count"] == c["classified_count"] + c["failed_count"] for c in cols)
        and body["saved_answer_count"] == sum(c["saved_answer_count"] for c in cols)
        and body["classified_count"] == sum(c["classified_count"] for c in cols)
        and body["failed_count"] == sum(c["failed_count"] for c in cols)
    )


print("========== A. routing 失敗不建立自動主題 ==========")
FAILURES = {
    "rate_limited": [RuntimeError("429 RESOURCE_EXHAUSTED quota exceeded")] * 3,
    "service_unavailable": [RuntimeError("503 UNAVAILABLE high demand key=AIzaSyTESTKEY_should_never_leak_1234567")] * 4,
    "timeout": [RuntimeError("DEADLINE_EXCEEDED: request timed out")],
    "auth_or_config": [ValueError("Missing key inputs argument! To use the Google AI API, provide (`api_key`) arguments.")],
    "parse_error": ["這不是 JSON"],
}
failed_answer_ids = []
for kind, errors in FAILURES.items():
    GEMINI_QUEUE.clear()
    before = auto_topic_count()
    q(*errors)
    status, body = upload({"開放式回答": [f"{kind} 的回答一", f"{kind} 的回答二"]})
    col = body["columns"][0]
    check(f"[{kind}] 201，欄位 routing_failed、routing_error_kind={kind}",
          status == 201 and col["routing_status"] == "routing_failed" and col["routing_error_kind"] == kind)
    check(f"[{kind}] 診斷 ROUTING_API_FAILED、failed，計數一致（2 存、0 分類、2 失敗）",
          col["diagnostic_code"] == "ROUTING_API_FAILED" and body["analysis_status"] == "failed"
          and (body["saved_answer_count"], body["classified_count"], body["failed_count"]) == (2, 0, 2) and consistent(body))
    check(f"[{kind}] 沒有建立自動主題、沒有呼叫分類 / 歸納", auto_topic_count() == before and not GEMINI_QUEUE)
    with app.app_context():
        answers = m.Uploaded_Answer.query.filter_by(upload_batch_id=body["upload_batch_id"]).all()
        check(f"[{kind}] 原始回答保存、沒有分類結果",
              len(answers) == 2 and all(a.question_type is None and a.routing_status == "routing_failed" for a in answers)
              and m.Response_Classification.query.filter_by(upload_batch_id=body["upload_batch_id"]).count() == 0)
        check(f"[{kind}] routing_detail 是安全摘要（不含 API key）",
              all("AIzaSy" not in (a.routing_detail or "") and "should_never_leak" not in (a.routing_detail or "")
                  and a.routing_detail.startswith(f"routing_error={kind}") for a in answers))
        failed_answer_ids.extend(a.id for a in answers)

body = client.get("/api/admin/ai/unassigned?kind=unrouted&page_size=100", headers=admin_header(1)).get_json()
listed = {i["id"]: i for i in body["items"]}
check("全部進入 Admin 未分類頁", all(i in listed for i in failed_answer_ids))
codes = {listed[i]["failure"]["code"] for i in failed_answer_ids}
check("未分類頁的原因依失敗種類說明（額度 / 忙碌 / 逾時 / 金鑰 / 格式）",
      {"AI_QUOTA_EXCEEDED", "AI_SERVICE_BUSY", "AI_TIMEOUT", "AI_AUTH_FAILED", "AI_RESPONSE_INVALID"} <= codes)
check("回傳給前端的原始錯誤也不含 API key", "should_never_leak" not in str(body))

GEMINI_QUEUE.clear()
q({"question_type": "career"})
classify("rate_limited 的回答一")
resp = client.post(f"/api/admin/ai/unassigned/answers/{failed_answer_ids[0]}/reroute", headers=admin_header(1))
check("稍後重新判斷主題：成功後分類", resp.status_code == 200 and resp.get_json()["routed"] is True)
GEMINI_QUEUE.clear()
q(RuntimeError("503 UNAVAILABLE"), RuntimeError("503 UNAVAILABLE"), RuntimeError("503 UNAVAILABLE"), RuntimeError("503 UNAVAILABLE"))
resp = client.post(f"/api/admin/ai/unassigned/answers/{failed_answer_ids[1]}/reroute", headers=admin_header(1))
check("重新判斷仍失敗：維持 routing_failed、不建立自動主題",
      resp.status_code == 200 and resp.get_json()["routed"] is False and resp.get_json()["routing_status"] == "routing_failed")

print("\n========== B. 診斷與計數 ==========")
GEMINI_QUEUE.clear()
# 欄位「失敗欄」：routing 429（放前面：成功欄彙整摘要的 AI 呼叫在最後，不會吃掉佇列）
q(*[RuntimeError("429 RESOURCE_EXHAUSTED")] * 3)
# 欄位「成功欄」：routing -> career，兩則都成功
q({"question_type": "career"})
classify("希望多開課")
classify("升遷不透明", sub="A2 升遷制度")
status, body = upload({"失敗欄": ["回答甲", "回答乙"], "成功欄": ["希望多開課", "升遷不透明"]})
cols = {c["column"]: c for c in body["columns"]}
check("多欄：成功欄 completed、沒有診斷 code", cols["成功欄"]["analysis_status"] == "completed" and cols["成功欄"]["diagnostic_code"] is None)
check("多欄：失敗欄 failed、ROUTING_API_FAILED", cols["失敗欄"]["analysis_status"] == "failed"
      and cols["失敗欄"]["diagnostic_code"] == "ROUTING_API_FAILED")
check("整批 partial、PARTIAL_CLASSIFICATION、成功欄結果照常顯示",
      body["analysis_status"] == "partial" and body["diagnostic_code"] == "PARTIAL_CLASSIFICATION"
      and len(body["aggregated_groups"]) == 2)
check("整批計數 = 各欄加總（4 存、2 分類、2 失敗）",
      (body["saved_answer_count"], body["classified_count"], body["failed_count"]) == (4, 2, 2) and consistent(body))
check("診斷附中英文說明", body["diagnostic_message"] and body["diagnostic_message_en"])

GEMINI_QUEUE.clear()
q({"question_type": "career"})
classify("第一則成功")
q(RuntimeError("segmentation boom"))  # 第二則：拆分失敗
classify("第三則成功")
status, body = upload({"部分成功": ["第一則成功", "第二則失敗了", "第三則成功"]})
col = body["columns"][0]
check("部分成功：3 存 2 分類 1 失敗、PARTIAL_CLASSIFICATION",
      (col["saved_answer_count"], col["classified_count"], col["failed_count"]) == (3, 2, 1)
      and col["diagnostic_code"] == "PARTIAL_CLASSIFICATION" and col["analysis_status"] == "partial" and consistent(body))

GEMINI_QUEUE.clear()
q({"question_type": "career"}, RuntimeError("segmentation boom"), RuntimeError("segmentation boom"))
status, body = upload({"拆分失敗": ["甲甲甲", "乙乙乙"]})
check("全部拆分失敗：SEGMENTATION_FAILED、classified 0",
      body["diagnostic_code"] == "SEGMENTATION_FAILED" and body["classified_count"] == 0 and body["failed_count"] == 2)

GEMINI_QUEUE.clear()
q({"question_type": "career"}, {"segments": [mask_pii("分類會失敗")]}, RuntimeError("429 RESOURCE_EXHAUSTED"),
  RuntimeError("429 RESOURCE_EXHAUSTED"), RuntimeError("429 RESOURCE_EXHAUSTED"))
status, body = upload({"分類失敗": ["分類會失敗"]})
col = body["columns"][0]
check("分類呼叫失敗：CLASSIFICATION_FAILED、補充原因是額度不足",
      col["diagnostic_code"] == "CLASSIFICATION_FAILED" and col["failure_code"] == "AI_QUOTA_EXCEEDED"
      and body["classified_count"] == 0 and body["failed_count"] == 1)
with app.app_context():
    check("分類失敗的回答不算 classified，但有失敗列可以重試",
          m.Response_Classification.query.filter_by(upload_batch_id=body["upload_batch_id"], status="failed").count() == 1)

GEMINI_QUEUE.clear()
with app.app_context():
    seed_topic("nospec", categories=[("其他", "Z9 無具體建議", "m", "c")])
q({"question_type": "nospec"})
classify("沒意見", main="其他", sub="Z9 無具體建議")
status, body = upload({"無建議": ["沒意見"]})
check("有分類但沒有可顯示的分組：NO_MEANINGFUL_RESULTS（completed）",
      body["diagnostic_code"] == "NO_MEANINGFUL_RESULTS" and body["analysis_status"] == "completed"
      and body["classified_count"] == 1 and body["aggregated_groups"] == [])

print("\n--- 固定分類模式 ---")
os.environ["OPEN_CLASSIFICATION_ENABLED"] = "0"
GEMINI_QUEUE.clear()
q({"question_type": None})
status, body = upload({"判斷不出": ["內容"]})
check("固定模式判斷不出主題：ROUTING_UNDETERMINED、不建立自動主題",
      body["diagnostic_code"] == "ROUTING_UNDETERMINED" and body["classified_count"] == 0)
with app.app_context():
    empty_topic = m.Topic(topic_key="empty_topic", title="沒有已發布版本")
    db.session.add(empty_topic)
    db.session.commit()
    seed_topic("draft_only", status="draft")
with app.app_context():
    published = m.Taxonomy_Version.query.filter_by(status="published").all()
    PUBLISHED_IDS = [v.version_id for v in published]
    for v in published:
        v.status = "archived"
        v.published_topic_key = None
    db.session.commit()
GEMINI_QUEUE.clear()
GEMINI_CALLS.clear()
status, body = upload({"沒有候選": ["內容"]})
check("固定模式沒有任何已發布主題：NO_PUBLISHED_TAXONOMY、不呼叫 AI",
      body["diagnostic_code"] == "NO_PUBLISHED_TAXONOMY" and body["columns"][0]["routing_status"] == "no_topic_candidates"
      and not GEMINI_CALLS)
with app.app_context():
    for v in m.Taxonomy_Version.query.filter(m.Taxonomy_Version.version_id.in_(PUBLISHED_IDS)).all():
        v.status = "published"
        v.published_topic_key = v.topic_key
    db.session.commit()
os.environ.pop("OPEN_CLASSIFICATION_ENABLED", None)

print("\n========== C. 通用欄位名不污染自動主題 ==========")
FOOD = ["午餐菜色太少，希望增加素食選擇", "員工餐廳的便當很難吃", "餐廳排隊太久，菜色選擇不多"]
FOOD2 = ["餐廳菜色太單調，希望多一點選擇", "午餐便當不好吃，排隊時間很長"]
PAY = ["薪水三年沒調整", "年終獎金太少", "加班費計算不透明，希望調薪"]


def auto_upload(texts, project_id, categories, user_id=1, routed=None):
    GEMINI_QUEUE.clear()
    GEMINI_CALLS.clear()
    q({"question_type": routed})
    if categories:
        q({"categories": [{"main_category": c[0], "sub_category": c[1], "definition": "d"} for c in categories]})
    for text in texts:
        classify(text, main=categories[0][0] if categories else "餐飲", sub=categories[0][1] if categories else "菜色")
    status, body = upload({"開放式回答": texts}, project_id=project_id, user_id=user_id)
    return body


b1 = auto_upload(FOOD, 11, [("餐飲", "菜色")])
k1 = b1["columns"][0]["question_type"]
b2 = auto_upload(PAY, 11, [("薪酬", "薪資")])
k2 = b2["columns"][0]["question_type"]
check("同 workspace、同為「開放式回答」但內容完全不同 -> 不同主題", k1 and k2 and k1 != k2 and k1.startswith("auto_"))
b3 = auto_upload(FOOD2, 11, None)  # 相近內容：沿用，不需要重新歸納
k3 = b3["columns"][0]["question_type"]
with app.app_context():
    versions_k1 = m.Taxonomy_Version.query.filter_by(topic_key=k1).count()
check("同 workspace、同題意、內容相近 -> 沿用同一個主題、不重新歸納",
      k3 == k1 and versions_k1 == 1 and b3["classified_count"] == 2)
routing_prompt = next(c["system_instruction"] for c in GEMINI_CALLS)
check("routing 候選包含同範圍的自動主題", k1 in routing_prompt)
b4 = auto_upload(FOOD2, 12, [("餐飲", "菜色")])
k4 = b4["columns"][0]["question_type"]
check("不同 workspace、內容相近 -> 不沿用（不同主題）", k4 not in (k1, k2))
routing_prompt = next(c["system_instruction"] for c in GEMINI_CALLS)
check("routing 候選不含其他 workspace 的自動主題", k1 not in routing_prompt and k2 not in routing_prompt)
b5 = auto_upload(FOOD2, 21, [("餐飲", "菜色")])
k5 = b5["columns"][0]["question_type"]
check("別人的 project_id 不能用（改用自己的使用者範圍，不沿用 project 21 / 11 的主題）", k5 not in (k1, k4))
with app.app_context():
    t1 = m.Topic.query.get(k1)
    t5 = m.Topic.query.get(k5)
    check("範圍記錄正確", t1.auto_scope == "project:11" and m.Topic.query.get(k4).auto_scope == "project:12" and t5.auto_scope == "user:1")
    check("topic key / 內容特徵不含原文", all(w not in (t1.topic_key + (t1.auto_signature or "")) for w in ("午餐", "便當", "餐廳")))
    answers = m.Uploaded_Answer.query.filter_by(upload_batch_id=b1["upload_batch_id"]).all()
    check("回答記錄範圍（Admin 重新判斷時沿用）", all(a.analysis_scope == "project:11" for a in answers))
b6 = auto_upload(FOOD, 11, [("餐飲", "菜色")], user_id=2)
check("另一個使用者（帶別人的 project）-> 自己的範圍，不沿用", b6["columns"][0]["question_type"] not in (k1, k2, k4, k5))
with app.app_context():
    check("另一個使用者的自動主題範圍是 user:2", m.Topic.query.get(b6["columns"][0]["question_type"]).auto_scope == "user:2")

print("\n========== D. 問卷：routing 失敗不建立自動主題 ==========")
GEMINI_QUEUE.clear()
q(*[RuntimeError("429 RESOURCE_EXHAUSTED")] * 3)
resp = client.post("/api/surveys", headers=user_header(1), json={
    "title": "意見調查", "questions": [{"id": "q1", "type": "short", "title": "其他建議"}],
})
check("建立問卷 201（routing 失敗不影響建立）", resp.status_code in (200, 201))
with app.app_context():
    tpl = m.Survey_Template.query.filter_by(title="意見調查").one()
    item = tpl.question_json["items"][0]
    check("題目記錄 routing_failed", item["question_type"] is None and item["routing_status"] == "routing_failed")
    db.session.add(m.Survey_Response(template_id=tpl.template_id, answer_json={"answers": {"q1": "希望多辦員工旅遊"}}))
    db.session.commit()
    code = tpl.access_code
before = auto_topic_count()
GEMINI_QUEUE.clear()
q(*[RuntimeError("503 UNAVAILABLE")] * 4)
resp = client.post(f"/api/surveys/{code}/analyze", headers=user_header(1))
per_q = resp.get_json()["diagnostic"]["per_question"]["q1"]
check("分析時重新判斷仍失敗：跳過、ROUTING_API_FAILED、不建立自動主題",
      resp.status_code == 200 and per_q["diagnostic_code"] == "ROUTING_API_FAILED" and auto_topic_count() == before
      and resp.get_json()["newly_classified_count"] == 0)
GEMINI_QUEUE.clear()
q({"question_type": None}, {"categories": [{"main_category": "福利", "sub_category": "員工旅遊", "definition": "d"}]})
classify("希望多辦員工旅遊", main="福利", sub="員工旅遊")
resp = client.post(f"/api/surveys/{code}/analyze", headers=user_header(1))
check("AI 恢復後重新分析：模型判斷沒有適合主題 -> 自動主題、分類 1 則",
      resp.status_code == 200 and resp.get_json()["newly_classified_count"] == 1 and auto_topic_count() == before + 1)
with app.app_context():
    item = m.Survey_Template.query.filter_by(title="意見調查").one().question_json["items"][0]
    check("題目的 routing 結果已更新", item["routing_status"] == "undetermined")

print("\n========== E. 診斷存進 Chat History；Admin 重新處理後計數跟著更新 ==========")
GEMINI_QUEUE.clear()
q(*[RuntimeError("429 RESOURCE_EXHAUSTED")] * 3)
status, body = upload({"稍後重試": ["想要更多訓練課程"]}, project_id=11)
meta = {k: body[k] for k in ("analysis_status", "diagnostic_code", "saved_answer_count", "classified_count", "failed_count")}
meta["columns"] = [{k: c.get(k) for k in ("column", "analysis_status", "diagnostic_code", "failure_code", "routing_status",
                                         "saved_answer_count", "classified_count", "failed_count")} for c in body["columns"]]
with app.app_context():
    from admin_test_support import seed_workspace_chat
    chat_id = seed_workspace_chat(body["upload_batch_id"], meta_extra=dict(meta, review_revision=body["review_revision"]), project_id=11)
    answer_id = m.Uploaded_Answer.query.filter_by(upload_batch_id=body["upload_batch_id"]).one().id
GEMINI_QUEUE.clear()
q({"question_type": "career"})
classify("想要更多訓練課程")
resp = client.post(f"/api/admin/ai/unassigned/answers/{answer_id}/reroute", headers=admin_header(1))
check("Admin 重新判斷成功", resp.status_code == 200 and resp.get_json()["routed"] is True)
resp = client.post(f"/api/chat/{chat_id}/classification-result/refresh", headers=user_header(1))
check("重新整理 200", resp.status_code == 200)
with app.app_context():
    from services.workspace_result_service import parse_classification_message
    stored = parse_classification_message(db.session.get(m.Chat_History, chat_id).message_content)["meta"]
check("Chat History 的診斷與計數已更新（completed、1 分類 0 失敗）",
      stored["analysis_status"] == "completed" and stored["diagnostic_code"] is None
      and (stored["saved_answer_count"], stored["classified_count"], stored["failed_count"]) == (1, 1, 0)
      and stored["columns"][0]["analysis_status"] == "completed")

GEMINI_QUEUE.clear()
finish()
