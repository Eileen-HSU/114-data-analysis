"""

回答層級的拆分（segmentation）狀態紀錄。

跟 Response_Classification 是不同粒度的兩張表：
    Response_Classification：一列 = 一個真實 segment（AI 分類結果）
    Response_Segmentation_Status：一列 = 一則回答（response_id/
        upload_batch_id + question_id）目前的拆分現況快照

兩張表用 (source_type, response_id/upload_batch_id, question_id)
互相對應，但不建立正式的 SQL 外鍵互相指向對方——兩者是平行關係，
不是誰從屬於誰，各自的外鍵都是直接指向 Survey_Response。

這張表刻意維持最小範圍：只存「目前狀態」，不是完整的歷史 log 系統
（不記錄重跑次數、每次重跑的細節等），如果之後需要更完整的歷史
追蹤，屬於另一個獨立的擴充決定，不在這張表的範圍內。
"""

from sqlalchemy import CheckConstraint, event

from extensions import db, taiwan_now


# 拆分狀態：這則回答整體的拆分結果，跟 Response_Classification 裡
# 單一 segment 的 status／review_status 是不同粒度的概念。
SEGMENTATION_STATUS_PENDING = "pending"
SEGMENTATION_STATUS_COMPLETED = "completed"
SEGMENTATION_STATUS_PARTIAL_FAILED = "partial_failed"
SEGMENTATION_STATUS_FAILED = "failed"
ALLOWED_SEGMENTATION_STATUSES = {
    SEGMENTATION_STATUS_PENDING,
    SEGMENTATION_STATUS_COMPLETED,
    SEGMENTATION_STATUS_PARTIAL_FAILED,
    SEGMENTATION_STATUS_FAILED,
}


class Response_Segmentation_Status(db.Model):
    __tablename__ = "Response_Segmentation_Status"

    # 與 Response_Classification 完全一致的來源規則：
    # survey 一定要有 response_id、沒有 upload_batch_id；
    # user_upload 一定不能有 response_id、一定要有 upload_batch_id。
    __table_args__ = (
        CheckConstraint(
            f"""
            (
                source_type = 'survey'
                AND response_id IS NOT NULL
                AND upload_batch_id IS NULL
                AND uploaded_answer_id IS NULL
            )
            OR
            (
                source_type = 'user_upload'
                AND response_id IS NULL
                AND upload_batch_id IS NOT NULL
                AND uploaded_answer_id IS NOT NULL
            )
            """,
            name="chk_response_segmentation_status_source",
        ),
        # 最終唯一性原則：
        #   survey：      (response_id, question_id) 唯一
        #   user_upload： uploaded_answer_id 唯一（見下方欄位定義的 unique=True）
        # 這裡加的是 survey 那一半。對 user_upload 列而言，response_id
        # 恆為 NULL，依 MySQL 對 UNIQUE 約束裡 NULL 的標準語意（多欄位
        # 唯一約束只要有一欄是 NULL，該列就不會跟任何其他列產生衝突），
        # 這個約束對 user_upload 列完全不會生效、也不會誤擋——
        # user_upload 的唯一性保護，繼續完全依賴下面 uploaded_answer_id
        # 欄位本身的 unique=True，兩者互不干擾。
        db.UniqueConstraint(
            "response_id", "question_id",
            name="uq_response_segmentation_status_response_question",
        ),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    response_id = db.Column(
        db.Integer,
        db.ForeignKey("Survey_Response.response_id", ondelete="CASCADE"),
        nullable=True,
    )
    upload_batch_id = db.Column(db.String(50), nullable=True)

    # 對應外部上傳的原始文字（Uploaded_Answer.id）。
    # 這裡「要」加 unique=True：一筆 Uploaded_Answer 只需要一筆整體
    # segmentation 狀態快照，跟 Response_Classification.uploaded_answer_id
    # 刻意不加 unique 的原因不同（那邊是 1 筆對應 0~N 個 segment），
    # 不要把兩邊搞混。MySQL 對單一欄位的 UNIQUE 允許多個 NULL 共存，
    # 但非 NULL 值彼此仍會真正互斥，這裡的用法可以正常生效。
    uploaded_answer_id = db.Column(
        db.Integer,
        db.ForeignKey("Uploaded_Answer.id", ondelete="CASCADE"),
        nullable=True,
        unique=True,
    )
    question_id = db.Column(db.String(255), nullable=True)
    source_type = db.Column(db.String(20), nullable=False)

    segmentation_status = db.Column(
        db.String(20), nullable=False, default=SEGMENTATION_STATUS_PENDING
    )
    # 拆分驗證失敗時的細節（哪個 segment_text、卡在哪條驗證規則），
    # 供前端提示與除錯使用；不是完整歷史 log，只存「最新一次」的狀況。
    error_detail = db.Column(db.Text, nullable=True)

    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=taiwan_now
    )
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=taiwan_now, onupdate=taiwan_now
    )

    # ── 驗證邏輯（比照 Response_Classification 的既有風格）───────
    def validate_source_relation(self) -> None:
        """驗證資料來源與 response_id / upload_batch_id 的關係是否合法。

        Raises:
            ValueError: source_type 不合法，或 response_id /
                upload_batch_id 與 source_type 的搭配不符合規則。
        """
        allowed = {"survey", "user_upload"}
        if self.source_type not in allowed:
            raise ValueError(f"source_type 只能是 {sorted(allowed)} 其中之一")

        if self.source_type == "survey":
            if self.response_id is None:
                raise ValueError("survey 來源必須提供 response_id")
            if self.upload_batch_id is not None:
                raise ValueError(
                    "survey 來源不可帶有 upload_batch_id，必須為 None"
                )
            if self.uploaded_answer_id is not None:
                raise ValueError(
                    "survey 來源不可帶有 uploaded_answer_id，必須為 None"
                )

        if self.source_type == "user_upload":
            if self.response_id is not None:
                raise ValueError(
                    "user_upload 來源不可綁定 Survey_Response，"
                    "response_id 必須為 None"
                )
            if self.upload_batch_id is None:
                raise ValueError("user_upload 來源必須提供 upload_batch_id")
            if self.uploaded_answer_id is None:
                raise ValueError("user_upload 來源必須提供 uploaded_answer_id")

        if self.segmentation_status not in ALLOWED_SEGMENTATION_STATUSES:
            raise ValueError(
                f"segmentation_status 只能是 "
                f"{sorted(ALLOWED_SEGMENTATION_STATUSES)} 其中之一"
            )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "response_id": self.response_id,
            "upload_batch_id": self.upload_batch_id,
            "uploaded_answer_id": self.uploaded_answer_id,
            "question_id": self.question_id,
            "source_type": self.source_type,
            "segmentation_status": self.segmentation_status,
            "error_detail": self.error_detail,
            "created_at": (
                self.created_at.isoformat() if self.created_at else None
            ),
            "updated_at": (
                self.updated_at.isoformat() if self.updated_at else None
            ),
        }


@event.listens_for(Response_Segmentation_Status, "before_insert")
@event.listens_for(Response_Segmentation_Status, "before_update")
def validate_response_segmentation_status(mapper, connection, target):
    """每次 INSERT 或 UPDATE 前自動檢查，
    防止資料寫成 source_type 與 response_id/upload_batch_id 不合法的組合。
    """
    target.validate_source_relation()