"""
測試腳本：對 backend/routes/classifications/classification.py 的兩條路由
（POST /api/survey-response、POST /api/classification/upload）做端到端測試。

用真實的 Flask app + 真實的 SQLAlchemy model（只建立分類相關資料表，
避開專案裡其他跟這次功能無關、在 SQLite 上編譯會失敗的 MySQL 專屬型別
如 MEDIUMTEXT）+ 假的 google.generativeai，驗證整條 pipeline：

    routing -> 遮罩 -> 拆分 -> 驗證 -> 批次分類 -> 寫入 DB

執行方式：
    cd backend
    python3 test_classification_routes.py
"""

import sys
import os
import types
import json
import io

sys.path.insert(0, os.path.dirname(__file__))

FAILED = []


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    if status == "FAIL":
        FAILED.append(label)
    print(f"[{status}] {label}")


# ── 假的 google.generativeai：依序從佇列吐出回應 ──
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


from flask import Flask
from extensions import db
import models as m
from routes.classifications.classification import classification_bp
from services.privacy_service import mask_pii

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

    db.session.add(m.Prompt_Template(
        prompt_key="leadership_and_dept", draft_content="d", live_content="LIVE_LEADERSHIP_PROMPT"
    ))
    db.session.add(m.Prompt_Template(
        prompt_key="career_and_feedback", draft_content="d", live_content="LIVE_CAREER_PROMPT"
    ))
    db.session.commit()

client = app.test_client()


# ═══════════════════════════════════════════════════════════════
# 測試 A：Survey 路由端到端
# ═══════════════════════════════════════════════════════════════
print("========== Survey：端到端測試 ==========")

SURVEY_ANSWER = "王小明覺得主管很願意聽取意見，但工作量太大，希望增加人力"
MASKED_SURVEY_ANSWER = mask_pii(SURVEY_ANSWER)
print(f"masked = {MASKED_SURVEY_ANSWER!r}")

with app.app_context():
    template = m.Survey_Template(title="測試問卷", access_code="TEST1", question_json={
        "items": [
            {"id": "q1", "type": "short", "title": "對主管的建議", "question_type": "leadership_and_dept"},
            {"id": "q2", "type": "short", "title": "沒有 routing 結果的題目", "question_type": None},
        ]
    })
    db.session.add(template)
    db.session.commit()
    template_id = template.template_id

q({"segments": [MASKED_SURVEY_ANSWER[:MASKED_SURVEY_ANSWER.index("，但")], MASKED_SURVEY_ANSWER[MASKED_SURVEY_ANSWER.index("，但") + 1:]]})
q({"classifications": [
    {"index": 0, "main_category": "主管領導", "sub_category": "A2 回饋與溝通",
     "secondary_sub_category": None, "reasoning": "r1", "summary": "s1", "confidence": "high"},
    {"index": 1, "main_category": "部門合作", "sub_category": "B2 支援協作",
     "secondary_sub_category": None, "reasoning": "r2", "summary": "s2", "confidence": "high"},
]})

resp = client.post("/api/survey-response", json={
    "template_id": template_id,
    "answer_json": {"answers": {
        "q1": SURVEY_ANSWER,
        "q2": "這題沒有 question_type，應該被跳過",
    }},
})
data = resp.get_json()

check("HTTP 201", resp.status_code == 201)
check("classified_question_count 為 1", data.get("classified_question_count") == 1)
check("q2 出現在 skipped_question_ids", data.get("skipped_question_ids") == ["q2"])

with app.app_context():
    rc_rows = m.Response_Classification.query.filter_by(response_id=data["response_id"]).all()
    rss_rows = m.Response_Segmentation_Status.query.filter_by(response_id=data["response_id"]).all()

    check("寫入 2 筆 Response_Classification（一個 segment 一筆）", len(rc_rows) == 2)
    check("寫入 1 筆 Response_Segmentation_Status", len(rss_rows) == 1)
    check("Response_Classification.answer_text 是完整原文（非片段）", all(r.answer_text == SURVEY_ANSWER for r in rc_rows))
    check("Response_Classification.response_id 正確帶入", all(r.response_id == data["response_id"] for r in rc_rows))
    check("Response_Classification.upload_batch_id 為 None（survey 來源）", all(r.upload_batch_id is None for r in rc_rows))
    check("Response_Classification.uploaded_answer_id 為 None（survey 來源）", all(r.uploaded_answer_id is None for r in rc_rows))
    check("segment_start/segment_end 可以正確切出對應原文片段", any(
        SURVEY_ANSWER[r.segment_start:r.segment_end] in SURVEY_ANSWER for r in rc_rows
    ))
    check("Response_Segmentation_Status.segmentation_status 為 completed", rss_rows[0].segmentation_status == "completed")


# ═══════════════════════════════════════════════════════════════
# 測試 B：Excel 上傳路由端到端
# ═══════════════════════════════════════════════════════════════
print("\n========== Excel 上傳：端到端測試 ==========")

import pandas as pd

df = pd.DataFrame({"意見": [
    "主管很願意聽取意見",
    "希望增加人力資源",
    "陳怡君覺得溝通不錯",
    "",
    None,
]})
buf = io.BytesIO()
df.to_excel(buf, index=False)
buf.seek(0)

q({"question_type": "leadership_and_dept"})  # routing
q({"segments": ["主管很願意聽取意見"]})
q({"classifications": [{"index": 0, "main_category": "m", "sub_category": "A2 回饋與溝通",
                          "secondary_sub_category": None, "reasoning": "r", "summary": "s", "confidence": "high"}]})
q({"segments": ["希望增加人力資源"]})
q({"classifications": [{"index": 0, "main_category": "m", "sub_category": "B2 支援協作",
                          "secondary_sub_category": None, "reasoning": "r", "summary": "s", "confidence": "high"}]})
q({"segments": [mask_pii("陳怡君覺得溝通不錯")]})
q({"classifications": [{"index": 0, "main_category": "m", "sub_category": "A2 回饋與溝通",
                          "secondary_sub_category": None, "reasoning": "r", "summary": "s", "confidence": "high"}]})

resp = client.post("/api/classification/upload", data={
    "file": (buf, "test.xlsx"),
    "text_column": "意見",
})
data = resp.get_json()

check("HTTP 201", resp.status_code == 201)
check("question_type 判斷成功", data.get("question_type") == "leadership_and_dept")
check("saved_answer_count 為 3（跳過空字串與 None）", data.get("saved_answer_count") == 3)
check("classified_count 為 3", data.get("classified_count") == 3)

with app.app_context():
    batch_id = data["upload_batch_id"]
    ua_rows = m.Uploaded_Answer.query.filter_by(upload_batch_id=batch_id).all()
    rc_rows = m.Response_Classification.query.filter_by(upload_batch_id=batch_id).all()
    rss_rows = m.Response_Segmentation_Status.query.filter_by(upload_batch_id=batch_id).all()

    check("Uploaded_Answer 寫入 3 筆", len(ua_rows) == 3)
    check("Uploaded_Answer 保留完整原文（含明文 PII，例如陳怡君）", any("陳怡君" in u.answer_text for u in ua_rows))
    check("Uploaded_Answer.question_type 全部正確填入", all(u.question_type == "leadership_and_dept" for u in ua_rows))
    check("Response_Classification 寫入 3 筆（各自對應一個 segment）", len(rc_rows) == 3)
    check("Response_Classification.upload_batch_id 正確帶入", all(r.upload_batch_id == batch_id for r in rc_rows))
    check("Response_Classification.response_id 為 None（user_upload 來源）", all(r.response_id is None for r in rc_rows))
    check("Response_Classification.uploaded_answer_id 皆有值且對應到 Uploaded_Answer", all(
        r.uploaded_answer_id in [u.id for u in ua_rows] for r in rc_rows
    ))
    check("Response_Segmentation_Status 寫入 3 筆（各自對應一個 Uploaded_Answer）", len(rss_rows) == 3)
    check(
        "Response_Segmentation_Status.uploaded_answer_id 彼此不重複（unique 生效）",
        len({r.uploaded_answer_id for r in rss_rows}) == 3,
    )


print("\n========== Excel 上傳：routing 失敗 fallback 路徑 ==========")

df2 = pd.DataFrame({"雜項": ["隨便寫點什麼", "再寫一點別的"]})
buf2 = io.BytesIO()
df2.to_excel(buf2, index=False)
buf2.seek(0)

q("not valid json")  # routing 呼叫失敗

resp2 = client.post("/api/classification/upload", data={
    "file": (buf2, "t2.xlsx"),
    "text_column": "雜項",
})
data2 = resp2.get_json()

check("HTTP 201（routing 失敗不影響上傳本身成功）", resp2.status_code == 201)
check("question_type 為 None", data2.get("question_type") is None)
check("saved_answer_count 為 2（原始內容仍照常保存）", data2.get("saved_answer_count") == 2)
check("classified_count 為 0（不進 segmentation/classification）", data2.get("classified_count") == 0)

with app.app_context():
    batch_id2 = data2["upload_batch_id"]
    ua_rows2 = m.Uploaded_Answer.query.filter_by(upload_batch_id=batch_id2).all()
    rc_rows2 = m.Response_Classification.query.filter_by(upload_batch_id=batch_id2).all()
    rss_rows2 = m.Response_Segmentation_Status.query.filter_by(upload_batch_id=batch_id2).all()

    check("routing 失敗仍寫入 2 筆 Uploaded_Answer", len(ua_rows2) == 2)
    check("routing 失敗時 Uploaded_Answer.question_type 皆為 None", all(u.question_type is None for u in ua_rows2))
    check("routing 失敗時完全不建立 Response_Classification", len(rc_rows2) == 0)
    check("routing 失敗時完全不建立 Response_Segmentation_Status", len(rss_rows2) == 0)


print("\n" + "=" * 50)
if FAILED:
    print(f"共 {len(FAILED)} 項測試失敗：")
    for f in FAILED:
        print("  -", f)
    sys.exit(1)
else:
    print("全部測試通過！")