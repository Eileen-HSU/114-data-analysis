"""

Report Outdated 判定的唯一集中入口。

只有一個對外函式：mark_reports_outdated_for_classification()。
services/review_service.py 在 confirm_original() / confirm_candidate() /
exclude() 三個會真正影響「有效分類」的動作各自呼叫一次，是這個
helper 唯一的呼叫時機——review conversation 過程中每一輪 AI candidate
（尚未 confirm）不會呼叫，因為那些還沒有變成任何 Report 可能用到的
有效資料。

刻意不在這裡：
    - 不觸發任何重新計算、不呼叫 Gemini。
    - 不負責 Report 產生（那是 Phase 5 services/report_service.py 的
      職責，這裡只負責把已存在、status='completed' 的舊 Report
      標記為 is_outdated=True）。
    - 不由任何 route 各自判斷「這個 classification 屬於哪個 Report
      範圍」，統一走這裡，避免同一個規則散落在多個檔案裡各寫一次、
      未來改規則要到處改。
"""

from models import Report, Survey_Response
from report import REPORT_STATUS_COMPLETED, SOURCE_TYPE_SURVEY, SOURCE_TYPE_USER_UPLOAD


def mark_reports_outdated_for_classification(classification) -> int:
    """
    Args:
        classification: 已經 review_status 剛變成
            confirmed/modified/excluded 的 Response_Classification
            實例（呼叫端負責先完成那個變更，這裡只讀取它的
            source_type/response_id/upload_batch_id 來判斷影響範圍，
            不會再去改 classification 本身的任何欄位）。

    Returns:
        實際被標記為 outdated 的 Report 筆數（供呼叫端寫 log/測試用，
        不影響行為）。

    只負責 db.session.add()/屬性賦值，不呼叫 commit()，交給呼叫端
    （services/review_service.py）跟其他變更一起統一 commit，確保
    review_status 的變更跟 outdated 標記在同一個 transaction 裡。
    """
    if classification.source_type == SOURCE_TYPE_SURVEY:
        survey_response = Survey_Response.query.get(classification.response_id)
        if survey_response is None:
            return 0
        matching_reports = Report.query.filter_by(
            source_type=SOURCE_TYPE_SURVEY,
            template_id=survey_response.template_id,
            status=REPORT_STATUS_COMPLETED,
            is_outdated=False,
        ).all()
    elif classification.source_type == SOURCE_TYPE_USER_UPLOAD:
        matching_reports = Report.query.filter_by(
            source_type=SOURCE_TYPE_USER_UPLOAD,
            upload_batch_id=classification.upload_batch_id,
            status=REPORT_STATUS_COMPLETED,
            is_outdated=False,
        ).all()
    else:
        return 0

    for report in matching_reports:
        report.is_outdated = True

    return len(matching_reports)
