"""
分類流程相關的資料模型（原分散於四個檔案，2026-09 合併為單一檔案）：

    Uploaded_Answer              ：外部 Excel/CSV 上傳的原始文字保存層
    Response_Segmentation_Status ：回答層級的拆分（segmentation）狀態紀錄
    Response_Classification      ：AI 分類結果（一列 = 一個真實 segment）
    Classification_Review        ：Human Review Conversation 會話
    Classification_Review_Message：Human Review Conversation 單輪訊息

這五個 model 圍繞著同一條「上傳/填答 → 拆分 → 分類 → 人工審核」流程，
彼此透過 ForeignKey 緊密關聯，因此合併為一個檔案，比照本專案 taxonomy.py
（Topic / Taxonomy_Version / Taxonomy_Category 三個 model 共用一檔）已經
採用的方式，不再依 model 逐一拆檔。原本各自檔案內的設計說明全數保留於
對應區塊，僅调整檔案結構，不變更任何欄位、行為或資料庫 schema。
"""

from sqlalchemy import CheckConstraint, event

from extensions import db, taiwan_now


# ═══════════════════════════════════════════════════════════════
# Uploaded_Answer：外部上傳的原始文字保存層
# ═══════════════════════════════════════════════════════════════
#
# 角色對應 survey 來源的 Survey_Response：不管 question_type routing
# 判斷不判斷得出來，原始 answer_text 都先進這張表，不會因為判斷不出來
# 就整批丟棄。
#
# v1 採單表設計（不拆 Upload_Batch）：question_type / source_column
# 在同一批次的每一列重複儲存，因為目前一次上傳只有一個檔案、一個
# 文字欄位，重複儲存的成本很低；等未來上傳量變大有需要，再考慮
# 拆成批次表 + 列表兩張表。
#
# question_type 為 NULL，代表這批資料目前無法自動 routing、待處理，
# 不另外增加 status 欄位表達這件事。
#
# user_id：Human Review 權限判斷需要知道「這批上傳是誰的」，因此補上
# 這個欄位當作 user_upload 來源的 ownership 依據（對應 survey 來源用
# Survey_Template.user_id 判斷 ownership 的方式）。
#
#     欄位設計為 nullable=True，只是為了相容 migration 之前就存在的
#     舊資料列（那些列沒有機會補回真正的上傳者）。這不代表新資料可以
#     沒有 owner——routes/classifications/classification.py 的上傳路由
#     從這次 migration 之後，一律要求先通過 verify_token() 才能呼叫，
#     並強制把 authenticated user_id 寫入這個欄位；路由層本身就不允許
#     產生 user_id 為 None 的新列，nullable=True 純粹是資料庫層級對
#     舊資料的相容設計，不是允許新資料略過 owner 的後門。

class Uploaded_Answer(db.Model):
    __tablename__ = "Uploaded_Answer"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    upload_batch_id = db.Column(db.String(50), nullable=False)


    user_id = db.Column(
        db.Integer,
        db.ForeignKey("User.user_id", ondelete="SET NULL"),
        nullable=True,
    )

    source_column = db.Column(db.String(255), nullable=False)
    row_index = db.Column(db.Integer, nullable=False)

    answer_text = db.Column(db.Text, nullable=False)

    # routing 判斷結果：leadership_and_dept / career_and_feedback / NULL
    # NULL = 尚未判斷出來、待處理，不代表錯誤
    question_type = db.Column(db.String(50), nullable=True)

    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=taiwan_now
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "upload_batch_id": self.upload_batch_id,
            "user_id": self.user_id,
            "source_column": self.source_column,
            "row_index": self.row_index,
            "answer_text": self.answer_text,
            "question_type": self.question_type,
            "created_at": (
                self.created_at.isoformat() if self.created_at else None
            ),
        }


# ═══════════════════════════════════════════════════════════════
# Response_Segmentation_Status：回答層級的拆分（segmentation）狀態紀錄
# ═══════════════════════════════════════════════════════════════
#
# 跟 Response_Classification 是不同粒度的兩張表：
#     Response_Classification：一列 = 一個真實 segment（AI 分類結果）
#     Response_Segmentation_Status：一列 = 一則回答（response_id/
#         upload_batch_id + question_id）目前的拆分現況快照
#
# 兩張表用 (source_type, response_id/upload_batch_id, question_id)
# 互相對應，但不建立正式的 SQL 外鍵互相指向對方——兩者是平行關係，
# 不是誰從屬於誰，各自的外鍵都是直接指向 Survey_Response。
#
# 這張表刻意維持最小範圍：只存「目前狀態」，不是完整的歷史 log 系統
# （不記錄重跑次數、每次重跑的細節等），如果之後需要更完整的歷史
# 追蹤，屬於另一個獨立的擴充決定，不在這張表的範圍內。

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
            """
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


# ═══════════════════════════════════════════════════════════════
# Response_Classification：AI 分類結果（一列 = 一個真實 segment）
# ═══════════════════════════════════════════════════════════════

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
    # 【修正】原本是 String(20)，但 services/classify_v2.py 會寫入
    # "methodology_not_found"（22 字元），超過 20 就會讓 INSERT 直接
    # 撞到 MySQL 的 "Data too long for column 'status'" 炸掉整筆分類。
    # 目前實際會寫入這個欄位的值只有 "pending" / "completed" /
    # "methodology_not_found" / "failed"（見 classify_v2.py），
    # 50 字元留了足夠餘裕，之後合理範圍內新增狀態值也不會再重演
    # 同樣的問題。這裡只放寬長度、不縮短、不改變任何既有資料。
    status = db.Column(db.String(50), nullable=False, default=STATUS_PENDING)
    review_status = db.Column(
        db.String(20), nullable=False, default=REVIEW_STATUS_PENDING
    )
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=taiwan_now
    )

    # ── Taxonomy version 追溯（Phase B 新增，additive-only）─────────
    # 這筆分類實際使用哪一版 Published Taxonomy 產生（見
    # services/taxonomy_service.py）。nullable=True 是刻意的：
    #   - 舊資料（Phase B 之前，讀 DEFAULT_PROMPT_* + Prompt_Template
    #     產生的分類結果）沒有對應的 Taxonomy_Version，永遠是 NULL，
    #     不回填、不猜測對應到哪一版。
    #   - 不用 ondelete="CASCADE"：Taxonomy_Version 之後如果被刪除
    #     （目前沒有任何流程會這麼做，但不排除未來 Admin 清除舊草稿），
    #     不應該連帶砍掉已經產生的分類結果，比照 Uploaded_Answer.user_id
    #     的作法改用 SET NULL。
    taxonomy_version_id = db.Column(
        db.Integer,
        db.ForeignKey("Taxonomy_Version.version_id", ondelete="SET NULL"),
        nullable=True,
    )

    # ── Confidence Gate（新增，additive-only）───────────────────
    # 這三個欄位是「AI 分類當下的判斷與送審原因」的歷史紀錄，永久
    # 保留：review_status 之後不管變成 confirmed / modified /
    # excluded 哪一種，都不會清除或重算這三個欄位——它們回答的是
    # 「AI 當時為什麼建議/不建議人工介入」，review_status 回答的是
    # 「人工確認流程目前走到哪裡」，兩者是獨立、互不覆寫的概念。
    #
    # confidence：模型自陳信心分數（0.0～1.0），是 Gemini 主觀輸出的
    # 數字，不是 calibrated probability，不代表「正確率」。缺失、
    # 非數值、或超出 [0,1] 範圍一律視為 invalid_confidence（見
    # services/confidence_gate.py），這裡刻意 nullable=True 存這些
    # 異常情況的原始值（通常是 None），不偷偷補一個看起來正常的數字。
    confidence = db.Column(db.Float, nullable=True)

    # needs_human_review / review_flag_reason：由
    # services.confidence_gate.evaluate_confidence_gate() 逐 segment
    # 判斷產生，寫入當下就固定，之後不會因為人工審核流程而被改寫。
    needs_human_review = db.Column(db.Boolean, nullable=False, default=False)
    review_flag_reason = db.Column(db.String(50), nullable=True)

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
            "taxonomy_version_id": self.taxonomy_version_id,
            "confidence": self.confidence,
            "needs_human_review": self.needs_human_review,
            "review_flag_reason": self.review_flag_reason,
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


# ═══════════════════════════════════════════════════════════════
# Classification_Review / Classification_Review_Message：
# Human Review Conversation 的獨立 persistence
# ═══════════════════════════════════════════════════════════════
#
# 比照 Response_Classification / Response_Segmentation_Status 的風格
# 另外建表，不塞進既有的 Chat_History（那是給問卷填答聊天室用的，跟
# 「針對某一筆 Response_Classification 做分類覆核」是完全不同的資料
# 語意與生命週期）。
#
# 兩張表：
#     Classification_Review：一列 = 針對某一筆 Response_Classification 的
#         一次 review 會話（review session）。
#     Classification_Review_Message：一列 = 該會話裡的一輪訊息（User 發的
#         或 AI 回的）。role='assistant' 的訊息如果有附帶「這輪 AI 提出的
#         candidate 分類」，會存在 candidate_* 欄位裡。
#
# 【重要】這兩張表本身只負責「儲存對話與 candidate 歷史」，不負責業務
# 規則判斷（例如 candidate 何時可以變成 final、taxonomy 合法性檢查等）。
# 那些屬於 services/review_service.py 與 services/review_ai_service.py
# 的職責，這裡只負責把資料結構立好。
#
# Classification_Review.status 目前先給一個寬鬆的 String 欄位（不加
# CheckConstraint），因為完整的狀態機（例如 in_progress / confirmed /
# excluded 分別對應什麼、什麼時候可以轉換）屬於 service 邏輯的一部分，
# 不在這裡的 schema 範圍內先寫死，避免之後定案時要跟著改 DB constraint。

class Classification_Review(db.Model):
    __tablename__ = "Classification_Review"

    review_id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    classification_id = db.Column(
        db.Integer,
        db.ForeignKey("Response_Classification.classification_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("User.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    status = db.Column(db.String(20), nullable=False, default="in_progress")

    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=taiwan_now
    )
    confirmed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    messages = db.relationship(
        "Classification_Review_Message",
        backref="review",
        cascade="all, delete-orphan",
        order_by="Classification_Review_Message.created_at",
    )

    def to_dict(self, include_messages: bool = False) -> dict:
        data = {
            "review_id": self.review_id,
            "classification_id": self.classification_id,
            "user_id": self.user_id,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "confirmed_at": self.confirmed_at.isoformat() if self.confirmed_at else None,
        }
        if include_messages:
            data["messages"] = [m.to_dict() for m in self.messages]
        return data


class Classification_Review_Message(db.Model):
    __tablename__ = "Classification_Review_Message"

    message_id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    review_id = db.Column(
        db.Integer,
        db.ForeignKey("Classification_Review.review_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # user / assistant，比照 Chat_History.sender_type 的簡單字串風格
    role = db.Column(db.String(10), nullable=False)

    # User 訊息：原文意見。Assistant 訊息：AI 的自然語言回覆。
    content = db.Column(db.Text, nullable=False)

    # Assistant 訊息才會有 candidate_* 欄位，User 訊息這些欄位永遠是 None。
    candidate_main_category = db.Column(db.String(100))
    candidate_sub_category = db.Column(db.String(100))
    candidate_secondary_main_category = db.Column(db.String(100))
    candidate_secondary_sub_category = db.Column(db.String(100))
    candidate_reasoning = db.Column(db.Text)

    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=taiwan_now
    )

    def to_dict(self) -> dict:
        return {
            "message_id": self.message_id,
            "review_id": self.review_id,
            "role": self.role,
            "content": self.content,
            "candidate_main_category": self.candidate_main_category,
            "candidate_sub_category": self.candidate_sub_category,
            "candidate_secondary_main_category": self.candidate_secondary_main_category,
            "candidate_secondary_sub_category": self.candidate_secondary_sub_category,
            "candidate_reasoning": self.candidate_reasoning,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
