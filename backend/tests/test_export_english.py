#!/usr/bin/env python
"""
匯出檔案的語言：英文介面的使用者拿到的 Excel / Word，系統固定文字全部是英文。

語言 = ui_lang（使用者匯出當下的 Accept-Language）。使用者的資料（回答、題目、類別名稱、AI 產生的
理由 / 摘要）不翻譯。只服務使用者端的匯出；Admin 報告匯出不傳語言，維持原本的繁體中文。

涵蓋：
    1. 英文匯出（8 種：分類結果 / 問卷原始回覆 × Excel / Word × 有無評分統計、匿名 / 具名、無回覆）：
       用英文資料，抽出檔案內所有文字，不能有任何漢字
       - 對照組：同一份資料用 zh-TW 匯出，檢查器一定要抓得到漢字（證明檢查本身有效）
    2. 欄位標題 / 分頁名稱 / 標籤的實際內容（與畫面上的英文措辭一致）
    3. 繁體中文輸出與改動前完全相同（預設 lang、lang="zh-TW"、lang 不合法都一樣）
    4. 「受試者N：」「（次要分類）」轉換（與前端共用 language_cases.json 的案例）；回答原文不動
    5. 路由：Accept-Language 決定語言；沒有 Accept-Language -> 繁體中文；分頁與下載檔名
    6. 使用者的資料不被翻譯

執行方式：
    cd backend
    python3 tests/test_export_english.py
"""

import base64
import datetime
import io
import json
import os
import re

import docx
import openpyxl

from admin_test_support import check, create_app, finish, seed_people, user_header
import models as m
from extensions import db
from services import export_file_service as E
from services.export_labels import export_labels, localize_respondent_text

HAN = re.compile(r"[\u4e00-\u9fff]")
CASES = json.load(open(os.path.join(os.path.dirname(__file__), "fixtures", "language_cases.json"), encoding="utf-8"))

ROWS = [
    {"main_category": "Learning", "sub_category": "Course needs",
     "respondent_text": "受試者1：I want more Excel courses\n受試者2：Please add English classes（次要分類）",
     "aggregated_reasoning": "Respondents ask for training.", "aggregated_summary": "Wants more courses.", "source_column": "Feedback"},
    {"main_category": "Environment", "sub_category": "Equipment", "respondent_text": "受試者3：The projector is too old",
     "aggregated_reasoning": "Old equipment.", "aggregated_summary": "Replace the projector.", "source_column": "Suggestions"},
]
RATING = [
    {"question_number": 3, "title": "Overall satisfaction", "average": 3.5, "answered_count": 8,
     "distribution": {"0": 0, "1": 1, "2": 1, "3": 2, "4": 3, "5": 1}},
    {"question_number": 4, "title": "Would recommend", "average": None, "answered_count": 0, "distribution": {}},
]
QUESTIONS = [{"id": "q1", "title": "Do you like it?", "type": "text"}, {"id": "q2", "title": "Pick several", "type": "checkbox"},
             {"id": "q3", "title": "Satisfaction", "type": "rating"}, {"id": "q4", "title": "Comment", "type": "text"}]
RESPONSES = [
    {"answers": {"q1": "Yes", "q2": ["A", "B"], "q3": 4}, "respondent_identity": "Alex", "submitted_at": datetime.datetime(2026, 9, 20, 5, 30)},
    {"answers": {"q3": 0, "q4": None}, "respondent_identity": None, "submitted_at": None},
]


def xlsx_texts(data):
    wb = openpyxl.load_workbook(io.BytesIO(data))
    out = [ws.title for ws in wb.worksheets]
    for ws in wb.worksheets:
        out += [str(c.value) for row in ws.iter_rows() for c in row if c.value not in (None, "")]
    return out, [ws.title for ws in wb.worksheets], wb


def docx_texts(data):
    d = docx.Document(io.BytesIO(data))
    out = [p.text for p in d.paragraphs if p.text.strip()]
    out += [c.text for t in d.tables for r in t.rows for c in r.cells if c.text.strip()]
    return out


def builders(lang):
    return {
        "分類結果 xlsx（含評分統計）": lambda: xlsx_texts(E.build_xlsx(ROWS, rating_stats=RATING, lang=lang))[0],
        "分類結果 xlsx（預設標題）": lambda: xlsx_texts(E.build_xlsx(ROWS, lang=lang))[0],
        "分類結果 docx（含評分統計）": lambda: docx_texts(E.build_docx(ROWS, rating_stats=RATING, lang=lang)),
        "分類結果 docx（多題目）": lambda: docx_texts(E.build_docx(ROWS, lang=lang)),
        "問卷原始回覆 xlsx（匿名）": lambda: xlsx_texts(E.build_survey_xlsx(title="Course survey", questions=QUESTIONS, responses=RESPONSES, identity_mode="anonymous", lang=lang))[0],
        "問卷原始回覆 xlsx（具名）": lambda: xlsx_texts(E.build_survey_xlsx(title="Course survey", questions=QUESTIONS, responses=RESPONSES, identity_mode="identified", lang=lang))[0],
        "問卷原始回覆 docx（具名）": lambda: docx_texts(E.build_survey_docx(title="Course survey", questions=QUESTIONS, responses=RESPONSES, identity_mode="identified", lang=lang)),
        "問卷原始回覆 docx（無回覆）": lambda: docx_texts(E.build_survey_docx(title="", questions=QUESTIONS, responses=[], identity_mode="anonymous", lang=lang)),
    }


print("========== 1. 英文匯出：檔案裡沒有任何漢字 ==========")
for name, build in builders("en").items():
    texts = build()
    han = [t for t in texts if HAN.search(t)]
    check(f"{name}：{len(texts)} 段文字、漢字 0 段" + (f"（漏翻：{han[:2]}）" if han else ""), not han)

print("\n   --- 對照組：同一份資料用 zh-TW 匯出，檢查器要抓得到漢字 ---")
for name, build in builders("zh-TW").items():
    check(f"{name}：zh-TW 版含漢字（證明上面的檢查有效）", any(HAN.search(t) for t in build()))

print("\n========== 2. 欄位標題 / 分頁名稱 / 標籤 ==========")
texts, sheets, wb = xlsx_texts(E.build_xlsx(ROWS, rating_stats=RATING, lang="en"))
check("分頁：Rating summary + Classification results", sheets == ["Rating summary", "Classification results"])
ws = wb["Classification results"]
check("欄位標題沿用畫面上的英文措辭", [c.value for c in ws[1]] == ["Main category", "Subcategory", "Survey response", "Reasoning and explanation", "Summary of respondent suggestions"])
rating_ws = wb["Rating summary"]
rating_text = [str(c.value) for row in rating_ws.iter_rows() for c in row if c.value]
check("評分統計：Average score / Valid responses / No data", "Average score: " in rating_text and "Valid responses: " in rating_text and "No data" in rating_text)
check("評分統計：分數表頭與人數（含單複數：1 point / 1 respondent）", "5 points" in rating_text and "3 respondents" in rating_text and "1 point" in rating_text and "1 respondent" in rating_text and "1 points" not in rating_text and "1 respondents" not in rating_text)
check("評分統計：題目列用 Q3: 標題", any(t.startswith("Q3: Overall satisfaction") for t in rating_text))
check("評分統計：跳轉提示是英文、指向真實分頁名稱",
      any("Classification results" in t and "second tab" in t for t in rating_text) and not any(HAN.search(t) for t in rating_text))
check("自訂標題優先於預設分頁名稱", xlsx_texts(E.build_xlsx(ROWS, title="My analysis", lang="en"))[1] == ["My analysis"])
survey_ws = xlsx_texts(E.build_survey_xlsx(title="Course survey", questions=QUESTIONS, responses=RESPONSES, identity_mode="anonymous", lang="en"))[2]["Course survey"]
check("問卷匯出表頭：Respondent / Submitted / Q1: …", [c.value for c in survey_ws[1]][:3] == ["Respondent", "Submitted", "Q1: Do you like it?"])
check("匿名受試者：Anonymous respondent N", survey_ws["A2"].value == "Anonymous respondent 1" and survey_ws["A3"].value == "Anonymous respondent 2")
check("沒作答：No answer；有作答的原樣", survey_ws["C3"].value == "No answer" and survey_ws["D3"].value == "No answer" and survey_ws["F3"].value == "No answer" and survey_ws["C2"].value == "Yes")
check("評分 0 分仍是數字 0（不是 No answer）、4 分是 4", survey_ws["E3"].value == 0 and survey_ws["E2"].value == 4)
identified = xlsx_texts(E.build_survey_xlsx(title="Course survey", questions=QUESTIONS, responses=RESPONSES, identity_mode="identified", lang="en"))[2]["Course survey"]
check("具名但沒填身分：(identity not provided)", identified["A3"].value == "(identity not provided)" and identified["A2"].value == "Alex")
q2 = [c.value for c in identified[2]]
check("多選答案：A, B（不是頓號）", "A, B" in q2 and "A、B" not in q2)
word = docx_texts(E.build_survey_docx(title="Course survey", questions=QUESTIONS, responses=RESPONSES, identity_mode="identified", lang="en"))
check("Word 問卷：Respondent: / Submitted: / Question / Answer", "Respondent: Alex" in word and any(t.startswith("Submitted: ") for t in word) and "Question" in word and "Answer" in word)
word_cls = docx_texts(E.build_docx(ROWS, rating_stats=RATING, lang="en"))
check("Word 分類結果：Rating summary 標題 + Average score + Valid responses", "Rating summary" in word_cls and "Average score: 3.5 / 5" in word_cls and "Valid responses: 8" in word_cls)
check("Word 分布一行：含單複數（1 point: 1 respondent … 5 points: 1 respondent）", any("1 point: 1 respondent" in t and "3 points: 2 respondents" in t and "5 points: 1 respondent" in t and "1 points" not in t for t in word_cls))

print("\n========== 3. 繁體中文輸出與改動前相同 ==========")
default_xlsx = E.build_xlsx(ROWS, title="我的分析")
for label, data in (("lang=zh-TW", E.build_xlsx(ROWS, title="我的分析", lang="zh-TW")), ("lang 不合法（fr）", E.build_xlsx(ROWS, title="我的分析", lang="fr")),
                    ("lang=None", E.build_xlsx(ROWS, title="我的分析", lang=None))):
    a, b = xlsx_texts(default_xlsx)[0], xlsx_texts(data)[0]
    check(f"{label} 與預設輸出相同", a == b)
zh_ws = xlsx_texts(E.build_xlsx(ROWS, rating_stats=RATING))[2]
check("預設仍是繁體中文欄位標題與分頁", [c.value for c in zh_ws["分類結果"][1]] == E.COLUMN_HEADERS and zh_ws.sheetnames == ["評分題統計", "分類結果"])
check("繁中的「受試者N：」「（次要分類）」原樣", "受試者2：Please add English classes（次要分類）" in zh_ws["分類結果"]["C2"].value)

print("\n========== 4. 「受試者N：」「（次要分類）」轉換（與前端共用案例）==========")
for case in CASES["respondent_text_cases"]:
    check(f"{case['name']}：en", localize_respondent_text(case["input"], "en") == case["en"])
    check(f"{case['name']}：zh-TW 原樣", localize_respondent_text(case["input"], "zh-TW") == case["zh-TW"])
check("非字串 / None 原樣回傳", localize_respondent_text(None, "en") is None and localize_respondent_text(123, "en") == 123)
check("使用者的回答原文不被翻譯（只轉固定字樣）", "I want more Excel courses" in xlsx_texts(E.build_xlsx(ROWS, lang="en"))[2]["Classification results"]["C2"].value)

print("\n========== 5. 路由：Accept-Language 決定匯出語言 ==========")
app = create_app()
client = app.test_client()
with app.app_context():
    seed_people()
    if db.session.get(m.Workspace, 1) is None:
        db.session.add(m.Workspace(project_id=1, user_id=1, project_name="ws")); db.session.flush()
    chat = m.Chat_History(project_id=1, sender_type="ai", message_content="legacy text, not a classification snapshot")
    db.session.add(chat); db.session.commit()
    chat_id = chat.chat_id


def export(lang_header, export_type="xlsx", **extra):
    headers = dict(user_header(1))
    if lang_header is not None:
        headers["Accept-Language"] = lang_header
    body = {"export_type": export_type, "chat_id": chat_id, "filename": "result", "rows": ROWS, "rating_stats": RATING, **extra}
    resp = client.post("/api/exports", json=body, headers=headers)
    return resp


def stored_texts(resp):
    export_id = resp.get_json()["export_id"]
    content = db.session.get(m.Export_File, export_id).content
    return base64.b64decode(content)


with app.app_context():
    r = export("en")
    check("英文介面：匯出成功", r.status_code in (200, 201))
    data = stored_texts(r)
    texts, sheets, _ = xlsx_texts(data)
    check("英文介面：分頁與欄位是英文、沒有漢字（除了使用者資料裡系統組的字樣已被轉換）", sheets == ["Rating summary", "Classification results"] and not any(HAN.search(t) for t in texts))
    r = export("zh-TW")
    check("中文介面：維持繁體中文", xlsx_texts(stored_texts(r))[1] == ["評分題統計", "分類結果"])
    r = export(None)
    check("沒有 Accept-Language：維持繁體中文（原本行為）", xlsx_texts(stored_texts(r))[1] == ["評分題統計", "分類結果"])
    r = export("fr-FR,fr;q=0.9")
    check("不支援的語言：維持繁體中文", xlsx_texts(stored_texts(r))[1] == ["評分題統計", "分類結果"])
    r = export("en", title="My analysis")
    check("前端自訂 title 優先（不被預設分頁名稱蓋掉）", "My analysis" in xlsx_texts(stored_texts(r))[1])
    r = export("en", export_type="docx")
    d = docx_texts(stored_texts(r))
    check("英文介面 Word：沒有漢字", not any(HAN.search(t) for t in d) and "Rating summary" in d)
    r = export("en", rating_stats=None)
    check("英文介面、無評分統計：預設分頁 Classification results", xlsx_texts(stored_texts(r))[1] == ["Classification results"])

print("\n========== 6. 問卷原始回覆下載（語言與檔名）==========")
from urllib.parse import unquote
from flask import Flask
from routes.surveys.survey import survey_bp

# 共用的 create_app() 沒註冊問卷 blueprint（也不該為了這支測試去改共用的測試工具）。
# 另起一個 Flask app 不行（SQLite :memory: 每個連線各一份、Flask-SQLAlchemy 也要求每個 app 各自 init_app），
# 所以在這支測試自己的 app 上補註冊；必須在 app 處理第一個請求之前，所以用全新的 app 做這一節。
from flask import Flask
from extensions import db as _db
from routes.surveys.survey import survey_bp
from routes.exports.export import exports_bp

survey_app = Flask("survey_export_test")
survey_app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
survey_app.config["TESTING"] = True
survey_app.register_blueprint(survey_bp)
_db.init_app(survey_app)
survey_client = survey_app.test_client()
with survey_app.app_context():
    _db.create_all()
    seed_people()

with survey_app.app_context():
    tpl = m.Survey_Template(user_id=1, title="Course survey", access_code="EXPL1", is_anonymous=True,
                            question_json={"identity_mode": "anonymous", "items": QUESTIONS})
    db.session.add(tpl)
    db.session.flush()
    for answers in ({"q1": "Yes", "q2": ["A", "B"], "q3": 4}, {"q3": 0}):
        db.session.add(m.Survey_Response(template_id=tpl.template_id, answer_json={"answers": answers}))
    blank = m.Survey_Template(user_id=1, title="", access_code="EXPL2", is_anonymous=True,
                              question_json={"identity_mode": "anonymous", "items": QUESTIONS})
    db.session.add(blank)
    db.session.commit()


def download(code, fmt, lang_header):
    headers = dict(user_header(1))
    if lang_header is not None:
        headers["Accept-Language"] = lang_header
    return survey_client.get(f"/api/surveys/{code}/export?format={fmt}", headers=headers)


def disposition_name(resp):
    cd = resp.headers["Content-Disposition"]
    return unquote(cd.split("filename*=UTF-8''", 1)[1])


r = download("EXPL1", "xlsx", "en")
texts, sheets, wb = xlsx_texts(r.data)
check("問卷下載（英文介面）：200", r.status_code == 200)
check("問卷下載（英文介面）：分頁與標籤是英文、沒有漢字", sheets == ["Rating summary", "Course survey"] and not any(HAN.search(t) for t in texts))
check("問卷下載（英文介面）：匿名受試者與未作答是英文", wb["Course survey"]["A2"].value == "Anonymous respondent 1" and wb["Course survey"]["D3"].value == "No answer")
check("問卷下載（英文介面）：檔名後綴是 Survey_responses", disposition_name(r) == "Course survey_Survey_responses.xlsx")
r = download("EXPL1", "docx", "en")
check("問卷下載 Word（英文介面）：沒有漢字", r.status_code == 200 and not any(HAN.search(t) for t in docx_texts(r.data)))
r = download("EXPL1", "xlsx", "zh-TW")
check("問卷下載（中文介面）：維持繁體中文", xlsx_texts(r.data)[1] == ["評分題統計", "Course survey"] and disposition_name(r) == "Course survey_問卷回覆.xlsx")
r = download("EXPL1", "xlsx", None)
check("問卷下載（沒有 Accept-Language）：維持繁體中文", disposition_name(r) == "Course survey_問卷回覆.xlsx")
r = download("EXPL2", "xlsx", "en")
check("問卷沒有標題 + 英文介面：預設分頁與檔名是英文", xlsx_texts(r.data)[1][-1] == "Survey responses" and disposition_name(r) == "Survey responses_Survey_responses.xlsx")

finish()
