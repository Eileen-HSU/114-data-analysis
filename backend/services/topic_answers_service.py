"""
主題底下的原始回答（Admin 看分類架構時的「證據」）。

Admin 在分類架構頁看到「B1 模糊的負面感受與不確定性」這種 AI 歸納出來的
類別時，必須能看到：
    - 這個主題的資料是從哪個欄位 / 題目來的、共幾則
    - 每個類別底下實際有哪些原始回答
才有辦法判斷類別合不合理、主題有沒有分錯（要不要移到 / 併入其他主題）。

規則：
    - 以分類時使用的 taxonomy version 判斷歸屬（version.topic_key == topic）
    - superseded（已被重新分類取代）不列入
    - 類別依 effective 分類（人工修改過的用 final_*）
    - excluded / failed 另外計數，不混進類別
"""

from collections import OrderedDict

from classification_models import SOURCE_TYPE_USER_UPLOAD
from models import Response_Classification, Taxonomy_Version, Topic, Uploaded_Answer
from services.effective_classification_service import (
    CLASSIFICATION_STATUS_FAILED,
    CLASSIFICATION_STATUS_SUPERSEDED,
    effective_view,
)
from services.source_lookup_service import source_question_label

MAX_ITEMS_PER_CATEGORY = 200
_REVIEWED = ("confirmed", "modified")


class TopicAnswersError(Exception):
    def __init__(self, code, message, http_status=400):
        super().__init__(message)
        self.code, self.message, self.http_status = code, message, http_status


def _segment(row):
    text = row.answer_text or ""
    if row.segment_start is None or row.segment_end is None:
        return text
    return text[row.segment_start:row.segment_end] or text


def _answer_key(row):
    if row.source_type == SOURCE_TYPE_USER_UPLOAD:
        return ("upload", row.uploaded_answer_id)
    return ("survey", row.response_id, row.question_id)


def list_topic_answers(topic_key, per_category=5, main_category=None, sub_category=None):
    topic = Topic.query.get(topic_key)
    if topic is None:
        raise TopicAnswersError("TOPIC_NOT_FOUND", "找不到主題", 404)
    per_category = max(0, min(int(per_category or 0), MAX_ITEMS_PER_CATEGORY))

    version_ids = [v.version_id for v in Taxonomy_Version.query.filter_by(topic_key=topic_key).all()]
    rows = []
    if version_ids:
        rows = (
            Response_Classification.query
            .filter(Response_Classification.taxonomy_version_id.in_(version_ids))
            .filter(Response_Classification.status != CLASSIFICATION_STATUS_SUPERSEDED)
            .order_by(Response_Classification.classification_id.asc())
            .all()
        )

    # 題目 / 欄位名稱：上傳資料一次查完，問卷逐筆（有快取）
    upload_columns = {}
    upload_ids = {r.uploaded_answer_id for r in rows if r.source_type == SOURCE_TYPE_USER_UPLOAD and r.uploaded_answer_id}
    if upload_ids:
        for answer in Uploaded_Answer.query.filter(Uploaded_Answer.id.in_(upload_ids)).all():
            upload_columns[answer.id] = answer.source_column
    survey_labels = {}

    def label_of(row):
        if row.source_type == SOURCE_TYPE_USER_UPLOAD:
            return upload_columns.get(row.uploaded_answer_id)
        key = (row.response_id, row.question_id)
        if key not in survey_labels:
            survey_labels[key] = source_question_label(row)
        return survey_labels[key]

    answers_by_source = {}
    groups = OrderedDict()
    excluded = failed = reviewed = 0
    failed_items = []

    for row in rows:
        label = label_of(row) or "（未知題目）"
        answers_by_source.setdefault(label, set()).add(_answer_key(row))
        item = {
            "classification_id": row.classification_id,
            "segment_text": _segment(row),
            "answer_text": row.answer_text,
            "source_question": label,
            "review_status": row.review_status,
            "confidence": row.confidence,
            "is_new_category": row.status == "new_category",
        }
        if row.status == CLASSIFICATION_STATUS_FAILED:
            failed += 1
            if len(failed_items) < per_category:
                failed_items.append(item)
            continue
        view = effective_view(row)
        if view is None:  # excluded
            excluded += 1
            continue
        if row.review_status in _REVIEWED:
            reviewed += 1
        key = (view["main_category"] or "", view["sub_category"] or "")
        group = groups.setdefault(key, {"main_category": key[0], "sub_category": key[1], "count": 0, "items": []})
        group["count"] += 1
        wanted = (main_category is None and sub_category is None) or (
            key == (main_category or "", sub_category or ""))
        if wanted and len(group["items"]) < per_category:
            group["items"].append(item)

    group_list = list(groups.values())
    if main_category is not None or sub_category is not None:
        group_list = [g for g in group_list if (g["main_category"], g["sub_category"]) == (main_category or "", sub_category or "")]

    return {
        "topic_key": topic.topic_key,
        "title": topic.title,
        "question_text": topic.question_text,
        "total_answers": len({k for keys in answers_by_source.values() for k in keys}),
        "total_segments": len(rows),
        "reviewed_count": reviewed,
        "excluded_count": excluded,
        "failed_count": failed,
        "failed_items": failed_items,
        "sources": sorted(
            ({"label": label, "answer_count": len(keys)} for label, keys in answers_by_source.items()),
            key=lambda s: -s["answer_count"],
        ),
        "groups": sorted(group_list, key=lambda g: -g["count"]),
    }

