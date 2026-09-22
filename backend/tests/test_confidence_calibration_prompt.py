#!/usr/bin/env python
"""
測試腳本：Gemini classification 的 confidence calibration 修正。

只針對「prompt 本身寫了什麼」做驗證，不改、也不測試 Human Review、
feedback loop、DB 寫入、aggregation/report/export、CONFIDENCE_THRESHOLD
本身的值（那些不在本次修正範圍內）。

涵蓋：
    1. services/taxonomy_service.py 的 build_classification_prompt()
       （正式 production taxonomy classification 走的唯一 prompt 組裝
       入口）確實包含明確的「【分類信心評分規則】」，含四個級距
       （0.90–1.00 / 0.75–0.89 / 0.50–0.74 / 0.00–0.49）與五條補充
       規則（不可因選出類別就給高分／兩個以上候選須 <0.75／需要腦補
       須 <0.75／極短模糊須 <0.75／confidence 不是格式成功率）。
    2. 這段規則區塊在 prompt 裡的位置：接在分類規則/次要類別規則
       之後、【輸出格式】JSON schema 之前，且早於 BATCH_OUTPUT_FORMAT_OVERRIDE
       附加的內容。
    3. services/classify_v2.py 的 BATCH_OUTPUT_FORMAT_OVERRIDE 裡的
       confidence schema 已經從模糊的 "..." 字串佔位符，改成明確要求
       0.0～1.0 的 numeric 浮點數，且明講「不是字串、不可省略小數點」，
       並重申仍要套用信心評分規則，不因為改成陣列格式就可以隨口給分。
    4. 組出完整 system_instruction（prompt_content + reviewed_examples_block
       + BATCH_OUTPUT_FORMAT_OVERRIDE，這裡 reviewed_examples_block 為
       空字串）之後，同時包含 rubric 本身跟 batch override 的 numeric
       schema 說明，且完全找不到舊版模糊寫法 '"confidence": "..."'。
    5. services/confidence_gate.py 的 CONFIDENCE_THRESHOLD 仍是 0.75，
       這次修正沒有動到它。

不依賴真實 google.genai 網路呼叫：跟
tests/test_review_feedback_service.py 一樣，用假的
services.gemini_client.GenerativeModel 攔截「送進去的
system_instruction」，不會真的打 API，也不使用會跟目前 gemini_client.py
（新版 google-genai SDK）衝突的 sys.modules["google"] 偽造寫法。

執行方式：
    cd backend
    export JWT_SECRET_KEY=test-secret-key-for-testing-only
    python3 tests/test_confidence_calibration_prompt.py
"""

import sys
import os
import json

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

FAILED = []


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    if status == "FAIL":
        FAILED.append(label)
    print(f"[{status}] {label}")


# ═══════════════════════════════════════════════════════════════
# 共用：Flask app + SQLite in-memory，建立一份 published Taxonomy_Version
# 供 build_classification_prompt() 使用（跟 test_taxonomy_classification.py
# 相同的最小建置方式）。
# ═══════════════════════════════════════════════════════════════

from flask import Flask
from extensions import db
import models as m
from services import taxonomy_service as ts

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
app.config["TESTING"] = True
db.init_app(app)

with app.app_context():
    tables = [
        m.Topic.__table__,
        m.Taxonomy_Version.__table__,
        m.Taxonomy_Category.__table__,
    ]
    db.metadata.create_all(bind=db.engine, tables=tables)

    db.session.add(m.Topic(topic_key="topic_confidence_rubric", title="信心校準測試題"))
    version = m.Taxonomy_Version(
        topic_key="topic_confidence_rubric", version_number=1,
        status="published", source="manual",
    )
    db.session.add(version)
    db.session.flush()
    db.session.add(m.Taxonomy_Category(
        version_id=version.version_id, sort_order=1,
        main_category="M", sub_category="S1", definition="測試用子類別定義",
    ))
    db.session.commit()
    version_id = version.version_id


with app.app_context():
    published_version = ts.get_published_taxonomy_version("topic_confidence_rubric")
    PROMPT_CONTENT = ts.build_classification_prompt(published_version)


print("========== 1. production taxonomy prompt 包含明確 confidence rubric ==========")

check("prompt 包含 rubric 標頭「【分類信心評分規則】」", "【分類信心評分規則】" in PROMPT_CONTENT)
check(
    "rubric 明講 confidence 必須反映『能否明確歸入此分類』、不可習慣性給高分",
    "不可習慣性給高分" in PROMPT_CONTENT,
)

for band_label in ["0.90", "1.00", "0.75", "0.89", "0.50", "0.74", "0.00", "0.49"]:
    check(f"rubric 包含級距數字 {band_label}", band_label in PROMPT_CONTENT)

check("rubric 包含最高級距的描述（語意明確、與其他類別幾乎沒有合理競爭）", "幾乎沒有合理競爭" in PROMPT_CONTENT)
check("rubric 明確要求 0.50–0.74 這個級距必須進 Human Review", "這類必須進 Human Review" in PROMPT_CONTENT)
check(
    "rubric 明確列出『兩個以上合理候選類別、落在類別邊界、文字過短、語意不足、需要推論』",
    all(s in PROMPT_CONTENT for s in ["兩個以上合理候選類別", "落在類別邊界", "文字過短", "語意不足", "需要推論"]),
)
check(
    "rubric 明確列出最低級距『資訊明顯不足、與 Taxonomy 對不上、語意矛盾、無法可靠判斷』",
    all(s in PROMPT_CONTENT for s in ["資訊明顯不足", "與 Taxonomy 對不上", "語意矛盾", "無法可靠判斷"]),
)

check(
    "補充規則 1：不可因為『成功選出一個類別』就給 >=0.75",
    "不可因為「成功選出一個類別」就給 >= 0.75" in PROMPT_CONTENT
    or "不可因為「成功選出一個類別」就給 >=0.75" in PROMPT_CONTENT,
)
check("補充規則 2：兩個類別都合理時 confidence 必須 <0.75", "confidence 必須 < 0.75" in PROMPT_CONTENT)
check("補充規則 3：需要自行補足原文未說出的資訊時 confidence 必須 <0.75", "推測、腦補" in PROMPT_CONTENT or "自行補足原文未明確說出的資訊" in PROMPT_CONTENT)
check("補充規則 4：極短／模糊回答沒有明確類別證據時 confidence 必須 <0.75", "極短" in PROMPT_CONTENT and "模糊" in PROMPT_CONTENT)
check(
    "補充規則 5：confidence 是分類確定程度、不是 JSON 格式成功率",
    "分類判斷的確定程度" in PROMPT_CONTENT and "JSON 格式是否成功產生" in PROMPT_CONTENT,
)


print("\n========== 2. rubric 在 prompt 裡的相對位置正確 ==========")

idx_category_rules = PROMPT_CONTENT.find("【各子類別判斷指令與判斷規則】")
idx_secondary_rule = PROMPT_CONTENT.find("次要類別規則")
idx_rubric = PROMPT_CONTENT.find("【分類信心評分規則】")
idx_output_format = PROMPT_CONTENT.find("【輸出格式】")

check("prompt 裡確實找得到子類別判斷規則段落", idx_category_rules != -1)
check("prompt 裡確實找得到次要類別規則段落", idx_secondary_rule != -1)
check("prompt 裡確實找得到 rubric 段落", idx_rubric != -1)
check("prompt 裡確實找得到輸出格式段落", idx_output_format != -1)

check("rubric 排在子類別判斷規則之後", idx_rubric > idx_category_rules)
check("rubric 排在次要類別規則之後", idx_rubric > idx_secondary_rule)
check("rubric 排在【輸出格式】JSON schema 之前", idx_rubric < idx_output_format)


print("\n========== 3. BATCH_OUTPUT_FORMAT_OVERRIDE 的 confidence schema 已改成明確 numeric ==========")

import services.classify_v2 as cv2

RAW_OVERRIDE_TEMPLATE = cv2.BATCH_OUTPUT_FORMAT_OVERRIDE
FORMATTED_OVERRIDE = RAW_OVERRIDE_TEMPLATE.format(n=3, n_minus_1=2)

check(
    "batch override 不再是模糊字串佔位符 \"confidence\": \"...\"",
    '"confidence": "..."' not in FORMATTED_OVERRIDE,
)
check(
    "batch override 明確要求 confidence 是 0.0 到 1.0 之間的浮點數",
    "confidence" in FORMATTED_OVERRIDE and "0.0 到 1.0 之間的浮點數" in FORMATTED_OVERRIDE,
)
check(
    "batch override 明講 confidence 不是字串、不是 high/low",
    "不是字串" in FORMATTED_OVERRIDE and ('"high"/"low"' in FORMATTED_OVERRIDE or "high" in FORMATTED_OVERRIDE),
)
check(
    "batch override 重申每個片段仍要套用信心評分規則、不能因為換成陣列格式就隨口給高分",
    "分類信心評分規則" in FORMATTED_OVERRIDE and "隨口給高分" in FORMATTED_OVERRIDE,
)
check(
    "batch override 仍保留固定的 index 完整性規則（沒有被這次修改破壞）",
    "index 必須恰好包含 0 到 {n_minus_1}".format(n_minus_1=2) in FORMATTED_OVERRIDE,
)


print("\n========== 4. CONFIDENCE_THRESHOLD 這次沒有被動到 ==========")

from services.confidence_gate import CONFIDENCE_THRESHOLD

check("CONFIDENCE_THRESHOLD 仍是 0.75（本次修正不動 threshold）", CONFIDENCE_THRESHOLD == 0.75)


print("\n========== 5. 端到端：完整 system_instruction 同時具備 rubric + numeric batch schema ==========")

# 假的 GenerativeModel：只攔截送進去的 system_instruction，不打真實 API。
_call_log = []
_queued_responses = []


class _FakeResp:
    def __init__(self, text):
        self.text = text


class _FakeGenerativeModel:
    def __init__(self, model_name=None, system_instruction=None, **kwargs):
        self.model_name = model_name
        self.system_instruction = system_instruction

    def generate_content(self, contents, **kwargs):
        _call_log.append({"system_instruction": self.system_instruction, "contents": contents})
        return _FakeResp(_queued_responses.pop(0))


def queue_json(obj):
    _queued_responses.append(json.dumps(obj, ensure_ascii=False))


import services.gemini_client as gemini_client_module
gemini_client_module.GenerativeModel = _FakeGenerativeModel

with app.app_context():
    category_lookup = ts.methodology_lookup_for_taxonomy_version(published_version)

_call_log.clear()
_queued_responses.clear()
masked_segments = ["這是一段測試用的遮罩後文字片段"]
queue_json({"classifications": [{
    "index": 0, "main_category": "M", "sub_category": "S1",
    "secondary_sub_category": None, "reasoning": "測試用判斷依據",
    "summary": "測試摘要", "confidence": 0.55,
}]})
result = cv2._call_gemini_batch_classification(masked_segments, PROMPT_CONTENT, category_lookup)

check("這次呼叫確實觸發一次 Gemini（沒有因為改 prompt 就出錯短路）", len(_call_log) == 1)
si = _call_log[0]["system_instruction"]

check("完整 system_instruction 仍包含 rubric 標頭", "【分類信心評分規則】" in si)
check("完整 system_instruction 仍包含 batch override 的 numeric confidence 要求", "0.0 到 1.0 之間的浮點數" in si)
check("完整 system_instruction 完全找不到舊版模糊 confidence 佔位符", '"confidence": "..."' not in si)
check("完整 system_instruction 完全找不到殘留的 high/low 字串型 confidence 範例", '"confidence": "high"' not in si and '"confidence": "low"' not in si)
check(
    "system_instruction 組裝順序仍是 prompt_content -> (reviewed_examples_block，這裡為空) -> BATCH_OUTPUT_FORMAT_OVERRIDE",
    si == PROMPT_CONTENT + "" + cv2.BATCH_OUTPUT_FORMAT_OVERRIDE.format(n=1, n_minus_1=0),
)
check("這次分類本身仍正常運作（只調整 prompt 文字，不影響既有分類/解析邏輯）", result[0]["status"] == "completed")
check("回傳的 confidence 原樣保留（0.55，中等信心，這次修正不影響數值本身的傳遞）", result[0]["confidence"] == 0.55)


print("\n" + "=" * 50)
if FAILED:
    print(f"共 {len(FAILED)} 項測試失敗：")
    for label in FAILED:
        print(f"  - {label}")
    sys.exit(1)
else:
    print("全部測試通過！")