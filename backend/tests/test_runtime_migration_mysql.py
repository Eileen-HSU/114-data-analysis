#!/usr/bin/env python
"""
app.py 啟動路徑（runtime migration + taxonomy bootstrap）在 MySQL 上的整合測試。

app.py 的 ensure_column / ensure_table 依賴 MySQL information_schema，
bootstrap 使用 MySQL GET_LOCK，因此這支測試只在 ADMIN_TEST_DATABASE_URI
指向 MySQL / MariaDB 時執行；否則印出 SKIP 並以 0 結束（不假裝通過）。

    ADMIN_TEST_DATABASE_URI="mysql+pymysql://user:pass@localhost/emptydb?charset=utf8mb4" \\
        python3 tests/test_runtime_migration_mysql.py

涵蓋：
    1. 舊 schema（缺少本次新增的欄位 / Admin_Audit_Log / published 唯一索引、
       taxonomy 表為空）啟動 app：欄位與表補齊、索引建立、legacy taxonomy
       bootstrap 成功，既有資料不受影響
    2. 重複啟動：完全冪等（不重複建立版本、不重複 audit）
    3. 既有資料已經有重複 published：不建立唯一索引、明確 log，
       fail-closed 行為保留
"""

import os
import subprocess
import sys

URI = os.environ.get("ADMIN_TEST_DATABASE_URI", "")
if not URI.startswith("mysql"):
    print("SKIP: ADMIN_TEST_DATABASE_URI 未指向 MySQL，略過 runtime migration 整合測試")
    sys.exit(0)

from admin_test_support import check, create_app, finish  # noqa: E402
from sqlalchemy import text  # noqa: E402
from extensions import db  # noqa: E402

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

NEW_COLUMNS = [
    ("Response_Classification", "reviewed_by_admin_id"),
    ("Response_Classification", "reviewed_at"),
    ("Response_Classification", "updated_at"),
    ("Classification_Review", "closed_at"),
    ("Classification_Review", "closed_reason"),
    ("Report", "outdated_reason"),
    ("Report", "outdated_at"),
    ("Report", "updated_at"),
    ("Report", "generated_by_admin_id"),
    ("Report", "taxonomy_version_ids"),
    ("Uploaded_Answer", "routing_status"),
    ("Uploaded_Answer", "routing_detail"),
    ("Uploaded_Answer", "assigned_by_admin_id"),
    ("Uploaded_Answer", "assigned_at"),
    ("Taxonomy_Version", "published_topic_key"),
    # fix/classification-integrity-followup：重新分析 attempt 模型
    ("Response_Segmentation_Status", "attempt_no"),
    ("Response_Segmentation_Status", "last_attempt_error"),
    ("Response_Segmentation_Status", "last_attempt_at"),
    ("Response_Classification", "attempt_no"),
    # 自動主題範圍（通用欄位名不跨 workspace 共用）
    ("Topic", "auto_scope"),
    ("Topic", "auto_label"),
    ("Topic", "auto_signature"),
    ("Uploaded_Answer", "analysis_scope"),
]


def column_exists(table, column):
    return db.session.execute(text(
        "SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() "
        "AND TABLE_NAME = :t AND COLUMN_NAME = :c"), {"t": table, "c": column}).scalar() == 1


def index_exists():
    return db.session.execute(text(
        "SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE() "
        "AND TABLE_NAME = 'Taxonomy_Version' AND INDEX_NAME = 'uq_taxonomy_version_published_topic'")).scalar() > 0


def run_app_startup():
    env = dict(os.environ, DATABASE_URL=URI, JWT_SECRET_KEY="x")
    proc = subprocess.run(
        # APScheduler 的背景 thread 會讓 process 不結束，import 完成後直接結束
        [sys.executable, "-c", "import os, app; os._exit(0)"], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=180,
    )
    return proc.returncode, proc.stdout + proc.stderr


app = create_app()

print("========== 1. 舊 schema 啟動 ==========")
with app.app_context():
    db.session.execute(text("DROP INDEX uq_taxonomy_version_published_topic ON Taxonomy_Version"))
    for table, column in NEW_COLUMNS:
        db.session.execute(text(f"ALTER TABLE `{table}` DROP COLUMN `{column}`"))
    db.session.execute(text("DROP TABLE Admin_Audit_Log"))
    db.session.execute(text("DROP TABLE Response_Classification_Secondary"))
    db.session.execute(text(
        "INSERT INTO User (user_id, user_name, email, password_hash) VALUES (1, 'u', 'u@example.com', 'x')"))
    db.session.execute(text(
        "INSERT INTO Uploaded_Answer (upload_batch_id, user_id, source_column, row_index, answer_text, question_type, created_at) "
        "VALUES ('legacy-batch', 1, 'c', 0, '舊資料', 'other', NOW())"))
    db.session.execute(text(
        "INSERT INTO Response_Segmentation_Status (upload_batch_id, uploaded_answer_id, question_id, source_type, "
        "segmentation_status, created_at, updated_at) SELECT 'legacy-batch', id, 'c_row0', 'user_upload', 'completed', "
        "NOW(), NOW() FROM Uploaded_Answer WHERE upload_batch_id='legacy-batch'"))
    # 舊資料：只有 secondary_sub_category（沒有大類別）、以及人工 final 次要分類
    db.session.execute(text(
        "INSERT INTO Response_Classification (source_type, upload_batch_id, uploaded_answer_id, question_id, "
        "answer_text, segment_start, segment_end, main_category, sub_category, secondary_sub_category, status, "
        "review_status, final_main_category, final_sub_category, final_secondary_sub_category, needs_human_review, created_at) "
        "SELECT 'user_upload', 'legacy-batch', id, 'c_row0', '舊資料', 0, 3, '主管領導', 'A1 工作與生活邊界', "
        "'A2 回饋與溝通', 'completed', 'modified', '主管領導', 'A1 工作與生活邊界', 'A3 主管覺察力', 0, NOW() "
        "FROM Uploaded_Answer WHERE upload_batch_id='legacy-batch'"))
    db.session.commit()
    check("前置：新欄位確實不存在", not column_exists("Uploaded_Answer", "routing_status"))

code, output = run_app_startup()
check("app 啟動成功（import app exit 0）", code == 0)
check("啟動 log 沒有 Runtime schema check failed", "Runtime schema check failed" not in output)
check("啟動 log 沒有 follow-up schema 失敗", "follow-up schema check failed" not in output)
with app.app_context():
    db.session.remove()
    check("所有新欄位都已補上", all(column_exists(t, c) for t, c in NEW_COLUMNS))
    check("Admin_Audit_Log 已建立", db.session.execute(text("SELECT COUNT(*) FROM Admin_Audit_Log")).scalar() >= 0)
    check("published 唯一索引已建立", index_exists())
    topics = db.session.execute(text("SELECT topic_key FROM Taxonomy_Version WHERE status='published' ORDER BY topic_key")).all()
    check("legacy taxonomy bootstrap：2 個 published", [t[0] for t in topics] == ["career_and_feedback", "leadership_and_dept"])
    check("published_topic_key 已回填", db.session.execute(text(
        "SELECT COUNT(*) FROM Taxonomy_Version WHERE status='published' AND published_topic_key = topic_key")).scalar() == 2)
    check("既有 Response_Segmentation_Status 補上 attempt_no = 1", db.session.execute(text(
        "SELECT attempt_no FROM Response_Segmentation_Status WHERE upload_batch_id='legacy-batch'")).scalar() == 1)
    check("次要分類子表已建立並回填舊資料（ai + final 各 1 列）", db.session.execute(text(
        "SELECT COUNT(*) FROM Response_Classification_Secondary")).scalar() == 2)
    check("舊欄位原值不變", db.session.execute(text(
        "SELECT secondary_sub_category FROM Response_Classification WHERE upload_batch_id='legacy-batch'")).scalar() == "A2 回饋與溝通")
    check("既有資料不受影響", db.session.execute(text(
        "SELECT question_type FROM Uploaded_Answer WHERE upload_batch_id='legacy-batch'")).scalar() == "other")
    audit_count = db.session.execute(text("SELECT COUNT(*) FROM Admin_Audit_Log WHERE action='taxonomy_bootstrap'")).scalar()
    check("bootstrap audit 1 筆", audit_count == 1)

print("\n========== 2. 重複啟動冪等 ==========")
code, output = run_app_startup()
check("第二次啟動成功", code == 0)
with app.app_context():
    db.session.remove()
    check("版本數不變（2）", db.session.execute(text("SELECT COUNT(*) FROM Taxonomy_Version")).scalar() == 2)
    check("次要分類回填冪等（仍是 2 列）", db.session.execute(text(
        "SELECT COUNT(*) FROM Response_Classification_Secondary")).scalar() == 2)
    check("bootstrap audit 仍是 1 筆", db.session.execute(text(
        "SELECT COUNT(*) FROM Admin_Audit_Log WHERE action='taxonomy_bootstrap'")).scalar() == 1)

print("\n========== 3. 既有資料已損毀（多個 published）==========")
with app.app_context():
    from services.taxonomy_bootstrap_service import ensure_published_topic_unique_index
    db.session.execute(text("DROP INDEX uq_taxonomy_version_published_topic ON Taxonomy_Version"))
    db.session.execute(text(
        "INSERT INTO Taxonomy_Version (topic_key, version_number, status, source, created_at) "
        "VALUES ('leadership_and_dept', 2, 'published', 'manual', NOW())"))
    db.session.commit()
    check("偵測到重複 published，不建立索引", ensure_published_topic_unique_index() == "duplicates_found" and not index_exists())
    from services.taxonomy_service import PublishedTaxonomyIntegrityError, get_published_taxonomy_version
    try:
        get_published_taxonomy_version("leadership_and_dept")
        check("fail-closed：仍拋 PublishedTaxonomyIntegrityError", False)
    except PublishedTaxonomyIntegrityError:
        check("fail-closed：仍拋 PublishedTaxonomyIntegrityError", True)
    db.session.remove()  # 先結束這個 session 的 transaction，避免 DROP TABLE 等待 metadata lock
    db.drop_all()

finish()
