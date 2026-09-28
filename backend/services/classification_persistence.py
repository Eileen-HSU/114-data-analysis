"""
Response_Classification 列的建立（第一次分析、重新分析、Admin 重新處理共用）。

只負責把 classify_response_multi_segment() 的 segments 轉成 ORM 列並
db.session.add()；不建立 / 更新 Response_Segmentation_Status、不 commit。
第一次分析見 routes/classifications/classification.py 的
_persist_segmentation_result()；重新分析見
services/classification_attempt_service.py。
"""

import re
import unicodedata

from classification_models import Response_Classification
from extensions import db

_MAIN_CATEGORY_PREFIX_RE = re.compile(r"^大類別[:：]\s*")
_WHITESPACE_RUN_RE = re.compile(r"[\s\t\n\r]+")


def normalize_main_category(raw) -> str:
    """把 main_category 正規化成唯一的 canonical 字串。

    步驟（依序執行，順序會影響結果，不能任意調換）：
      1. Unicode NFKC normalize（統一全形/半形符號，例如全形冒號「：」
         正規化後會變成半形「:」）
      2. strip 前後空白
      3. 移除開頭的「大類別：」或「大類別:」前綴
      4. 把連續空白／tab／換行壓成單一半形空白
      5. 再 strip 一次

    只處理字串層級的正規化，不改變分類語意本身。raw 是 None 時回傳空字串。
    """
    if raw is None:
        return ""
    text = unicodedata.normalize("NFKC", str(raw))
    text = text.strip()
    text = _MAIN_CATEGORY_PREFIX_RE.sub("", text)
    text = _WHITESPACE_RUN_RE.sub(" ", text)
    text = text.strip()
    return text


def _confidence(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    return None


def build_classification_rows(scope, segments, taxonomy_version_id, attempt_no=1):
    """segments -> Response_Classification 列（已 add 進 session，未 flush）。"""
    from services.confidence_gate import evaluate_confidence_gate

    rows = []
    for seg in segments or []:
        reasoning = seg.get("reasoning")
        if seg.get("status") != "completed" and seg.get("error_detail"):
            reasoning = seg["error_detail"]

        needs_human_review, review_flag_reason = evaluate_confidence_gate(seg)

        row = Response_Classification(
            response_id=scope["response_id"],
            upload_batch_id=scope["upload_batch_id"],
            uploaded_answer_id=scope["uploaded_answer_id"],
            source_type=scope["source_type"],
            question_id=scope["question_id"],
            answer_text=scope["answer_text"],
            segment_start=seg["orig_start"],
            segment_end=seg["orig_end"],
            main_category=normalize_main_category(seg.get("main_category")),
            sub_category=seg.get("sub_category"),
            secondary_sub_category=seg.get("secondary_sub_category"),
            reasoning=reasoning,
            summary=seg.get("summary"),
            methodology=seg.get("methodology"),
            citation=seg.get("citation"),
            secondary_methodology=seg.get("secondary_methodology"),
            secondary_citation=seg.get("secondary_citation"),
            status=seg.get("status"),
            taxonomy_version_id=taxonomy_version_id,
            confidence=_confidence(seg.get("confidence")),
            needs_human_review=needs_human_review,
            review_flag_reason=review_flag_reason,
            attempt_no=attempt_no,
        )
        db.session.add(row)
        rows.append(row)
    return rows
