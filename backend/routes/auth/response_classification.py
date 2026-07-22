"""
Response_Classification：存放每一則「文字類問卷回答」的 AI 分類結果

來源區分：
1. source_type = 'survey'
   - 系統內建問卷回答
   - response_id 必須對應 Survey_Response.response_id

2. source_type = 'user_upload'
   - 使用者外部上傳的 Excel／文件內容
   - response_id 必須為 None

一份系統問卷回覆可能有多題文字題，因此一筆 Survey_Response
可以對應多筆 Response_Classification。
"""

from datetime import datetime, timedelta

from sqlalchemy import CheckConstraint, event
from extensions import db


def taiwan_now():
    return datetime.utcnow() + timedelta(hours=8)


class Response_Classification(db.Model):
    __tablename__ = "Response_Classification"

    __table_args__ = (
        CheckConstraint(
            """
            (
                source_type = 'survey'
                AND response_id IS NOT NULL
            )
            OR
            (
                source_type = 'user_upload'
                AND response_id IS NULL
            )
            """,
            name="chk_response_classification_source"
        ),
    )

    classification_id = db.Column(
        db.Integer,
        primary_key=True,
        autoincrement=True
    )

    # 只有系統內建問卷回答才可關聯 Survey_Response
    # 外部上傳資料必須為 None
    response_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "Survey_Response.response_id",
            ondelete="CASCADE"
        ),
        nullable=True
    )

    # survey：系統內建問卷
    # user_upload：外部上傳資料
    source_type = db.Column(
        db.String(20),
        nullable=False
    )

    # 系統問卷：題目 UUID
    # 外部上傳：欄位名稱、列號或自訂識別碼
    question_id = db.Column(
        db.String(255),
        nullable=True
    )

    # 原始文字，AI 不可修改
    answer_text = db.Column(
        db.Text,
        nullable=False
    )

    main_category = db.Column(db.String(100))
    sub_category = db.Column(db.String(100))
    reasoning = db.Column(db.Text)
    summary = db.Column(db.Text)
    methodology = db.Column(db.String(100))

    status = db.Column(
        db.String(20),
        nullable=False,
        default="pending"
    )

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=taiwan_now
    )

    def validate_source_relation(self):
        """
        驗證資料來源與 response_id 的關係。

        survey：
            必須有 response_id

        user_upload：
            response_id 必須為 None
        """
        allowed_source_types = {"survey", "user_upload"}

        if self.source_type not in allowed_source_types:
            raise ValueError(
                "source_type 只能是 'survey' 或 'user_upload'"
            )

        if self.source_type == "survey" and self.response_id is None:
            raise ValueError(
                "系統內建問卷分類必須提供 response_id"
            )

        if self.source_type == "user_upload" and self.response_id is not None:
            raise ValueError(
                "外部上傳分類不可綁定 Survey_Response，"
                "response_id 必須為 None"
            )

    def to_dict(self):
        return {
            "classification_id": self.classification_id,
            "response_id": self.response_id,
            "source_type": self.source_type,
            "question_id": self.question_id,
            "answer_text": self.answer_text,
            "main_category": self.main_category,
            "sub_category": self.sub_category,
            "reasoning": self.reasoning,
            "summary": self.summary,
            "methodology": self.methodology,
            "status": self.status,
            "created_at": (
                self.created_at.isoformat()
                if self.created_at
                else None
            ),
        }


@event.listens_for(Response_Classification, "before_insert")
@event.listens_for(Response_Classification, "before_update")
def validate_response_classification(mapper, connection, target):
    """
    每次 INSERT 或 UPDATE 前自動檢查，
    防止外部上傳資料誤綁系統問卷 response_id。
    """
    target.validate_source_relation()