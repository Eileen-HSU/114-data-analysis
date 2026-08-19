"""

Aggregation Readiness：讓 User 在還沒 review 完 100% 的情況下，也能
清楚看到「目前有多少筆可以拿去產生報告」，並可以選擇「只用已確認
結果產生」。

後端本身不會偷偷把 pending_review 加進 Aggregation——can_generate
只反映「eligible > 0」，pending 存不存在完全不影響 eligible 的計算，
前端要不要在 has_pending=True 時跳警告是前端的事，這裡只負責給出
正確的數字。
"""

from response_classification import (
    REVIEW_STATUS_PENDING,
    REVIEW_STATUS_CONFIRMED,
    REVIEW_STATUS_MODIFIED,
    REVIEW_STATUS_EXCLUDED,
)
from services.source_lookup_service import fetch_classifications_in_scope


def get_readiness(source_type, template_id=None, upload_batch_id=None) -> dict:
    rows = fetch_classifications_in_scope(
        source_type=source_type, template_id=template_id, upload_batch_id=upload_batch_id,
    )

    counts = {
        REVIEW_STATUS_PENDING: 0,
        REVIEW_STATUS_CONFIRMED: 0,
        REVIEW_STATUS_MODIFIED: 0,
        REVIEW_STATUS_EXCLUDED: 0,
    }
    for row in rows:
        # 理論上 review_status 只會是上面四個值之一（DB 層雖然沒有
        # CheckConstraint 強制，但所有寫入路徑都只會寫這四個值）；
        # 萬一出現意外值，不要讓整個 readiness 計算噴例外，計入
        # total 但不歸入任何一類，eligible/pending 都不會算到它，
        # 這樣的資料異常會反映成 total > 四類總和，方便事後排查。
        if row.review_status in counts:
            counts[row.review_status] += 1

    confirmed = counts[REVIEW_STATUS_CONFIRMED]
    modified = counts[REVIEW_STATUS_MODIFIED]
    excluded = counts[REVIEW_STATUS_EXCLUDED]
    pending = counts[REVIEW_STATUS_PENDING]
    eligible = confirmed + modified

    return {
        "total": len(rows),
        "confirmed": confirmed,
        "modified": modified,
        "excluded": excluded,
        "pending_review": pending,
        "eligible": eligible,
        "has_pending": pending > 0,
        "can_generate": eligible > 0,
    }
