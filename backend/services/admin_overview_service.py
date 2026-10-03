"""
AI 管理首頁「今天需要處理的事」用的彙整數字（GET /api/admin/ai/overview）。

把散在各頁的待辦數量一次算好，依「Admin 要做什麼」分三類：
    cannot_classify ：無法分類（未歸屬主題、分類失敗）—— 這些回答目前沒有任何結果
    auto_processing ：系統自動處理中（不需要人）：等 AI 再確認、等自動通過、無法分類等排程重試
    needs_decision  ：需要人工決策：AI 判斷不一致、新類別候選（群組）、自動重試仍失敗…
    needs_person    ：待人工審查（逐筆）。只算 ai_disagreement + AI 再確認失敗 + 其他無法自動處理的；
                      不是所有 pending_review。每一筆待審歸到唯一的桶，見 bucket_expr()
    auto_confirmed  ：系統已自動通過，可以抽查（不要求逐筆確認）

另外回傳每個主題各自的數字，首頁的主題卡片用它顯示待辦、排序。
只讀不寫。
"""

from sqlalchemy import case, func

from classification_models import REVIEW_STATUS_CONFIRMED, REVIEW_STATUS_PENDING, Response_Classification
from extensions import db

_NON_LIVE_STATUSES = ("failed", "superseded")
NEW_CATEGORY_STATUS = "new_category"


# ── 每一筆「待處理」結果歸到唯一一個桶（互斥，不會重複計算）────────────
# 系統自動處理中（不需要人）：
#   awaiting_second_opinion ：低信心，排程會交給 AI 再判斷一次（second_opinion_service）
#   awaiting_auto_confirm   ：沒有被標記、分類架構已發布，排程會補做自動通過（auto_confirm_service）
#   new_category            ：AI 提出的新類別，以「群組」為單位決策（見 _new_category_groups）
#   provisional             ：AI 自動主題的暫定分類，要先對「主題」決策（發布 / 合併），不是逐筆
# 需要人工（逐筆）：
#   ai_disagreement         ：AI 兩次判斷不一致
#   second_opinion_failed   ：AI 再確認本身失敗
#   other                   ：分類不完整、找不到方法論、已有人開始審核等無法自動處理的
BUCKET_AWAITING_SECOND_OPINION = "awaiting_second_opinion"
BUCKET_AWAITING_AUTO_CONFIRM = "awaiting_auto_confirm"
BUCKET_NEW_CATEGORY = "new_category"
BUCKET_PROVISIONAL = "provisional"
BUCKET_AI_DISAGREEMENT = "ai_disagreement"
BUCKET_SECOND_OPINION_FAILED = "second_opinion_failed"
BUCKET_OTHER = "other"
BUCKET_AUTO_CONFIRMED = "auto_confirmed"
BUCKET_DONE = "done"
HUMAN_ROW_BUCKETS = (BUCKET_AI_DISAGREEMENT, BUCKET_SECOND_OPINION_FAILED, BUCKET_OTHER)
ALL_BUCKETS = (
    BUCKET_AWAITING_SECOND_OPINION, BUCKET_AWAITING_AUTO_CONFIRM, BUCKET_NEW_CATEGORY, BUCKET_PROVISIONAL,
    BUCKET_AI_DISAGREEMENT, BUCKET_SECOND_OPINION_FAILED, BUCKET_OTHER, BUCKET_AUTO_CONFIRMED,
)


def bucket_expr():
    """SQL CASE：每一筆分類結果屬於哪個桶。判斷順序就是優先順序。
    /classifications 的 queue 篩選與首頁數字共用這一份定義，清單跟數字才會一致。"""
    from classification_models import Classification_Review
    from models import Taxonomy_Version
    from taxonomy import TAXONOMY_VERSION_STATUS_PUBLISHED

    R = Response_Classification
    published_ids = db.session.query(Taxonomy_Version.version_id).filter(
        Taxonomy_Version.status == TAXONOMY_VERSION_STATUS_PUBLISHED)
    published = R.taxonomy_version_id.in_(published_ids)
    reviewed = R.classification_id.in_(db.session.query(Classification_Review.classification_id).distinct())
    completed = R.status == "completed"
    return case(
        (db.and_(R.review_status == REVIEW_STATUS_CONFIRMED, R.auto_confirmed.is_(True)), BUCKET_AUTO_CONFIRMED),
        (R.review_status != REVIEW_STATUS_PENDING, BUCKET_DONE),
        (R.status.in_(_NON_LIVE_STATUSES), BUCKET_DONE),
        (R.status == NEW_CATEGORY_STATUS, BUCKET_NEW_CATEGORY),
        (db.and_(R.taxonomy_version_id.isnot(None), ~published), BUCKET_PROVISIONAL),
        (R.review_flag_reason == "ai_disagreement", BUCKET_AI_DISAGREEMENT),
        (R.second_opinion_status == "failed", BUCKET_SECOND_OPINION_FAILED),
        (db.and_(completed, R.review_flag_reason == "low_confidence", R.second_opinion_status.is_(None),
                 published, ~reviewed), BUCKET_AWAITING_SECOND_OPINION),
        (db.and_(completed, R.needs_human_review.is_(False), R.main_category.isnot(None),
                 R.sub_category.isnot(None), published, ~reviewed), BUCKET_AWAITING_AUTO_CONFIRM),
        else_=BUCKET_OTHER,
    )


def queue_clause(queue):
    """分類審查清單的 queue 篩選：
        human          ：待審之中只留需要人工逐筆處理的（隱藏系統處理中、新類別群組、暫定主題）
        <某個人工桶>    ：只看那一種（例如 ai_disagreement）
    非待審的列（已確認、已排除…）不受影響。回傳 None 代表不篩選。"""
    R = Response_Classification
    if queue == "human":
        return db.or_(R.review_status != REVIEW_STATUS_PENDING, bucket_expr().in_(HUMAN_ROW_BUCKETS))
    if queue in HUMAN_ROW_BUCKETS:
        return db.or_(R.review_status != REVIEW_STATUS_PENDING, bucket_expr() == queue)
    return None


def _topic_counts():
    """{topic_key: {bucket: 筆數}}（topic_key=None 是沒有分類架構的舊資料）。"""
    from models import Taxonomy_Version

    live = db.or_(
        Response_Classification.status.is_(None),
        ~Response_Classification.status.in_(_NON_LIVE_STATUSES),
    )
    # 先在子查詢裡算出每筆的桶，再外層 group by，避免 GROUP BY 重複一整段 CASE
    inner = (
        db.session.query(Taxonomy_Version.topic_key.label("topic_key"), bucket_expr().label("bucket"))
        .select_from(Response_Classification)
        .outerjoin(Taxonomy_Version, Response_Classification.taxonomy_version_id == Taxonomy_Version.version_id)
        .filter(live)
        .subquery()
    )
    rows = db.session.query(inner.c.topic_key, inner.c.bucket, func.count()).group_by(inner.c.topic_key, inner.c.bucket).all()
    counts = {}
    for topic_key, bucket, n in rows:
        counts.setdefault(topic_key, {b: 0 for b in ALL_BUCKETS})
        if bucket in counts[topic_key]:
            counts[topic_key][bucket] += int(n)
    return counts


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
    from services.bulk_retry_service import retry_split

    unassigned = unassigned_counts()
    split = retry_split()
    per_topic = _topic_counts()
    new_groups = _new_category_groups()

    totals = {b: 0 for b in ALL_BUCKETS}
    for counts in per_topic.values():
        for key in totals:
            totals[key] += counts[key]
    provisional_topics = sum(1 for key, c in per_topic.items() if key is not None and c[BUCKET_PROVISIONAL] > 0)

    def judgement(c):  # 需要人工逐筆處理的列
        return c[BUCKET_AI_DISAGREEMENT] + c[BUCKET_SECOND_OPINION_FAILED] + c[BUCKET_OTHER]

    topics = {}
    for topic_key in set(per_topic) | set(new_groups):
        if topic_key is None:
            continue
        c = per_topic.get(topic_key) or {b: 0 for b in ALL_BUCKETS}
        topics[topic_key] = {
            "needs_judgement": judgement(c),
            "other_pending": c[BUCKET_PROVISIONAL] + c[BUCKET_AWAITING_AUTO_CONFIRM],
            "provisional": c[BUCKET_PROVISIONAL],
            "low_confidence": c[BUCKET_AWAITING_SECOND_OPINION] + c[BUCKET_SECOND_OPINION_FAILED],
            "ai_disagreement": c[BUCKET_AI_DISAGREEMENT],
            "auto_confirmed": c[BUCKET_AUTO_CONFIRMED],
            "new_category_groups": new_groups.get(topic_key, 0),
        }

    review_rows = judgement(totals)
    retry_failed = split["still_failed"] + totals[BUCKET_SECOND_OPINION_FAILED]
    decisions = (totals[BUCKET_AI_DISAGREEMENT] + sum(new_groups.values()) + retry_failed
                 + totals[BUCKET_OTHER] + provisional_topics)

    return {
        # 無法分類：total 是全部；retrying 是系統排程還沒重試過的，still_failed 才需要人
        "cannot_classify": {
            "unrouted": unassigned[KIND_UNROUTED],
            "failed": unassigned[KIND_FAILED],
            "total": unassigned[KIND_UNROUTED] + unassigned[KIND_FAILED],
            "retrying": split["pending"],
            "still_failed": split["still_failed"],
        },
        # 系統自動處理中：不需要人，排程會處理
        "auto_processing": {
            "awaiting_second_opinion": totals[BUCKET_AWAITING_SECOND_OPINION],
            "awaiting_auto_confirm": totals[BUCKET_AWAITING_AUTO_CONFIRM],
            "unassigned_retrying": split["pending"],
            "total": totals[BUCKET_AWAITING_SECOND_OPINION] + totals[BUCKET_AWAITING_AUTO_CONFIRM] + split["pending"],
        },
        # 需要人工決策：單位是「一次決策」（新類別、暫定主題以群組／主題計）
        "needs_decision": {
            "ai_disagreement": totals[BUCKET_AI_DISAGREEMENT],
            "new_category_groups": sum(new_groups.values()),
            "retry_failed": retry_failed,
            "unassigned_retry_failed": split["still_failed"],
            "second_opinion_failed": totals[BUCKET_SECOND_OPINION_FAILED],
            "other": totals[BUCKET_OTHER],
            "provisional_topics": provisional_topics,
            "total": decisions,
        },
        # 待人工審查（分類審查頁「待審查」）只算真正要人逐筆處理的列
        "needs_person": {
            "needs_judgement": review_rows,
            "low_confidence": totals[BUCKET_AWAITING_SECOND_OPINION] + totals[BUCKET_SECOND_OPINION_FAILED],
            "awaiting_second_opinion": totals[BUCKET_AWAITING_SECOND_OPINION],
            "ai_disagreement": totals[BUCKET_AI_DISAGREEMENT],
            "new_category_groups": sum(new_groups.values()),
            "other_pending": totals[BUCKET_PROVISIONAL] + totals[BUCKET_AWAITING_AUTO_CONFIRM],
            "total": review_rows,
        },
        "auto_confirmed": {"total": totals[BUCKET_AUTO_CONFIRMED]},
        "topics": topics,
    }
