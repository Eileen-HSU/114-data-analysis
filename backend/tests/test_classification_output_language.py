#!/usr/bin/env python
"""
規則 A：AI 產生的「逐筆理由 / 摘要」的語言 = 介面語言（英文介面 -> 英文，與資料語言無關）。

分類提示詞 = prompt_content + 已審核範例 + 輸出格式覆蓋（既有）+ 輸出語言要求（新增，附加在最後）。
繁體中文時語言要求是空字串，所以提示詞與改動前逐字相同；英文時附加一段明確要求：
reasoning / summary 用英文，類別名稱（main_category / sub_category）一字不改。

涵蓋：
    1. 提示詞組裝：zh-TW 與改動前逐字相同；en 附加語言要求、且附在「最後面」（在輸出格式覆蓋之後）
       - 語言要求保護類別名稱（不翻譯）；其餘提示詞（分類定義、輸出格式）完全不變
    2. 語言來源：明確 lang > 請求的 Accept-Language > 沒有請求環境時退回文字語言 > 繁體中文
       - 中文資料 + 英文介面 -> 英文（規則 A 的核心）；英文資料 + 中文介面 -> 中文
    3. 單筆路徑（_call_gemini_and_parse）也一樣
    4. 端到端：英文介面上傳中文檔案 -> 送給 Gemini 的提示詞要求英文，但類別名稱仍是分類架構的原名，
       分類成功寫入
    5. Admin 代為重新處理：用資料本身的語言，不吃管理員的介面語言
    6. 沒有影響其他東西：問答（instruction_lang）與固定句不受影響

執行方式：
    cd backend
    python3 tests/test_classification_output_language.py
"""

import io
import json
import os
from unittest import mock

import pandas as pd

from admin_test_support import (
    GEMINI_QUEUE, check, create_app, finish, q, seed_people, seed_topic, user_header,
)
import models as m
from extensions import db
import services.classify_v2 as cv2
import services.gemini_client as gemini_client
from services import language_service as ls
from services.privacy_service import mask_pii

os.environ.pop("OPEN_CLASSIFICATION_ENABLED", None)
app = create_app()
client = app.test_client()

PROMPT = "你是分類助手。\n輸出：{\"main_category\": \"...\", \"sub_category\": \"...\"}"
EXAMPLES = "\n【已審核範例】\n範例一"
LOOKUP = lambda sub: {"main_category": "學習", "methodology": "m", "citation": "c"}


class _Capture:
    """假的 GenerativeModel：記下每次收到的 system_instruction，回傳合法的批次分類結果。"""
    instructions = []

    def __init__(self, model_name=None, system_instruction=None, **kwargs):
        _Capture.instructions.append(system_instruction)

    def generate_content(self, content, generation_config=None, **kwargs):
        n = content.count("\n[") + (1 if "[0]" in content else 0)
        payload = {"classifications": [
            {"index": i, "main_category": "學習", "sub_category": "課程需求", "secondary_categories": [],
             "reasoning": "r", "summary": "s", "confidence": 0.9} for i in range(max(n, 1))]}

        class R:
            text = json.dumps(payload)
        return R()


def batch_prompt(lang=None, texts=("想上 Excel 課",), request_lang=None):
    _Capture.instructions.clear()
    with mock.patch.object(gemini_client, "GenerativeModel", _Capture):
        if request_lang is not None:
            with app.test_request_context("/", headers={"Accept-Language": request_lang}):
                cv2._call_gemini_batch_classification(list(texts), PROMPT, LOOKUP, EXAMPLES, lang=lang)
        else:
            cv2._call_gemini_batch_classification(list(texts), PROMPT, LOOKUP, EXAMPLES, lang=lang)
    return _Capture.instructions[-1]


BASE = PROMPT + EXAMPLES + cv2.BATCH_OUTPUT_FORMAT_OVERRIDE.format(n=1, n_minus_1=0)

print("========== 1. 提示詞組裝 ==========")
zh = batch_prompt(lang="zh-TW")
check("zh-TW：提示詞與改動前逐字相同（prompt + 範例 + 輸出格式覆蓋，沒有任何附加）", zh == BASE)
en = batch_prompt(lang="en")
check("en：前面的內容完全不變（只在最後面附加）", en.startswith(BASE) and len(en) > len(BASE))
tail = en[len(BASE):]
check("en：附加的是輸出語言要求，要求 reasoning / summary 用英文", "OUTPUT LANGUAGE" in tail and 'Write the values of "reasoning" and "summary" in English' in tail)
check("en：明確要求類別名稱一字不改（不翻譯、不縮寫、不重排）",
      "main_category and sub_category EXACTLY" in tail and "do not translate" in tail)
check("en：語言要求在輸出格式覆蓋「之後」（最後一段，優先度最高）", en.rindex("OUTPUT LANGUAGE") > en.rindex("本次輸出格式覆蓋"))
check("en：沒有誤改分類定義 / 輸出格式（BASE 原樣保留）", en[:len(BASE)] == BASE)
check("不合法的語言代碼 -> 視為繁體中文（提示詞不變）", batch_prompt(lang="fr") == BASE)

print("\n========== 2. 語言來源 ==========")
check("明確 lang=en 優先", ls.resolve_output_lang("en", ["主管很好"]) == "en")
check("明確 lang=zh-TW 優先（即使文字是英文）", ls.resolve_output_lang("zh-TW", ["The manager is nice"]) == "zh-TW")
with app.test_request_context("/", headers={"Accept-Language": "en-US,en;q=0.9"}):
    check("請求內：英文介面 + 中文資料 -> en（規則 A 的核心：不看資料）", ls.resolve_output_lang(None, ["主管很好，但是加班太多了"] * 5) == "en")
with app.test_request_context("/", headers={"Accept-Language": "zh-TW"}):
    check("請求內：中文介面 + 英文資料 -> zh-TW", ls.resolve_output_lang(None, ["The manager is nice but overtime is too much"] * 5) == "zh-TW")
with app.test_request_context("/"):
    check("請求內沒有 Accept-Language -> 預設繁體中文（仍不看資料）", ls.resolve_output_lang(None, ["The manager is nice"] * 5) == "zh-TW")
check("沒有請求環境（背景重試）+ 英文資料 -> en（退路：資料語言）", ls.resolve_output_lang(None, ["The manager is nice but overtime is too much"] * 5) == "en")
check("沒有請求環境 + 中文資料 -> zh-TW", ls.resolve_output_lang(None, ["主管很好，但是加班太多了"] * 5) == "zh-TW")
check("沒有請求環境 + 判斷不出來 / 沒資料 -> zh-TW", ls.resolve_output_lang(None, ["ok", "123"]) == "zh-TW" and ls.resolve_output_lang(None, None) == "zh-TW")

print("\n========== 3. 經過真正的分類函式 ==========")
check("中文資料 + 英文介面：送給 Gemini 的提示詞要求英文", "Write the values of" in batch_prompt(texts=("想上 Excel 課",) * 3, request_lang="en"))
check("英文資料 + 中文介面：提示詞維持原樣（沒有英文要求）", batch_prompt(texts=("I want more training",) * 3, request_lang="zh-TW") == BASE.replace("n=1", "n=3") or "OUTPUT LANGUAGE" not in batch_prompt(texts=("I want more training",) * 3, request_lang="zh-TW"))
check("沒有請求環境 + 英文資料：退回資料語言 -> 英文要求", "Write the values of" in batch_prompt(texts=("The manager is nice but overtime is too much",) * 3))
check("沒有請求環境 + 中文資料：提示詞不變", "OUTPUT LANGUAGE" not in batch_prompt(texts=("主管很好，但是加班太多了",) * 3))

_Capture.instructions.clear()
with mock.patch.object(gemini_client, "GenerativeModel", _Capture):
    class _Single(_Capture):
        def generate_content(self, content, generation_config=None, **kwargs):
            class R:
                text = json.dumps({"main_category": "學習", "sub_category": "課程需求", "reasoning": "r", "summary": "s", "confidence": "high"})
            return R()
    with mock.patch.object(gemini_client, "GenerativeModel", _Single):
        cv2._call_gemini_and_parse("想上課", PROMPT, LOOKUP, lang="en")
        single_en = _Capture.instructions[-1]
        cv2._call_gemini_and_parse("想上課", PROMPT, LOOKUP, lang="zh-TW")
        single_zh = _Capture.instructions[-1]
check("單筆路徑：en 附加語言要求、zh-TW 與原本逐字相同", single_en.startswith(PROMPT) and "OUTPUT LANGUAGE" in single_en and single_zh == PROMPT)

print("\n========== 4. 端到端：英文介面上傳中文檔案 ==========")
with app.app_context():
    seed_people()
    seed_topic("custom_topic", categories=[("學習", "課程需求", "m", "c")])


def upload(accept_language, texts, column="意見"):
    GEMINI_QUEUE.clear()
    q({"question_type": "custom_topic"})
    for t in texts:
        q({"segments": [mask_pii(t)]})
        q({"classifications": [{"index": 0, "main_category": "學習", "sub_category": "課程需求",
                                "secondary_sub_category": None, "reasoning": "r", "summary": "s", "confidence": 0.9}]})
    seen = []
    real = cv2._call_gemini_batch_classification

    def spy(*args, **kwargs):
        seen.append(kwargs.get("lang"))
        return real(*args, **kwargs)

    buf = io.BytesIO()
    pd.DataFrame({column: texts}).to_excel(buf, index=False)
    buf.seek(0)
    headers = dict(user_header(1))
    if accept_language:
        headers["Accept-Language"] = accept_language
    with mock.patch.object(cv2, "_call_gemini_batch_classification", side_effect=spy):
        resp = client.post("/api/classification/upload", data={"file": (buf, "u.xlsx"), "text_column": column},
                           headers=headers, content_type="multipart/form-data")
    return resp, seen


resp, seen = upload("en", ["想上 Excel 課", "希望有英文課"])
body = resp.get_json()
check("英文介面 + 中文資料：上傳成功", resp.status_code == 201 and body["classified_count"] == 2)
check("分類時沒有被明確指定語言（交給請求的 Accept-Language 決定）", seen and all(v is None for v in seen))
check("類別名稱原樣（沒被翻譯）寫進結果", [g["main_category"] for g in body["aggregated_groups"]] == ["學習"])
check("language 資訊：ui_lang=en、data_lang=zh-TW（data_lang 只是資訊）",
      body["language"]["ui_lang"] == "en" and body["language"]["data_lang"] == "zh-TW")

print("\n========== 5. Admin 代為重新處理：用資料語言，不吃管理員的介面語言 ==========")
from admin_test_support import admin_header, seed_classification, seed_upload_batch
import services.classify_v2 as classify_v2_module

with app.app_context():
    vid = m.Taxonomy_Version.query.filter_by(topic_key="custom_topic").first().version_id


def reclassify_as_admin(text, admin_language):
    """用管理員身分（介面語言 = admin_language）重新分類一則回答；回傳分類函式實際收到的 lang。"""
    with app.app_context():
        aid = seed_upload_batch(f"adm-{abs(hash((text, admin_language))) % 10**6}", [text], question_type="custom_topic")[0]
        cid = seed_classification(aid, f"adm-{abs(hash((text, admin_language))) % 10**6}", text, "學習", "課程需求", version_id=vid)
    received = {}
    real = classify_v2_module.classify_response_multi_segment

    def spy(answer_text, prompt_content, topic_key, **kwargs):
        received["lang"] = kwargs.get("lang", "（沒有傳）")
        return real(answer_text, prompt_content, topic_key, **kwargs)

    GEMINI_QUEUE.clear()
    q({"segments": [mask_pii(text)]})
    q({"classifications": [{"index": 0, "main_category": "學習", "sub_category": "課程需求",
                            "secondary_sub_category": None, "reasoning": "r", "summary": "s", "confidence": 0.9}]})
    headers = dict(admin_header(1))
    headers["Accept-Language"] = admin_language
    with mock.patch.object(classify_v2_module, "classify_response_multi_segment", side_effect=spy):
        resp = client.post(f"/api/admin/ai/classifications/{cid}/reclassify", headers=headers, json={"topic_key": "custom_topic"})
    GEMINI_QUEUE.clear()
    return resp.status_code, received.get("lang")


status, lang = reclassify_as_admin("The manager is nice but overtime is too much", "zh-TW")
check("管理員介面中文 + 英文資料：重新分類的語言 = en（資料語言），不是管理員的 zh-TW", status == 200 and lang == "en")
status, lang = reclassify_as_admin("主管很好，但是加班太多了", "en")
check("管理員介面英文 + 中文資料：語言 = zh-TW（資料語言），不是管理員的 en", status == 200 and lang == "zh-TW")
status, lang = reclassify_as_admin("ok", "en")
check("資料判斷不出來（短句）：預設繁體中文，不吃管理員的 en", status == 200 and lang == "zh-TW")

print("\n========== 5b. 最壞情況：模型把類別名稱翻成英文（行為被記錄、被測試保護）==========")
# 提示詞要求「類別名稱一字不改」，但自動測試沒辦法證明真的模型會照做（見 tests/test_gemini_output_language.py，
# 需要真的 Gemini 金鑰手動跑）。這裡鎖定「萬一模型沒照做」時系統的實際行為：
#   - 不會崩潰、不會悄悄接受：sub_category 對不上分類架構
#   - 封閉模式：標為 methodology_not_found（帶錯誤原因）
#   - 開放模式：標為 new_category（進新類別候選，交給管理員決定）——這是最容易被忽略的後果
lookup_zh = lambda sub: {"main_category": "學習", "methodology": "m", "citation": "c"} if sub == "課程需求" else None
parsed_translated = {"main_category": "Learning", "sub_category": "Course needs", "reasoning": "r", "summary": "s", "confidence": 0.9}
from services.open_classification import NEW_CATEGORY_STATUS
os.environ["OPEN_CLASSIFICATION_ENABLED"] = "0"
closed = cv2._build_classification_result(dict(parsed_translated), lookup_zh)
check("封閉模式：翻譯過的類別名稱 -> methodology_not_found，並帶出原因（不會悄悄當成正常結果）",
      closed["status"] == "methodology_not_found" and "Course needs" in (closed["error_detail"] or ""))
os.environ.pop("OPEN_CLASSIFICATION_ENABLED", None)
opened = cv2._build_classification_result(dict(parsed_translated), lookup_zh)
check("開放模式：翻譯過的類別名稱 -> 被當成「新類別」候選（所以模型沒保留類別名稱時，新類別候選會被汙染）",
      opened["status"] == NEW_CATEGORY_STATUS and opened["sub_category"] == "Course needs")
parsed_ok = {"main_category": "學習", "sub_category": "課程需求", "reasoning": "Wants more courses.", "summary": "More courses.", "confidence": 0.9}
good = cv2._build_classification_result(dict(parsed_ok), lookup_zh)
check("模型照做（類別原名 + 英文理由）：正常完成，理由保留英文", good["status"] == "completed" and good["reasoning"] == "Wants more courses.")

print("\n========== 6. 不影響其他語言規則 ==========")
check("問答仍是 instruction_lang（提問語言），不受規則 A 影響",
      ls.resolve_instruction_lang("Please summarize", "zh-TW") == "en" and ls.resolve_instruction_lang("請摘要", "en") == "zh-TW")

GEMINI_QUEUE.clear()
finish()
