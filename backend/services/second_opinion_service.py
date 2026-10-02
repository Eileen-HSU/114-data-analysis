"""
AI 第二意見：低信心的分類結果，交給更強的模型獨立再判斷一次，取代人工審核。

流程（每一筆）：
    1. 只處理：待審、分類成功、被標記為低信心（low_confidence）、還沒做過
       第二意見、分類架構已發布、沒有人正在審核的結果。
    2. 把這一段回答（先遮蔽個資，跟第一次分類一樣）和這個分類架構的
       所有類別定義交給 SECOND_OPINION_MODEL，請它「獨立」選一個類別。
       不告訴它第一次的答案，避免它被第一次的答案帶著走。
    3. 兩次選的子類別一樣 -> 自動通過（auto_confirmed，跟高信心自動通過相同，
       仍可隨時重新審核）。
       不一樣（或它認為都不適合）-> 維持待審，標記 ai_disagreement，
       並把第二意見存起來，人工審核時可以直接看到兩個選項。

執行方式：用 bulk_retry_service 的背景工作機制（kind="second_opinion"），
所以額度退避、自動暫停、停止、中斷接續都跟「全部重試」一樣。
排程每 10 分鐘自動檢查一次（app.py），新資料不需要任何人按按鈕；
Admin 也可以在首頁手動開始（例如處理舊資料）。
"""

import json
import os
import re

from classification_models import REVIEW_STATUS_CONFIRMED, REVIEW_STATUS_PENDING, Response_Classification
from extensions import db, taiwan_now

STATUS_AGREED = "agreed"
STATUS_DISAGREED = "disagreed"
STATUS_FAILED = "failed"
ACTION_SECOND_OPINION = "second_opinion"
REASON_LOW_CONFIDENCE = "low_confidence"
REASON_AI_DISAGREEMENT = "ai_disagreement"

_SYSTEM_PROMPT = """你是問卷開放式回覆的分類審查員。另一位分析員已經分類過這段回覆，但沒有把握，
所以請你獨立判斷這段回覆最適合下面哪一個子類別。

規則：
- 只能從下面清單中選一個子類別，名稱必須完全一樣。
- 如果每一個都明顯不適合，sub_category 回 null。
- 只回傳 JSON，不要任何其他文字：{{"sub_category": "子類別名稱或 null", "reasoning": "一句話說明"}}

可選的類別（大類別 / 子類別：定義）：
{categories}
"""


def second_opinion_model() -> str:
    return os.environ.get("SECOND_OPINION_MODEL", "").strip() or "gemini-3.5-flash"


def _segment_text(row) -> str:
    text = row.answer_text or ""
    start, end = row.segment_start, row.segment_end
    if start is not None and end is not None and 0 <= start < end <= len(text):
        return text[start:end]
    return text


def _published_version(row):
    from models import Taxonomy_Version
    from taxonomy import TAXONOMY_VERSION_STATUS_PUBLISHED

    if row.taxonomy_version_id is None:
        return None
    version = db.session.get(Taxonomy_Version, row.taxonomy_version_id)
    if version is None or version.status != TAXONOMY_VERSION_STATUS_PUBLISHED:
        return None
    return version


def eligible_query():
    """需要第二意見的列（見檔案開頭第 1 點）。分類架構是否已發布在處理時再檢查。"""
    from classification_models import Classification_Review

    reviewed_ids = db.session.query(Classification_Review.classification_id).distinct()
    return Response_Classification.query.filter(
        Response_Classification.review_status == REVIEW_STATUS_PENDING,
        Response_Classification.status == "completed",
        Response_Classification.review_flag_reason == REASON_LOW_CONFIDENCE,
        Response_Classification.second_opinion_status.is_(None),
        Response_Classification.taxonomy_version_id.isnot(None),
        ~Response_Classification.classification_id.in_(reviewed_ids),
    )


def eligible_count() -> int:
    return eligible_query().count()


def ask_model(row, version) -> dict:
    """呼叫第二意見模型。回傳 {"main_category", "sub_category", "reasoning"}；
    sub_category 為 None 代表模型認為都不適合。API 錯誤直接往上拋（交給背景工作退避）。"""
    from services import gemini_client as genai
    from services.privacy_service import mask_pii

    categories = sorted(version.categories, key=lambda c: (c.main_category or "", c.sub_category or ""))
    lines = "\n".join(f"- {c.main_category} / {c.sub_category}：{(c.definition or '').strip()}" for c in categories)
    model = genai.GenerativeModel(
        model_name=second_opinion_model(),
        system_instruction=_SYSTEM_PROMPT.format(categories=lines),
    )
    response = model.generate_content(
        f"問卷回覆內容：\n{mask_pii(_segment_text(row))}", generation_config={"temperature": 0},
    )
    parsed = json.loads(re.sub(r"```json|```", "", response.text or "").strip())
    sub = parsed.get("sub_category")
    sub = sub.strip() if isinstance(sub, str) and sub.strip().lower() not in ("", "null", "none") else None
    by_sub = {c.sub_category: c for c in categories}
    if sub is not None and sub not in by_sub:
        raise ValueError(f"第二意見回傳了清單以外的類別：{sub!r}")
    return {
        "main_category": by_sub[sub].main_category if sub else None,
        "sub_category": sub,
        "reasoning": str(parsed.get("reasoning") or "")[:2000],
    }


def _apply(row, opinion):
    from services import audit_service

    before = audit_service.classification_state(row)
    now = taiwan_now()
    row.second_opinion_main_category = opinion["main_category"]
    row.second_opinion_sub_category = opinion["sub_category"]
    row.second_opinion_reasoning = opinion["reasoning"]
    row.second_opinion_at = now
    agreed = opinion["sub_category"] is not None and opinion["sub_category"] == row.sub_category
    if agreed:
        row.second_opinion_status = STATUS_AGREED
        row.review_status = REVIEW_STATUS_CONFIRMED
        row.auto_confirmed = True
        row.reviewed_by_admin_id = None
        row.reviewed_at = now
    else:
        row.second_opinion_status = STATUS_DISAGREED
        row.review_flag_reason = REASON_AI_DISAGREEMENT
    row.updated_at = now
    audit_service.record(
        ACTION_SECOND_OPINION, audit_service.ENTITY_CLASSIFICATION, row.classification_id, None,
        before=before, after=audit_service.classification_state(row),
        reason=f"AI 第二意見（{second_opinion_model()}）：{'一致' if agreed else '不一致'}",
    )
    return agreed


# ── 給 bulk_retry_service 背景工作用的兩個函式 ───────────────────────

def next_item(tried):
    for row in eligible_query().order_by(Response_Classification.classification_id.asc()).yield_per(200):
        key = ("cls", row.classification_id)
        if key not in tried:
            return "second_opinion", row.classification_id, key
    return None


def _still_eligible(row):
    return (row is not None and row.review_status == REVIEW_STATUS_PENDING
            and row.second_opinion_status is None and row.review_flag_reason == REASON_LOW_CONFIDENCE)


def process(_kind, classification_id, _admin_id):
    """回傳 (outcome, code, message)：success=一致自動通過、failed=不一致或第二意見失敗、
    transient=AI 暫時無法使用（等一下再試）、skipped=已經不需要處理。

    呼叫 AI 時不持有資料列的鎖（AI 可能要好幾秒，不能卡住正在審核的人）；
    拿到結果後才鎖定、再確認一次還符合條件，才寫入。"""
    from services.failure_explainer import explain_failure

    row = db.session.get(Response_Classification, classification_id)
    if not _still_eligible(row):
        return "skipped", "NOT_ELIGIBLE", "已經不需要第二意見"
    version = _published_version(row)
    if version is None:
        return "skipped", "TAXONOMY_NOT_PUBLISHED", "分類架構不是已發布版本"

    try:
        opinion = ask_model(row, version)
        error = None
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        failure = explain_failure(str(exc)) or {}
        if failure.get("code") in ("AI_QUOTA_EXCEEDED", "AI_SERVICE_BUSY", "AI_TIMEOUT"):
            return "transient", failure["code"], failure.get("message")
        opinion, error = None, (failure.get("code") or "SECOND_OPINION_FAILED", str(exc))

    db.session.rollback()  # 結束讀取用的 transaction，下面重新鎖定
    row = (Response_Classification.query.filter_by(classification_id=classification_id)
           .with_for_update().first())
    if not _still_eligible(row):
        db.session.rollback()
        return "skipped", "NOT_ELIGIBLE", "處理期間已經有人審核"

    if error is not None:
        row.second_opinion_status = STATUS_FAILED
        row.second_opinion_reasoning = error[1][:2000]
        row.second_opinion_at = taiwan_now()
        db.session.commit()
        return "failed", error[0], error[1][:300]

    agreed = _apply(row, opinion)
    db.session.commit()
    if agreed:
        return "success", None, None
    return "failed", "AI_DISAGREEMENT", "兩次 AI 判斷不一致，留給人工確認"
