"""
高信心分類結果自動通過。

規則（全部符合才自動通過，任何一項不符合就維持 pending_review 等人工審核）：
    1. status == "completed"：AI 分類成功。新類別（status=new_category）、
       失敗、methodology_not_found 都不算。
    2. needs_human_review == False：Confidence Gate 沒有標記
       （分類完整、類別在清單內、信心分數有效且 >= 0.75，見
       services/confidence_gate.py）。
    3. 這筆分類使用的分類架構版本是「已發布」的。AI 自動建立的主題
       只有 AI 自己歸納、還沒有人審過的草稿（暫定分類架構），「類別在
       清單內」不代表可信，所以不自動通過。

自動通過的列：review_status = confirmed、auto_confirmed = True、
reviewed_by_admin_id = NULL。它們會進入報告（跟人工確認一樣），但：
    - 不當成回饋給 Gemini 的「人工審核範例」（避免 AI 拿自己的答案當標準）
    - 不受重新分析保護（見 classification_attempt_service.protected_row_ids）
    - 隨時可以重新開啟審核；任何人工動作都會把 auto_confirmed 改回 False

緊急開關：環境變數 AUTO_CONFIRM_HIGH_CONFIDENCE=0 可以關閉新資料的自動
通過（已經自動通過的資料不受影響）。
"""

import os

from classification_models import (
    REVIEW_STATUS_CONFIRMED,
    REVIEW_STATUS_PENDING,
    Response_Classification,
)
from extensions import db, taiwan_now
from taxonomy import TAXONOMY_VERSION_STATUS_PUBLISHED

CLASSIFICATION_STATUS_COMPLETED = "completed"
ACTION_AUTO_CONFIRM_BACKFILL = "auto_confirm_backfill"


def auto_confirm_enabled() -> bool:
    return os.environ.get("AUTO_CONFIRM_HIGH_CONFIDENCE", "1").strip().lower() not in ("0", "false", "no", "off")


def _version_is_published(taxonomy_version_id, cache) -> bool:
    if taxonomy_version_id is None:
        return False
    if taxonomy_version_id not in cache:
        from models import Taxonomy_Version

        version = db.session.get(Taxonomy_Version, taxonomy_version_id)
        cache[taxonomy_version_id] = version is not None and version.status == TAXONOMY_VERSION_STATUS_PUBLISHED
    return cache[taxonomy_version_id]


def is_eligible(row, version_cache=None) -> bool:
    """這筆列目前是否符合自動通過的條件（不看 review_status）。"""
    if version_cache is None:
        version_cache = {}
    return (
        row.status == CLASSIFICATION_STATUS_COMPLETED
        and not row.needs_human_review
        and bool(row.main_category) and bool(row.sub_category)
        and _version_is_published(row.taxonomy_version_id, version_cache)
    )


def _mark(row, now):
    row.review_status = REVIEW_STATUS_CONFIRMED
    row.auto_confirmed = True
    row.reviewed_by_admin_id = None
    row.reviewed_at = now
    row.updated_at = now


def apply_to_new_rows(rows) -> int:
    """剛建立、還沒 flush 的分類列：符合條件的直接自動通過。回傳筆數。"""
    if not auto_confirm_enabled():
        return 0
    cache, now, count = {}, taiwan_now(), 0
    for row in rows:
        # 還沒 flush 的新列，review_status 可能是 None（DB 預設值要 INSERT 時才套用）
        if row.review_status in (None, REVIEW_STATUS_PENDING) and is_eligible(row, cache):
            _mark(row, now)
            count += 1
    return count


def backfill_existing(admin_id, dry_run=True, limit=5000) -> dict:
    """把「已經存在、還在待審、但其實符合條件」的列補做自動通過。

    - 有人正在審核（in_progress session）或曾經進過審核對話的列不動：
      那代表有人已經在看，不應該被系統搶先定案。
    - 被新分析取代的舊 attempt（superseded）不動（status 不是 completed）。
    - dry_run=True 只回傳會影響的筆數，不寫入。
    - 實際執行時逐筆寫 audit（admin_id = 觸發的管理員）。報告不會過期：
      待審的結果本來就算在報告裡，自動通過不改變報告內容。
    """
    from classification_models import Classification_Review
    from services import audit_service

    reviewed_ids = db.session.query(Classification_Review.classification_id).distinct()
    rows = (
        Response_Classification.query.filter(
            Response_Classification.review_status == REVIEW_STATUS_PENDING,
            Response_Classification.status == CLASSIFICATION_STATUS_COMPLETED,
            Response_Classification.needs_human_review.is_(False),
            Response_Classification.taxonomy_version_id.isnot(None),
            ~Response_Classification.classification_id.in_(reviewed_ids),
        )
        .order_by(Response_Classification.classification_id.asc())
        .limit(limit)
        .all()
    )
    cache = {}
    eligible = [r for r in rows if is_eligible(r, cache)]
    result = {
        "dry_run": bool(dry_run),
        "eligible_count": len(eligible),
        "classification_ids": [r.classification_id for r in eligible][:500],
        "limit_reached": len(rows) >= limit,
    }
    if dry_run or not eligible:
        return result

    now = taiwan_now()
    try:
        for row in eligible:
            before = audit_service.classification_state(row)
            _mark(row, now)
            audit_service.record(
                ACTION_AUTO_CONFIRM_BACKFILL, audit_service.ENTITY_CLASSIFICATION, row.classification_id, admin_id,
                before=before, after=audit_service.classification_state(row),
            )
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return result
