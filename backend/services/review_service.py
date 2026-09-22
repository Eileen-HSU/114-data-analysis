"""

Human Review 業務邏輯層。routes/classifications/review.py 只負責解析
request/組 HTTP response，實際的 conversation 讀寫、confirm/exclude
規則、併發控制全部在這裡，不分散到 route 裡各寫一份。

【Admin-only 定案】Human Review 是 Admin 專用功能，不是 User 功能，
不保留雙軌：
    - 沒有任何 ownership 概念——Admin 可以 review 任一筆
      Response_Classification，不檢查 Survey_Template.user_id /
      Uploaded_Answer.user_id。
    - Classification_Review.admin_id 取代原本的 user_id，紀錄「這個
      review session 是哪個 Admin 開的」。
    - 對外函式一律接收 admin_id（來自 verify_admin_token()），不是
      auth_user_id。

【taxonomy 來源】question_type（leadership_and_dept / career_and_feedback）
不是 Response_Classification 自己的欄位，要分來源推導：
    survey     ：response_id -> Survey_Response.template_id ->
                 Survey_Template.question_json 裡對應 question_id 那個
                 item 的 question_type
    user_upload：uploaded_answer_id -> Uploaded_Answer.question_type

【併發控制】同一個 classification_id 同時間只能有一筆
status="in_progress" 的 Classification_Review。MySQL 不支援
partial unique index（WHERE status='in_progress'），所以不靠 DB
constraint 表達這個限制，改成 start_review() 用
`SELECT ... FOR UPDATE` 鎖住對應的 Response_Classification row 當
mutex：同一筆 classification_id 的多個併發 start_review 請求會被
序列化（後到的會等前一個交易 commit/rollback 才能繼續），鎖到之後
才查詢「目前是否已有 in_progress」，就不會有兩個交易同時看到「還沒有
in_progress」而各自建立一筆的競速問題。
"""

from extensions import db, taiwan_now
from models import (
    Admin,
    Response_Classification,
    Classification_Review,
    Classification_Review_Message,
)
from classification_models import (
    REVIEW_STATUS_PENDING,
    REVIEW_STATUS_CONFIRMED,
    REVIEW_STATUS_MODIFIED,
    REVIEW_STATUS_EXCLUDED,
)
from services.review_ai_service import build_review_reply
from services.report_service import mark_reports_outdated_for_classification
from services.source_lookup_service import resolve_question_type


class ReviewError(Exception):
    """業務邏輯錯誤，attrs: http_status, message, extra。routes 層負責
    轉成 JSON response，extra 裡的欄位（例如 409 衝突時的
    reviewing_admin_id/reviewing_admin_name）會一起攤平進 response body。
    """

    def __init__(self, message: str, http_status: int = 400, extra: dict | None = None):
        super().__init__(message)
        self.message = message
        self.http_status = http_status
        self.extra = extra or {}


_LOCKED_REVIEW_STATUSES = (REVIEW_STATUS_CONFIRMED, REVIEW_STATUS_MODIFIED, REVIEW_STATUS_EXCLUDED)


def _resolve_question_type(classification):
    return resolve_question_type(classification)


def _admin_display_name(admin_id):
    """查 Admin.admin_name 當顯示名稱；查不到（理論上不該發生，
    Admin 被刪除但 review row 還在）就回 None，呼叫端會處理成
    「查不到名字但仍帶 id」。"""
    admin = db.session.get(Admin, admin_id)
    return admin.admin_name if admin else None


def _load_classification(classification_id):
    """共用的「取出 classification，不存在就 404」；Admin-only 模型
    下沒有 ownership 檢查，任一筆都可以 review。"""
    classification = Response_Classification.query.get(classification_id)
    if classification is None:
        raise ReviewError("找不到這筆分類結果", 404)
    return classification


def _get_active_review(classification_id):
    """取這筆 classification 目前進行中的 review session
    （status='in_progress'），不依 admin_id 過濾——同一時間本來就只
    應該存在最多一筆，理論上 .first() 跟 .one_or_none() 等價，這裡用
    .first() 是為了在資料異常（例如手動改過 DB）時不會直接炸掉
    整支 API，而是取最新一筆繼續運作。"""
    return (
        Classification_Review.query
        .filter_by(classification_id=classification_id, status="in_progress")
        .order_by(Classification_Review.created_at.desc())
        .first()
    )


def _require_no_conflicting_reviewer(classification_id, admin_id):
    """message／confirm-candidate／confirm-original／exclude 共用的
    檢查：如果目前有其他 Admin 持有這筆的 in_progress session，一律
    擋下（409），不能讓第三方繞過 start_review 的併發檢查直接操作
    別人正在審核中的 session。回傳目前的 active review（可能是
    None、或屬於呼叫者自己的那一筆），呼叫端不需要再另外查一次。
    """
    active_review = _get_active_review(classification_id)
    if active_review is not None and active_review.admin_id != admin_id:
        raise ReviewError(
            "這筆分類目前正由其他管理員審核中",
            409,
            extra={
                "reviewing_admin_id": active_review.admin_id,
                "reviewing_admin_name": _admin_display_name(active_review.admin_id),
            },
        )
    return active_review


def _has_ever_entered_conversation(classification_id):
    """
    是否曾經有任何一輪訊息進過這個 classification 的 review
    conversation（不限哪個 review session、不限哪個 Admin——一旦有人
    跟這筆分類討論過，就不再算「從未進入」）。
    """
    review_ids = [
        r.review_id for r in
        Classification_Review.query.filter_by(classification_id=classification_id).all()
    ]
    if not review_ids:
        return False
    return (
        Classification_Review_Message.query
        .filter(Classification_Review_Message.review_id.in_(review_ids))
        .filter_by(role="user")
        .count()
        > 0
    )


def _segment_text(classification):
    return classification.answer_text[classification.segment_start:classification.segment_end]


# ── 對外主要介面 ──────────────────────────────────────────────

def get_review_state(classification_id, admin_id):
    """需求文件 API 第 1 點：AI original + 目前 review 狀態。任一
    Admin 都可以查看，不因為別人正在審核就擋掉（前端需要顯示「目前由
    誰審核中」，必須讀得到這個狀態）。"""
    classification = _load_classification(classification_id)
    active_review = _get_active_review(classification_id)
    return {
        "classification": classification.to_dict(),
        "active_review": active_review.to_dict() if active_review else None,
    }


def start_review(classification_id, admin_id):
    """需求文件 API 第 2 點：開始/取得 conversation。

    併發控制流程：
      1. SELECT ... FOR UPDATE 鎖住這筆 Response_Classification row
         （同一 classification_id 的並行請求會在這裡被序列化）。
      2. 鎖到之後才查詢是否已有 in_progress 的 review。
      3a. 沒有 -> 建立一筆 admin_id=目前這個 Admin 的新 review。
      3b. 有，且是同一個 Admin -> 冪等回傳那一筆（重新整理頁面、
          重複點擊都安全）。
      3c. 有，且是別的 Admin -> 409，告知目前是誰在審核。
    """
    classification = (
        Response_Classification.query
        .filter_by(classification_id=classification_id)
        .with_for_update()
        .first()
    )
    if classification is None:
        raise ReviewError("找不到這筆分類結果", 404)

    if classification.review_status in _LOCKED_REVIEW_STATUSES:
        raise ReviewError("這筆分類已經確認或排除，無法再開始新的 review", 409)

    existing = _get_active_review(classification_id)
    if existing is not None:
        if existing.admin_id == admin_id:
            return existing
        raise ReviewError(
            "這筆分類目前正由其他管理員審核中",
            409,
            extra={
                "reviewing_admin_id": existing.admin_id,
                "reviewing_admin_name": _admin_display_name(existing.admin_id),
            },
        )

    review = Classification_Review(
        classification_id=classification_id, admin_id=admin_id, status="in_progress",
    )
    db.session.add(review)
    db.session.commit()
    return review


def send_message(classification_id, admin_id, message_text):
    """需求文件 API 第 3 點：Admin 傳送 Review message。"""
    if not message_text or not message_text.strip():
        raise ReviewError("訊息內容不可為空", 400)

    classification = _load_classification(classification_id)

    review = _require_no_conflicting_reviewer(classification_id, admin_id)
    if review is None:
        raise ReviewError("尚未開始 review conversation，請先呼叫 start", 400)

    question_type = _resolve_question_type(classification)
    if question_type is None:
        raise ReviewError("這筆分類找不到對應的題目分類架構（question_type），無法進行 review", 422)

    # 目前候選：取這個 session 裡最新一則、有實際提出 candidate 的
    # assistant 訊息；沒有的話 fallback 成 AI original，讓 Gemini
    # 知道「目前候選」的起點是什麼。
    latest_candidate_msg = (
        Classification_Review_Message.query
        .filter_by(review_id=review.review_id, role="assistant")
        .filter(Classification_Review_Message.candidate_sub_category.isnot(None))
        .order_by(Classification_Review_Message.created_at.desc())
        .first()
    )
    candidate_sub = latest_candidate_msg.candidate_sub_category if latest_candidate_msg else classification.sub_category
    candidate_secondary_sub = (
        latest_candidate_msg.candidate_secondary_sub_category if latest_candidate_msg
        else classification.secondary_sub_category
    )

    history = [
        {"role": m.role, "content": m.content}
        for m in Classification_Review_Message.query
            .filter_by(review_id=review.review_id)
            .order_by(Classification_Review_Message.created_at.asc())
            .all()
    ]

    user_msg = Classification_Review_Message(
        review_id=review.review_id, role="user", content=message_text,
    )
    db.session.add(user_msg)

    ai_result = build_review_reply(
        question_type=question_type,
        segment_text=_segment_text(classification),
        ai_main_category=classification.main_category,
        ai_sub_category=classification.sub_category,
        ai_secondary_sub_category=classification.secondary_sub_category,
        ai_reasoning=classification.reasoning,
        candidate_sub_category=candidate_sub,
        candidate_secondary_sub_category=candidate_secondary_sub,
        conversation_history=history,
        user_message=message_text,
    )

    assistant_msg = Classification_Review_Message(
        review_id=review.review_id,
        role="assistant",
        content=ai_result["reply"],
        candidate_main_category=ai_result["candidate_main_category"],
        candidate_sub_category=ai_result["candidate_sub_category"],
        candidate_secondary_main_category=ai_result["candidate_secondary_main_category"],
        candidate_secondary_sub_category=ai_result["candidate_secondary_sub_category"],
        candidate_reasoning=ai_result["candidate_reasoning"],
    )
    db.session.add(assistant_msg)
    db.session.commit()

    return {
        "message": assistant_msg.to_dict(),
        "taxonomy_rejected": ai_result["taxonomy_rejected"],
    }


def confirm_original(classification_id, admin_id):
    """需求文件 API 第 4 點。只有從未進入 Review Conversation 才允許：
    review_status -> confirmed，不寫入任何 final_* 欄位（effective
    分類直接讀 AI original）。"""
    classification = _load_classification(classification_id)

    if classification.review_status in _LOCKED_REVIEW_STATUSES:
        raise ReviewError("這筆分類已經確認或排除過了", 409)

    _require_no_conflicting_reviewer(classification_id, admin_id)

    if _has_ever_entered_conversation(classification_id):
        raise ReviewError(
            "這筆分類已經進入過 review conversation，請用 confirm-candidate 確認，"
            "不能再用 confirm-original",
            409,
        )

    classification.review_status = REVIEW_STATUS_CONFIRMED
    mark_reports_outdated_for_classification(classification)
    db.session.commit()
    return classification


def confirm_candidate(classification_id, admin_id):
    """需求文件 API 第 5 點。曾經進入過 Review Conversation 才允許：
    寫入 final_*，review_status -> modified（即使最終候選跟 AI
    original 完全相同也一樣，因為「Admin 曾提出異議」本身就是重要
    feedback data）。"""
    classification = _load_classification(classification_id)

    if classification.review_status in _LOCKED_REVIEW_STATUSES:
        raise ReviewError("這筆分類已經確認或排除過了", 409)

    if not _has_ever_entered_conversation(classification_id):
        raise ReviewError(
            "這筆分類還沒有進入過 review conversation，請用 confirm-original 確認，"
            "不能用 confirm-candidate",
            409,
        )

    review = _require_no_conflicting_reviewer(classification_id, admin_id)
    if review is None:
        raise ReviewError("找不到進行中的 review session", 404)

    latest_candidate_msg = (
        Classification_Review_Message.query
        .filter_by(review_id=review.review_id, role="assistant")
        .filter(Classification_Review_Message.candidate_sub_category.isnot(None))
        .order_by(Classification_Review_Message.created_at.desc())
        .first()
    )

    if latest_candidate_msg is not None:
        final_main = latest_candidate_msg.candidate_main_category
        final_sub = latest_candidate_msg.candidate_sub_category
        final_secondary_main = latest_candidate_msg.candidate_secondary_main_category
        final_secondary_sub = latest_candidate_msg.candidate_secondary_sub_category
        final_reasoning = latest_candidate_msg.candidate_reasoning
    else:
        # 對話發生過，但 AI 從未正式提出候選變更（例如 Admin 問了問題，
        # AI 只回答說明、始終認為 AI original 才是對的）：final 直接
        # 沿用 AI original 的值，review_status 仍然是 modified
        # ——「Admin 曾提出異議」本身就是 feedback，不代表最終結果
        # 一定要不一樣。
        final_main = classification.main_category
        final_sub = classification.sub_category
        final_secondary_main = classification.secondary_main_category
        final_secondary_sub = classification.secondary_sub_category
        final_reasoning = classification.reasoning

    # Primary == Secondary 正規化（跟 classify_v2 / review_ai_service 一致）
    if final_sub is not None and final_sub == final_secondary_sub:
        final_secondary_main = None
        final_secondary_sub = None

    classification.final_main_category = final_main
    classification.final_sub_category = final_sub
    classification.final_secondary_main_category = final_secondary_main
    classification.final_secondary_sub_category = final_secondary_sub
    classification.final_reasoning = final_reasoning
    classification.review_status = REVIEW_STATUS_MODIFIED

    review.status = "confirmed"
    review.confirmed_at = taiwan_now()

    mark_reports_outdated_for_classification(classification)
    db.session.commit()
    return classification


def exclude(classification_id, admin_id):
    """需求文件 API 第 6 點：Admin 決定這個 segment 不納入後續分析。"""
    classification = _load_classification(classification_id)

    if classification.review_status in _LOCKED_REVIEW_STATUSES:
        raise ReviewError("這筆分類已經確認或排除過了", 409)

    active_review = _require_no_conflicting_reviewer(classification_id, admin_id)

    classification.review_status = REVIEW_STATUS_EXCLUDED

    if active_review is not None:
        active_review.status = "excluded"

    mark_reports_outdated_for_classification(classification)
    db.session.commit()
    return classification


def exclude_legacy_pending_classifications(admin_id) -> int:
    """
    批次「排除舊版資料」（Human Review 新增功能）：一次性把符合下列
    全部條件的 Response_Classification 從 pending_review 標記為
    excluded，讓它們不再納入目前分析，但不刪除任何資料、也不修改
    review_status 以外的任何欄位：

        taxonomy_version_id IS NULL      （Phase B 之前的舊資料，
                                            沒有對應 Published
                                            Taxonomy 版本）
        AND confidence IS NULL           （沒有信心分數，本來就無法
                                            套用 Confidence Gate 判斷，
                                            也不可能有 needs_human_review
                                            以外的正常分析路徑會用到）
        AND review_status = 'pending_review'（還沒被人工確認/排除過；
                                            confirmed/modified/excluded
                                            已經是定案狀態，不動）

    跟單筆 exclude() 的刻意差異：
        - 不呼叫 mark_reports_outdated_for_classification()：
          aggregation/report/export 不在這次功能範圍內，且這批本來
          就是「沒有 taxonomy_version_id、沒有 confidence」的舊資料，
          不會被現有 Confidence Gate / Phase B 分析路徑實際採用，
          這裡刻意不去動 Report 相關狀態。
        - 不檢查是否有 in_progress 的 Classification_Review session：
          「舊版資料」的定義完全由上面三個條件決定，不额外收斂範圍；
          這批資料本身也還沒有需求要支援針對它們開 review conversation。
        - main_category / sub_category / reasoning / confidence /
          taxonomy_version_id 等其餘欄位原樣保留，只改 review_status。

    Args:
        admin_id: 觸發這次批次操作的 Admin（跟其他 review_service
            對外函式簽章一致，保留給未來加操作紀錄用；
            Response_Classification 本身沒有「誰排除的」欄位，
            目前沒有實際寫入任何地方，跟單筆 exclude() 的既有行為
            一致）。

    Returns:
        實際被更新（pending_review -> excluded）的筆數。
    """
    matched_rows = (
        Response_Classification.query
        .filter(
            Response_Classification.confidence.is_(None),
            Response_Classification.review_status == REVIEW_STATUS_PENDING,
        )
        .all()
    )

    for row in matched_rows:
        row.review_status = REVIEW_STATUS_EXCLUDED

    db.session.commit()
    return len(matched_rows)


def get_history(classification_id, admin_id):
    """需求文件 API 第 7 點：取得這筆 classification 的全部 review
    session 歷史，不依登入 Admin 過濾——稽核情境下要看到「這筆被哪些
    Admin 審過」的完整紀錄，不是只看自己的。admin_id 參數保留是為了
    跟其他對外函式簽章一致（未來若要加操作紀錄/權限分級，這裡已經
    有掛載點），目前查詢本身不使用它。
    """
    _load_classification(classification_id)

    reviews = (
        Classification_Review.query
        .filter_by(classification_id=classification_id)
        .order_by(Classification_Review.created_at.asc())
        .all()
    )
    result = []
    for r in reviews:
        data = r.to_dict(include_messages=True)
        data["admin_name"] = _admin_display_name(r.admin_id)
        result.append(data)
    return result

def exclude_legacy_pending_classifications(admin_id) -> int:
    """批次「排除舊版資料」：把符合以下全部條件的 Response_Classification
    從 pending_review 標記為 excluded，不刪除資料、不改其他欄位。

        confidence IS NULL
        AND review_status = 'pending_review'
    """
    from classification_models import REVIEW_STATUS_PENDING, REVIEW_STATUS_EXCLUDED

    matched_rows = (
        Response_Classification.query
        .filter(
            Response_Classification.taxonomy_version_id.is_(None),
            Response_Classification.confidence.is_(None),
            Response_Classification.review_status == REVIEW_STATUS_PENDING,
        )
        .all()
    )

    for row in matched_rows:
        row.review_status = REVIEW_STATUS_EXCLUDED

    db.session.commit()
    return len(matched_rows)
