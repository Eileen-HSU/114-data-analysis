#!/usr/bin/env python
"""
測試腳本：驗證 backend/services/batch_classification_service.py，
以及 backend/routes/classifications/classification.py 接上批次協調
服務之後的行為（Excel 上傳 + 新的 POST /api/surveys/<access_code>/analyze）。

用真實 Flask app + 真實 SQLAlchemy model（只建立這次會用到的資料表）
+ 假的 google.generativeai，涵蓋：
    - 同一 pending 批次內部去重（trailing-addition 成功案例、
      中段改寫的 fallback 案例）
    - 已分析回答作為 duplicate reference（第二次分析情境）
    - 已分析回答不會被重新處理／重寫
    - Excel 批次去重
    - survey 依 question_id 分組，不同題目不會混在一起去重

執行方式：
    cd backend
    export JWT_SECRET_KEY=test-secret
    python3 test_batch_classification.py
"""

import sys
import os
import types
import json
import io

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only")
sys.path.insert(0, os.path.dirname(__file__))

FAILED = []


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    if status == "FAIL":
        FAILED.append(label)
    print(f"[{status}] {label}")


# ── 假的 google.generativeai ──
_queue = []


class _FakeResp:
    def __init__(self, text):
        self.text = text


class _FakeModel:
    def __init__(self, system_instruction=None, **kwargs):
        self.system_instruction = system_instruction

    def generate_content(self, prompt, **kwargs):
        return _FakeResp(_queue.pop(0))


_fake_genai = types.ModuleType("google.generativeai")
_fake_genai.GenerativeModel = _FakeModel
_fake_genai.configure = lambda **kwargs: None
_fake_google = types.ModuleType("google")
_fake_google.generativeai = _fake_genai
sys.modules["google"] = _fake_google
sys.modules["google.generativeai"] = _fake_genai


def q(obj_or_text):
    _queue.append(obj_or_text if isinstance(obj_or_text, str) else json.dumps(obj_or_text, ensure_ascii=False))


from services.privacy_service import mask_pii
from services.batch_classification_service import run_batch_analysis, _relocate_segments


# ═══════════════════════════════════════════════════════════════
# Part A：batch_classification_service.py 單元測試
# ═══════════════════════════════════════════════════════════════
print("========== Part A：run_batch_analysis / _relocate_segments 單元測試 ==========")

print("\n--- A1：_relocate_segments 基本情境 ---")
segs = _relocate_segments(
    [{"orig_start": 0, "orig_end": 16, "main_category": "m"}],
    "希望主管可以多給一些工作上的回饋",
    "希望主管可以多給一些工作上的回饋，謝謝",
)
check("成功定位，回傳非 None", segs is not None)
check("main_category 沿用", segs[0]["main_category"] == "m")
check("座標正確", "希望主管可以多給一些工作上的回饋，謝謝"[segs[0]["orig_start"]:segs[0]["orig_end"]] == "希望主管可以多給一些工作上的回饋")

segs2 = _relocate_segments(
    [{"orig_start": 0, "orig_end": 21, "main_category": "m"}],
    "主管很願意聽取部屬的意見，整體來說溝通順暢",
    "主管很願意聽取部屬的意見，整體來說溝通算順暢",  # 中段插入「算」
)
check("中段被改寫，定位失敗回傳 None", segs2 is None)

check("空 candidate_segments 回傳 None", _relocate_segments([], "a", "b") is None)


print("\n--- A2：run_batch_analysis 批次內部去重（trailing addition 成功）---")
_queue.clear()
texts = [
    "希望主管可以多給一些工作上的回饋",
    "希望主管可以多給一些工作上的回饋，謝謝",
    "希望增加人力資源，工作量目前太大了",
]
masked_a = mask_pii(texts[0])
masked_c = mask_pii(texts[2])
q({"segments": [masked_a]})
q({"classifications": [{"index": 0, "main_category": "m1", "sub_category": "A2 回饋與溝通",
                          "secondary_sub_category": None, "reasoning": "r", "summary": "s", "confidence": "high"}]})
q({"segments": [masked_c]})
q({"classifications": [{"index": 0, "main_category": "m2", "sub_category": "B2 支援協作",
                          "secondary_sub_category": None, "reasoning": "r", "summary": "s", "confidence": "high"}]})

call_count_before = len(_queue)
pending = [{"identifier": i, "answer_text": t} for i, t in enumerate(texts)]
results = run_batch_analysis([], pending, "prompt", "leadership_and_dept")

check("只呼叫 4 次（A的2次+C的2次，B沿用零呼叫）", len(_queue) == 0)
check("item1(B) 正確沿用 item0(A)", results[1]["reused_from"] == 0)
check("item1 座標正確指向自己的原文", texts[1][results[1]["segments"][0]["orig_start"]:results[1]["segments"][0]["orig_end"]] == texts[0])
check("item2(C) 是全新處理", results[2]["reused_from"] is None)


print("\n--- A3：中段改寫，relocation 失敗，fallback 完整處理 ---")
_queue.clear()
texts2 = [
    "主管很願意聽取部屬的意見，整體來說溝通順暢",
    "主管很願意聽取部屬的意見，整體來說溝通算順暢",
]
masked_a2 = mask_pii(texts2[0])
masked_b2 = mask_pii(texts2[1])
q({"segments": [masked_a2]})
q({"classifications": [{"index": 0, "main_category": "m", "sub_category": "A2 回饋與溝通",
                          "secondary_sub_category": None, "reasoning": "r", "summary": "s", "confidence": "high"}]})
q({"segments": [masked_b2]})
q({"classifications": [{"index": 0, "main_category": "m", "sub_category": "A2 回饋與溝通",
                          "secondary_sub_category": None, "reasoning": "r2", "summary": "s2", "confidence": "high"}]})

pending2 = [{"identifier": i, "answer_text": t} for i, t in enumerate(texts2)]
results2 = run_batch_analysis([], pending2, "prompt", "leadership_and_dept")
check("relocation 失敗時完整呼叫 4 次（沒有省到）", len(_queue) == 0)
check("fallback 後不標記為沿用", results2[1]["reused_from"] is None)
check("fallback 後仍正確完成分類", results2[1]["segmentation_status"] == "completed")


print("\n--- A4：沿用既有已分析回答（第二次分析情境），零 Gemini 呼叫 ---")
existing = [{
    "identifier": 3,
    "answer_text": "希望主管可以多給一些工作上的回饋",
    "segments": [{
        "orig_start": 0, "orig_end": 16,
        "main_category": "m", "sub_category": "A2 回饋與溝通", "secondary_sub_category": None,
        "reasoning": "r", "summary": "s", "confidence": "high",
        "methodology": "x", "citation": "y", "secondary_methodology": None, "secondary_citation": None,
        "status": "completed",
    }],
}]
pending3 = [{"identifier": 11, "answer_text": "希望主管可以多給一些工作上的回饋，謝謝"}]
_queue.clear()
results3 = run_batch_analysis(existing, pending3, "prompt", "leadership_and_dept")
check("完全零 Gemini 呼叫", len(_queue) == 0)
check("正確標記沿用自 identifier 3", results3[0]["reused_from"] == 3)
check("新回答的座標指向自己的原文", pending3[0]["answer_text"][results3[0]["segments"][0]["orig_start"]:results3[0]["segments"][0]["orig_end"]] == existing[0]["answer_text"])


# ═══════════════════════════════════════════════════════════════
# Part B：完整 Flask + 真實 model 端到端測試
# ═══════════════════════════════════════════════════════════════
print("\n========== Part B：完整端到端測試（真實 Flask app + 真實 model）==========")

import jwt
from flask import Flask
from extensions import db
import models as m
from routes.classifications.classification import classification_bp

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
app.config["TESTING"] = True
app.register_blueprint(classification_bp)
db.init_app(app)

with app.app_context():
    tables = [
        m.Survey_Template.__table__,
        m.Survey_Response.__table__,
        m.Prompt_Template.__table__,
        m.Response_Classification.__table__,
        m.Response_Segmentation_Status.__table__,
        m.Uploaded_Answer.__table__,
    ]
    db.metadata.create_all(bind=db.engine, tables=tables)

    db.session.add(m.Prompt_Template(prompt_key="leadership_and_dept", draft_content="d", live_content="LIVE_PROMPT"))
    db.session.commit()

client = app.test_client()


def auth_header(user_id):
    token = jwt.encode({"user_id": user_id}, os.environ["JWT_SECRET_KEY"], algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


print("\n--- B1：Survey 第一次分析（10 筆回答，含內部重複）---")
with app.app_context():
    template = m.Survey_Template(
        title="測試問卷", access_code="TEST1", user_id=1,
        question_json={"items": [
            {"id": "q1", "type": "short", "title": "對主管的建議", "question_type": "leadership_and_dept"},
        ]},
    )
    db.session.add(template)
    db.session.commit()
    template_id = template.template_id
    access_code = template.access_code

    answer_texts = [
        "希望主管可以多給一些工作上的回饋",       # r0：代表項
        "希望主管可以多給一些工作上的回饋，謝謝",  # r1：應沿用 r0
        "希望增加人力資源",                       # r2：獨立
    ]
    response_ids = []
    for t in answer_texts:
        r = m.Survey_Response(template_id=template_id, answer_json={"answers": {"q1": t}})
        db.session.add(r)
        db.session.flush()
        response_ids.append(r.response_id)
    db.session.commit()

masked_r0 = mask_pii(answer_texts[0])
masked_r2 = mask_pii(answer_texts[2])
q({"segments": [masked_r0]})
q({"classifications": [{"index": 0, "main_category": "m1", "sub_category": "A2 回饋與溝通",
                          "secondary_sub_category": None, "reasoning": "r", "summary": "s", "confidence": "high"}]})
q({"segments": [masked_r2]})
q({"classifications": [{"index": 0, "main_category": "m2", "sub_category": "B2 支援協作",
                          "secondary_sub_category": None, "reasoning": "r", "summary": "s", "confidence": "high"}]})

resp = client.post(f"/api/surveys/{access_code}/analyze", headers=auth_header(1))
data = resp.get_json()
check("HTTP 200", resp.status_code == 200)
check("newly_classified_count 為 3", data.get("newly_classified_count") == 3)
check("q1 出現在 analyzed_question_ids", data.get("analyzed_question_ids") == ["q1"])
check("Gemini 呼叫全部消耗完（只呼叫4次，r1零呼叫沿用）", len(_queue) == 0)

with app.app_context():
    rss_rows = m.Response_Segmentation_Status.query.all()
    rc_rows = m.Response_Classification.query.all()
    check("寫入 3 筆 Response_Segmentation_Status（每則回答各一筆）", len(rss_rows) == 3)
    check("寫入 3 筆 Response_Classification（各一個 segment）", len(rc_rows) == 3)

    r1_rc = m.Response_Classification.query.filter_by(response_id=response_ids[1]).first()
    check("r1 沿用了 r0 的分類（sub_category 相同）", r1_rc.sub_category == "A2 回饋與溝通")
    check("r1 的 segment_start/end 指向自己的原文", answer_texts[1][r1_rc.segment_start:r1_rc.segment_end] == answer_texts[0])
    check("r1 的 answer_text 是自己完整的原文，不是 r0 的", r1_rc.answer_text == answer_texts[1])


print("\n--- B2：Survey 第二次分析（新增第 4 筆，跟 r0 相似）---")
with app.app_context():
    r3 = m.Survey_Response(template_id=template_id, answer_json={"answers": {"q1": "希望主管可以多給一些工作上的回饋。"}})
    db.session.add(r3)
    db.session.commit()
    response_id_3 = r3.response_id

_queue.clear()  # 完全不應該有任何 Gemini 呼叫

resp2 = client.post(f"/api/surveys/{access_code}/analyze", headers=auth_header(1))
data2 = resp2.get_json()
check("HTTP 200", resp2.status_code == 200)
check("newly_classified_count 為 1（只有新增那筆）", data2.get("newly_classified_count") == 1)
check("零 Gemini 呼叫（完全靠沿用既有 r0）", len(_queue) == 0)

with app.app_context():
    rss_rows_after = m.Response_Segmentation_Status.query.all()
    rc_rows_after = m.Response_Classification.query.all()
    check("Response_Segmentation_Status 總數變成 4（沒有重寫舊的 3 筆）", len(rss_rows_after) == 4)
    check("Response_Classification 總數變成 4", len(rc_rows_after) == 4)

    r3_rc = m.Response_Classification.query.filter_by(response_id=response_id_3).first()
    check("新回答正確沿用 r0 的分類", r3_rc is not None and r3_rc.sub_category == "A2 回饋與溝通")
    check("新回答的座標指向自己的原文", r3_rc.answer_text[r3_rc.segment_start:r3_rc.segment_end] == "希望主管可以多給一些工作上的回饋")


print("\n--- B3：第三次分析（沒有新回答），完全冪等 ---")
_queue.clear()
resp3 = client.post(f"/api/surveys/{access_code}/analyze", headers=auth_header(1))
data3 = resp3.get_json()
check("HTTP 200", resp3.status_code == 200)
check("newly_classified_count 為 0", data3.get("newly_classified_count") == 0)
check("analyzed_question_ids 為空（沒有題目有新回答要處理）", data3.get("analyzed_question_ids") == [])
with app.app_context():
    check("DB 列數完全沒有增加", m.Response_Segmentation_Status.query.count() == 4 and m.Response_Classification.query.count() == 4)


print("\n--- B4：Excel 上傳批次去重 ---")
import pandas as pd
df = pd.DataFrame({"意見": [
    "主管很願意聽取意見",
    "主管很願意聽取意見，謝謝",  # 應沿用上一筆
    "希望增加教育訓練資源",
]})
buf = io.BytesIO()
df.to_excel(buf, index=False)
buf.seek(0)

masked_e0 = mask_pii("主管很願意聽取意見")
masked_e2 = mask_pii("希望增加教育訓練資源")
q({"question_type": "leadership_and_dept"})  # routing
q({"segments": [masked_e0]})
q({"classifications": [{"index": 0, "main_category": "m", "sub_category": "A2 回饋與溝通",
                          "secondary_sub_category": None, "reasoning": "r", "summary": "s", "confidence": "high"}]})
q({"segments": [masked_e2]})
q({"classifications": [{"index": 0, "main_category": "m", "sub_category": "C1 教育訓練",
                          "secondary_sub_category": None, "reasoning": "r", "summary": "s", "confidence": "high"}]})

resp4 = client.post("/api/classification/upload", data={"file": (buf, "t.xlsx"), "text_column": "意見"})
data4 = resp4.get_json()
check("HTTP 201", resp4.status_code == 201)
check("saved_answer_count 為 3", data4.get("saved_answer_count") == 3)
check("classified_count 為 3（含沿用的那筆）", data4.get("classified_count") == 3)
check("Gemini 呼叫全部消耗完（routing 1次 + 分類4次 = 5次，中間那筆沿用零呼叫）", len(_queue) == 0)

with app.app_context():
    batch_id = data4["upload_batch_id"]
    rc_excel = m.Response_Classification.query.filter_by(upload_batch_id=batch_id).all()
    check("Excel 這批寫入 3 筆 Response_Classification", len(rc_excel) == 3)
    dup_row = [r for r in rc_excel if r.answer_text == "主管很願意聽取意見，謝謝"][0]
    check("Excel 內部沿用正確，sub_category 相同", dup_row.sub_category == "A2 回饋與溝通")
    check("Excel 沿用後座標指向自己的原文", dup_row.answer_text[dup_row.segment_start:dup_row.segment_end] == "主管很願意聽取意見")


print("\n" + "=" * 50)
if FAILED:
    print(f"共 {len(FAILED)} 項測試失敗：")
    for f in FAILED:
        print("  -", f)
    sys.exit(1)
else:
    print("全部測試通過！")