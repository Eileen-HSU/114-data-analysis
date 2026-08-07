from sqlalchemy import CheckConstraint, event

from extensions import db, taiwan_now


# ── 允許的來源類型──────────────
SOURCE_TYPE_SURVEY = "survey"
SOURCE_TYPE_USER_UPLOAD = "user_upload"
ALLOWED_SOURCE_TYPES = {SOURCE_TYPE_SURVEY, SOURCE_TYPE_USER_UPLOAD}

# 分類狀態
STATUS_PENDING = "pending"


class Response_Classification(db.Model):
    __tablename__ = "Response_Classification"

    # survey 一定要有 response_id、
    # user_upload 一定不能有 response_id。
    __table_args__ = (
        CheckConstraint(
            f"""
            (
                source_type = '{SOURCE_TYPE_SURVEY}'
                AND response_id IS NOT NULL
            )
            OR
            (
                source_type = '{SOURCE_TYPE_USER_UPLOAD}'
                AND response_id IS NULL
            )
            """,
            name="chk_response_classification_source",
        ),
    )

    classification_id = db.Column(
        db.Integer, primary_key=True, autoincrement=True
    )

    # 只有系統內建問卷回答才可關聯 Survey_Response
    # 外部上傳資料必須為 None
    response_id = db.Column(
        db.Integer,
        db.ForeignKey("Survey_Response.response_id", ondelete="CASCADE"),
        nullable=True,
    )
    source_type = db.Column(db.String(20), nullable=False)

    # 系統問卷：題目 UUID；外部上傳：欄位名稱、列號或自訂識別碼
    question_id = db.Column(db.String(255), nullable=True)

    # ── 原始資料（AI 不可修改）───────────────────────────────
    answer_text = db.Column(db.Text, nullable=False)

    # ── AI 分類結果 ───────────────────────────────────────
    main_category = db.Column(db.String(100))
    sub_category = db.Column(db.String(100))
    reasoning = db.Column(db.Text)
    summary = db.Column(db.Text)
    methodology = db.Column(db.String(100))

    # ── 狀態與時間戳 ──────────────────────────────────────
    status = db.Column(db.String(20), nullable=False, default=STATUS_PENDING)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=taiwan_now
    )

    # ── 驗證邏輯 ──────────────────────────────────────────
    def validate_source_relation(self) -> None:
        """驗證資料來源與 response_id 的關係是否合法。

        Raises:
            ValueError: source_type 不合法，或 response_id
                與 source_type 的搭配不符合規則。
        """
        if self.source_type not in ALLOWED_SOURCE_TYPES:
            raise ValueError(
                f"source_type 只能是 {sorted(ALLOWED_SOURCE_TYPES)} 其中之一"
            )

        if self.source_type == SOURCE_TYPE_SURVEY and self.response_id is None:
            raise ValueError("系統內建問卷分類必須提供 response_id")

        if (
            self.source_type == SOURCE_TYPE_USER_UPLOAD
            and self.response_id is not None
        ):
            raise ValueError(
                "外部上傳分類不可綁定 Survey_Response，"
                "response_id 必須為 None"
            )

    def to_dict(self) -> dict:
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
                self.created_at.isoformat() if self.created_at else None
            ),
        }


@event.listens_for(Response_Classification, "before_insert")
@event.listens_for(Response_Classification, "before_update")
def validate_response_classification(mapper, connection, target):
    """每次 INSERT 或 UPDATE 前自動檢查，
    防止外部上傳資料誤綁系統問卷 response_id。
    """
    target.validate_source_relation()