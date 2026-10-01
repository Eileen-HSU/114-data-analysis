#!/usr/bin/env python
"""
問卷重新分析（re-analysis）不得刪除人工審核結果：attempt 模型。

情境（同一題 q1，每則回答事先建立「上一次分析」的狀態）：
    R1 partial_failed：A confirmed（有 reviewer / reviewed_at）+ B failed
        -> 只重新分類 B（不重新拆分），A 原封不動
    R2 partial_failed：A modified（final_*、review 對話、audit）+ B failed + C pending
        -> 只重新分類 B
    R3 partial_failed：A excluded（有 review 紀錄）+ B pending，沒有失敗片段
        -> 不動（blocked_by_review）
    R4 failed：A pending + B failed，沒有人工審核
        -> 整則重新分析，新 attempt 生效，舊列 superseded
    R5 partial_failed：A pending + B failed，沒有人工審核，但重新分析 AI 失敗
        -> 舊結果維持生效，失敗原因記在 last_attempt_error
    R6 從沒分析過 -> 第一次分析（attempt 1）

驗證（對應需求 1~7）：
    1. confirmed 結果重跑後仍存在且仍生效
    2. modified 的 final_* / reviewer / review 對話重跑後仍存在
    3. excluded 與 review history 保留
    4. 新 attempt 成為 current（attempt_no、status 列）
    5. 舊 attempt 不進 aggregation / report / export / workspace
    6. 重新分析失敗時舊 current result 仍可用
    7. 重複請求不產生重複 current attempt（循序 + 模擬併發）
    另外：沒有任何 Response_Classification 被 hard-delete。

執行方式：
    cd backend
    python3 tests/test_survey_reanalysis_attempts.py
"""

import base64
import io
import os

import openpyxl

from admin_test_support import (
    GEMINI_CALLS, GEMINI_QUEUE, admin_header, check, create_app, finish, q, seed_people, seed_topic, user_header,
)
import models as m
from extensions import db, taiwan_now
from services import classification_attempt_service as attempt_service
from services.privacy_service import mask_pii

os.environ.pop("OPEN_CLASSIFICATION_ENABLED", None)
app = create_app()
client = app.test_client()

TEXTS = {
    "R1": "薪水三年沒有調整。希望公司多開教育訓練課程",
    "R2": "主管很少給回饋。升遷標準不透明。其實團隊氣氛不錯",
    "R3": "辦公室冷氣太冷。會議室總是訂不到",
    "R4": "加班沒有加班費。年終獎金縮水",
    "R5": "想要彈性上班。通勤時間太長",
    "R6": "希望有導師制度協助新人",
}


def span(text, part):
    start = text.index(part)
    return start, start + len(part)


with app.app_context():
    seed_people()
    vid = seed_topic("career", categories=[
        ("職涯發展", "A1 教育訓練", "Method A1", "Cite A1"),
        ("職涯發展", "A2 升遷制度", "Method A2", "Cite A2"),
        ("薪酬福利", "C1 薪資", "Method C1", "Cite C1"),
        ("工作環境", "E1 設施", "Method E1", "Cite E1"),
    ])
    tpl = m.Survey_Template(user_id=1, title="員工意見", access_code="REAN1", question_json={"items": [
        {"id": "q1", "type": "short", "title": "對公司的建議", "question_type": "career"},
    ]})
    db.session.add(tpl)
    db.session.flush()
    TEMPLATE_ID = tpl.template_id
    RID = {}
    for key, text in TEXTS.items():
        resp = m.Survey_Response(template_id=TEMPLATE_ID, answer_json={"answers": {"q1": text}})
        db.session.add(resp)
        db.session.flush()
        RID[key] = resp.response_id

    def status(key, seg_status):
        db.session.add(m.Response_Segmentation_Status(
            response_id=RID[key], question_id="q1", source_type="survey", segmentation_status=seg_status,
            error_detail="BATCH_CLASSIFICATION_FAILED: 503" if seg_status != "completed" else None,
        ))

    def row(key, part, main, sub, *, status_="completed", review="pending_review", **extra):
        text = TEXTS[key]
        start, end = span(text, part)
        r = m.Response_Classification(
            response_id=RID[key], source_type="survey", question_id="q1", answer_text=text,
            segment_start=start, segment_end=end, main_category=main, sub_category=sub,
            reasoning="AI 理由", summary="s", status=status_, review_status=review,
            taxonomy_version_id=vid, confidence=0.9, **extra,
        )
        db.session.add(r)
        db.session.flush()
        return r.classification_id

    now = taiwan_now()
    status("R1", "partial_failed")
    R1A = row("R1", "薪水三年沒有調整", "薪酬福利", "C1 薪資", review="confirmed", reviewed_by_admin_id=2, reviewed_at=now)
    R1B = row("R1", "希望公司多開教育訓練課程", None, None, status_="failed")

    status("R2", "partial_failed")
    R2A = row("R2", "主管很少給回饋", "職涯發展", "A1 教育訓練", review="modified",
              final_main_category="職涯發展", final_sub_category="A2 升遷制度", final_reasoning="人工：其實在講升遷",
              reviewed_by_admin_id=1, reviewed_at=now)
    R2B = row("R2", "升遷標準不透明", None, None, status_="failed")
    R2C = row("R2", "其實團隊氣氛不錯", "工作環境", "E1 設施")
    review = m.Classification_Review(classification_id=R2A, admin_id=1, status="confirmed")
    db.session.add(review)
    db.session.flush()
    db.session.add(m.Classification_Review_Message(review_id=review.review_id, role="user", content="應該是升遷"))
    db.session.add(m.Admin_Audit_Log(action="confirm_manual", entity_type="classification", entity_id=str(R2A), admin_id=1))

    status("R3", "partial_failed")
    R3A = row("R3", "辦公室冷氣太冷", "工作環境", "E1 設施", review="excluded", reviewed_by_admin_id=1, reviewed_at=now)
    R3B = row("R3", "會議室總是訂不到", "工作環境", "E1 設施")
    db.session.add(m.Classification_Review(classification_id=R3A, admin_id=1, status="excluded"))

    status("R4", "failed")
    R4A = row("R4", "加班沒有加班費", "舊大類", "舊子類 X")
    R4B = row("R4", "年終獎金縮水", None, None, status_="failed")

    status("R5", "partial_failed")
    R5A = row("R5", "想要彈性上班", "工作環境", "E1 設施")
    R5B = row("R5", "通勤時間太長", None, None, status_="failed")
    db.session.commit()
    ORIGINAL_IDS = {r.classification_id for r in m.Response_Classification.query.all()}


def seg_q(key, parts):
    q({"segments": [mask_pii(p) for p in parts]})


def cls_q(*pairs):
    q({"classifications": [
        {"index": i, "main_category": main, "sub_category": sub, "secondary_sub_category": None,
         "reasoning": "新理由", "summary": "s", "confidence": 0.9}
        for i, (main, sub) in enumerate(pairs)
    ]})


print("========== 第一次重新分析 ==========")
GEMINI_QUEUE.clear()
GEMINI_CALLS.clear()
# pending（依回答順序）：R4 整則、R5 整則（AI 失敗）、R6 第一次
seg_q("R4", ["加班沒有加班費", "年終獎金縮水"])
cls_q(("薪酬福利", "C1 薪資"), ("薪酬福利", "C1 薪資"))
q(RuntimeError("segmentation boom"))
seg_q("R6", ["希望有導師制度協助新人"])
cls_q(("職涯發展", "A1 教育訓練"))
# 只重新分類失敗片段（依回答順序）：R1 的 B、R2 的 B
cls_q(("職涯發展", "A1 教育訓練"))
cls_q(("職涯發展", "A2 升遷制度"))
resp = client.post("/api/surveys/REAN1/analyze", headers=user_header(1))
body = resp.get_json()
check("analyze 200", resp.status_code == 200)
def ai_calls():
    return [c for c in GEMINI_CALLS if "量化前彙整助手" not in (c["system_instruction"] or "")]


check("Gemini 呼叫次數正確（整則 2+1+2、片段重試 1+1）", len(ai_calls()) == 7 and not GEMINI_QUEUE)
diag = body["diagnostic"]["per_question"]["q1"]
check("diagnostic：整則重新分析 2、片段重試 2、受審核保護 1、失敗保留舊結果 1",
      diag["reanalyzed"] == 2 and diag["segment_retries"] == 2 and diag["blocked_by_review"] == 1
      and diag["kept_previous"] == 1)
check("newly_classified_count = 實際生效的 attempt（R1、R2、R4、R6）", body["newly_classified_count"] == 4)

with app.app_context():
    get = lambda cid: db.session.get(m.Response_Classification, cid)  # noqa: E731
    all_ids = {r.classification_id for r in m.Response_Classification.query.all()}
    check("沒有任何分類結果被 hard-delete", ORIGINAL_IDS <= all_ids)

    print("\n--- 1. confirmed 保留 ---")
    a = get(R1A)
    check("R1 confirmed 片段仍存在、仍生效", a.status == "completed" and a.review_status == "confirmed")
    check("R1 reviewer / reviewed_at 保留", a.reviewed_by_admin_id == 2 and a.reviewed_at is not None)
    check("R1 失敗片段 superseded", get(R1B).status == "superseded")
    r1_current = attempt_service.current_rows(attempt_service.survey_scope(RID["R1"], "q1", TEXTS["R1"]))
    new_b = [r for r in r1_current if r.classification_id not in (R1A, R1B)]
    check("R1 失敗片段用原位置重新分類成功（attempt 2）",
          len(new_b) == 1 and new_b[0].sub_category == "A1 教育訓練" and new_b[0].attempt_no == 2
          and (new_b[0].segment_start, new_b[0].segment_end) == (get(R1B).segment_start, get(R1B).segment_end))
    s1 = m.Response_Segmentation_Status.query.filter_by(response_id=RID["R1"], question_id="q1").one()
    check("R1 status：completed、attempt 2", s1.segmentation_status == "completed" and s1.attempt_no == 2)

    print("\n--- 2. modified 的 final_* 保留 ---")
    a = get(R2A)
    check("R2 modified final_* 保留", a.review_status == "modified" and a.final_sub_category == "A2 升遷制度"
          and a.final_reasoning == "人工：其實在講升遷" and a.status == "completed")
    check("R2 review 對話與 audit 保留",
          m.Classification_Review.query.filter_by(classification_id=R2A).count() == 1
          and m.Classification_Review_Message.query.count() >= 1
          and m.Admin_Audit_Log.query.filter_by(entity_id=str(R2A)).count() == 1)
    check("R2 pending 片段 C 沒被取代（有受保護片段時不重新拆分）", get(R2C).status == "completed")

    print("\n--- 3. excluded history 保留 ---")
    a = get(R3A)
    check("R3 excluded 保留、review 紀錄保留", a.review_status == "excluded"
          and m.Classification_Review.query.filter_by(classification_id=R3A).count() == 1)
    check("R3 其他片段也沒被動", get(R3B).status == "completed")
    s3 = m.Response_Segmentation_Status.query.filter_by(response_id=RID["R3"], question_id="q1").one()
    check("R3 status 維持 partial_failed、attempt 1", s3.segmentation_status == "partial_failed" and s3.attempt_no == 1)

    print("\n--- 4. 新 attempt 成為 current ---")
    check("R4 舊列全部 superseded（保留在 DB）", get(R4A).status == "superseded" and get(R4B).status == "superseded")
    r4 = attempt_service.current_rows(attempt_service.survey_scope(RID["R4"], "q1", TEXTS["R4"]))
    check("R4 current = 新 attempt 的 2 個片段", len(r4) == 2 and all(r.attempt_no == 2 and r.sub_category == "C1 薪資" for r in r4))
    s4 = m.Response_Segmentation_Status.query.filter_by(response_id=RID["R4"], question_id="q1").one()
    check("R4 status：completed、attempt 2", s4.segmentation_status == "completed" and s4.attempt_no == 2)
    s6 = m.Response_Segmentation_Status.query.filter_by(response_id=RID["R6"], question_id="q1").one()
    check("R6 第一次分析：attempt 1", s6.attempt_no == 1 and s6.segmentation_status == "completed")

    print("\n--- 6. 重新分析失敗時舊結果仍可用 ---")
    check("R5 舊的可用片段仍生效", get(R5A).status == "completed" and get(R5B).status == "failed")
    s5 = m.Response_Segmentation_Status.query.filter_by(response_id=RID["R5"], question_id="q1").one()
    check("R5 status 維持 attempt 1，失敗原因記在 last_attempt_error",
          s5.attempt_no == 1 and s5.segmentation_status == "partial_failed" and "boom" in (s5.last_attempt_error or ""))

print("\n--- 5. 舊 attempt 不進 aggregation / report / export ---")
groups = {(g["main_category"], g["sub_category"]): g for g in body["aggregated_groups"]}
check("analyze 彙整不含被取代的舊類別（舊子類 X）", ("舊大類", "舊子類 X") not in groups)
all_item_texts = " ".join(str(g) for g in body["aggregated_groups"])
check("analyze 彙整不含 excluded 片段", "辦公室冷氣太冷" not in all_item_texts)
with app.app_context():
    from services.workspace_result_service import build_live_groups
    live = build_live_groups({"source_type": "survey", "template_id": TEMPLATE_ID})
    live_keys = {(g["main_category"], g["sub_category"]) for g in live}
    check("Workspace 即時彙整不含舊 attempt", ("舊大類", "舊子類 X") not in live_keys)
    c1 = next(g for g in live if "薪資" in g["sub_category"])
    check("C1 薪資只計 current（R1A + R4 兩段），不重複計數",
          c1["respondent_count"] == 3 and "加班沒有加班費" in c1["respondent_text"] and "薪水三年沒有調整" in c1["respondent_text"])

    ws = m.Workspace(project_id=9, user_id=1, project_name="ws")
    db.session.add(ws)
    db.session.flush()
    from services.workspace_result_service import build_classification_message
    chat = m.Chat_History(project_id=9, sender_type="ai", message_content=build_classification_message(
        {"rows": [], "meta": {"template_id": TEMPLATE_ID, "source_type": "survey"}, "rating_stats": []}))
    db.session.add(chat)
    db.session.commit()
    CHAT_ID = chat.chat_id
resp = client.post("/api/exports", headers=user_header(1), json={"chat_id": CHAT_ID, "filename": "o.xlsx", "export_type": "xlsx", "rows": []})
check("export 201", resp.status_code == 201)
with app.app_context():
    export = db.session.get(m.Export_File, resp.get_json()["export_id"])
    wb = openpyxl.load_workbook(io.BytesIO(base64.b64decode(export.content)))
    cells = " ".join(str(c.value) for ws_ in wb.worksheets for r in ws_.iter_rows() for c in r if c.value)
check("匯出不含舊 attempt 的類別", "舊子類 X" not in cells and "C1 薪資" in cells)

# report：收所有 current 的有效列（待審、自動通過、人工確認、修改）
with app.app_context():
    for r in m.Response_Classification.query.filter_by(response_id=RID["R4"]).all():
        r.review_status = "confirmed"  # 包含 superseded 的舊列：確認它們仍被排除
    db.session.commit()
GEMINI_QUEUE.clear()
q(*[{"summary": "報告摘要"}] * 4)  # C1 薪資、A2 升遷制度、A1 教育訓練、E1 設施 四個 group
resp = client.post(f"/api/admin/ai/reports/survey/{TEMPLATE_ID}/generate", headers=admin_header(1))
# eligible 只算 current：人工的 R1A、R2A + R4 新的 2 段 + 這次新分析、高信心自動通過的
# R1／R2 失敗片段重試結果與 R6 第一次分析（3 段）+ 待審的 E1 設施（R2、R3、R5 各 1 段，
# 報告不等人工審核）= 10；superseded 的舊列、excluded、failed 都不計入
check("report 產生 201（eligible 只算 current = 10，含自動通過與待審）",
      resp.status_code == 201 and resp.get_json()["report"]["eligible_count_at_generation"] == 10)
detail = client.get(f"/api/admin/ai/reports/detail/{resp.get_json()['report']['report_id']}", headers=admin_header(1)).get_json()
agg = {(a["main_category"], a["sub_category"]): a for a in detail["aggregations"]}
check("report 不含 superseded 的舊類別", ("舊大類", "舊子類 X") not in agg)
check("report 的 C1 薪資：R1A + R4 新的兩段 = 3 段（舊 attempt 沒被重複計入）",
      len(agg.get(("薪酬福利", "C1 薪資"), {}).get("items", [])) == 3)
check("report 使用 modified 的 final 類別（A2 升遷制度）", ("職涯發展", "A2 升遷制度") in agg)

print("\n========== 7. 冪等 ==========")
GEMINI_QUEUE.clear()
GEMINI_CALLS.clear()
q(RuntimeError("still failing"))  # 只有 R5 還是 partial_failed 會再試一次
resp = client.post("/api/surveys/REAN1/analyze", headers=user_header(1))
check("第二次 analyze 200", resp.status_code == 200)
check("已完成的回答不重跑：只有 R5 再試 1 次", len(ai_calls()) == 1)
check("第二次沒有新的生效 attempt", resp.get_json()["newly_classified_count"] == 0)
with app.app_context():
    for key in TEXTS:
        s = m.Response_Segmentation_Status.query.filter_by(response_id=RID[key], question_id="q1").all()
        check(f"{key} 只有一筆 status 列", len(s) == 1)
    r4 = attempt_service.current_rows(attempt_service.survey_scope(RID["R4"], "q1", TEXTS["R4"]))
    check("R4 仍只有一份 current attempt", len(r4) == 2 and {r.attempt_no for r in r4} == {2})

    print("\n--- 模擬併發：兩個請求規劃時看到同一個 attempt_no ---")
    scope = attempt_service.survey_scope(RID["R5"], "q1", TEXTS["R5"])
    plan_a = attempt_service.plan_reanalysis(scope)
    plan_b = attempt_service.plan_reanalysis(scope)
    good = {"segmentation_status": "completed", "segmentation_error_detail": None, "segments": [
        {"orig_start": 0, "orig_end": len(TEXTS["R5"]), "main_category": "工作環境", "sub_category": "E1 設施",
         "secondary_sub_category": None, "reasoning": "r", "summary": "s", "confidence": 0.9,
         "methodology": "Method E1", "citation": "Cite E1", "secondary_methodology": None,
         "secondary_citation": None, "status": "completed", "error_detail": None},
    ]}
    first = attempt_service.apply_attempt(scope, good, vid, plan_a["expected_attempt_no"], plan_a["mode"])
    db.session.commit()
    second = attempt_service.apply_attempt(scope, good, vid, plan_b["expected_attempt_no"], plan_b["mode"])
    db.session.commit()
    check("第一個請求生效", first.applied)
    check("第二個請求被判定為 attempt conflict，不寫入", second.outcome == attempt_service.OUTCOME_CONFLICT)
    cur = attempt_service.current_rows(scope)
    check("R5 只有一份 current attempt", len(cur) == 1 and cur[0].attempt_no == 2)

    print("\n--- 模擬併發：同一則回答第一次分析被寫兩次 ---")
    tpl_resp = m.Survey_Response(template_id=TEMPLATE_ID, answer_json={"answers": {"q1": "全新的一則"}})
    db.session.add(tpl_resp)
    db.session.commit()
    new_scope = attempt_service.survey_scope(tpl_resp.response_id, "q1", "全新的一則")
    one = attempt_service.apply_attempt(new_scope, good | {"segments": [dict(good["segments"][0], orig_end=5)]}, vid, 0, attempt_service.MODE_NEW)
    db.session.commit()
    two = attempt_service.apply_attempt(new_scope, good | {"segments": [dict(good["segments"][0], orig_end=5)]}, vid, 0, attempt_service.MODE_NEW)
    db.session.commit()
    check("第一次寫入生效、第二次 conflict", one.applied and two.outcome == attempt_service.OUTCOME_CONFLICT)
    check("只有一份結果", len(attempt_service.current_rows(new_scope)) == 1
          and m.Response_Segmentation_Status.query.filter_by(response_id=tpl_resp.response_id).count() == 1)

    print("\n--- 規劃之後才被審核：整則重新分析不得取代 ---")
    tpl_resp2 = m.Survey_Response(template_id=TEMPLATE_ID, answer_json={"answers": {"q1": "規劃後才審核"}})
    db.session.add(tpl_resp2)
    db.session.flush()
    db.session.add(m.Response_Segmentation_Status(response_id=tpl_resp2.response_id, question_id="q1",
                                                  source_type="survey", segmentation_status="failed"))
    late = m.Response_Classification(response_id=tpl_resp2.response_id, source_type="survey", question_id="q1",
                                     answer_text="規劃後才審核", segment_start=0, segment_end=3, main_category="x",
                                     sub_category="y", status="completed", review_status="pending_review")
    db.session.add(late)
    db.session.commit()
    scope2 = attempt_service.survey_scope(tpl_resp2.response_id, "q1", "規劃後才審核")
    plan = attempt_service.plan_reanalysis(scope2)
    check("規劃時是整則重新分析", plan["mode"] == attempt_service.MODE_FULL)
    late.review_status = "confirmed"
    db.session.commit()
    out = attempt_service.apply_attempt(scope2, good | {"segments": [dict(good["segments"][0], orig_end=3)]}, vid,
                                        plan["expected_attempt_no"], plan["mode"])
    db.session.commit()
    check("寫入時發現已被審核 -> blocked，confirmed 列仍生效",
          out.outcome == attempt_service.OUTCOME_BLOCKED and db.session.get(m.Response_Classification, late.classification_id).status == "completed")

print("\n========== 9. 分析新的回覆會讓既有報告過期（new_results_added）==========")
# 報告不等人工審核，新回覆的分析結果會直接進入下一版報告，所以既有報告要提示需要重新產生。
# 用獨立的問卷，避免前面還在重試的回答（rerun）影響過期原因。
with app.app_context():
    new_tpl = m.Survey_Template(user_id=1, title="新回覆", access_code="NEWR1", question_json={"items": [
        {"id": "q1", "type": "short", "title": "對公司的建議", "question_type": "career"},
    ]})
    db.session.add(new_tpl)
    db.session.flush()
    NEW_TPL_ID = new_tpl.template_id
    db.session.add(m.Survey_Response(template_id=NEW_TPL_ID, answer_json={"answers": {"q1": "希望增加教育訓練"}}))
    db.session.add(m.Report(
        source_type="survey", template_id=NEW_TPL_ID, version=1, generated_by=1, status="completed",
        is_outdated=False, eligible_count_at_generation=0, pending_count_at_generation=0,
        excluded_count_at_generation=0,
    ))
    db.session.commit()


def new_tpl_report():
    with app.app_context():
        r = m.Report.query.filter_by(template_id=NEW_TPL_ID).one()
        return r.is_outdated, r.outdated_reason


GEMINI_QUEUE.clear()
q({"segments": [mask_pii("希望增加教育訓練")]})
cls_q(("職涯發展", "A1 教育訓練"))
resp = client.post("/api/surveys/NEWR1/analyze", headers=user_header(1))
check("新回覆 analyze 200、分析 1 則", resp.status_code == 200 and resp.get_json()["newly_classified_count"] == 1)
check("既有報告標記過期，原因是 new_results_added", new_tpl_report() == (True, "new_results_added"))

with app.app_context():
    r = m.Report.query.filter_by(template_id=NEW_TPL_ID).one()
    r.is_outdated, r.outdated_reason, r.outdated_at = False, None, None
    db.session.commit()
GEMINI_QUEUE.clear()
resp = client.post("/api/surveys/NEWR1/analyze", headers=user_header(1))
check("沒有新回覆時再 analyze：沒有新結果", resp.status_code == 200 and resp.get_json()["newly_classified_count"] == 0)
check("沒有新結果時報告維持最新", new_tpl_report() == (False, None))

finish()
