"""
AI 管理首頁「今天需要處理的事」用的彙整數字（GET /api/admin/ai/overview）。

把散在各頁的待辦數量一次算好，依「Admin 要做什麼」分三類：
    cannot_classify ：無法分類（未歸屬主題、分類失敗）—— 這些回答目前沒有任何結果
    needs_person    ：需要人處理的待審結果
        needs_judgement：低信心、分類不完整、AI 新類別等（needs_human_review / status=new_category）
        other_pending  ：沒有被標記、但還在待審（AI 自動主題的暫定分類、
                         自動通過上線前的舊資料）
    auto_confirmed  ：系統已自動通過，可以抽查

另外回傳每個主題各自的數字，首頁的主題卡片用它顯示待辦、排序。
只讀不寫。
"""

from sqlalchemy import case, func

from classification_models import REVIEW_STATUS_CONFIRMED, REVIEW_STATUS_PENDING, Response_Classification
from extensions import db

_NON_LIVE_STATUSES = ("failed", "superseded")
NEW_CATEGORY_STATUS = "new_category"


def _topic_counts():
    from models import Taxonomy_Version

    flagged = db.or_(
        Response_Classification.needs_human_review.is_(True),
        Response_Classification.status == NEW_CATEGORY_STATUS,
    )
    live = db.or_(
        Response_Classification.status.is_(None),
        ~Response_Classification.status.in_(_NON_LIVE_STATUSES),
    )
    pending = Response_Classification.review_status == REVIEW_STATUS_PENDING
    auto = db.and_(
        Response_Classification.review_status == REVIEW_STATUS_CONFIRMED,
        Response_Classification.auto_confirmed.is_(True),
    )
    rows = (
        db.session.query(
            Taxonomy_Version.topic_key,
            func.sum(case((db.and_(pending, flagged), 1), else_=0)),
            func.sum(case((db.and_(pending, ~flagged), 1), else_=0)),
            func.sum(case((db.and_(pending, Response_Classification.review_flag_reason == "low_confidence"), 1), else_=0)),
            func.sum(case((auto, 1), else_=0)),
        )
        .select_from(Response_Classification)
        .outerjoin(Taxonomy_Version, Response_Classification.taxonomy_version_id == Taxonomy_Version.version_id)
        .filter(live)
        .group_by(Taxonomy_Version.topic_key)
        .all()
    )
    return {
        topic_key: {
            "needs_judgement": int(judgement or 0),
            "other_pending": int(other or 0),
            "low_confidence": int(low or 0),
            "auto_confirmed": int(auto_count or 0),
        }
        for topic_key, judgement, other, low, auto_count in rows
    }


def _new_category_groups():
    """每個主題有幾組待決定的新類別（同一主題、同一大類別／子類別算一組）。"""
    from models import Taxonomy_Version

    rows = (
        db.session.query(
            Taxonomy_Version.topic_key, Response_Classification.main_category, Response_Classification.sub_category,
        )
        .join(Taxonomy_Version, Response_Classification.taxonomy_version_id == Taxonomy_Version.version_id)
        .filter(
            Response_Classification.status == NEW_CATEGORY_STATUS,
            Response_Classification.review_status == REVIEW_STATUS_PENDING,
        )
        .distinct()
        .all()
    )
    groups = {}
    for topic_key, _main, _sub in rows:
        groups[topic_key] = groups.get(topic_key, 0) + 1
    return groups


def build_overview() -> dict:
    from services.admin_recovery_service import KIND_FAILED, KIND_UNROUTED, unassigned_counts

    unassigned = unassigned_counts()
    per_topic = _topic_counts()
    new_groups = _new_category_groups()

    # 沒有分類架構版本的舊資料（topic_key=None）也算進總數，但不歸到任何主題卡片
    totals = {"needs_judgement": 0, "other_pending": 0, "low_confidence": 0, "auto_confirmed": 0}
    for counts in per_topic.values():
        for key in totals:
            totals[key] += counts[key]

    topics = {}
    for topic_key in set(per_topic) | set(new_groups):
        if topic_key is None:
            continue
        counts = per_topic.get(topic_key, {"needs_judgement": 0, "other_pending": 0, "low_confidence": 0, "auto_confirmed": 0})
        topics[topic_key] = {**counts, "new_category_groups": new_groups.get(topic_key, 0)}

    return {
        "cannot_classify": {
            "unrouted": unassigned[KIND_UNROUTED],
            "failed": unassigned[KIND_FAILED],
            "total": unassigned[KIND_UNROUTED] + unassigned[KIND_FAILED],
        },
        "needs_person": {
            "needs_judgement": totals["needs_judgement"],
            "low_confidence": totals["low_confidence"],
            "new_category_groups": sum(new_groups.values()),
            "other_pending": totals["other_pending"],
            "total": totals["needs_judgement"] + totals["other_pending"],
        },
        "auto_confirmed": {"total": totals["auto_confirmed"]},
        "topics": topics,
    }
