#!/usr/bin/env python
"""
測試腳本：驗證 migrate_taxonomy_from_legacy.py 本身。

涵蓋：
  1. 解析出的段落數、子類別代碼集合，跟 SUBCATEGORY_METHODOLOGY 完全一致
     （leadership_and_dept 10 個、career_and_feedback 11 個）。
  2. 每個 Taxonomy_Category 的 main_category / methodology / citation
     跟 SUBCATEGORY_METHODOLOGY 裡的值逐字相同（沒有被搬移過程改動）。
  3. source_raw_text 有內容、且以正確的子類別代碼開頭。
  4. 實際跑一次 migrate()：對 sqlite in-memory DB 建立 Topic /
     Taxonomy_Version(status=published, version_number=1) /
     Taxonomy_Category，且重跑一次不會重複建立（idempotent）。
  5. definition / include_rules / exclude_rules / boundary_rules
     維持 NULL（本次 migration 刻意不猜測拆分，見腳本內註解）。

執行方式：
    cd backend
    python3 test_taxonomy_migration.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ.setdefault("GEMINI_API_KEY", "test-key-not-used")

FAILED = []


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    if status == "FAIL":
        FAILED.append(label)
    print(f"[{status}] {label}")


from extensions import db
import models as m
from services.subcategory_methodology import (
    QUESTION_LEADERSHIP,
    QUESTION_CAREER,
    SUBCATEGORY_METHODOLOGY,
)
import migrate_taxonomy_from_legacy as migration


# ═══════════════════════════════════════════════════════════════
# 測試 1：純解析邏輯（不碰 DB）
# ═══════════════════════════════════════════════════════════════
print("========== 解析 DEFAULT_PROMPT_* 規則段落 ==========")

from services.classify_v2 import DEFAULT_PROMPT_LEADERSHIP, DEFAULT_PROMPT_CAREER

leadership_categories = migration._parse_topic_categories(
    QUESTION_LEADERSHIP, DEFAULT_PROMPT_LEADERSHIP
)
career_categories = migration._parse_topic_categories(
    QUESTION_CAREER, DEFAULT_PROMPT_CAREER
)

check(
    "leadership_and_dept 解析出 10 個子類別",
    len(leadership_categories) == len(SUBCATEGORY_METHODOLOGY[QUESTION_LEADERSHIP]) == 10,
)
check(
    "career_and_feedback 解析出 11 個子類別",
    len(career_categories) == len(SUBCATEGORY_METHODOLOGY[QUESTION_CAREER]) == 11,
)
check(
    "leadership 子類別代碼集合跟 SUBCATEGORY_METHODOLOGY 完全一致",
    {c["sub_category"] for c in leadership_categories}
    == set(SUBCATEGORY_METHODOLOGY[QUESTION_LEADERSHIP].keys()),
)
check(
    "career 子類別代碼集合跟 SUBCATEGORY_METHODOLOGY 完全一致",
    {c["sub_category"] for c in career_categories}
    == set(SUBCATEGORY_METHODOLOGY[QUESTION_CAREER].keys()),
)

all_match = True
for cat in leadership_categories + career_categories:
    question_type = (
        QUESTION_LEADERSHIP if cat["sub_category"] in SUBCATEGORY_METHODOLOGY[QUESTION_LEADERSHIP] else QUESTION_CAREER
    )
    legacy = SUBCATEGORY_METHODOLOGY[question_type][cat["sub_category"]]
    if (
        cat["main_category"] != legacy["main_category"]
        or cat["methodology"] != legacy["methodology"]
        or cat["citation"] != legacy["citation"]
    ):
        all_match = False
check("每個子類別的 main_category/methodology/citation 跟原始查表逐字相同", all_match)

check(
    "source_raw_text 皆以對應子類別代碼開頭",
    all(c["source_raw_text"].startswith(c["sub_category"]) for c in leadership_categories + career_categories),
)

check(
    "解析結果不含 GLOBAL_RULES 段落文字（沒有把後面內容一起吃進來）",
    all("系統層級總分類規則" not in c["source_raw_text"] for c in leadership_categories + career_categories),
)


# ═══════════════════════════════════════════════════════════════
# 測試 2：對不上時要 fail-closed（負向測試）
# ═══════════════════════════════════════════════════════════════
print("\n========== 錯位輸入應該直接失敗，不能吞掉錯誤 ==========")

try:
    migration._parse_topic_categories(QUESTION_LEADERSHIP, DEFAULT_PROMPT_CAREER)
    check("題目與規則文字對不上時應拋出例外", False)
except RuntimeError:
    check("題目與規則文字對不上時應拋出例外", True)


# ═══════════════════════════════════════════════════════════════
# 測試 3：實際執行 migrate()，驗證 DB 結果
# ═══════════════════════════════════════════════════════════════
print("\n========== 實際執行 migrate_taxonomy_from_legacy.migrate() ==========")

with migration.app.app_context():
    db.metadata.create_all(
        bind=db.engine,
        tables=[m.Topic.__table__, m.Taxonomy_Version.__table__, m.Taxonomy_Category.__table__],
    )

migration.migrate()

with migration.app.app_context():
    leadership_topic = m.Topic.query.get(QUESTION_LEADERSHIP)
    career_topic = m.Topic.query.get(QUESTION_CAREER)

    check("leadership_and_dept Topic 已建立", leadership_topic is not None)
    check("career_and_feedback Topic 已建立", career_topic is not None)
    check(
        "leadership Topic.title 正確",
        leadership_topic is not None and leadership_topic.title == "主管領導和部門合作",
    )
    check(
        "leadership Topic.question_text 有內容",
        bool(leadership_topic and leadership_topic.question_text),
    )

    leadership_version = m.Taxonomy_Version.query.filter_by(
        topic_key=QUESTION_LEADERSHIP
    ).one_or_none()
    career_version = m.Taxonomy_Version.query.filter_by(
        topic_key=QUESTION_CAREER
    ).one_or_none()

    check(
        "leadership 版本為 version_number=1 / status=published / source=migrated_legacy",
        leadership_version is not None
        and leadership_version.version_number == 1
        and leadership_version.status == "published"
        and leadership_version.source == "migrated_legacy",
    )
    check(
        "career 版本為 version_number=1 / status=published / source=migrated_legacy",
        career_version is not None
        and career_version.version_number == 1
        and career_version.status == "published"
        and career_version.source == "migrated_legacy",
    )

    leadership_db_categories = m.Taxonomy_Category.query.filter_by(
        version_id=leadership_version.version_id
    ).all()
    career_db_categories = m.Taxonomy_Category.query.filter_by(
        version_id=career_version.version_id
    ).all()

    check("leadership 版本底下有 10 筆 Taxonomy_Category", len(leadership_db_categories) == 10)
    check("career 版本底下有 11 筆 Taxonomy_Category", len(career_db_categories) == 11)
    check(
        "definition/include_rules/exclude_rules/boundary_rules 皆為 NULL（本次刻意不猜測拆分）",
        all(
            c.definition is None
            and c.include_rules is None
            and c.exclude_rules is None
            and c.boundary_rules is None
            for c in leadership_db_categories + career_db_categories
        ),
    )
    check(
        "每筆 Taxonomy_Category 都有 source_raw_text",
        all(c.source_raw_text for c in leadership_db_categories + career_db_categories),
    )

    total_topics_before = m.Topic.query.count()
    total_versions_before = m.Taxonomy_Version.query.count()
    total_categories_before = m.Taxonomy_Category.query.count()

# 重跑一次，驗證 idempotent（不會重複建立）
migration.migrate()

with migration.app.app_context():
    check("重跑 migrate() 不會增加 Topic 筆數", m.Topic.query.count() == total_topics_before)
    check(
        "重跑 migrate() 不會增加 Taxonomy_Version 筆數",
        m.Taxonomy_Version.query.count() == total_versions_before,
    )
    check(
        "重跑 migrate() 不會增加 Taxonomy_Category 筆數",
        m.Taxonomy_Category.query.count() == total_categories_before,
    )


print("\n" + "=" * 50)
if FAILED:
    print(f"共 {len(FAILED)} 項測試失敗：")
    for f in FAILED:
        print("  -", f)
    sys.exit(1)
else:
    print("全部測試通過！")
