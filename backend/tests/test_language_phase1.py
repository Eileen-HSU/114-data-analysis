#!/usr/bin/env python
"""
多語言第一階段：三種語言來源各自獨立，不混用。

    ui_lang            來源 Accept-Language          （按鈕 / 標題 / 歡迎訊息 / 匯出檔 / AI 產生的理由、摘要、彙整摘要、報告摘要）
    instruction_lang   來源 使用者這次的文字指令     （問答回覆語言；固定系統句）
    data_lang          來源 原始回答內容             （只記在 language 資訊裡；不再決定 AI 內容的語言 —— 規則 A）

涵蓋：
    1. language_service 規則：共用案例 tests/fixtures/language_cases.json（前端 language.js 也跑同一份）
       - 只辨識中文 / 英文；日 / 韓 / 俄 / 泰 / 阿拉伯 / 法西德文、中英混合 -> None（不是「有 CJK 就是中文」）
       - Accept-Language 依 q 值、跳過不支援的語言；請求內讀取、沒有請求時用預設
    2. 問答：回答語言 = instruction_lang（不是 ui_lang）；沒有可判斷的指令才用 ui_lang；
       提示詞不再寫死「繁體中文」，但 zh-TW 時與原本逐字相同
    3. 摘要提示詞：lang 參數決定輸出語言；zh-TW 提示詞與原本逐字相同
    4. 彙整 / 報告（規則 A）：英文介面 -> 英文摘要、中文介面 -> 中文摘要，與資料語言無關
       （中文資料 + 英文介面 = 英文；英文資料 + 中文介面 = 中文）；沒有請求環境才退回資料語言
    5. 上傳回應多帶 language 資訊（不改資料庫）；重新整理快照保留 meta.language
    6. 不影響既有行為：沒有請求環境 / 沒有 Accept-Language -> 與原本一樣是繁體中文

執行方式：
    cd backend
    python3 tests/test_language_phase1.py
"""

import io
import json
import os
from unittest import mock

import pandas as pd

from admin_test_support import (
    GEMINI_QUEUE, check, create_app, finish, q, seed_classification, seed_people, seed_topic, seed_upload_batch,
    seed_workspace_chat, user_header,
)
import models as m
from extensions import db
from services import language_service as ls
from services.privacy_service import mask_pii

os.environ.pop("OPEN_CLASSIFICATION_ENABLED", None)
os.environ.setdefault("GEMINI_API_KEY", "test-key")
app = create_app()
client = app.test_client()

CASES = json.load(open(os.path.join(os.path.dirname(__file__), "fixtures", "language_cases.json"), encoding="utf-8"))


def expand(repeat):
    return [r["text"] for r in repeat for _ in range(r["times"])]


print("========== 1. language_service 共用案例 ==========")
bad = [c["value"] for c in CASES["normalize_cases"] if ls.normalize_lang(c["value"]) != c["expected"]]
check(f"normalize_lang：{len(CASES['normalize_cases'])} 個案例", not bad)
bad = [c["name"] for c in CASES["text_cases"] if ls.detect_text_lang(c["text"]) != c["expected"]]
check(f"detect_text_lang：{len(CASES['text_cases'])} 個案例（失敗：{bad}）", not bad)
bad = [c["header"] for c in CASES["accept_language_cases"] if ls.parse_accept_language(c["header"]) != c["expected"]]
check(f"parse_accept_language：{len(CASES['accept_language_cases'])} 個案例", not bad)
bad = [c["name"] for c in CASES["data_cases"] if ls.detect_data_lang(expand(c["repeat"])) != c["expected"]]
check(f"detect_data_lang：{len(CASES['data_cases'])} 個案例（失敗：{bad}）", not bad)

check("只辨識中文 / 英文：日文含漢字不會被當成中文", ls.detect_text_lang("日本語の分析") is None)
check("只辨識中文 / 英文：法文不會被當成英文", ls.detect_text_lang("Bonjour, je voudrais analyser les résultats") is None)
check("資料抽樣固定（同一批資料每次結果相同）",
      len({ls.detect_data_lang(["很好"] * 500 + ["good"] * 10) for _ in range(5)}) == 1)

with app.test_request_context("/", headers={"Accept-Language": "en-US,en;q=0.9"}):
    check("請求內：ui_lang_from_request 讀 Accept-Language -> en", ls.ui_lang_from_request() == "en")
with app.test_request_context("/", headers={"Accept-Language": "zh-TW"}):
    check("請求內：zh-TW -> zh-TW", ls.ui_lang_from_request() == "zh-TW")
with app.test_request_context("/"):
    check("請求內沒有 Accept-Language -> 預設 zh-TW", ls.ui_lang_from_request() == "zh-TW")
with app.test_request_context("/", headers={"Accept-Language": "fr-FR"}):
    check("請求內只有不支援的語言 -> 預設 zh-TW", ls.ui_lang_from_request() == "zh-TW")
check("不在請求內 -> 預設 zh-TW（背景工作 / 既有測試）", ls.ui_lang_from_request() == "zh-TW")
check("resolve_instruction_lang：指令語言優先於介面語言", ls.resolve_instruction_lang("Please summarize", "zh-TW") == "en"
      and ls.resolve_instruction_lang("請摘要", "en") == "zh-TW")
check("resolve_instruction_lang：沒有指令 / 判斷不出來 -> ui_lang",
      ls.resolve_instruction_lang(None, "en") == "en" and ls.resolve_instruction_lang("123", "en") == "en"
      and ls.resolve_instruction_lang("", "zh-TW") == "zh-TW")
check("resolve_data_lang：資料語言優先於介面語言；判斷不出來 -> ui_lang",
      ls.resolve_data_lang(["很好"] * 5, "en") == "zh-TW" and ls.resolve_data_lang(["good"] * 5, "zh-TW") == "en"
      and ls.resolve_data_lang(["ok", "123"], "en") == "en")
check("language_meta 三種來源分開記", ls.language_meta("en", instruction_lang="zh", data_lang=None)
      == {"ui_lang": "en", "instruction_lang": "zh-TW", "data_lang": None})

print("\n========== 2. 問答：回答語言 = instruction_lang ==========")
from services import chat_ask_service as ask
check("zh-TW 提示詞與原本逐字相同（既有行為不變）", ask.build_system_prompt("zh-TW") == ask.SYSTEM_PROMPT)
en_prompt = ask.build_system_prompt("en")
check("en 提示詞要求用英文回答、不再有「一律使用繁體中文回答」",
      "Answer entirely in English" in en_prompt and "一律使用繁體中文回答" not in en_prompt)
check("提示詞其餘規則不受影響（只換第 7 條）", en_prompt.replace(ls.answer_language_rule("en"), "") .count("嚴格規則") == 1
      and len(en_prompt.splitlines()) == len(ask.SYSTEM_PROMPT.splitlines()))
check("未知語言代碼 -> 預設繁體中文", ask.build_system_prompt("fr") == ask.SYSTEM_PROMPT)

captured = {}


class _Resp:
    text = "answer"


class _Models:
    def generate_content(self, model, contents, config):
        captured["system"] = config.system_instruction
        return _Resp()


class _Client:
    def __init__(self, api_key=None):
        self.models = _Models()


import google.genai as genai_mod
with mock.patch.object(genai_mod, "Client", _Client):
    ask._call_gemini("context", "question", "en")
    check("_call_gemini 把語言傳進系統提示詞（en）", "Answer entirely in English" in captured["system"])
    ask._call_gemini("context", "question")
    check("_call_gemini 沒指定語言 -> 繁體中文（原本行為）", captured["system"] == ask.SYSTEM_PROMPT)

with app.app_context():
    seed_people()
    if db.session.get(m.Workspace, 1) is None:
        db.session.add(m.Workspace(project_id=1, user_id=1, project_name="ws"))
        db.session.commit()


def ask_route(message, accept_language, **extra):
    seen = {}

    def fake_answer(project_id, user_message, lang="zh-TW"):
        seen["lang"] = lang
        return "ok"

    headers = dict(user_header(1))
    if accept_language is not None:
        headers["Accept-Language"] = accept_language
    with mock.patch("routes.chats.chat.answer_chat_question", side_effect=fake_answer):
        resp = client.post("/api/chat/1/ask", json={"message": message, **extra}, headers=headers)
    return resp, seen


resp, seen = ask_route("請整理這份資料的重點", "en")
check("中文提問 + 介面英文 -> 用中文回答（instruction_lang 優先）", resp.status_code == 200 and seen["lang"] == "zh-TW")
check("回應帶語言資訊：ui_lang=en、instruction_lang=zh-TW",
      resp.get_json()["language"] == {"ui_lang": "en", "instruction_lang": "zh-TW", "data_lang": None})
resp, seen = ask_route("What are the main complaints?", "zh-TW")
check("英文提問 + 介面中文 -> 用英文回答", seen["lang"] == "en" and resp.get_json()["language"]["ui_lang"] == "zh-TW")
resp, seen = ask_route("123", "en")
check("提問判斷不出語言 -> 用 ui_lang（en）", seen["lang"] == "en")
resp, seen = ask_route("ok", "zh-TW")
check("提問判斷不出語言 -> 用 ui_lang（zh-TW）", seen["lang"] == "zh-TW")
resp, seen = ask_route("分析 Q1 survey", "en")
check("中英混合 -> 不猜，用 ui_lang", seen["lang"] == "en")
resp, seen = ask_route("日本語の分析をお願いします", "en")
check("其他語言（日文）-> fallback ui_lang", seen["lang"] == "en")
resp, seen = ask_route("[檔案：data.txt] Please summarize the results", "zh-TW")
check("對照：訊息帶系統加的「[檔案：…]」中文前綴、又沒有純指令 -> 被干擾而判斷不出來，只能用 ui_lang",
      seen["lang"] == "zh-TW")
resp, seen = ask_route("[檔案：data.txt] Please summarize the results", "zh-TW", instruction="Please summarize the results")
check("前端另外送純指令文字 instruction -> 以它判斷（英文），不被「[檔案：…]」前綴干擾", seen["lang"] == "en")
resp, seen = ask_route("[檔案：資料.txt] 請整理重點", "en", instruction="請整理重點")
check("純指令是中文 + 介面英文 -> 中文", seen["lang"] == "zh-TW")
resp, seen = ask_route("[檔案：資料.txt] ", "en", instruction="")
check("只有附檔、沒有文字指令（instruction 為空）-> fallback ui_lang", seen["lang"] == "en")
resp, seen = ask_route("Please summarize", "zh-TW", instruction=123)
check("instruction 不是字串 -> 忽略，退回用 message 判斷", seen["lang"] == "en")
resp, seen = ask_route("請整理重點", None)
check("沒有 Accept-Language -> 以指令語言為準（原本行為）", seen["lang"] == "zh-TW")
resp, seen = ask_route("123", None)
check("沒有 Accept-Language 又判斷不出指令 -> 預設繁體中文", seen["lang"] == "zh-TW")

print("\n========== 3. 摘要：語言 = data_lang ==========")
from services import aggregated_summary_service as summ
import services.gemini_client as gemini_client
seen_instructions = []


class _SummaryModel:
    def __init__(self, model_name=None, system_instruction=None, **kwargs):
        seen_instructions.append(system_instruction)

    def generate_content(self, content, generation_config=None):
        class R:
            text = json.dumps({"summary": "S", "reasoning_summary": "R", "summary_summary": "S2"})
        return R()


items = [{"matched_segment_text": "主管很好"}]
with mock.patch.object(gemini_client, "GenerativeModel", _SummaryModel):
    seen_instructions.clear(); summ.build_aggregated_summary("A", "B", items)
    check("單一摘要：預設語言的提示詞與原本逐字相同", seen_instructions[-1] == summ.AGGREGATED_SUMMARY_SYSTEM_INSTRUCTION)
    seen_instructions.clear(); summ.build_aggregated_summary("A", "B", items, lang="en")
    check("單一摘要：lang=en -> 英文，不再有「使用繁體中文」",
          "Write the summary in English." in seen_instructions[-1] and "使用繁體中文" not in seen_instructions[-1])
    seen_instructions.clear(); summ.build_aggregated_summary_pair("A", "B", items, items)
    check("成對摘要：預設語言的提示詞與原本逐字相同", seen_instructions[-1] == summ.AGGREGATED_PAIR_SYSTEM_INSTRUCTION)
    seen_instructions.clear(); summ.build_aggregated_summary_pair("A", "B", items, items, lang="en")
    check("成對摘要：lang=en -> 英文", "Write the summary in English." in seen_instructions[-1] and "使用繁體中文" not in seen_instructions[-1])

print("\n========== 4. 彙整 / 報告：規則 A：摘要語言 = 介面語言（與資料語言無關）==========")
from routes.classifications import classification as cls_routes
with app.app_context():
    vid = seed_topic("custom_topic")


def aggregated_lang(texts, accept_language, batch):
    """用 texts 建一批分類列，呼叫共用的彙整函式，回傳它交給摘要的 lang。"""
    seen = {}

    def fake_pair(main, sub, reasoning_items, summary_items, lang="zh-TW"):
        seen["lang"] = lang
        return "r", "s"

    with app.app_context():
        ids = seed_upload_batch(batch, texts)
        for aid, t in zip(ids, texts):
            seed_classification(aid, batch, t, "Main A", "A1 Original", version_id=vid)
        rows = m.Response_Classification.query.filter_by(upload_batch_id=batch).all()
        with mock.patch.object(cls_routes, "build_aggregated_summary_pair", side_effect=fake_pair):
            if accept_language is None:
                cls_routes._build_aggregated_groups(rows, {a: i for i, a in enumerate(ids)}, "custom_topic")
            else:
                with app.test_request_context("/", headers={"Accept-Language": accept_language}):
                    cls_routes._build_aggregated_groups(rows, {a: i for i, a in enumerate(ids)}, "custom_topic")
    return seen.get("lang")


EN_ROWS = ["The manager is nice but overtime is too much"] * 4
ZH_ROWS = ["主管很好，但是加班太多了"] * 4
check("英文資料 + 介面中文 -> 中文摘要（跟介面，不跟資料）", aggregated_lang(EN_ROWS, "zh-TW", "b-en") == "zh-TW")
check("中文資料 + 介面英文 -> 英文摘要（規則 A 的核心）", aggregated_lang(ZH_ROWS, "en", "b-zh") == "en")
check("英文資料 + 介面英文 -> 英文", aggregated_lang(EN_ROWS, "en", "b-en2") == "en")
check("中文資料 + 介面中文 -> 中文", aggregated_lang(ZH_ROWS, "zh-TW", "b-zh2") == "zh-TW")
check("資料判斷不出來 / 混合 / 日文：一律照介面語言（不再需要猜資料語言）",
      aggregated_lang(["ok", "123", "N/A", "ok"], "en", "b-un") == "en"
      and aggregated_lang(EN_ROWS[:2] + ZH_ROWS[:2], "en", "b-mix") == "en"
      and aggregated_lang(["ありがとうございます"] * 4, "en", "b-ja") == "en")
check("沒有 Accept-Language 的請求 -> 預設繁體中文（不看資料）", aggregated_lang(EN_ROWS, "fr-FR", "b-fr") == "zh-TW")
check("沒有請求環境（背景工作 / 舊測試）才退回資料語言：中文資料 -> 中文", aggregated_lang(ZH_ROWS, None, "b-nr") == "zh-TW")
check("沒有請求環境 + 英文資料 -> 英文（背景重試的已知退路）", aggregated_lang(EN_ROWS, None, "b-nr3") == "en")
check("沒有請求環境 + 判斷不出來 -> 預設繁體中文", aggregated_lang(["ok", "123"], None, "b-nr2") == "zh-TW")


def report_lang(texts, ui_lang, batch):
    from services import report_service
    seen = {}

    def fake_summary(main, sub, items, lang="zh-TW"):
        seen["lang"] = lang
        return "summary"

    with app.app_context():
        ids = seed_upload_batch(batch, texts)
        for aid, t in zip(ids, texts):
            seed_classification(aid, batch, t, "Main A", "A1 Original", version_id=vid, review_status="confirmed")
        with mock.patch.object(report_service, "build_aggregated_summary", side_effect=fake_summary):
            report = report_service.generate_report("user_upload", 1, upload_batch_id=batch, ui_lang=ui_lang)
        return seen.get("lang"), report.status


lang, status = report_lang(EN_ROWS, "zh-TW", "r-en")
check("報告：英文資料 + 介面中文 -> 中文摘要（規則 A）", lang == "zh-TW" and status == "completed")
lang, status = report_lang(ZH_ROWS, "en", "r-zh")
check("報告：中文資料 + 介面英文 -> 英文摘要（規則 A 的核心）", lang == "en" and status == "completed")
lang, status = report_lang(["ok", "123", "N/A", "ok"], "en", "r-un")
check("報告：資料判斷不出來 -> 照介面語言（en）", lang == "en")
lang, status = report_lang(EN_ROWS[:2] + ZH_ROWS[:2], "zh-TW", "r-mix")
check("報告：混合資料 -> 照介面語言，整份報告同一個語言", lang == "zh-TW")

print("\n========== 5. 上傳回應多帶 language；快照重新整理保留 ==========")


def classify_q(text, main, sub):
    q({"segments": [mask_pii(text)]})
    q({"classifications": [{"index": 0, "main_category": main, "sub_category": sub,
                            "secondary_sub_category": None, "reasoning": "r", "summary": "s", "confidence": 0.9}]})


def upload(column, texts, accept_language, category=("Learning", "Course needs")):
    GEMINI_QUEUE.clear()
    q({"question_type": None})
    q({"categories": [{"main_category": category[0], "sub_category": category[1], "definition": "d"}]})
    for t in texts:
        classify_q(t, *category)
    buf = io.BytesIO()
    pd.DataFrame({column: texts}).to_excel(buf, index=False)
    buf.seek(0)
    headers = dict(user_header(1))
    if accept_language:
        headers["Accept-Language"] = accept_language
    resp = client.post("/api/classification/upload", data={"file": (buf, "u.xlsx"), "text_column": column},
                       headers=headers, content_type="multipart/form-data")
    return resp.status_code, resp.get_json()


status, data = upload("Feedback", ["I want more training courses", "Please add English classes"], "zh-TW")
check("英文檔案 + 介面中文：language = ui zh-TW / data en（instruction 由前端決定，後端為 null）",
      status == 201 and data["language"] == {"ui_lang": "zh-TW", "instruction_lang": None, "data_lang": "en"})
status, data = upload("意見", ["想上 Excel 課程", "希望有英文課"], "en", category=("學習", "課程需求"))
check("中文檔案 + 介面英文：language = ui en / data zh-TW",
      status == 201 and data["language"] == {"ui_lang": "en", "instruction_lang": None, "data_lang": "zh-TW"})
status, data = upload("Note", ["ok", "123"], None, category=("Misc", "Other"))
check("判斷不出資料語言（ok / 123）、沒有 Accept-Language：data_lang = null、ui_lang 預設 zh-TW",
      status == 201 and data["language"] == {"ui_lang": "zh-TW", "instruction_lang": None, "data_lang": None})

with app.app_context():
    batch = "snap-batch"
    ids = seed_upload_batch(batch, ["主管很好，但是加班太多了"])
    seed_classification(ids[0], batch, "主管很好，但是加班太多了", "Main A", "A1 Original", version_id=vid)
    stored_language = {"ui_lang": "en", "instruction_lang": "en", "data_lang": "zh-TW"}
    chat_id = seed_workspace_chat(batch, rows=[], meta_extra={"language": stored_language}, project_id=1)
resp = client.post(f"/api/chat/{chat_id}/classification-result/refresh", headers=user_header(1))
payload = resp.get_json()
check("重新整理快照（人工審核後重建）後，meta.language 原封不動保留",
      resp.status_code == 200 and payload["meta"].get("language") == stored_language)

GEMINI_QUEUE.clear()
finish()
