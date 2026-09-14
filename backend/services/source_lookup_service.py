"""

Response_Classification 的來源相關共用查詢邏輯，抽出來給
services/review_service.py（Phase 3）與 Aggregation / Report 相關服務
（Phase 4、Phase 5）共用，避免同一套「survey/user_upload 該怎麼從
Response_Classification 反查回 owner / question_type / 同一分析單位
底下有哪些列」的邏輯，在多個檔案裡各寫一份、規則跑掉。

不包含任何業務規則判斷（confirm/exclude、aggregation 分組邏輯、
report 產生流程等），純粹是查詢輔助。
"""

from models import Response_Classification, Survey_Response, Survey_Template, Uploaded_Answer
from response_classification import SOURCE_TYPE_SURVEY, SOURCE_TYPE_USER_UPLOAD


def get_owner_user_id(classification):
    """回傳這筆 classification 所屬 survey/upload 的擁有者 user_id，
    查不到（資料缺失或舊資料沒有 owner）回傳 None。"""
    if classification.source_type == SOURCE_TYPE_SURVEY:
        survey_response = Survey_Response.query.get(classification.response_id)
        if survey_response is None:
            return None
        template = Survey_Template.query.get(survey_response.template_id)
        return template.user_id if template else None

    if classification.source_type == SOURCE_TYPE_USER_UPLOAD:
        uploaded_answer = Uploaded_Answer.query.get(classification.uploaded_answer_id)
        return uploaded_answer.user_id if uploaded_answer else None

    return None


def resolve_question_type(classification):
    """回傳這筆 classification 對應的 question_type
    （leadership_and_dept / career_and_feedback），查不到回傳 None。"""
    if classification.source_type == SOURCE_TYPE_SURVEY:
        survey_response = Survey_Response.query.get(classification.response_id)
        if survey_response is None:
            return None
        template = Survey_Template.query.get(survey_response.template_id)
        if template is None or not template.question_json:
            return None
        for item in template.question_json.get("items", []):
            if item.get("id") == classification.question_id:
                return item.get("question_type")
        return None

    if classification.source_type == SOURCE_TYPE_USER_UPLOAD:
        uploaded_answer = Uploaded_Answer.query.get(classification.uploaded_answer_id)
        return uploaded_answer.question_type if uploaded_answer else None

    return None


def get_survey_owner(template_id):
    """Report API 用：直接給 template_id 查 owner（不透過某一筆
    classification），readiness/generate/versions 這幾個端點在還沒有
    任何 classification 存在時也要能做 ownership 檢查。"""
    template = Survey_Template.query.get(template_id)
    return template.user_id if template else None


def get_upload_batch_owner(upload_batch_id):
    """Report API 用：直接給 upload_batch_id 查 owner。同一次上傳的
    每一列 Uploaded_Answer.user_id 理論上都相同（upload 路由整批寫入
    同一個 authenticated user_id），這裡只需要取任一筆確認即可，不用
    要求全部逐筆比對。"""
    uploaded_answer = Uploaded_Answer.query.filter_by(upload_batch_id=upload_batch_id).first()
    return uploaded_answer.user_id if uploaded_answer else None


def get_source_owner(source_type, template_id=None, upload_batch_id=None):
    if source_type == SOURCE_TYPE_SURVEY:
        return get_survey_owner(template_id)
    if source_type == SOURCE_TYPE_USER_UPLOAD:
        return get_upload_batch_owner(upload_batch_id)
    return None


def response_dedup_key(classification):
    """
    用來判斷「這幾筆 Response_Classification 是不是同一份原始回答拆
    出來的」的 key。同一份原始回答（同一個 response_id，或同一個
    uploaded_answer_id）不論拆成幾個 segment，這裡都回傳同一個 key。

    survey     ：("survey", response_id)
    user_upload：("user_upload", uploaded_answer_id)
    """
    if classification.source_type == SOURCE_TYPE_SURVEY:
        return (SOURCE_TYPE_SURVEY, classification.response_id)
    return (SOURCE_TYPE_USER_UPLOAD, classification.uploaded_answer_id)


def fetch_classifications_in_scope(source_type, template_id=None, upload_batch_id=None, review_statuses=None):
    """
    取出「同一個分析單位」（同一份 survey 的 template_id，或同一次
    upload 的 upload_batch_id）底下的所有 Response_Classification，
    可選 review_statuses 篩選（不篩選就回傳全部）。

    這是 Aggregation Readiness 與 Aggregation 本身唯一的資料來源
    查詢入口，確保兩邊看到的「這個分析單位有哪些列」定義完全一致。
    """
    query = Response_Classification.query.filter(
        Response_Classification.source_type == source_type
    )

    if source_type == SOURCE_TYPE_SURVEY:
        if template_id is None:
            raise ValueError("source_type=survey 時必須提供 template_id")
        response_ids = [
            r.response_id for r in Survey_Response.query.filter_by(template_id=template_id).all()
        ]
        if not response_ids:
            return []
        query = query.filter(Response_Classification.response_id.in_(response_ids))
    elif source_type == SOURCE_TYPE_USER_UPLOAD:
        if upload_batch_id is None:
            raise ValueError("source_type=user_upload 時必須提供 upload_batch_id")
        query = query.filter(Response_Classification.upload_batch_id == upload_batch_id)
    else:
        raise ValueError(f"source_type 只能是 {SOURCE_TYPE_SURVEY!r} 或 {SOURCE_TYPE_USER_UPLOAD!r}")

    if review_statuses is not None:
        query = query.filter(Response_Classification.review_status.in_(review_statuses))

    return query.all()
