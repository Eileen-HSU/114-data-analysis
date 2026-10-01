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
    Taxonomy_Version,
)
from classification_models import (
    REVIEW_STATUS_PENDING,
    REVIEW_STATUS_CONFIRMED,
    REVIEW_STATUS_MODIFIED,
    REVIEW_STATUS_EXCLUDED,
)
from services.review_ai_service import build_review_reply
from services import audit_service
from services.effective_classification_service import is_failed
from services.secondary_classification_service import get_secondaries, legacy_fields, set_final_secondaries

from services.report_service import (
    OUTDATED_BULK_REVIEW_ACTION,
    OUTDATED_CLASSIFICATION_CONFIRMED,
    OUTDATED_CLASSIFICATION_EXCLUDED,
    OUTDATED_CLASSIFICATION_MODIFIED,
    OUTDATED_CLASSIFICATION_REOPENED,
    classification_source,
    mark_reports_outdated_for_classification,
    mark_reports_outdated_for_sources,
)
from services.source_lookup_service import resolve_question_type, source_question_label


class ReviewError(Exception):
    """業務邏輯錯誤，attrs: http_status, message, code, extra。routes 層負責
    轉成 JSON response（machine-readable `code` + user-readable `message`），
    extra 裡的欄位（例如 409 衝突時的 reviewing_admin_id/reviewing_admin_name）
    會一起攤平進 response body。
    """

    def __init__(self, message: str, http_status: int = 400, extra: dict | None = None, code: str | None = None):
        super().__init__(message)
        self.message = message
        self.http_status = http_status
        self.extra = extra or {}
        self.code = code or _DEFAULT_CODES.get(http_status, "REVIEW_ERROR")


_DEFAULT_CODES = {400: "BAD_REQUEST", 404: "CLASSIFICATION_NOT_FOUND", 409: "REVIEW_CONFLICT", 422: "UNPROCESSABLE"}

# Classification_Review.status
REVIEW_SESSION_IN_PROGRESS = "in_progress"
REVIEW_SESSION_CONFIRMED = "confirmed"
REVIEW_SESSION_EXCLUDED = "excluded"
REVIEW_SESSION_CLOSED = "closed"


_LOCKED_REVIEW_STATUSES = (REVIEW_STATUS_CONFIRMED, REVIEW_STATUS_MODIFIED, REVIEW_STATUS_EXCLUDED)


def _resolve_question_type(classification):
    return resolve_question_type(classification)


def _admin_display_name(admin_id):
    """查 Admin.admin_name 當顯示名稱；查不到（理論上不該發生，
    Admin 被刪除但 review row 還在）就回 None，呼叫端會處理成
    「查不到名字但仍帶 id」。"""
    admin = db.session.get(Admin, admin_id)
    return admin.admin_name if admin else None


def _first_ai_secondary(classification) -> dict:
    """第一個「在分類架構裡」的 AI 次要分類（secondary_main_category /
    secondary_sub_category / ...），來源是 Response_Classification_Secondary。"""
    return legacy_fields(get_secondaries(classification))


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
        raise _conflict_error(active_review)
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


def _has_entered_current_conversation(review_id):
    return (
        Classification_Review_Message.query
        .filter_by(review_id=review_id, role="user")
        .count()
        > 0
    )


def _taxonomy_categories(classification):
    """這筆 classification 可以選的分類清單（Human Review 對話與人工直接
    指定分類共用）。

    - 有 taxonomy_version_id：該版 Taxonomy_Category（不是目前 published
      版，確保跟當初分類用的是同一份清單）。
    - legacy（taxonomy_version_id IS NULL）：依 question_type 取 legacy
      SUBCATEGORY_METHODOLOGY 表——原本這裡回傳空清單，導致 AI 對話永遠
      提不出任何合法候選（每個建議都被當成「不在清單內」拒絕）。
    - 版本已被刪除：退回這筆原本的 AI 分類，至少不會是空清單。
    """
    if classification.taxonomy_version_id is None:
        from services.subcategory_methodology import SUBCATEGORY_METHODOLOGY
        question_type = _resolve_question_type(classification)
        table = SUBCATEGORY_METHODOLOGY.get(question_type) or {}
        return [
            {
                "main_category": info["main_category"],
                "sub_category": sub,
                "methodology": info.get("methodology"),
                "citation": info.get("citation"),
            }
            for sub, info in table.items()
        ]
    version = db.session.get(Taxonomy_Version, classification.taxonomy_version_id)
    if version is None:
        return [
            {
                "main_category": classification.main_category,
                "sub_category": classification.sub_category,
                "methodology": classification.methodology,
                "citation": classification.citation,
            },
            *(
                {
                    "main_category": s["main_category"],
                    "sub_category": s["sub_category"],
                    "methodology": s["methodology"],
                    "citation": s["citation"],
                }
                for s in get_secondaries(classification)
                if s.get("in_taxonomy")
            ),
        ]
    return [
        {
            "main_category": category.main_category,
            "sub_category": category.sub_category,
            "methodology": category.methodology,
            "citation": category.citation,
            "category_id": category.category_id,
        }
        for category in version.categories
    ]


def _option_item(classification, sub_category, main_category=None):
    """人工 final 次要分類：用這筆分類的合法清單補齊大類別 / methodology / identity。"""
    options = {c["sub_category"]: c for c in _with_proposed_categories(classification, _taxonomy_categories(classification))}
    info = options.get(sub_category) or {}
    return {
        "main_category": info.get("main_category") or main_category,
        "sub_category": sub_category,
        "methodology": info.get("methodology"),
        "citation": info.get("citation"),
        "taxonomy_category_id": info.get("category_id"),
    }


def _with_proposed_categories(classification, categories):
    """開放式分類：AI 提出的新類別（status=new_category）也要能被選，
    「維持 AI 原始分類」才能運作；標記 proposed=True 讓前端顯示為新類別。"""
    if classification.status != "new_category":
        return categories
    existing = {c["sub_category"] for c in categories}
    extra = []
    from services.secondary_classification_service import get_secondaries

    pairs = [(classification.main_category, classification.sub_category)] + [
        (s["main_category"], s["sub_category"]) for s in get_secondaries(classification)
    ]
    for main, sub in pairs:
        if sub and sub not in existing:
            extra.append({"main_category": main, "sub_category": sub, "methodology": None,
                          "citation": None, "proposed": True})
            existing.add(sub)
    return categories + extra


def _topic_of(classification):
    """這筆分類目前歸屬的主題（依分類時使用的 taxonomy version）。"""
    from models import Topic

    topic_key = None
    if classification.taxonomy_version_id is not None:
        version = db.session.get(Taxonomy_Version, classification.taxonomy_version_id)
        topic_key = version.topic_key if version is not None else None
    if topic_key is None:
        topic_key = _resolve_question_type(classification)
    topic = db.session.get(Topic, topic_key) if topic_key else None
    return {"topic_key": topic_key, "title": topic.title if topic else topic_key}


def taxonomy_options(classification):
    """前端「直接選擇分類」下拉選單用（只給名稱，不含 methodology 細節）。"""
    return [
        {"main_category": c["main_category"], "sub_category": c["sub_category"], "proposed": bool(c.get("proposed"))}
        for c in _with_proposed_categories(classification, _taxonomy_categories(classification))
        if c.get("sub_category")
    ]


def _reject_failed_classification(classification):
    if is_failed(classification):
        raise ReviewError(
            "分類結果處理失敗，無法進行人工確認；請使用「重新處理」",
            409,
            code="CLASSIFICATION_FAILED",
        )


def _segment_text(classification):
    return classification.answer_text[classification.segment_start:classification.segment_end]




def _conflict_error(active_review):
    return ReviewError(
        "這筆分類目前正由其他管理員審核中",
        409,
        code="REVIEW_IN_PROGRESS_BY_OTHER",
        extra={
            "reviewing_admin_id": active_review.admin_id,
            "reviewing_admin_name": _admin_display_name(active_review.admin_id),
        },
    )


def _lock_classification(classification_id):
    """SELECT ... FOR UPDATE 鎖住這筆 classification，作為同一筆
    classification 所有狀態轉換的 mutex（start / confirm / modify /
    exclude / reopen 全部都要先鎖，避免併發請求交錯寫出非法狀態）。"""
    classification = (
        Response_Classification.query
        .filter_by(classification_id=classification_id)
        .with_for_update()
        .first()
    )
    if classification is None:
        raise ReviewError("找不到這筆分類結果", 404)
    return classification


def _active_reviews(classification_id):
    """所有 in_progress session（正常情況最多一筆；歷史資料若有殘留
    多筆也全部回傳，交給呼叫端一起關閉，不會只處理第一筆）。"""
    return (
        Classification_Review.query
        .filter_by(classification_id=classification_id, status=REVIEW_SESSION_IN_PROGRESS)
        .order_by(Classification_Review.created_at.desc(), Classification_Review.review_id.desc())
        .all()
    )


def _close_reviews(reviews, status, reason, now):
    for review in reviews:
        review.status = status
        review.closed_at = now
        review.closed_reason = reason
        if status == REVIEW_SESSION_CONFIRMED:
            review.confirmed_at = now


def _require_own_or_no_active(classification_id, admin_id):
    """其他 Admin 持有 in_progress session -> 409；否則回傳自己的
    active sessions（可能是空 list）。"""
    actives = _active_reviews(classification_id)
    for review in actives:
        if review.admin_id != admin_id:
            raise _conflict_error(review)
    return actives


def _stamp(classification, admin_id, now):
    # 任何人工審核動作之後，這筆就不再是「系統自動通過」
    classification.auto_confirmed = False
    classification.reviewed_by_admin_id = admin_id
    classification.reviewed_at = now
    classification.updated_at = now


NEW_CATEGORY_STATUS = "new_category"  # 同 services.open_classification.NEW_CATEGORY_STATUS


def _is_auto_confirmed(classification):
    return classification.review_status == REVIEW_STATUS_CONFIRMED and bool(classification.auto_confirmed)


def _is_finalized_by_human(classification):
    """已人工定案（要先 reopen 才能再改）。系統自動通過的不算：Admin 可以
    直接對它做單筆審核動作（確認、手動指定、排除、開始審核對話）。"""
    return classification.review_status in _LOCKED_REVIEW_STATUSES and not _is_auto_confirmed(classification)


def _new_category_error():
    return ReviewError(
        "這筆是 AI 提出的新類別，不能直接確認。請到「新類別候選」選擇採用、合併或排除。",
        409,
        code="NEW_CATEGORY_NEEDS_DECISION",
    )


def _already_finalized_error(classification):
    return ReviewError(
        "這筆分類已經確認或排除過了",
        409,
        code="ALREADY_FINALIZED",
        extra={"review_status": classification.review_status},
    )


def _commit_or_rollback():
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def derive_review_state(classification, active_review=None) -> str:
    """給前端顯示用的衍生狀態：failed / in_review / pending_review /
    confirmed / modified / excluded。in_review 不是另外存的
    review_status，而是「pending_review + 有 in_progress session」。"""
    if classification.review_status == REVIEW_STATUS_PENDING:
        if is_failed(classification):
            return "failed"
        if active_review is not None:
            return "in_review"
    return classification.review_status


# ── 對外主要介面 ──────────────────────────────────────────────

def get_review_state(classification_id, admin_id):
    """AI original + 目前 review 狀態。任一 Admin 都可以查看，不因為別人
    正在審核就擋掉（前端需要顯示「目前由誰審核中」）。"""
    classification = _load_classification(classification_id)
    active_review = _get_active_review(classification_id)
    return {
        "classification": classification.to_dict(),
        "active_review": active_review.to_dict() if active_review else None,
        "review_state": derive_review_state(classification, active_review),
        "taxonomy_options": taxonomy_options(classification),
        "topic": _topic_of(classification),
        "source_question": source_question_label(classification),
    }


def start_review(classification_id, admin_id):
    """pending_review -> in_review（建立 in_progress session）。

      1. SELECT ... FOR UPDATE 鎖住 classification（併發請求被序列化）。
      2. failed -> 409（failed 走 retry，不走一般審核）。
      3. 已定案（confirmed/modified/excluded）-> 409（要先 reopen）。
      4. 已有 in_progress：同一 Admin 冪等回傳；別的 Admin 409。
    """
    classification = _lock_classification(classification_id)
    _reject_failed_classification(classification)

    if _is_auto_confirmed(classification):
        # 在系統自動通過的結果上開始審核對話 = 重新開啟（回到待審 + 新 session），
        # 避免「狀態是已確認、卻同時有審核對話在進行」。
        db.session.rollback()
        return reopen_review(classification_id, admin_id, reason="start_review_on_auto_confirmed")

    if classification.review_status in _LOCKED_REVIEW_STATUSES:
        raise ReviewError(
            "這筆分類已經確認或排除，無法再開始新的 review", 409, code="ALREADY_FINALIZED",
        )

    actives = _require_own_or_no_active(classification_id, admin_id)
    if actives:
        return actives[0]

    review = Classification_Review(
        classification_id=classification_id, admin_id=admin_id, status=REVIEW_SESSION_IN_PROGRESS,
    )
    db.session.add(review)
    _commit_or_rollback()
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
    if question_type is None and classification.taxonomy_version_id is not None:
        # 例如問卷題目本身沒有存 question_type，但這筆分類是用某個 Topic
        # 的 taxonomy 產生的：直接用那個 Topic。
        version = db.session.get(Taxonomy_Version, classification.taxonomy_version_id)
        question_type = version.topic_key if version is not None else None
    taxonomy_categories = _taxonomy_categories(classification)
    if question_type is None or not taxonomy_categories:
        raise ReviewError(
            "這筆分類找不到對應的主題分類清單，AI 無法討論；請改用「直接選擇分類」，"
            "或先到「其他 / 未歸屬資料」替這筆資料指派主題。",
            422,
            code="NO_TAXONOMY_OPTIONS",
        )

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
        else _first_ai_secondary(classification)["secondary_sub_category"]
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
        ai_secondary_sub_category=_first_ai_secondary(classification)["secondary_sub_category"],
        ai_reasoning=classification.reasoning,
        candidate_sub_category=candidate_sub,
        candidate_secondary_sub_category=candidate_secondary_sub,
        conversation_history=history,
        user_message=message_text,
        taxonomy_categories=taxonomy_categories,
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

    from services.failure_explainer import explain_failure

    return {
        "message": assistant_msg.to_dict(),
        "taxonomy_rejected": ai_result["taxonomy_rejected"],
        # AI 呼叫失敗（額度不足、模型忙碌…）時的中文說明；對話仍然保存，
        # 可以直接再送一次或改用「直接選擇分類」。
        "ai_error": explain_failure(ai_result.get("error_detail")),
    }



def confirm_original(classification_id, admin_id, batch_id=None, action=None, _allow_new_category=False):
    """pending_review / in_review（尚未送出任何訊息）-> confirmed。

    - 系統自動通過（confirmed + auto_confirmed）-> 人工確認（auto_confirmed=False）。
    - AI 提出的新類別（status=new_category）不能直接確認 -> 409
      NEW_CATEGORY_NEEDS_DECISION：直接確認會讓這筆變成「已確認」，但類別
      從來沒有加進分類架構，也會從「新類別候選」消失。請改用新類別的
      採用（adopt，會一起確認）或合併（merge）。_allow_new_category 只給
      new_category_service.adopt() 使用。

    - 自己持有、但還沒送出任何訊息的 in_progress session 會一併關閉
      （status=closed, closed_reason=quick_confirm）——修正「開始 review
      後直接返回列表按快速確認，classification 變 confirmed 但 session
      永遠停在 in_progress」的斷鏈。
    - 已經在 session 裡送出過訊息 -> 409（必須用 confirm-candidate）。
    - failed -> 409；已定案 -> 409（重試不會產生重複紀錄）。
    """
    classification = _lock_classification(classification_id)
    _reject_failed_classification(classification)

    # 系統自動通過的結果可以直接「人工確認」：Admin 看過、同意 AI 的判斷，
    # 這筆就變成人工確認（auto_confirmed=False，記錄審核人，受重新分析保護）。
    if _is_finalized_by_human(classification):
        raise _already_finalized_error(classification)
    if classification.status == NEW_CATEGORY_STATUS and not _allow_new_category:
        raise _new_category_error()

    actives = _require_own_or_no_active(classification_id, admin_id)
    if any(_has_entered_current_conversation(r.review_id) for r in actives):
        raise ReviewError(
            "這筆分類已經進入過 review conversation，請用 confirm-candidate 確認，"
            "不能再用 confirm-original",
            409,
            code="CONVERSATION_STARTED",
        )

    now = taiwan_now()
    before = audit_service.classification_state(classification)
    _close_reviews(actives, REVIEW_SESSION_CLOSED, "quick_confirm", now)
    classification.review_status = REVIEW_STATUS_CONFIRMED
    _stamp(classification, admin_id, now)

    audit_service.record(
        action or (audit_service.ACTION_BATCH_CONFIRM if batch_id else audit_service.ACTION_QUICK_CONFIRM),
        audit_service.ENTITY_CLASSIFICATION, classification_id, admin_id,
        before=before, after=audit_service.classification_state(classification),
        batch_id=batch_id,
    )
    mark_reports_outdated_for_classification(
        classification, OUTDATED_BULK_REVIEW_ACTION if batch_id else OUTDATED_CLASSIFICATION_CONFIRMED,
    )
    _commit_or_rollback()
    return classification


def confirm_candidate(classification_id, admin_id):
    """in_review（已送出訊息）-> modified：寫入 final_*（即使最終候選跟
    AI original 完全相同也一樣，「Admin 曾提出異議」本身就是 feedback）。
    session -> confirmed。"""
    classification = _lock_classification(classification_id)
    _reject_failed_classification(classification)

    if classification.review_status in _LOCKED_REVIEW_STATUSES:
        raise _already_finalized_error(classification)

    actives = _require_own_or_no_active(classification_id, admin_id)
    review = next((r for r in actives if _has_entered_current_conversation(r.review_id)), None)
    if review is None:
        raise ReviewError(
            "這筆分類還沒有進入過 review conversation，請用 confirm-original 確認，"
            "不能用 confirm-candidate",
            409,
            code="CONVERSATION_NOT_STARTED",
        )

    latest_candidate_msg = (
        Classification_Review_Message.query
        .filter_by(review_id=review.review_id, role="assistant")
        .filter(Classification_Review_Message.candidate_sub_category.isnot(None))
        .order_by(Classification_Review_Message.created_at.desc(), Classification_Review_Message.message_id.desc())
        .first()
    )

    if latest_candidate_msg is not None:
        final_main = latest_candidate_msg.candidate_main_category
        final_sub = latest_candidate_msg.candidate_sub_category
        final_secondary_main = latest_candidate_msg.candidate_secondary_main_category
        final_secondary_sub = latest_candidate_msg.candidate_secondary_sub_category
        final_reasoning = latest_candidate_msg.candidate_reasoning
    else:
        # 對話發生過，但 AI 從未正式提出候選變更：final 沿用 AI original，
        # review_status 仍然是 modified。
        final_main = classification.main_category
        final_sub = classification.sub_category
        first_ai = _first_ai_secondary(classification)
        final_secondary_main = first_ai["secondary_main_category"]
        final_secondary_sub = first_ai["secondary_sub_category"]
        final_reasoning = classification.reasoning

    # Primary == Secondary 正規化（跟 classify_v2 / review_ai_service 一致）
    if final_sub is not None and final_sub == final_secondary_sub:
        final_secondary_main = None
        final_secondary_sub = None

    now = taiwan_now()
    before = audit_service.classification_state(classification)
    classification.final_main_category = final_main
    classification.final_sub_category = final_sub
    classification.final_reasoning = final_reasoning
    if latest_candidate_msg is not None:
        final_secondaries = (
            [_option_item(classification, final_secondary_sub, final_secondary_main)] if final_secondary_sub else []
        )
    else:
        # 沒有候選：沿用 AI 原始的次要分類（可能不只一個、只取在分類架構裡的）
        final_secondaries = [s for s in get_secondaries(classification) if s["in_taxonomy"]]
    set_final_secondaries(classification, final_secondaries, admin_id=admin_id)
    classification.review_status = REVIEW_STATUS_MODIFIED
    _stamp(classification, admin_id, now)

    _close_reviews([review], REVIEW_SESSION_CONFIRMED, "candidate_confirmed", now)
    # 同一 Admin 殘留的其他 in_progress（歷史資料）一併關閉，保證不留 active。
    _close_reviews([r for r in actives if r is not review], REVIEW_SESSION_CLOSED, "superseded_session", now)

    audit_service.record(
        audit_service.ACTION_MODIFY, audit_service.ENTITY_CLASSIFICATION, classification_id, admin_id,
        before=before, after=audit_service.classification_state(classification),
        reason=f"review_id={review.review_id}",
    )
    mark_reports_outdated_for_classification(classification, OUTDATED_CLASSIFICATION_MODIFIED)
    _commit_or_rollback()
    return classification


def confirm_manual(classification_id, admin_id, sub_category, secondary_sub_category=None, reasoning=None,
                   secondary_sub_categories=None):
    """Admin 不經過 AI 對話，直接從這筆分類的合法分類清單裡指定最終分類：
    pending / in_review -> modified（寫入 final_*）。

    - 只接受清單內的子類別（fail-closed：不能自創分類）；main_category
      由清單查表決定，不由前端傳入。
    - 自己的 in_progress session 一併結束（confirmed）；別的 Admin 審核中 -> 409。
    - failed -> 409（請用重新處理）；已定案 -> 409（請先 reopen）。
    """
    classification = _lock_classification(classification_id)
    _reject_failed_classification(classification)
    if _is_finalized_by_human(classification):  # 自動通過的可以直接處理
        raise _already_finalized_error(classification)
    actives = _require_own_or_no_active(classification_id, admin_id)

    options = {
        c["sub_category"]: c
        for c in _with_proposed_categories(classification, _taxonomy_categories(classification))
        if c.get("sub_category")
    }
    if not sub_category or sub_category not in options:
        raise ReviewError("請從清單中選擇一個子類別", 400, code="INVALID_CATEGORY")
    # 次要分類可以不只一個：secondary_sub_categories（清單）；舊的單一
    # secondary_sub_category 參數仍接受。
    requested = list(secondary_sub_categories or [])
    if secondary_sub_category:
        requested.insert(0, secondary_sub_category)
    secondaries = []
    for sub in requested:
        if not sub or sub == sub_category or sub in secondaries:
            continue
        if sub not in options:
            raise ReviewError("次要子類別必須在清單中", 400, code="INVALID_CATEGORY")
        secondaries.append(sub)

    now = taiwan_now()
    before = audit_service.classification_state(classification)
    classification.final_main_category = options[sub_category]["main_category"]
    classification.final_sub_category = sub_category
    set_final_secondaries(classification, [
        {"main_category": options[sub]["main_category"], "sub_category": sub,
         "methodology": options[sub].get("methodology"), "citation": options[sub].get("citation"),
         "taxonomy_category_id": options[sub].get("category_id")}
        for sub in secondaries
    ], admin_id=admin_id)
    classification.final_reasoning = (reasoning or "").strip() or "管理員直接指定分類"
    classification.review_status = REVIEW_STATUS_MODIFIED
    _stamp(classification, admin_id, now)
    _close_reviews(actives, REVIEW_SESSION_CONFIRMED, "manual_selection", now)

    audit_service.record(
        audit_service.ACTION_MODIFY, audit_service.ENTITY_CLASSIFICATION, classification_id, admin_id,
        before=before, after=audit_service.classification_state(classification),
        reason="manual_selection" + (f": {reasoning.strip()}" if reasoning and reasoning.strip() else ""),
    )
    mark_reports_outdated_for_classification(classification, OUTDATED_CLASSIFICATION_MODIFIED)
    _commit_or_rollback()
    return classification


def reopen_review(classification_id, admin_id, reason=None):
    """confirmed / modified / excluded -> pending_review，並替重新開啟的
    Admin 建立新的 in_progress session（= in_review）。

    - 舊的審核歷史、AI original、final_* 全部保留（final_* 在 pending
      狀態下不會被 effective 規則採用，下一次 confirm 才決定新結果）。
    - 殘留的舊 in_progress session（例如舊版 quick confirm 留下的）不會
      再讓 reopen 提早 return：已定案的 classification 上的 in_progress
      一律視為過期，關閉後才建立新的 session。
    - 冪等：已經被自己 reopen（pending + 自己的 in_progress）-> 回傳既有
      session；被別的 Admin reopen / 審核中 -> 409。
    - failed 且未排除 -> 409（failed 走 retry）。
    """
    classification = _lock_classification(classification_id)
    actives = _active_reviews(classification_id)

    if classification.review_status == REVIEW_STATUS_PENDING:
        for review in actives:
            if review.admin_id != admin_id:
                raise _conflict_error(review)
        if actives:
            return actives[0]  # 重試：已經是 reopen 後的狀態
        _reject_failed_classification(classification)
        raise ReviewError("這筆分類目前是待處理狀態，不需要重新開啟", 409, code="NOT_REOPENABLE")

    if classification.review_status not in _LOCKED_REVIEW_STATUSES:
        raise ReviewError(
            f"review_status={classification.review_status!r} 無法重新開啟", 409, code="NOT_REOPENABLE",
        )
    if is_failed(classification) and classification.review_status != REVIEW_STATUS_EXCLUDED:
        _reject_failed_classification(classification)

    now = taiwan_now()
    before = audit_service.classification_state(classification)
    _close_reviews(actives, REVIEW_SESSION_CLOSED, "reopen_cleanup", now)

    classification.review_status = REVIEW_STATUS_PENDING
    _stamp(classification, admin_id, now)
    review = Classification_Review(
        classification_id=classification_id, admin_id=admin_id, status=REVIEW_SESSION_IN_PROGRESS,
    )
    db.session.add(review)

    audit_service.record(
        audit_service.ACTION_REOPEN, audit_service.ENTITY_CLASSIFICATION, classification_id, admin_id,
        before=before, after=audit_service.classification_state(classification),
        reason=reason,
    )
    mark_reports_outdated_for_classification(classification, OUTDATED_CLASSIFICATION_REOPENED)
    _commit_or_rollback()
    return review


def exclude(classification_id, admin_id, reason=None):
    """pending_review / in_review -> excluded（軟刪除標記，不刪資料）。
    自己的 in_progress session -> excluded。已定案 -> 409（要先 reopen）。
    failed 也可以排除（明確決定捨棄這筆失敗結果）。"""
    classification = _lock_classification(classification_id)

    if _is_finalized_by_human(classification):  # 自動通過的可以直接處理
        raise _already_finalized_error(classification)

    actives = _require_own_or_no_active(classification_id, admin_id)

    now = taiwan_now()
    before = audit_service.classification_state(classification)
    classification.review_status = REVIEW_STATUS_EXCLUDED
    _stamp(classification, admin_id, now)
    _close_reviews(actives, REVIEW_SESSION_EXCLUDED, "excluded", now)

    audit_service.record(
        audit_service.ACTION_EXCLUDE, audit_service.ENTITY_CLASSIFICATION, classification_id, admin_id,
        before=before, after=audit_service.classification_state(classification),
        reason=reason,
    )
    mark_reports_outdated_for_classification(classification, OUTDATED_CLASSIFICATION_EXCLUDED)
    _commit_or_rollback()
    return classification


# ── 批次操作 ─────────────────────────────────────────────────

def _normalize_batch_id(batch_id):
    import uuid
    if batch_id is None or str(batch_id).strip() == "":
        return uuid.uuid4().hex
    batch_id = str(batch_id).strip()
    if len(batch_id) > 64:
        raise ReviewError("batch_id 長度不可超過 64", 400, code="INVALID_BATCH_ID")
    return batch_id


def batch_confirm(classification_ids, admin_id, batch_id=None):
    """一次確認多筆（維持 AI 原始分類）。需要人工判斷的列（needs_human_review，
    例如低信心、分類不完整）和 AI 提出的新類別不能批次確認，會回報在 skipped。
    在單一 transaction 裡處理：
    每筆各自鎖定、檢查資格；不合格的逐筆回報原因（skipped），合格的
    一起 commit。同一個 batch_id 重試時，已經在這個 batch 被確認過的
    筆數回報 already_done，不會重複寫入 audit / 重複改狀態。"""
    from audit import Admin_Audit_Log

    if not isinstance(classification_ids, list) or not classification_ids:
        raise ReviewError("classification_ids 必須是非空陣列", 400, code="INVALID_IDS")
    if len(classification_ids) > 500:
        raise ReviewError("一次最多 500 筆", 400, code="BATCH_TOO_LARGE")
    try:
        ids = sorted({int(i) for i in classification_ids})
    except (TypeError, ValueError):
        raise ReviewError("classification_ids 只能是整數", 400, code="INVALID_IDS")
    batch_id = _normalize_batch_id(batch_id)

    done_in_batch = {
        int(a.entity_id) for a in Admin_Audit_Log.query.filter_by(
            batch_id=batch_id, action=audit_service.ACTION_BATCH_CONFIRM,
        ).all()
    }

    confirmed, skipped, already_done = [], [], []
    sources = set()
    now = taiwan_now()
    try:
        for cid in ids:
            row = (
                Response_Classification.query.filter_by(classification_id=cid)
                .with_for_update().first()
            )
            if row is None:
                skipped.append({"classification_id": cid, "code": "CLASSIFICATION_NOT_FOUND", "message": "找不到這筆分類結果"})
                continue
            if cid in done_in_batch and row.review_status == REVIEW_STATUS_CONFIRMED:
                already_done.append(cid)
                continue
            if is_failed(row):
                skipped.append({"classification_id": cid, "code": "CLASSIFICATION_FAILED", "message": "分類處理失敗，請改用重新處理"})
                continue
            if row.review_status in _LOCKED_REVIEW_STATUSES:
                skipped.append({"classification_id": cid, "code": "ALREADY_FINALIZED", "message": f"已經是 {row.review_status}"})
                continue
            if row.status == NEW_CATEGORY_STATUS:
                skipped.append({
                    "classification_id": cid, "code": "NEW_CATEGORY_NEEDS_DECISION",
                    "message": "AI 提出的新類別，請到「新類別候選」採用、合併或排除",
                })
                continue
            if row.needs_human_review:
                skipped.append({
                    "classification_id": cid, "code": "NEEDS_HUMAN_JUDGEMENT",
                    "message": f"需要人工判斷（{row.review_flag_reason or '已標記'}），請逐筆確認",
                })
                continue
            actives = _active_reviews(cid)
            other = next((r for r in actives if r.admin_id != admin_id), None)
            if other is not None:
                skipped.append({
                    "classification_id": cid, "code": "REVIEW_IN_PROGRESS_BY_OTHER",
                    "message": f"目前由 {_admin_display_name(other.admin_id) or f'Admin #{other.admin_id}'} 審核中",
                })
                continue
            if any(_has_entered_current_conversation(r.review_id) for r in actives):
                skipped.append({"classification_id": cid, "code": "CONVERSATION_STARTED", "message": "已進入審核對話，請在對話中確認"})
                continue

            before = audit_service.classification_state(row)
            _close_reviews(actives, REVIEW_SESSION_CLOSED, "quick_confirm", now)
            row.review_status = REVIEW_STATUS_CONFIRMED
            _stamp(row, admin_id, now)
            audit_service.record(
                audit_service.ACTION_BATCH_CONFIRM, audit_service.ENTITY_CLASSIFICATION, cid, admin_id,
                before=before, after=audit_service.classification_state(row), batch_id=batch_id,
            )
            sources.add(classification_source(row))
            confirmed.append(cid)

        if confirmed:
            mark_reports_outdated_for_sources(sources, OUTDATED_BULK_REVIEW_ACTION)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return {
        "batch_id": batch_id,
        "confirmed_ids": confirmed,
        "already_done_ids": already_done,
        "skipped": skipped,
        "confirmed_count": len(confirmed),
        "skipped_count": len(skipped),
    }


# ── Bulk exclude（排除舊版資料）─────────────────────────────────
#
# 舊行為（confidence IS NULL + pending_review）範圍過寬，可能誤排除
# taxonomy-versioned / failed / 審核中 / 已有人工動作的資料。收窄為：
#   review_status = pending_review
#   AND confidence IS NULL
#   AND taxonomy_version_id IS NULL      （真正的 legacy 分類）
#   AND status NOT IN (failed, superseded)（failed 應走 retry，不是靜默排除）
#   AND 沒有 in_progress review session  （有人正在審核）
#   AND 從未有任何人工動作                （沒有任何 review session / audit 紀錄）

BULK_EXCLUDE_SKIP_REASONS = {
    "HAS_TAXONOMY_VERSION": "有 taxonomy version（非 legacy 資料）",
    "CLASSIFICATION_FAILED": "分類處理失敗，請改用重新處理",
    "REVIEW_IN_PROGRESS": "目前有進行中的審核",
    "HAS_HUMAN_ACTION": "已經有人工審核紀錄",
}


def _bulk_exclude_scan():
    from audit import Admin_Audit_Log
    from services.effective_classification_service import NON_COUNTABLE_STATUSES

    candidates = (
        Response_Classification.query
        .filter(
            Response_Classification.confidence.is_(None),
            Response_Classification.review_status == REVIEW_STATUS_PENDING,
        )
        .order_by(Response_Classification.classification_id.asc())
        .all()
    )
    ids = [c.classification_id for c in candidates]
    reviewed_ids, active_ids, audited_ids = set(), set(), set()
    if ids:
        for review in Classification_Review.query.filter(Classification_Review.classification_id.in_(ids)).all():
            reviewed_ids.add(review.classification_id)
            if review.status == REVIEW_SESSION_IN_PROGRESS:
                active_ids.add(review.classification_id)
        audited_ids = {
            int(a.entity_id) for a in Admin_Audit_Log.query.filter(
                Admin_Audit_Log.entity_type == audit_service.ENTITY_CLASSIFICATION,
                Admin_Audit_Log.entity_id.in_([str(i) for i in ids]),
            ).all()
        }

    eligible, skipped = [], []
    for row in candidates:
        cid = row.classification_id
        if row.taxonomy_version_id is not None:
            code = "HAS_TAXONOMY_VERSION"
        elif row.status in NON_COUNTABLE_STATUSES:
            code = "CLASSIFICATION_FAILED"
        elif cid in active_ids:
            code = "REVIEW_IN_PROGRESS"
        elif cid in reviewed_ids or cid in audited_ids:
            code = "HAS_HUMAN_ACTION"
        else:
            eligible.append(row)
            continue
        skipped.append({"classification_id": cid, "code": code, "message": BULK_EXCLUDE_SKIP_REASONS[code]})
    return eligible, skipped


def preview_legacy_bulk_exclude():
    """執行前預覽：回傳 eligible / skipped 數量、原因與 affected IDs。"""
    eligible, skipped = _bulk_exclude_scan()
    reasons = {}
    for item in skipped:
        reasons[item["code"]] = reasons.get(item["code"], 0) + 1
    return {
        "eligible_count": len(eligible),
        "eligible_ids": [r.classification_id for r in eligible],
        "skipped_count": len(skipped),
        "skipped_reasons": [
            {"code": code, "message": BULK_EXCLUDE_SKIP_REASONS[code], "count": count}
            for code, count in sorted(reasons.items())
        ],
        "skipped": skipped,
    }


def execute_legacy_bulk_exclude(admin_id, batch_id=None, expected_ids=None):
    """真正執行 bulk exclude（單一 transaction）。

    - batch_id 是冪等鍵：同一個 batch_id 重試時，回傳上一次的結果，
      不會重複寫入。
    - expected_ids（選填，通常是 preview 回傳的 eligible_ids）：只處理
      這些 ID 裡「執行當下仍然合格」的列，避免預覽後資料變動造成範圍
      擴大。
    """
    from audit import Admin_Audit_Log

    batch_id = _normalize_batch_id(batch_id)
    previous = Admin_Audit_Log.query.filter_by(batch_id=batch_id, action=audit_service.ACTION_BULK_EXCLUDE).all()
    if previous:
        ids = sorted(int(a.entity_id) for a in previous)
        return {"batch_id": batch_id, "affected_count": len(ids), "affected_ids": ids, "skipped_count": 0, "skipped": [], "idempotent_replay": True}

    eligible, skipped = _bulk_exclude_scan()
    if expected_ids is not None:
        expected = {int(i) for i in expected_ids}
        eligible = [r for r in eligible if r.classification_id in expected]

    now = taiwan_now()
    affected, sources = [], set()
    try:
        for row in eligible:
            locked = (
                Response_Classification.query.filter_by(classification_id=row.classification_id)
                .with_for_update().first()
            )
            if locked is None or locked.review_status != REVIEW_STATUS_PENDING:
                continue
            before = audit_service.classification_state(locked)
            locked.review_status = REVIEW_STATUS_EXCLUDED
            _stamp(locked, admin_id, now)
            audit_service.record(
                audit_service.ACTION_BULK_EXCLUDE, audit_service.ENTITY_CLASSIFICATION,
                locked.classification_id, admin_id,
                before=before, after=audit_service.classification_state(locked),
                reason="legacy bulk exclude", batch_id=batch_id,
            )
            sources.add(classification_source(locked))
            affected.append(locked.classification_id)
        if affected:
            mark_reports_outdated_for_sources(sources, OUTDATED_BULK_REVIEW_ACTION)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return {
        "batch_id": batch_id,
        "affected_count": len(affected),
        "affected_ids": affected,
        "skipped_count": len(skipped),
        "skipped": skipped,
        "idempotent_replay": False,
    }


def exclude_legacy_pending_classifications(admin_id, batch_id=None) -> int:
    """向後相容的舊入口：套用收窄後的 eligibility 規則，回傳實際排除筆數。"""
    return execute_legacy_bulk_exclude(admin_id, batch_id=batch_id)["affected_count"]


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


def get_audit_history(classification_id):
    """這筆 classification 的完整 Admin 操作稽核紀錄（不含聊天訊息）。"""
    _load_classification(classification_id)
    return [a.to_dict() for a in audit_service.list_for_entity(audit_service.ENTITY_CLASSIFICATION, classification_id)]
