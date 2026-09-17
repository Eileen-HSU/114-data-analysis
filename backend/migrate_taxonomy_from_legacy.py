"""
migrate_taxonomy_from_legacy.py

一次性腳本：把既有兩份研究案例（leadership_and_dept / career_and_feedback）
目前分裂在兩處的 taxonomy 資料，搬進新的 Topic / Taxonomy_Version /
Taxonomy_Category 結構，當作每個 Topic 的第一版（version_number=1,
status=published，因為這兩份目前本來就是正式在跑的分類架構）：

    1. services/classify_v2.py 的 DEFAULT_PROMPT_LEADERSHIP /
       DEFAULT_PROMPT_CAREER —— 每個子類別的判斷規則散文（
       main_category、包含判斷、排除判斷、與相近類別的邊界，混在同一段）
    2. services/subcategory_methodology.py 的 SUBCATEGORY_METHODOLOGY ——
       每個子類別對應的 main_category / methodology / citation 結構化查表

【這次刻意不做的事】
    - 不猜測怎麼把第 1 點的散文拆成 definition / include_rules /
      exclude_rules / boundary_rules 四個獨立欄位——原文沒有這種天然
      邊界，硬拆等於自己發明規則內容（需求文件第 11 節明確禁止）。
      改成整段原文（拿掉數字編號後）存進 source_raw_text，四個結構化
      欄位維持 NULL，交給 Phase D 人工審核時參考、手動拆分。
    - 不修改 Prompt_Template / classify_v2.py / SUBCATEGORY_METHODOLOGY
      本身，也不切換 production classification flow 去讀新表——這兩份
      legacy 來源在 Phase B 完成 Published Taxonomy reader 之前，
      仍然是唯一真正在跑的分類依據。這裡只是把同樣的內容「多存一份」
      到新結構，不是「取代」。

【正確性保證】
    每個 Topic 解析出的段落數、每個段落的子類別代碼，都會逐一比對
    SUBCATEGORY_METHODOLOGY 裡登記的子類別集合，只要有一個對不上
    （多、少、代碼打錯字）就直接拋例外、整個腳本失敗，不會半途寫入
    不完整或錯位的資料。

【使用方式】
    cd backend
    python3 migrate_taxonomy_from_legacy.py

跟 seed_prompt_templates.py 同樣的風格：自己建最小 Flask app 取得
DB context，不 import 完整 app.py。
"""

import os
import re

from flask import Flask
from dotenv import load_dotenv

load_dotenv()

from extensions import db
from models import Topic, Taxonomy_Version, Taxonomy_Category
from services.classify_v2 import (
    DEFAULT_PROMPT_LEADERSHIP,
    DEFAULT_PROMPT_CAREER,
    GLOBAL_RULES,
)
from services.subcategory_methodology import (
    QUESTION_LEADERSHIP,
    QUESTION_CAREER,
    SUBCATEGORY_METHODOLOGY,
)
from taxonomy import (
    TAXONOMY_VERSION_STATUS_PUBLISHED,
    TAXONOMY_VERSION_SOURCE_MIGRATED_LEGACY,
)

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL") or os.environ.get(
    "SQLALCHEMY_DATABASE_URI"
)
db.init_app(app)


# Topic 的人類可讀標題與問卷題目原文。question_text 逐字取自
# run_classification.py 的 COLUMN_QUESTION_MAP（該腳本用來把 Excel
# 欄位對應到分類架構），這裡不 import 該檔案本身，因為它會連帶載入
# google.generativeai 等重依賴，只為了兩行字串不值得；但內容必須
# 跟該檔案保持逐字一致，未來若該檔案的題目文字有修改，這裡也要同步更新。
TOPIC_METADATA = {
    QUESTION_LEADERSHIP: {
        "title": "主管領導和部門合作",
        "question_text": (
            "針對主管領導和部門合作這兩項，如果您有機會直接向管理層提出"
            "各一項建議，您會提出什麼建議？為什麼這項建議對您和公司很重要？"
        ),
    },
    QUESTION_CAREER: {
        "title": "工作表現的回饋及職涯發展",
        "question_text": (
            "關於工作表現的回饋及職涯發展，您認為公司再強化或提供哪些協助"
            "將能更好地激勵您和您的同事？"
        ),
    },
}

_RULE_SECTION_HEADER = "【各子類別判斷指令與判斷規則】"
_PARAGRAPH_SPLIT_RE = re.compile(r"\n\n(?=\d+\.\s)")
_LEADING_NUMBER_RE = re.compile(r"^\d+\.\s*")


def _extract_rule_paragraphs(prompt_content: str) -> list:
    """從 DEFAULT_PROMPT_* 裡切出「【各子類別判斷指令與判斷規則】」
    段落，回傳去掉數字編號後的每一段完整原文（例如
    "A1 工作與生活邊界：當回覆主要涉及..."）。"""
    if _RULE_SECTION_HEADER not in prompt_content:
        raise RuntimeError(f"找不到規則段落標頭：{_RULE_SECTION_HEADER!r}")
    if GLOBAL_RULES not in prompt_content:
        raise RuntimeError("找不到 GLOBAL_RULES，無法界定規則段落結尾")

    after_header = prompt_content.split(_RULE_SECTION_HEADER, 1)[1]
    section = after_header.split(GLOBAL_RULES, 1)[0].strip()

    raw_paragraphs = _PARAGRAPH_SPLIT_RE.split(section)
    return [_LEADING_NUMBER_RE.sub("", p).strip() for p in raw_paragraphs if p.strip()]


def _parse_topic_categories(question_type: str, prompt_content: str) -> list:
    """回傳 [{sub_category, main_category, methodology, citation,
    source_raw_text, sort_order}, ...]，並嚴格驗證跟
    SUBCATEGORY_METHODOLOGY 的子類別集合完全一致。"""
    legacy_table = SUBCATEGORY_METHODOLOGY[question_type]
    paragraphs = _extract_rule_paragraphs(prompt_content)

    if len(paragraphs) != len(legacy_table):
        raise RuntimeError(
            f"[{question_type}] 解析出 {len(paragraphs)} 段規則，"
            f"但 SUBCATEGORY_METHODOLOGY 有 {len(legacy_table)} 個子類別，數量對不上，"
            "拒絕繼續 migration（避免寫入錯位資料）"
        )

    parsed_labels = set()
    categories = []
    for i, paragraph in enumerate(paragraphs, start=1):
        if "：" not in paragraph:
            raise RuntimeError(f"[{question_type}] 第 {i} 段找不到「：」分隔符：{paragraph[:40]!r}...")
        label, _rest = paragraph.split("：", 1)
        label = label.strip()

        if label not in legacy_table:
            raise RuntimeError(
                f"[{question_type}] 第 {i} 段的子類別代碼 {label!r} "
                "不在 SUBCATEGORY_METHODOLOGY 裡，拒絕繼續 migration"
            )
        if label in parsed_labels:
            raise RuntimeError(f"[{question_type}] 子類別代碼 {label!r} 重複出現")
        parsed_labels.add(label)

        methodology_info = legacy_table[label]
        categories.append(
            {
                "sub_category": label,
                "main_category": methodology_info["main_category"],
                "methodology": methodology_info["methodology"],
                "citation": methodology_info["citation"],
                "source_raw_text": paragraph,
                "sort_order": i,
            }
        )

    if parsed_labels != set(legacy_table.keys()):
        missing = set(legacy_table.keys()) - parsed_labels
        raise RuntimeError(f"[{question_type}] 解析結果缺少子類別：{missing}")

    return categories


def migrate():
    with app.app_context():
        seeds = [
            (QUESTION_LEADERSHIP, DEFAULT_PROMPT_LEADERSHIP),
            (QUESTION_CAREER, DEFAULT_PROMPT_CAREER),
        ]

        for topic_key, prompt_content in seeds:
            existing_topic = Topic.query.get(topic_key)
            if existing_topic and existing_topic.taxonomy_versions:
                print(f"topic_key='{topic_key}' 已有 taxonomy 版本，略過（如需重跑請先手動清除）")
                continue

            categories = _parse_topic_categories(topic_key, prompt_content)

            topic = existing_topic
            if topic is None:
                topic = Topic(
                    topic_key=topic_key,
                    title=TOPIC_METADATA[topic_key]["title"],
                    question_text=TOPIC_METADATA[topic_key]["question_text"],
                    description="migration 自既有 DEFAULT_PROMPT_* + SUBCATEGORY_METHODOLOGY",
                )
                db.session.add(topic)
                db.session.flush()

            version = Taxonomy_Version(
                topic_key=topic_key,
                version_number=1,
                status=TAXONOMY_VERSION_STATUS_PUBLISHED,
                source=TAXONOMY_VERSION_SOURCE_MIGRATED_LEGACY,
                methodology_note=(
                    "沿用 services/classify_v2.py 的 "
                    f"{'DEFAULT_PROMPT_LEADERSHIP' if topic_key == QUESTION_LEADERSHIP else 'DEFAULT_PROMPT_CAREER'} "
                    "（判斷規則原文）+ services/subcategory_methodology.py 的 "
                    "SUBCATEGORY_METHODOLOGY（main_category / methodology / citation）。"
                ),
            )
            db.session.add(version)
            db.session.flush()

            for cat in categories:
                db.session.add(Taxonomy_Category(version_id=version.version_id, **cat))

            db.session.commit()
            print(f"topic_key='{topic_key}'：已建立 version_number=1（published），"
                  f"{len(categories)} 個子類別")

        print("完成")


if __name__ == "__main__":
    migrate()
