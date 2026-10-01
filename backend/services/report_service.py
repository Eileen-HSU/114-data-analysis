"""

Versioned Report Snapshot 產生流程（對應需求文件第十九～二十六節，
以及使用者對 Phase 5 的十點要求）。

【Snapshot 保證】
    Report_Aggregation / Report_Aggregation_Item 寫入的都是「產生當下
    的值」（文字內容、methodology/citation、response_count/segment_count
    等），不是只存 FK。之後 Response_Classification 即使被 Human
    Review 改變，本函式產生的這個版本完全不會跟著變——這是
    get_report_detail() 完全不去查即時 Response_Classification、只讀
    Report_Aggregation/_Item 快照內容的原因。

【Version 遞增與並行安全】
    version 不是用「查詢目前最大值 +1」就直接寫入這麼天真的作法
    ——兩個併發請求都查到同一個最大值會產生同一個 version，
    衝突無法用應用層邏輯完全避免（尤其正式環境是多進程的 MySQL）。
    這裡用 Phase 2 已經建好的 Report.source_key + version
    UniqueConstraint 當作唯一的併發防線：「claim 版本號」這一步
    先單獨 commit，若撞到 IntegrityError（DB 層擋下重複 version），
    直接 rollback 後重新查詢目前最大值再試一次，重試幾次仍失敗才
    視為真正的錯誤。這個機制不管是同一個 process 內的併發、還是
    正式環境多個 process/多台機器同時打 API，都一樣有效，因為勝負
    是由資料庫的 UNIQUE 約束決定，不是應用層的記憶體鎖。

【Transaction Boundary】
    Step 1（claim version）：建立 Report row，status=generating，
        單獨 commit——這一步本身就是「宣告我要開始產生這個 version」，
        即使後面失敗，也需要有一筆 status=failed 的紀錄可以查，不能
        整個消失不留痕跡。
    Step 2（aggregation + summary + snapshot items）：在同一個
        session 裡執行 build_aggregation() + 逐 group 呼叫
        build_aggregated_summary() + 寫入 Report_Aggregation/_Item，
        全部成功才一次 commit、把 Report.status 設成 completed。
        任何一步拋出例外：db.session.rollback()（丟掉這個 session
        裡所有尚未 commit 的 Report_Aggregation/_Item），重新讀回
        Step 1 已經 commit 的 Report row，把它的 status 改成
        failed + error_detail，再 commit 這一個更新。
    這樣不可能出現「Report_Aggregation 只寫了一半、但 Report.status
    卻是 completed」的半成品，因為 completed 只會在 Step 2 全部
    add() 完、即將要 commit 的那一刻一起被設定、一起被 commit。
"""

from sqlalchemy.exc import IntegrityError

from extensions import db, taiwan_now
from models import Report, Report_Aggregation, Report_Aggregation_Item, Survey_Response
from classification_models import (
    REVIEW_STATUS_PENDING,
    REVIEW_STATUS_CONFIRMED,
    REVIEW_STATUS_MODIFIED,
    REVIEW_STATUS_EXCLUDED,
)
from report import (
    SOURCE_TYPE_SURVEY,
    SOURCE_TYPE_USER_UPLOAD,
    REPORT_STATUS_GENERATING,
    REPORT_STATUS_COMPLETED,
    REPORT_STATUS_FAILED,
)
from services.source_lookup_service import get_source_owner, fetch_classifications_in_scope
from services.aggregation_service import build_aggregation
from services.aggregated_summary_service import build_aggregated_summary
from services.effective_classification_service import (
    CLASSIFICATION_STATUS_FAILED,
    NON_COUNTABLE_STATUSES,
)

_MAX_VERSION_CLAIM_ATTEMPTS = 5


# ═══════════════════════════════════════════════════════════════
# Aggregation Readiness（原 services/aggregation_readiness_service.py，
# 2026-09 合併於此：只有本檔案的 get_readiness_for() / generate_report()
# 會呼叫，是報告產生流程的前置檢查，不再獨立成檔）
# ═══════════════════════════════════════════════════════════════
#
# 讓 User 在還沒 review 完 100% 的情況下，也能清楚看到「目前有多少筆
# 可以拿去產生報告」，並可以選擇「只用已確認結果產生」。後端本身不會
# 偷偷把 pending_review 加進 Aggregation——can_generate 只反映
# 「eligible > 0」，pending 存不存在完全不影響 eligible 的計算，前端
# 要不要在 has_pending=True 時跳警告是前端的事，這裡只負責給出正確的
# 數字。

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
    failed = 0
    auto_confirmed = 0
    for row in rows:
        # failed / superseded 不是成功的分類結果（見
        # effective_classification_service），即使 review_status 是
        # confirmed 也不能算進 eligible；另外回報 failed 數量。
        if row.review_status != REVIEW_STATUS_EXCLUDED and row.status in NON_COUNTABLE_STATUSES:
            if row.status == CLASSIFICATION_STATUS_FAILED:
                failed += 1
            continue
        # 理論上 review_status 只會是上面四個值之一（DB 層雖然沒有
        # CheckConstraint 強制，但所有寫入路徑都只會寫這四個值）；
        # 萬一出現意外值，不要讓整個 readiness 計算噴例外，計入
        # total 但不歸入任何一類，eligible/pending 都不會算到它，
        # 這樣的資料異常會反映成 total > 四類總和，方便事後排查。
        if row.review_status in counts:
            counts[row.review_status] += 1
            if row.review_status == REVIEW_STATUS_CONFIRMED and getattr(row, "auto_confirmed", False):
                auto_confirmed += 1

    confirmed = counts[REVIEW_STATUS_CONFIRMED]
    modified = counts[REVIEW_STATUS_MODIFIED]
    excluded = counts[REVIEW_STATUS_EXCLUDED]
    pending = counts[REVIEW_STATUS_PENDING]
    eligible = confirmed + modified

    return {
        "total": len(rows),
        "confirmed": confirmed,
        "auto_confirmed": auto_confirmed,  # confirmed 之中由系統自動通過的筆數
        "modified": modified,
        "excluded": excluded,
        "pending_review": pending,
        "eligible": eligible,
        "failed": failed,
        "has_pending": pending > 0,
        "can_generate": eligible > 0,
    }


# ═══════════════════════════════════════════════════════════════
# Report Outdated 判定（原 services/report_outdated_service.py，
# 2026-09 合併於此：報告生命週期判定，跟本檔案其他函式屬於同一個
# 職責範圍，不再獨立成檔）
# ═══════════════════════════════════════════════════════════════
#
# 唯一對外函式：mark_reports_outdated_for_classification()。
# services/review_service.py 在 confirm_original() / confirm_candidate() /
# exclude() 三個會真正影響「有效分類」的動作各自呼叫一次，是這個
# helper 唯一的呼叫時機——review conversation 過程中每一輪 AI candidate
# （尚未 confirm）不會呼叫，因為那些還沒有變成任何 Report 可能用到的
# 有效資料。
#
# 刻意不在這裡：
#     - 不觸發任何重新計算、不呼叫 Gemini。
#     - 不負責 Report 產生（那是本檔案 generate_report() 的職責，這裡
#       只負責把已存在、status='completed' 的舊 Report 標記為
#       is_outdated=True）。
#     - 不由任何 route 各自判斷「這個 classification 屬於哪個 Report
#       範圍」，統一走這裡，避免同一個規則散落在多個檔案裡各寫一次、
#       未來改規則要到處改。

# outdated_reason 常數（Admin Report 管理畫面依此顯示具體原因）
OUTDATED_CLASSIFICATION_CONFIRMED = "classification_confirmed"
OUTDATED_CLASSIFICATION_MODIFIED = "classification_modified"
OUTDATED_CLASSIFICATION_EXCLUDED = "classification_excluded"
OUTDATED_CLASSIFICATION_REOPENED = "classification_reopened"
OUTDATED_CLASSIFICATION_RERUN = "classification_rerun"
OUTDATED_BULK_REVIEW_ACTION = "bulk_review_action"
OUTDATED_TAXONOMY_PUBLISHED = "taxonomy_published"


def classification_source(classification):
    """回傳 classification 所屬的分析單位 (source_type, template_id, upload_batch_id)；
    查不到回傳 None。"""
    if classification.source_type == SOURCE_TYPE_SURVEY:
        survey_response = db.session.get(Survey_Response, classification.response_id)
        if survey_response is None:
            return None
        return (SOURCE_TYPE_SURVEY, survey_response.template_id, None)
    if classification.source_type == SOURCE_TYPE_USER_UPLOAD:
        return (SOURCE_TYPE_USER_UPLOAD, None, classification.upload_batch_id)
    return None


def mark_reports_outdated_for_sources(sources, reason) -> int:
    """把這些分析單位底下所有 status=completed 的 Report 標記為過期，並
    記錄最新的過期原因。已經過期的報告也會更新 outdated_reason（Admin
    看到的是「最近一次」讓它過期的事件）。只 add / 賦值，不 commit。

    Returns: 這次「新」被標記為 outdated 的 Report 筆數。
    """
    now = taiwan_now()
    newly = 0
    for source_type, template_id, upload_batch_id in set(s for s in sources if s):
        query = Report.query.filter_by(source_type=source_type, status=REPORT_STATUS_COMPLETED)
        if source_type == SOURCE_TYPE_SURVEY:
            query = query.filter_by(template_id=template_id)
        else:
            query = query.filter_by(upload_batch_id=upload_batch_id)
        for report in query.all():
            if not report.is_outdated:
                newly += 1
            report.is_outdated = True
            report.outdated_reason = reason
            report.outdated_at = now
            report.updated_at = now
    return newly


def mark_reports_outdated_for_classification(classification, reason=OUTDATED_CLASSIFICATION_MODIFIED) -> int:
    """
    Human Review 改變「有效分類」時呼叫（confirm / modify / exclude /
    reopen / rerun）。只 add / 賦值，不 commit——交給呼叫端跟 review_status
    的變更一起 commit，確保兩者在同一個 transaction 裡。
    """
    return mark_reports_outdated_for_sources([classification_source(classification)], reason)


def mark_reports_outdated_for_topic(topic_key, reason=OUTDATED_TAXONOMY_PUBLISHED) -> int:
    """Taxonomy publish：凡是納入過這個 Topic（任一版本）分類結果的分析
    單位，既有報告都標記為過期。"""
    from models import Response_Classification, Taxonomy_Version

    rows = (
        db.session.query(
            Response_Classification.source_type,
            Response_Classification.response_id,
            Response_Classification.upload_batch_id,
        )
        .join(Taxonomy_Version, Response_Classification.taxonomy_version_id == Taxonomy_Version.version_id)
        .filter(Taxonomy_Version.topic_key == topic_key)
        .distinct()
        .all()
    )
    response_ids = {r.response_id for r in rows if r.source_type == SOURCE_TYPE_SURVEY and r.response_id}
    template_ids = set()
    if response_ids:
        template_ids = {
            t for (t,) in db.session.query(Survey_Response.template_id)
            .filter(Survey_Response.response_id.in_(response_ids)).distinct().all()
        }
    sources = [(SOURCE_TYPE_SURVEY, t, None) for t in template_ids]
    sources += [
        (SOURCE_TYPE_USER_UPLOAD, None, r.upload_batch_id)
        for r in rows if r.source_type == SOURCE_TYPE_USER_UPLOAD and r.upload_batch_id
    ]
    return mark_reports_outdated_for_sources(sources, reason)


class ReportError(Exception):
    """業務邏輯錯誤，attrs: http_status, message, code。routes 層負責轉成 JSON response。"""

    def __init__(self, message, http_status=400, code=None):
        super().__init__(message)
        self.message = message
        self.http_status = http_status
        self.code = code or {403: "REPORT_FORBIDDEN", 404: "REPORT_NOT_FOUND", 409: "REPORT_CONFLICT"}.get(
            http_status, "REPORT_ERROR"
        )


def _check_ownership(source_type, template_id, upload_batch_id, auth_user_id):
    if source_type not in (SOURCE_TYPE_SURVEY, SOURCE_TYPE_USER_UPLOAD):
        raise ReportError("source_type 只能是 survey 或 user_upload", 400)

    owner_user_id = get_source_owner(source_type, template_id=template_id, upload_batch_id=upload_batch_id)
    if owner_user_id is None:
        raise ReportError("找不到這個分析單位，或這個分析單位沒有已知的 owner", 404)
    if owner_user_id != auth_user_id:
        raise ReportError("無權限存取這個分析單位的報告", 403)


def get_readiness_for(source_type, auth_user_id, template_id=None, upload_batch_id=None):
    _check_ownership(source_type, template_id, upload_batch_id, auth_user_id)
    return get_readiness(source_type, template_id=template_id, upload_batch_id=upload_batch_id)


def _claim_next_version(source_type, template_id, upload_batch_id, auth_user_id, readiness, admin_id=None):
    last_error = None
    for _ in range(_MAX_VERSION_CLAIM_ATTEMPTS):
        current_max = (
            db.session.query(db.func.max(Report.version))
            .filter_by(source_type=source_type, template_id=template_id, upload_batch_id=upload_batch_id)
            .scalar()
        ) or 0

        report = Report(
            source_type=source_type,
            template_id=template_id,
            upload_batch_id=upload_batch_id,
            version=current_max + 1,
            generated_by=auth_user_id,
            generated_by_admin_id=admin_id,
            updated_at=taiwan_now(),
            status=REPORT_STATUS_GENERATING,
            eligible_count_at_generation=readiness["eligible"],
            pending_count_at_generation=readiness["pending_review"],
            excluded_count_at_generation=readiness["excluded"],
        )
        db.session.add(report)
        try:
            db.session.commit()
            return report
        except IntegrityError as e:
            db.session.rollback()
            last_error = e
            continue

    raise ReportError(
        f"版本號建立衝突過於頻繁（已重試 {_MAX_VERSION_CLAIM_ATTEMPTS} 次），請稍後再試",
        409,
    ) from last_error


def generate_report(source_type, auth_user_id, template_id=None, upload_batch_id=None):
    """
    對外主要介面。成功時回傳 status=completed 的 Report；產生過程中
    任何一步失敗時，回傳 status=failed 的 Report（不會拋例外中斷，
    因為「產生失敗」本身是一個合法、呼叫端需要能拿到 report_id 去
    查詢細節的結果，不是純粹的例外狀況）。ownership/前置條件不符合
    （如完全沒有 eligible 資料）則拋出 ReportError，不會建立任何
    Report row。
    """
    _check_ownership(source_type, template_id, upload_batch_id, auth_user_id)
    return _generate(source_type, template_id, upload_batch_id, user_id=auth_user_id)


def _taxonomy_versions_in_scope(source_type, template_id, upload_batch_id):
    rows = fetch_classifications_in_scope(
        source_type=source_type, template_id=template_id, upload_batch_id=upload_batch_id,
        review_statuses=[REVIEW_STATUS_CONFIRMED, REVIEW_STATUS_MODIFIED],
        exclude_statuses=list(NON_COUNTABLE_STATUSES),
    )
    ids = sorted({str(r.taxonomy_version_id) for r in rows if r.taxonomy_version_id is not None}, key=int)
    if any(r.taxonomy_version_id is None for r in rows):
        ids.append("legacy")
    return ",".join(ids)[:255] or None


def _generate(source_type, template_id, upload_batch_id, user_id=None, admin_id=None):
    readiness = get_readiness(source_type, template_id=template_id, upload_batch_id=upload_batch_id)
    if not readiness["can_generate"]:
        raise ReportError(
            "目前沒有任何 eligible（confirmed + modified）資料，無法產生報告",
            400,
            code="REPORT_NOT_READY",
        )

    # Step 1：claim version，單獨 commit。
    report = _claim_next_version(source_type, template_id, upload_batch_id, user_id, readiness, admin_id=admin_id)

    # Step 2：aggregation + summary + snapshot items，全部成功才一起 commit。
    try:
        groups = build_aggregation(source_type, template_id=template_id, upload_batch_id=upload_batch_id)

        for group in groups:
            summary = build_aggregated_summary(group["main_category"], group["sub_category"], group["items"])

            agg_row = Report_Aggregation(
                report_id=report.report_id,
                main_category=group["main_category"],
                sub_category=group["sub_category"],
                response_count=group["response_count"],
                segment_count=group["segment_count"],
                aggregated_summary=summary,
                methodology=group["methodology"],
                citation=group["citation"],
            )
            db.session.add(agg_row)
            db.session.flush()  # 取得 aggregation_id，供下面 Item 的 FK 使用

            for item in group["items"]:
                item_row = Report_Aggregation_Item(
                    aggregation_id=agg_row.aggregation_id,
                    classification_id=item["classification_id"],
                    original_answer_text=item["original_answer_text"],
                    matched_segment_text=item["matched_segment_text"],
                    effective_reasoning=item["effective_reasoning"],
                    response_id=item["response_id"],
                    upload_batch_id=item["upload_batch_id"],
                    uploaded_answer_id=item["uploaded_answer_id"],
                )
                db.session.add(item_row)

        report.status = REPORT_STATUS_COMPLETED
        report.taxonomy_version_ids = _taxonomy_versions_in_scope(source_type, template_id, upload_batch_id)
        report.updated_at = taiwan_now()
        db.session.commit()
        return report

    except Exception as e:
        db.session.rollback()
        # rollback 後原本的 report 物件會被 expire，重新讀回同一筆
        # （Step 1 已經 commit 過，這裡一定查得到），只更新 status/error_detail。
        failed_report = Report.query.get(report.report_id)
        failed_report.status = REPORT_STATUS_FAILED
        failed_report.error_detail = str(e)[:500]
        failed_report.updated_at = taiwan_now()
        db.session.commit()
        return failed_report


def list_versions(source_type, auth_user_id, template_id=None, upload_batch_id=None):
    _check_ownership(source_type, template_id, upload_batch_id, auth_user_id)

    reports = (
        Report.query
        .filter_by(source_type=source_type, template_id=template_id, upload_batch_id=upload_batch_id)
        .order_by(Report.version.asc())
        .all()
    )
    return [r.to_dict() for r in reports]


def get_report_detail(report_id, auth_user_id):
    """
    完全只讀 Report / Report_Aggregation / Report_Aggregation_Item 的
    快照內容，絕對不會去查即時的 Response_Classification——這是
    「Report 是不可變 snapshot」這個核心要求的關鍵：即使原始分類
    資料之後被 Human Review 改變，這裡回傳的內容永遠是產生當下的
    樣子，只有 is_outdated 這個 flag 會變。
    """
    report = Report.query.get(report_id)
    if report is None:
        raise ReportError("找不到這份報告", 404)

    _check_ownership(report.source_type, report.template_id, report.upload_batch_id, auth_user_id)

    data = report.to_dict()
    data["aggregations"] = [agg.to_dict(include_items=True) for agg in report.aggregations]
    return data


# ═══════════════════════════════════════════════════════════════
# Admin Report 管理（不做 owner 檢查；Admin-only route 呼叫）
# ═══════════════════════════════════════════════════════════════

OUTDATED_REASON_LABELS = {
    OUTDATED_CLASSIFICATION_CONFIRMED: "有分類結果被人工確認",
    OUTDATED_CLASSIFICATION_MODIFIED: "有分類結果被人工修改",
    OUTDATED_CLASSIFICATION_EXCLUDED: "有分類結果被排除",
    OUTDATED_CLASSIFICATION_REOPENED: "有分類結果被重新開啟審核",
    OUTDATED_CLASSIFICATION_RERUN: "有回答被重新分類",
    OUTDATED_BULK_REVIEW_ACTION: "批次審核操作",
    OUTDATED_TAXONOMY_PUBLISHED: "Taxonomy 發布新版本",
}


def _admin_units():
    """所有有分類結果或報告的分析單位。"""
    from models import Response_Classification, Survey_Template

    units = {}
    survey_rows = (
        db.session.query(Survey_Response.template_id, db.func.count(Response_Classification.classification_id))
        .join(Response_Classification, Response_Classification.response_id == Survey_Response.response_id)
        .group_by(Survey_Response.template_id).all()
    )
    for template_id, count in survey_rows:
        units[(SOURCE_TYPE_SURVEY, template_id, None)] = count
    upload_rows = (
        db.session.query(Response_Classification.upload_batch_id, db.func.count(Response_Classification.classification_id))
        .filter(Response_Classification.source_type == SOURCE_TYPE_USER_UPLOAD)
        .group_by(Response_Classification.upload_batch_id).all()
    )
    for batch_id, count in upload_rows:
        units[(SOURCE_TYPE_USER_UPLOAD, None, batch_id)] = count
    for r in db.session.query(Report.source_type, Report.template_id, Report.upload_batch_id).distinct().all():
        units.setdefault((r.source_type, r.template_id, r.upload_batch_id), 0)
    return units


def _unit_label(source_type, template_id, upload_batch_id):
    from models import Survey_Template, Uploaded_Answer

    if source_type == SOURCE_TYPE_SURVEY:
        template = db.session.get(Survey_Template, template_id)
        return template.title if template else f"問卷 #{template_id}"
    answer = Uploaded_Answer.query.filter_by(upload_batch_id=upload_batch_id).order_by(Uploaded_Answer.id.asc()).first()
    if answer is None:
        return f"上傳批次 {upload_batch_id}"
    created = answer.created_at.strftime("%Y-%m-%d %H:%M") if answer.created_at else ""
    return f"上傳：{answer.source_column}（{created}）"


def _report_lifecycle(source_type, template_id, upload_batch_id):
    from services.failure_explainer import explain_failure

    reports = (
        Report.query.filter_by(source_type=source_type, template_id=template_id, upload_batch_id=upload_batch_id)
        .order_by(Report.version.desc()).all()
    )
    latest = reports[0] if reports else None
    latest_completed = next((r for r in reports if r.status == REPORT_STATUS_COMPLETED), None)
    readiness = get_readiness(source_type, template_id=template_id, upload_batch_id=upload_batch_id)

    if latest_completed is None:
        needs, why = readiness["can_generate"], "no_completed_report"
    elif latest_completed.is_outdated:
        needs, why = True, latest_completed.outdated_reason or "outdated"
    else:
        needs, why = False, None
    if latest is not None and latest.status == REPORT_STATUS_FAILED:
        needs, why = readiness["can_generate"], "last_generation_failed"

    return {
        "source_type": source_type,
        "template_id": template_id,
        "upload_batch_id": upload_batch_id,
        "identifier": str(template_id) if source_type == SOURCE_TYPE_SURVEY else upload_batch_id,
        "label": _unit_label(source_type, template_id, upload_batch_id),
        "readiness": readiness,
        "latest_report": latest.to_dict() if latest else None,
        "latest_failure": explain_failure(latest.error_detail) if latest is not None and latest.status == REPORT_STATUS_FAILED else None,
        "latest_completed_report": latest_completed.to_dict() if latest_completed else None,
        "needs_regeneration": bool(needs),
        "regeneration_reason": why,
        "regeneration_reason_label": OUTDATED_REASON_LABELS.get(why) if why else None,
        "report_count": len(reports),
    }


def admin_list_report_units(page=1, page_size=20, only_needs_regeneration=False):
    page = max(int(page or 1), 1)
    page_size = min(max(int(page_size or 20), 1), 100)
    keys = sorted(
        _admin_units().keys(),
        key=lambda k: (k[0], -(k[1] or 0), k[2] or ""),
    )
    if only_needs_regeneration:
        items = [x for x in (_report_lifecycle(*k) for k in keys) if x["needs_regeneration"]]
        total = len(items)
        items = items[(page - 1) * page_size: page * page_size]
    else:
        total = len(keys)
        items = [_report_lifecycle(*k) for k in keys[(page - 1) * page_size: page * page_size]]
    return {"items": items, "page": page, "page_size": page_size, "total": total}


def admin_unit_detail(source_type, template_id=None, upload_batch_id=None):
    data = _report_lifecycle(source_type, template_id, upload_batch_id)
    data["versions"] = [
        r.to_dict() for r in Report.query.filter_by(
            source_type=source_type, template_id=template_id, upload_batch_id=upload_batch_id,
        ).order_by(Report.version.desc()).all()
    ]
    return data


def admin_generate_report(source_type, admin_id, template_id=None, upload_batch_id=None):
    from services import audit_service

    if source_type not in (SOURCE_TYPE_SURVEY, SOURCE_TYPE_USER_UPLOAD):
        raise ReportError("source_type 只能是 survey 或 user_upload", 400, code="INVALID_SOURCE_TYPE")
    if (source_type, template_id, upload_batch_id) not in _admin_units():
        raise ReportError("找不到這個分析單位", 404, code="REPORT_SOURCE_NOT_FOUND")

    previous = (
        Report.query.filter_by(source_type=source_type, template_id=template_id, upload_batch_id=upload_batch_id)
        .order_by(Report.version.desc()).first()
    )
    report = _generate(source_type, template_id, upload_batch_id, admin_id=admin_id)
    audit_service.record(
        audit_service.ACTION_REPORT_REGENERATE, audit_service.ENTITY_REPORT, report.report_id, admin_id,
        before=None if previous is None else {
            "report_id": previous.report_id, "version": previous.version,
            "is_outdated": previous.is_outdated, "outdated_reason": previous.outdated_reason,
        },
        after={"report_id": report.report_id, "version": report.version, "status": report.status,
               "error_detail": report.error_detail},
    )
    db.session.commit()
    return report


def admin_report_detail(report_id):
    report = db.session.get(Report, report_id)
    if report is None:
        raise ReportError("找不到這份報告", 404)
    data = report.to_dict()
    data["label"] = _unit_label(report.source_type, report.template_id, report.upload_batch_id)
    data["aggregations"] = [agg.to_dict(include_items=True) for agg in report.aggregations]
    return data


def report_export_rows(report):
    """把 Report 快照轉成 export_file_service 的 rows 格式（只讀快照，
    不查即時分類，確保匯出內容 = 該版本報告內容）。"""
    rows = []
    for agg in sorted(report.aggregations, key=lambda a: (a.main_category, a.sub_category)):
        rows.append({
            "main_category": agg.main_category,
            "sub_category": agg.sub_category,
            "respondent_text": "\n".join(item.matched_segment_text for item in agg.items),
            "aggregated_reasoning": "\n".join(
                item.effective_reasoning for item in agg.items if item.effective_reasoning
            ),
            "aggregated_summary": agg.aggregated_summary or "",
        })
    return rows


def admin_export_report(report_id, fmt):
    from services.export_file_service import build_docx, build_xlsx

    report = db.session.get(Report, report_id)
    if report is None:
        raise ReportError("找不到這份報告", 404)
    if report.status != REPORT_STATUS_COMPLETED:
        raise ReportError("只有產生完成的報告可以匯出", 409, code="REPORT_NOT_COMPLETED")
    if fmt not in ("xlsx", "docx"):
        raise ReportError("format 只能是 xlsx 或 docx", 400, code="INVALID_FORMAT")
    title = f"{_unit_label(report.source_type, report.template_id, report.upload_batch_id)} v{report.version}"
    rows = report_export_rows(report)
    # Excel sheet 名稱不允許 []:*?/\，也不可超過 31 字元
    import re
    sheet_title = re.sub(r"[\[\]:*?/\\：]", " ", title).strip()[:31] or "報告"
    data = build_xlsx(rows, title=sheet_title) if fmt == "xlsx" else build_docx(rows, title=title)
    return data, title
