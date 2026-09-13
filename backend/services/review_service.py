"""

Human Review 業務邏輯層。routes/classifications/review.py 只負責解析
request/組 HTTP response，實際的 ownership 檢查、conversation 讀寫、
confirm/exclude 規則全部在這裡，不分散到 route 裡各寫一份。

【taxonomy 來源】question_type（leadership_and_dept / career_and_feedback）
不是 Response_Classification 自己的欄位，要分來源推導：
    survey     ：response_id -> Survey_Response.template_id ->
                 Survey_Template.question_json 裡對應 question_id 那個
                 item 的 question_type
    user_upload：uploaded_answer_id -> Uploaded_Answer.question_type

【ownership 來源】Human Review 是 User 功能，只能 review 自己有權限
存取的 Survey/Upload：
    survey     ：Survey_Template.user_id
    user_upload：Uploaded_Answer.user_id（Phase 2 新增的欄位；migration
                 前的舊資料 user_id 可能是 None，None 視為「沒有已知
                 owner」，一律拒絕存取，不會有人因為欄位是 NULL 就
                 意外通過 ownership 檢查）
"""

from extensions import db, taiwan_now
from models import (
    Response_Classification,
    Classification_Review,
    Classification_Review_Message,
)
from response_classification import (
    REVIEW_STATUS_CONFIRMED,
    REVIEW_STATUS_MODIFIED,
    REVIEW_STATUS_EXCLUDED,
)
from services.review_ai_service import build_review_reply
from services.report_outdated_service import mark_reports_outdated_for_classification
from services.source_lookup_service import get_owner_user_id, resolve_question_type


class ReviewError(Exception):
    """業務邏輯錯誤，attrs: http_status, message。routes 層負責轉成 JSON response。"""

    def __init__(self, message: str, http_status: int = 400):
        super().__init__(message)
        self.message = message
        self.http_status = http_status


_LOCKED_REVIEW_STATUSES = (REVIEW_STATUS_CONFIRMED, REVIEW_STATUS_MODIFIED, REVIEW_STATUS_EXCLUDED)


# ── ownership / question_type 推導（實際邏輯見 services/source_lookup_service.py，
# 跟 Phase 4 的 Aggregation 服務共用同一套，這裡只是沿用既有函式名稱） ──

def _get_owner_user_id(classification):
    return get_owner_user_id(classification)


def _resolve_question_type(classification):
    return resolve_question_type(classification)


def _load_owned_classification(classification_id, auth_user_id):
    """
    共用的「取出 classification + 檢查這是不是這個 user 有權限 review
    的資料」邏輯，所有對外函式的第一步都呼叫這個，確保沒有任何一條
    路徑漏掉 ownership 檢查。
    """
    classification = Response_Classification.query.get(classification_id)
    if classification is None:
        raise ReviewError("找不到這筆分類結果", 404)

    owner_user_id = _get_owner_user_id(classification)
    if owner_user_id is None or owner_user_id != auth_user_id:
        raise ReviewError("無權限存取這筆分類結果", 403)

    return classification


def _get_active_review(classification_id, auth_user_id):
    """
    取「目前這個 user 進行中」的 review session（status='in_progress'）。
    一筆 classification 理論上可能有多次歷史 review session（Phase 2
    schema 註解已說明沒有 unique 限制），這裡固定取最新一筆
    in_progress，不存在則回傳 None（呼叫端決定要不要視為錯誤）。
    """
    return (
        Classification_Review.query
        .filter_by(classification_id=classification_id, user_id=auth_user_id, status="in_progress")
        .order_by(Classification_Review.created_at.desc())
        .first()
    )


def _has_ever_entered_conversation(classification_id):
    """
    是否曾經有任何一輪 User 訊息進過這個 classification 的 review
    conversation（不限哪個 review session，也不限是不是目前這個
    user——一旦有人跟這筆分類討論過，就不再算「從未進入」）。
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

def get_review_state(classification_id, auth_user_id):
    """需求文件 API 第 1 點：AI original + 目前 review 狀態。"""
    classification = _load_owned_classification(classification_id, auth_user_id)
    active_review = _get_active_review(classification_id, auth_user_id)
    return {
        "classification": classification.to_dict(),
        "active_review": active_review.to_dict() if active_review else None,
    }


def start_review(classification_id, auth_user_id):
    """需求文件 API 第 2 點：開始/取得 conversation。冪等：已有進行中
    的 session 就直接回傳那筆，不會重複建立。"""
    classification = _load_owned_classification(classification_id, auth_user_id)

    if classification.review_status in _LOCKED_REVIEW_STATUSES:
        raise ReviewError("這筆分類已經確認或排除，無法再開始新的 review", 409)

    existing = _get_active_review(classification_id, auth_user_id)
    if existing is not None:
        return existing

    review = Classification_Review(
        classification_id=classification_id, user_id=auth_user_id, status="in_progress",
    )
    db.session.add(review)
    db.session.commit()
    return review


def send_message(classification_id, auth_user_id, message_text):
    """需求文件 API 第 3 點：User 傳送 Review message。"""
    if not message_text or not message_text.strip():
        raise ReviewError("訊息內容不可為空", 400)

    classification = _load_owned_classification(classification_id, auth_user_id)

    review = _get_active_review(classification_id, auth_user_id)
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


def confirm_original(classification_id, auth_user_id):
    """需求文件 API 第 4 點。只有從未進入 Review Conversation 才允許：
    review_status -> confirmed，不寫入任何 final_* 欄位（effective
    分類直接讀 AI original）。"""
    classification = _load_owned_classification(classification_id, auth_user_id)

    if classification.review_status in _LOCKED_REVIEW_STATUSES:
        raise ReviewError("這筆分類已經確認或排除過了", 409)

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


def confirm_candidate(classification_id, auth_user_id):
    """需求文件 API 第 5 點。曾經進入過 Review Conversation 才允許：
    寫入 final_*，review_status -> modified（即使最終候選跟 AI
    original 完全相同也一樣，因為「User 曾提出異議」本身就是重要
    feedback data）。"""
    classification = _load_owned_classification(classification_id, auth_user_id)

    if classification.review_status in _LOCKED_REVIEW_STATUSES:
        raise ReviewError("這筆分類已經確認或排除過了", 409)

    if not _has_ever_entered_conversation(classification_id):
        raise ReviewError(
            "這筆分類還沒有進入過 review conversation，請用 confirm-original 確認，"
            "不能用 confirm-candidate",
            409,
        )

    review = _get_active_review(classification_id, auth_user_id)
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
        # 對話發生過，但 AI 從未正式提出候選變更（例如 User 問了問題，
        # AI 只回答說明、始終認為 AI original 才是對的）：final 直接
        # 沿用 AI original 的值，review_status 仍然是 modified
        # ——「User 曾提出異議」本身就是 feedback，不代表最終結果
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


def exclude(classification_id, auth_user_id):
    """需求文件 API 第 6 點：User 決定這個 segment 不納入後續分析。"""
    classification = _load_owned_classification(classification_id, auth_user_id)

    if classification.review_status in _LOCKED_REVIEW_STATUSES:
        raise ReviewError("這筆分類已經確認或排除過了", 409)

    classification.review_status = REVIEW_STATUS_EXCLUDED

    active_review = _get_active_review(classification_id, auth_user_id)
    if active_review is not None:
        active_review.status = "excluded"

    mark_reports_outdated_for_classification(classification)
    db.session.commit()
    return classification


def get_history(classification_id, auth_user_id):
    """需求文件 API 第 7 點：取得 conversation history（這個 user
    自己開的所有 review session，依時間排序）。"""
    _load_owned_classification(classification_id, auth_user_id)

    reviews = (
        Classification_Review.query
        .filter_by(classification_id=classification_id, user_id=auth_user_id)
        .order_by(Classification_Review.created_at.asc())
        .all()
    )
    return [r.to_dict(include_messages=True) for r in reviews]
