"""
Taxonomy bootstrap：新 DB（或 taxonomy 表為空的既有 DB）啟動時，安全、
冪等地把 legacy taxonomy 帶入 Topic / Taxonomy_Version / Taxonomy_Category。

【為什麼需要】app.py 的 runtime migration 只會建立 taxonomy 空表；
production classification 是 fail-closed（沒有 published taxonomy 就不
分類、不 fallback 到 hardcoded 分類），所以新 DB 上傳資料會全部變成
「零分類」。這裡補上一條明確的 bootstrap 路徑，但不改變 fail-closed：
bootstrap 失敗時只記錄 log，classification 仍然不會偷偷用 legacy 規則。

【執行條件】（全部滿足才寫入）
    1. Taxonomy_Version 完全沒有任何列（任何 Topic 只要有過任何版本——
       不論 draft/published/archived——就視為「已經有 taxonomy」，一律
       不動，不覆蓋、不重複建立版本）。
    2. 取得跨 worker 的 bootstrap 鎖（MySQL GET_LOCK）後，再檢查一次條件 1。

【併發保護】（多個 gunicorn worker / 多台機器同時啟動）
    - MySQL：GET_LOCK('taxonomy_bootstrap') 序列化；拿到鎖的人寫入，
      其他人等鎖釋放後重新檢查，發現已有資料就略過。
    - 即使沒有鎖（例如 SQLite 或鎖逾時），Topic 主鍵與
      UNIQUE(topic_key, version_number) 也保證不會重複插入：撞到
      IntegrityError 會 rollback 並回報 concurrent_bootstrap。

【資料轉換】完全共用 migrate_taxonomy_from_legacy.seed_legacy_taxonomy()，
不另外複製一套轉換邏輯。

【路徑】
    - app 啟動：app.py bootstrap_taxonomy_on_startup()（可用
      TAXONOMY_BOOTSTRAP_ON_STARTUP=0 關閉）
    - 部署 / 手動：FLASK_APP=cli.py flask bootstrap-taxonomy
    - 既有一次性腳本：python3 migrate_taxonomy_from_legacy.py（同一套 seed）
"""

import logging

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from extensions import db

_LOCK_NAME = "taxonomy_bootstrap"
_LOCK_TIMEOUT_SECONDS = 30
_PUBLISHED_INDEX_NAME = "uq_taxonomy_version_published_topic"

_default_logger = logging.getLogger("taxonomy_bootstrap")


def _dialect():
    return db.session.get_bind().dialect.name


def _acquire_lock(logger):
    if _dialect() != "mysql":
        return True
    got = db.session.execute(
        text("SELECT GET_LOCK(:name, :timeout)"), {"name": _LOCK_NAME, "timeout": _LOCK_TIMEOUT_SECONDS}
    ).scalar()
    if got != 1:
        logger.warning("[TAXONOMY_BOOTSTRAP] could not acquire lock within %ss", _LOCK_TIMEOUT_SECONDS)
        return False
    return True


def _release_lock():
    if _dialect() == "mysql":
        db.session.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": _LOCK_NAME})


def taxonomy_is_empty() -> bool:
    from models import Taxonomy_Version
    return db.session.query(Taxonomy_Version.version_id).first() is None


def bootstrap_legacy_taxonomy(logger=None) -> dict:
    """Returns: {"status": "created" | "skipped_existing" | "lock_timeout" |
    "concurrent_bootstrap", "created_topics": [...]}。其他例外直接往外拋
    （呼叫端負責 log，不可靜默吞掉）。"""
    logger = logger or _default_logger

    if not taxonomy_is_empty():
        return {"status": "skipped_existing", "created_topics": []}

    if not _acquire_lock(logger):
        return {"status": "lock_timeout", "created_topics": []}
    try:
        # 拿到鎖之後重新檢查：可能別的 worker 剛剛已經完成 bootstrap。
        db.session.expire_all()
        if not taxonomy_is_empty():
            return {"status": "skipped_existing", "created_topics": []}

        from migrate_taxonomy_from_legacy import seed_legacy_taxonomy
        from services import audit_service

        try:
            created = seed_legacy_taxonomy(log=lambda msg: logger.info("[TAXONOMY_BOOTSTRAP] %s", msg))
            if created:
                audit_service.record(
                    audit_service.ACTION_TAXONOMY_BOOTSTRAP, audit_service.ENTITY_TAXONOMY_VERSION,
                    ",".join(created), None,
                    after={"created_topics": created, "source": "migrated_legacy"},
                    reason="startup bootstrap: taxonomy tables were empty",
                )
            db.session.commit()
        except IntegrityError as exc:
            db.session.rollback()
            logger.warning("[TAXONOMY_BOOTSTRAP] concurrent bootstrap detected, rolled back: %s", exc)
            return {"status": "concurrent_bootstrap", "created_topics": []}
        except Exception:
            db.session.rollback()
            raise

        logger.info("[TAXONOMY_BOOTSTRAP] created topics: %s", created)
        return {"status": "created", "created_topics": created}
    finally:
        try:
            _release_lock()
            db.session.commit()
        except Exception:  # 釋放鎖失敗不影響結果；連線結束時 MySQL 也會自動釋放
            db.session.rollback()


def ensure_published_topic_unique_index(logger=None) -> str:
    """回填 Taxonomy_Version.published_topic_key 並建立 UNIQUE INDEX，
    讓「每個 Topic 最多一個 published 版本」由 DB 保證。

    既有資料若已經有同一 Topic 多個 published（資料損毀），不建立索引，
    明確 log error；此時 get_published_taxonomy_version() 仍會拋
    PublishedTaxonomyIntegrityError（fail-closed），需要人工修正資料。

    Returns: "created" | "exists" | "duplicates_found"
    """
    logger = logger or _default_logger

    db.session.execute(text(
        "UPDATE Taxonomy_Version SET published_topic_key = "
        "CASE WHEN status = 'published' THEN topic_key ELSE NULL END"
    ))
    db.session.commit()

    duplicates = db.session.execute(text(
        "SELECT topic_key, COUNT(*) FROM Taxonomy_Version WHERE status = 'published' "
        "GROUP BY topic_key HAVING COUNT(*) > 1"
    )).all()
    if duplicates:
        logger.error(
            "[TAXONOMY_PUBLISH_GUARD] multiple published versions found, unique index NOT created: %s",
            [(row[0], row[1]) for row in duplicates],
        )
        return "duplicates_found"

    if _dialect() == "mysql":
        exists = db.session.execute(text(
            "SELECT COUNT(*) FROM information_schema.STATISTICS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'Taxonomy_Version' "
            "AND INDEX_NAME = :name"
        ), {"name": _PUBLISHED_INDEX_NAME}).scalar()
        if exists:
            return "exists"
        db.session.execute(text(
            f"CREATE UNIQUE INDEX `{_PUBLISHED_INDEX_NAME}` ON `Taxonomy_Version` (`published_topic_key`)"
        ))
    else:
        db.session.execute(text(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {_PUBLISHED_INDEX_NAME} "
            "ON Taxonomy_Version (published_topic_key)"
        ))
    db.session.commit()
    return "created"
