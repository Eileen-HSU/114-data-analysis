#!/usr/bin/env python
"""
測試腳本：驗證 Taxonomy 核心資料層本身（Phase A）。

涵蓋：
  1. Topic / Taxonomy_Version / Taxonomy_Category 可以建立、寫入、讀出。
  2. Taxonomy_Version.status / source 的 CheckConstraint 擋下不合法值。
  3. 同一 Topic 底下 version_number 不可重複（UniqueConstraint）。
  4. 同一 Taxonomy_Version 底下 (main_category, sub_category) 不可重複。
  5. Cascade：刪除 Topic 連帶刪除 Taxonomy_Version，
     刪除 Taxonomy_Version 連帶刪除 Taxonomy_Category。
  6. Taxonomy_Version.created_by 指向 Admin，刪除 Admin 後設為 NULL
     （不砍掉既有 taxonomy 版本紀錄）。

執行方式：
    cd backend
    python3 test_taxonomy_schema.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

FAILED = []


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    if status == "FAIL":
        FAILED.append(label)
    print(f"[{status}] {label}")


from flask import Flask
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from extensions import db
import models as m


@event.listens_for(Engine, "connect")
def _enable_sqlite_fk(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


from taxonomy import (
    ALLOWED_TAXONOMY_VERSION_STATUSES,
    ALLOWED_TAXONOMY_VERSION_SOURCES,
    TAXONOMY_VERSION_STATUS_DRAFT,
    TAXONOMY_VERSION_STATUS_PUBLISHED,
    TAXONOMY_VERSION_SOURCE_MIGRATED_LEGACY,
)

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
app.config["TESTING"] = True
db.init_app(app)

with app.app_context():
    tables = [
        m.Admin.__table__,
        m.AdminVerification.__table__,
        m.Topic.__table__,
        m.Taxonomy_Version.__table__,
        m.Taxonomy_Category.__table__,
    ]
    db.metadata.create_all(bind=db.engine, tables=tables)

    admin = m.Admin(admin_name="tester", email="admin@example.com", password_hash="x")
    db.session.add(admin)
    db.session.commit()
    admin_id = admin.admin_id


# ═══════════════════════════════════════════════════════════════
# 測試 1：基本建立 / 讀出
# ═══════════════════════════════════════════════════════════════
print("========== 基本建立 / 讀出 ==========")

with app.app_context():
    topic = m.Topic(
        topic_key="leadership_and_dept",
        title="主管領導和部門合作",
        question_text="針對主管領導和部門合作...",
    )
    db.session.add(topic)
    db.session.commit()

    version = m.Taxonomy_Version(
        topic_key="leadership_and_dept",
        version_number=1,
        status=TAXONOMY_VERSION_STATUS_PUBLISHED,
        source=TAXONOMY_VERSION_SOURCE_MIGRATED_LEGACY,
    )
    db.session.add(version)
    db.session.commit()
    version_id = version.version_id

    category = m.Taxonomy_Category(
        version_id=version_id,
        main_category="主管領導",
        sub_category="A1 工作與生活邊界",
        methodology="非工作時間之工作邊界分析",
        citation="Park et al. (2020)",
        source_raw_text="當回覆主要涉及下班後...",
        sort_order=1,
    )
    db.session.add(category)
    db.session.commit()

    check("Topic 建立成功", m.Topic.query.get("leadership_and_dept") is not None)
    check(
        "Taxonomy_Version 建立成功且狀態正確",
        m.Taxonomy_Version.query.get(version_id).status == "published",
    )
    check(
        "Taxonomy_Category 建立成功且可讀回 methodology/citation",
        m.Taxonomy_Category.query.get(category.category_id).methodology
        == "非工作時間之工作邊界分析",
    )
    check(
        "Taxonomy_Version.topic backref 正確關聯",
        m.Taxonomy_Version.query.get(version_id).topic.title == "主管領導和部門合作",
    )
    check(
        "Taxonomy_Category.taxonomy_version backref 正確關聯",
        m.Taxonomy_Category.query.get(category.category_id).taxonomy_version.version_number
        == 1,
    )
    check(
        "to_dict(include_categories=True) 帶出 categories",
        len(m.Taxonomy_Version.query.get(version_id).to_dict(include_categories=True)["categories"]) == 1,
    )


# ═══════════════════════════════════════════════════════════════
# 測試 2：status / source CheckConstraint
# ═══════════════════════════════════════════════════════════════
print("\n========== status / source CheckConstraint ==========")

with app.app_context():
    check(
        "ALLOWED_TAXONOMY_VERSION_STATUSES 剛好是 4 個合法值",
        ALLOWED_TAXONOMY_VERSION_STATUSES
        == {"draft", "in_review", "published", "archived"},
    )
    check(
        "candidate 不在合法狀態值裡（避免跟 Prompt_Template candidate 撞名）",
        "candidate" not in ALLOWED_TAXONOMY_VERSION_STATUSES,
    )

    try:
        bad_version = m.Taxonomy_Version(
            topic_key="leadership_and_dept",
            version_number=99,
            status="candidate",  # 不合法值
            source=TAXONOMY_VERSION_SOURCE_MIGRATED_LEGACY,
        )
        db.session.add(bad_version)
        db.session.commit()
        check("不合法 status 被 CheckConstraint 擋下", False)
    except Exception:
        db.session.rollback()
        check("不合法 status 被 CheckConstraint 擋下", True)

    try:
        bad_version2 = m.Taxonomy_Version(
            topic_key="leadership_and_dept",
            version_number=98,
            status=TAXONOMY_VERSION_STATUS_DRAFT,
            source="hand_typed",  # 不合法值
        )
        db.session.add(bad_version2)
        db.session.commit()
        check("不合法 source 被 CheckConstraint 擋下", False)
    except Exception:
        db.session.rollback()
        check("不合法 source 被 CheckConstraint 擋下", True)


# ═══════════════════════════════════════════════════════════════
# 測試 3：UniqueConstraint
# ═══════════════════════════════════════════════════════════════
print("\n========== UniqueConstraint ==========")

with app.app_context():
    try:
        dup_version = m.Taxonomy_Version(
            topic_key="leadership_and_dept",
            version_number=1,  # 跟上面測試 1 建立的版本重複
            status=TAXONOMY_VERSION_STATUS_DRAFT,
            source=TAXONOMY_VERSION_SOURCE_MIGRATED_LEGACY,
        )
        db.session.add(dup_version)
        db.session.commit()
        check("同一 Topic 下重複 version_number 被擋下", False)
    except IntegrityError:
        db.session.rollback()
        check("同一 Topic 下重複 version_number 被擋下", True)

    version_id = m.Taxonomy_Version.query.filter_by(
        topic_key="leadership_and_dept", version_number=1
    ).first().version_id

    try:
        dup_category = m.Taxonomy_Category(
            version_id=version_id,
            main_category="主管領導",
            sub_category="A1 工作與生活邊界",  # 跟測試 1 建立的重複
            sort_order=2,
        )
        db.session.add(dup_category)
        db.session.commit()
        check("同一版本下重複 (main_category, sub_category) 被擋下", False)
    except IntegrityError:
        db.session.rollback()
        check("同一版本下重複 (main_category, sub_category) 被擋下", True)


# ═══════════════════════════════════════════════════════════════
# 測試 4：Cascade 刪除
# ═══════════════════════════════════════════════════════════════
print("\n========== Cascade 刪除 ==========")

with app.app_context():
    topic2 = m.Topic(topic_key="temp_topic", title="暫時主題")
    db.session.add(topic2)
    db.session.commit()

    v = m.Taxonomy_Version(
        topic_key="temp_topic",
        version_number=1,
        status=TAXONOMY_VERSION_STATUS_DRAFT,
        source=TAXONOMY_VERSION_SOURCE_MIGRATED_LEGACY,
        created_by=admin_id,
    )
    db.session.add(v)
    db.session.commit()
    v_id = v.version_id

    c = m.Taxonomy_Category(version_id=v_id, main_category="M", sub_category="S1")
    db.session.add(c)
    db.session.commit()
    c_id = c.category_id

    db.session.delete(m.Topic.query.get("temp_topic"))
    db.session.commit()

    check(
        "刪除 Topic 後，Taxonomy_Version 被 CASCADE 刪除",
        m.Taxonomy_Version.query.get(v_id) is None,
    )
    check(
        "刪除 Topic 後，Taxonomy_Category 也被連帶刪除",
        m.Taxonomy_Category.query.get(c_id) is None,
    )


# ═══════════════════════════════════════════════════════════════
# 測試 5：Taxonomy_Version.created_by 刪除 Admin 後 SET NULL
# ═══════════════════════════════════════════════════════════════
print("\n========== created_by SET NULL ==========")

with app.app_context():
    topic3 = m.Topic(topic_key="temp_topic2", title="暫時主題2")
    db.session.add(topic3)
    db.session.commit()

    admin2 = m.Admin(admin_name="tester2", email="admin2@example.com", password_hash="x")
    db.session.add(admin2)
    db.session.commit()
    admin2_id = admin2.admin_id

    v2 = m.Taxonomy_Version(
        topic_key="temp_topic2",
        version_number=1,
        status=TAXONOMY_VERSION_STATUS_DRAFT,
        source=TAXONOMY_VERSION_SOURCE_MIGRATED_LEGACY,
        created_by=admin2_id,
    )
    db.session.add(v2)
    db.session.commit()
    v2_id = v2.version_id

    db.session.delete(m.Admin.query.get(admin2_id))
    db.session.commit()

    check(
        "刪除 Admin 後，Taxonomy_Version 仍存在（未被連帶刪除）",
        m.Taxonomy_Version.query.get(v2_id) is not None,
    )
    check(
        "刪除 Admin 後，Taxonomy_Version.created_by 設為 NULL",
        m.Taxonomy_Version.query.get(v2_id).created_by is None,
    )


print("\n" + "=" * 50)
if FAILED:
    print(f"共 {len(FAILED)} 項測試失敗：")
    for f in FAILED:
        print("  -", f)
    sys.exit(1)
else:
    print("全部測試通過！")
