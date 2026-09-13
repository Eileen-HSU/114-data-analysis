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

from extensions import db
from models import Report, Report_Aggregation, Report_Aggregation_Item
from report import (
    SOURCE_TYPE_SURVEY,
    SOURCE_TYPE_USER_UPLOAD,
    REPORT_STATUS_GENERATING,
    REPORT_STATUS_COMPLETED,
    REPORT_STATUS_FAILED,
)
from services.source_lookup_service import get_source_owner
from services.aggregation_readiness_service import get_readiness
from services.aggregation_service import build_aggregation
from services.aggregated_summary_service import build_aggregated_summary

_MAX_VERSION_CLAIM_ATTEMPTS = 5


class ReportError(Exception):
    """業務邏輯錯誤，attrs: http_status, message。routes 層負責轉成 JSON response。"""

    def __init__(self, message, http_status=400):
        super().__init__(message)
        self.message = message
        self.http_status = http_status


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


def _claim_next_version(source_type, template_id, upload_batch_id, auth_user_id, readiness):
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

    readiness = get_readiness(source_type, template_id=template_id, upload_batch_id=upload_batch_id)
    if not readiness["can_generate"]:
        raise ReportError(
            "目前沒有任何 eligible（confirmed + modified）資料，無法產生報告",
            400,
        )

    # Step 1：claim version，單獨 commit。
    report = _claim_next_version(source_type, template_id, upload_batch_id, auth_user_id, readiness)

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
        db.session.commit()
        return report

    except Exception as e:
        db.session.rollback()
        # rollback 後原本的 report 物件會被 expire，重新讀回同一筆
        # （Step 1 已經 commit 過，這裡一定查得到），只更新 status/error_detail。
        failed_report = Report.query.get(report.report_id)
        failed_report.status = REPORT_STATUS_FAILED
        failed_report.error_detail = str(e)[:500]
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
