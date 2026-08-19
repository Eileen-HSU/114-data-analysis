from sqlalchemy import CheckConstraint, event

from extensions import db, taiwan_now


# ── 允許的來源類型──────────────
SOURCE_TYPE_SURVEY = "survey"
SOURCE_TYPE_USER_UPLOAD = "user_upload"
ALLOWED_SOURCE_TYPES = {SOURCE_TYPE_SURVEY, SOURCE_TYPE_USER_UPLOAD}

# 分類狀態（AI 處理這個 segment 是否成功，跟 review_status 是兩個獨立維度）
STATUS_PENDING = "pending"

# 人工審核狀態（review_status）：跟 status 分開，status 代表 AI 有沒有處理
# 成功，review_status 代表人有沒有看過、同不同意這個 segment 的分類結果。
#   pending_review：AI 已產生結果，User 尚未確認。
#   confirmed     ：User 沒有進 Review Conversation，直接接受 AI 原始結果。
#   modified      ：曾進過 Review Conversation 並按下確認（即使最後結論
#                    跟 AI original 完全一樣，仍是 modified，因為「User
#                    曾提出異議」本身就是重要 feedback data）。
#   excluded      ：User 決定這個 segment 不納入後續分析。是軟刪除標記，
#                    不會真的砍掉這筆列，保留給之後檢討 AI 拆分/分類
#                    準確率使用。
REVIEW_STATUS_PENDING = "pending_review"
REVIEW_STATUS_CONFIRMED = "confirmed"
REVIEW_STATUS_MODIFIED = "modified"
REVIEW_STATUS_EXCLUDED = "excluded"
ALLOWED_REVIEW_STATUSES = {
    REVIEW_STATUS_PENDING,
    REVIEW_STATUS_CONFIRMED,
    REVIEW_STATUS_MODIFIED,
    REVIEW_STATUS_EXCLUDED,
}

# 舊值相容：資料庫裡如果還留著 migration 前寫入的 "removed"，
# 一律視同 "excluded"。目前 repo 內沒有任何寫入路徑會產生 "removed"
# （review_status 尚未被任何 route 實際使用過），但保留這個常數
# 方便 app.py 的 runtime migration 明確引用，不用寫死字串。
_LEGACY_REVIEW_STATUS_REMOVED = "removed"


class Response_Classification(db.Model):
    __tablename__ = "Response_Classification"

    # survey 一定要有 response_id、沒有 upload_batch_id；
    # user_upload 一定不能有 response_id、一定要有 upload_batch_id。
    __table_args__ = (
        CheckConstraint(
            f"""
            (
                source_type = '{SOURCE_TYPE_SURVEY}'
                AND response_id IS NOT NULL
                AND upload_batch_id IS NULL
                AND uploaded_answer_id IS NULL
            )
            OR
            (
                source_type = '{SOURCE_TYPE_USER_UPLOAD}'
                AND response_id IS NULL
                AND upload_batch_id IS NOT NULL
                AND uploaded_answer_id IS NOT NULL
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

    # 外部上傳專用：同一次上傳（一次只能上傳一個檔案）產生一個 UUID，
    # 同一批檔案裡所有列共用這個值，用來區分不同次上傳
    # （即使是同一份檔案重新上傳，也會是新的 upload_batch_id）。
    # survey 來源一律為 None。
    upload_batch_id = db.Column(db.String(50), nullable=True)

    # 對應外部上傳的原始文字（Uploaded_Answer.id）。
    # 刻意「不」加 unique=True：一筆 Uploaded_Answer 拆分後可能對應
    # 0~N 個 segment，所以會有多筆 Response_Classification 共用同一個
    # uploaded_answer_id，這是正常且必要的行為，不是資料重複。
    # 如果之後有人想在這裡加 UniqueConstraint，請先確認清楚這一點，
    # 加了會直接讓 multi-segment 寫入從第二個 segment 開始失敗。
    uploaded_answer_id = db.Column(
        db.Integer,
        db.ForeignKey("Uploaded_Answer.id", ondelete="CASCADE"),
        nullable=True,
    )

    # ── 原始資料（AI 不可修改）───────────────────────────────
    answer_text = db.Column(db.Text, nullable=False)

    # 這個 segment 在 answer_text 裡的原文座標（左閉右開區間）。
    # 一列 = 一個真實 segment，不允許用這兩個欄位代表整則回答的
    # 特殊狀態列（回答層級的狀態另外存在 Response_Segmentation_Status）。
    segment_start = db.Column(db.Integer, nullable=False)
    segment_end = db.Column(db.Integer, nullable=False)

    # ── AI 分類結果（AI ORIGINAL RESULT，Human Review 絕對不能覆寫）──
    main_category = db.Column(db.String(100))
    sub_category = db.Column(db.String(100))
    # 次要分類可以跨大類別，因此 secondary_main_category 是獨立欄位，
    # 但這個值永遠是後端用 secondary_sub_category 查
    # services.subcategory_methodology.get_methodology() 表得到的結果，
    # 不是 Gemini 自己輸出的欄位（Gemini 的輸出格式沒有這個欄位）。
    secondary_main_category = db.Column(db.String(100))
    secondary_sub_category = db.Column(db.String(100))
    reasoning = db.Column(db.Text)
    summary = db.Column(db.Text)
    methodology = db.Column(db.String(100))
    citation = db.Column(db.Text)
    secondary_methodology = db.Column(db.String(100))
    secondary_citation = db.Column(db.Text)

    # ── Human Review 最終確認結果（final_*）─────────────────
    # 只有 User 在 Review Conversation 中明確按下確認後才會寫入，
    # 這之前 Review Conversation 過程中的所有 AI revision 都只是
    # candidate（存在 Classification_Review_Message，不會出現在這裡）。
    # review_status = confirmed：沒有進過 Review Conversation，
    #     effective 分類直接讀 AI original 欄位，這裡維持 None。
    # review_status = modified：曾進過 Review Conversation並確認，
    #     這裡一定有值（即使最終跟 AI original 一樣也會填，因為
    #     「User 曾對 AI 結果產生異議」本身是重要 feedback data）。
    final_main_category = db.Column(db.String(100))
    final_sub_category = db.Column(db.String(100))
    final_secondary_main_category = db.Column(db.String(100))
    final_secondary_sub_category = db.Column(db.String(100))
    final_reasoning = db.Column(db.Text)

    # ── 狀態與時間戳 ──────────────────────────────────────
    status = db.Column(db.String(20), nullable=False, default=STATUS_PENDING)
    review_status = db.Column(
        db.String(20), nullable=False, default=REVIEW_STATUS_PENDING
    )
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=taiwan_now
    )

    # ── 驗證邏輯 ──────────────────────────────────────────
    def validate_source_relation(self) -> None:
        """驗證資料來源與 response_id / upload_batch_id 的關係是否合法。

        Raises:
            ValueError: source_type 不合法，或 response_id /
                upload_batch_id 與 source_type 的搭配不符合規則。
        """
        if self.source_type not in ALLOWED_SOURCE_TYPES:
            raise ValueError(
                f"source_type 只能是 {sorted(ALLOWED_SOURCE_TYPES)} 其中之一"
            )

        if self.source_type == SOURCE_TYPE_SURVEY:
            if self.response_id is None:
                raise ValueError("系統內建問卷分類必須提供 response_id")
            if self.upload_batch_id is not None:
                raise ValueError(
                    "系統內建問卷分類不可帶有 upload_batch_id，"
                    "upload_batch_id 必須為 None"
                )
            if self.uploaded_answer_id is not None:
                raise ValueError(
                    "系統內建問卷分類不可帶有 uploaded_answer_id，"
                    "uploaded_answer_id 必須為 None"
                )

        if self.source_type == SOURCE_TYPE_USER_UPLOAD:
            if self.response_id is not None:
                raise ValueError(
                    "外部上傳分類不可綁定 Survey_Response，"
                    "response_id 必須為 None"
                )
            if self.upload_batch_id is None:
                raise ValueError("外部上傳分類必須提供 upload_batch_id")
            if self.uploaded_answer_id is None:
                raise ValueError("外部上傳分類必須提供 uploaded_answer_id")

    def to_dict(self) -> dict:
        return {
            "classification_id": self.classification_id,
            "response_id": self.response_id,
            "upload_batch_id": self.upload_batch_id,
            "uploaded_answer_id": self.uploaded_answer_id,
            "source_type": self.source_type,
            "question_id": self.question_id,
            "answer_text": self.answer_text,
            "segment_start": self.segment_start,
            "segment_end": self.segment_end,
            "main_category": self.main_category,
            "sub_category": self.sub_category,
            "secondary_main_category": self.secondary_main_category,
            "secondary_sub_category": self.secondary_sub_category,
            "reasoning": self.reasoning,
            "summary": self.summary,
            "methodology": self.methodology,
            "citation": self.citation,
            "secondary_methodology": self.secondary_methodology,
            "secondary_citation": self.secondary_citation,
            "final_main_category": self.final_main_category,
            "final_sub_category": self.final_sub_category,
            "final_secondary_main_category": self.final_secondary_main_category,
            "final_secondary_sub_category": self.final_secondary_sub_category,
            "final_reasoning": self.final_reasoning,
            "status": self.status,
            "review_status": self.review_status,
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