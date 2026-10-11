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
    非待審的列（已確認、已排除…）與失敗的列不受影響。回傳 None 代表不篩選。"""
    R = Response_Classification
    from services.admin_recovery_service import _legacy_classification_clause

    # status=failed 的列有自己的「無法分類」分頁（state=failed），不屬於待審佇列，不能被這個篩選藏起來；
    # 否則前端沒帶 queue 的 failed 分頁與 status_counts.failed 會永遠是 0。
    # 待審分頁（state=pending_review）本來就排除 failed，所以這裡放行不會改變待審清單。
    not_in_queue_view = db.or_(R.review_status != REVIEW_STATUS_PENDING, R.status == "failed")
    if queue == "human":
        return db.or_(
            not_in_queue_view,
            db.and_(bucket_expr().in_(HUMAN_ROW_BUCKETS), ~_legacy_classification_clause()),
        )
    if queue in HUMAN_ROW_BUCKETS:
        return db.or_(
            not_in_queue_view,
            db.and_(bucket_expr() == queue, ~_legacy_classification_clause()),
        )
    return None  # 其他值（例如 all）：不篩選


def _not_done_clause():
    """只留會被計入桶的列：待審的，加上自動通過的。

    其他已處理的列（已確認但不是自動通過、已修改、已排除）在 bucket_expr 一律是 BUCKET_DONE，
    而 DONE 不在 ALL_BUCKETS 裡、算完就丟掉；在 SQL 先排除，結果完全相同，但不必替這些列算 CASE。"""
    R = Response_Classification
    return db.or_(
        R.review_status == REVIEW_STATUS_PENDING,
        db.and_(R.review_status == REVIEW_STATUS_CONFIRMED, R.auto_confirmed.is_(True)),
    )


def _topic_counts():
    """{topic_key: {bucket: 筆數}}（topic_key=None 是沒有分類架構的舊資料）。"""
    from models import Taxonomy_Version
    from services.admin_recovery_service import _legacy_classification_clause

    live = db.or_(
        Response_Classification.status.is_(None),
        ~Response_Classification.status.in_(_NON_LIVE_STATUSES),
    )
    # 先在子查詢裡算出每筆的桶，再外層 group by，避免 GROUP BY 重複一整段 CASE
    inner = (
        db.session.query(Taxonomy_Version.topic_key.label("topic_key"), bucket_expr().label("bucket"))
        .select_from(Response_Classification)
        .outerjoin(Taxonomy_Version, Response_Classification.taxonomy_version_id == Taxonomy_Version.version_id)
        .filter(live, ~_legacy_classification_clause(), _not_done_clause())
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
    from models import Taxonomy_Version, Topic
    from services.admin_recovery_service import _legacy_classification_clause

    # 只算「正常現行候選」：legacy、主題不存在、主題已被合併的屬於殘留 bucket，
    # 另外由 residual_new_category_groups 回報，不計入這個徽章。
    rows = (
        db.session.query(
            Taxonomy_Version.topic_key, Response_Classification.main_category, Response_Classification.sub_category,
        )
        .join(Taxonomy_Version, Response_Classification.taxonomy_version_id == Taxonomy_Version.version_id)
        .join(Topic, Taxonomy_Version.topic_key == Topic.topic_key)
        .filter(
            Response_Classification.status == NEW_CATEGORY_STATUS,
            Response_Classification.review_status == REVIEW_STATUS_PENDING,
            ~_legacy_classification_clause(),
            db.or_(Topic.merged_into.is_(None), Topic.merged_into == ""),
        )
        .distinct()
        .all()
    )
    groups = {}
    for topic_key, _main, _sub in rows:
        groups[topic_key] = groups.get(topic_key, 0) + 1
    return groups


def _undecided_topic_keys() -> set:
    """主題存在、沒有被併入其他主題、也還沒有 published 版本。"""
    from models import Taxonomy_Version, Topic
    from taxonomy import TAXONOMY_VERSION_STATUS_PUBLISHED

    existing = {k for (k,) in db.session.query(Topic.topic_key).filter(
        db.or_(Topic.merged_into.is_(None), Topic.merged_into == "")).all()}
    published = {k for (k,) in db.session.query(Taxonomy_Version.topic_key).filter(
        Taxonomy_Version.status == TAXONOMY_VERSION_STATUS_PUBLISHED).distinct().all()}
    return existing - published


def undecided_auto_topic_keys() -> set:
    """分類架構頁「AI 暫時主題」篩選的同一個定義：auto_ 開頭、未併入其他主題、沒有 published 版本，
    並排除舊資料主題。不看有沒有回答、有沒有草稿或新類別候選。"""
    from models import Topic
    from services.admin_recovery_service import LEGACY_SOURCE_COLUMN
    from services.open_classification import is_auto_topic

    keys = {k for k, title in db.session.query(Topic.topic_key, Topic.title).all()
            if is_auto_topic(k) and k != LEGACY_SOURCE_COLUMN and title != LEGACY_SOURCE_COLUMN}
    return keys & _undecided_topic_keys()


def residual_new_category_groups() -> int:
    from services.new_category_service import residual_group_count

    return residual_group_count()


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
    # 「待決策的 AI 自動主題」：還沒決定去向的主題。已被併入其他主題、或已經有 published 版本（已是
    # 正式主題）的，即使還有待處理回答仍綁在舊版（採用 / 合併後的常見狀態），也不算待決策。
    undecided = _undecided_topic_keys()
    provisional_topics = sum(1 for key, c in per_topic.items() if key in undecided and c[BUCKET_PROVISIONAL] > 0)

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
            "system_blocked": split["system_blocked"],
            "total": totals[BUCKET_AWAITING_SECOND_OPINION] + totals[BUCKET_AWAITING_AUTO_CONFIRM] + split["pending"],
        },
        # 需要人工決策：單位是「一次決策」（新類別、暫定主題以群組／主題計）
        "needs_decision": {
            "ai_disagreement": totals[BUCKET_AI_DISAGREEMENT],
            "new_category_groups": sum(new_groups.values()),
            "retry_failed": retry_failed,
            "unassigned_retry_failed": split["still_failed"],
            "unassigned_retry_failed_by_kind": split["still_failed_by_kind"],
            "second_opinion_failed": totals[BUCKET_SECOND_OPINION_FAILED],
            "other": totals[BUCKET_OTHER],
            "provisional_topics": provisional_topics,
            "undecided_auto_topics": len(undecided_auto_topic_keys()),  # 與分類架構頁「AI 暫時主題」一致；不計入 total
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
        # 殘留／舊新類別候選（legacy、找不到主題、主題已被合併）：不計入上面的新類別徽章
        "residual_new_category_groups": residual_new_category_groups(),
        "topics": topics,
    }
