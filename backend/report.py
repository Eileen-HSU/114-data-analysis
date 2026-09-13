"""

Versioned Report Snapshot。

三層 normalized 結構：

    Report
      -> Report_Aggregation      （一列 = 一個 (main_category, sub_category) group）
           -> Report_Aggregation_Item （一列 = 該 group 當時納入的一筆
                                         classification/response snapshot）

設計重點（對應需求文件第十九～二十一節）：

1. Report 是「快照」，不是即時視圖。每次 Generate 都是新的一列
   （version 遞增），不會 overwrite 舊版本；已產生的 Report 內容
   即使之後 Response_Classification 被 Human Review 改變，也不會
   跟著變——所以 Report_Aggregation / Report_Aggregation_Item 裡
   保存的是「當時的數值」，不是只存 FK 之後展示時才去重新查詢
   最新的 Response_Classification。

2. is_outdated 是一個獨立的 flag，由
   services/report_outdated_service.py（Phase 5）在 Human Review
   確認/排除動作發生時集中更新，不是靠「每次打開都重新算」判斷。

3. status（generating / completed / failed）避免「看起來成功但其實
   沒算完」的半成品被當成正式版本使用；只有 completed 的 Report
   才會被視為「已存在的版本」計入 version 序列與 outdated 判斷範圍
   （Phase 5 service 邏輯負責，這裡先把欄位立好）。

Phase 2 只建立 schema，不實作 generate/outdated 的判斷邏輯本身。
"""

from sqlalchemy import CheckConstraint, event

from extensions import db, taiwan_now


SOURCE_TYPE_SURVEY = "survey"
SOURCE_TYPE_USER_UPLOAD = "user_upload"
ALLOWED_REPORT_SOURCE_TYPES = {SOURCE_TYPE_SURVEY, SOURCE_TYPE_USER_UPLOAD}

REPORT_STATUS_GENERATING = "generating"
REPORT_STATUS_COMPLETED = "completed"
REPORT_STATUS_FAILED = "failed"
ALLOWED_REPORT_STATUSES = {
    REPORT_STATUS_GENERATING,
    REPORT_STATUS_COMPLETED,
    REPORT_STATUS_FAILED,
}


class Report(db.Model):
    __tablename__ = "Report"

    # 比照 Response_Classification 的 source invariant 寫法：
    # survey 一定要有 template_id、沒有 upload_batch_id；
    # user_upload 一定不能有 template_id、一定要有 upload_batch_id。
    __table_args__ = (
        CheckConstraint(
            f"""
            (
                source_type = '{SOURCE_TYPE_SURVEY}'
                AND template_id IS NOT NULL
                AND upload_batch_id IS NULL
            )
            OR
            (
                source_type = '{SOURCE_TYPE_USER_UPLOAD}'
                AND template_id IS NULL
                AND upload_batch_id IS NOT NULL
            )
            """,
            name="chk_report_source",
        ),
        # 同一個分析單位（同一份 survey 或同一個 upload batch）內，
        # version 必須唯一遞增，避免兩次併發 generate 產生同一個
        # version 號碼的衝突資料。
        #
        # 這裡刻意不是直接對 (source_type, template_id, upload_batch_id,
        # version) 建 UniqueConstraint：ANSI SQL（MySQL、SQLite、
        # Postgres 皆然）的 UNIQUE 語意是「NULL 不等於 NULL」，而
        # survey 來源的 upload_batch_id 永遠是 NULL、user_upload 來源
        # 的 template_id 永遠是 NULL——用這兩個可為 NULL 的欄位直接做
        # UniqueConstraint，兩筆 NULL 永遠不會被視為衝突，等於這個
        # constraint 對 survey/user_upload 兩種來源都完全不會生效。
        # 改用下面永遠非 NULL 的 source_key（by before_insert/before_update
        # event 自動算出 f"{source_type}:{template_id or upload_batch_id}"）
        # 才能讓 UniqueConstraint 真正生效。
        db.UniqueConstraint(
            "source_key", "version",
            name="uq_report_source_version",
        ),
    )

    report_id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    source_type = db.Column(db.String(20), nullable=False)

    # survey 來源：對應 Survey_Template.template_id
    template_id = db.Column(
        db.Integer,
        db.ForeignKey("Survey_Template.template_id", ondelete="CASCADE"),
        nullable=True,
    )
    # user_upload 來源：對應 Uploaded_Answer.upload_batch_id（字串批次識別碼，
    # 沒有獨立的 Upload_Batch 表可以外鍵，比照 Response_Classification
    # 現有設計直接存字串）
    upload_batch_id = db.Column(db.String(50), nullable=True)

    # 見上方 UniqueConstraint 註解：由 before_insert/before_update event
    # 自動算出，不由呼叫端手動設定。永遠非 NULL，格式固定為
    # "survey:<template_id>" 或 "user_upload:<upload_batch_id>"，
    # 只用來讓 DB 層 UniqueConstraint 能正確生效，不是業務欄位，
    # to_dict() 不會輸出這個欄位。
    source_key = db.Column(db.String(80), nullable=False)

    version = db.Column(db.Integer, nullable=False)

    generated_by = db.Column(
        db.Integer,
        db.ForeignKey("User.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    generated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=taiwan_now
    )

    # 產生當下的統計快照（對應 Aggregation Readiness 的數字），
    # 用來讓使用者事後仍能看到「這個版本是在什麼完成度下產生的」。
    eligible_count_at_generation = db.Column(db.Integer, nullable=False, default=0)
    pending_count_at_generation = db.Column(db.Integer, nullable=False, default=0)
    excluded_count_at_generation = db.Column(db.Integer, nullable=False, default=0)

    status = db.Column(
        db.String(20), nullable=False, default=REPORT_STATUS_GENERATING
    )
    # Human Review 後續若有會影響報告內容的變更，由
    # services/report_outdated_service.py 集中負責把這個欄位設成 True，
    # 不會由任何 route 各自判斷、也不會觸發重新計算。
    is_outdated = db.Column(db.Boolean, nullable=False, default=False)

    # generate 失敗時的除錯資訊，比照 Response_Segmentation_Status.error_detail
    # 的作法，只存最新一次失敗原因，不做完整歷史 log。
    error_detail = db.Column(db.Text, nullable=True)

    aggregations = db.relationship(
        "Report_Aggregation",
        backref="report",
        cascade="all, delete-orphan",
    )

    def compute_source_key(self) -> str:
        if self.source_type == SOURCE_TYPE_SURVEY:
            return f"{SOURCE_TYPE_SURVEY}:{self.template_id}"
        if self.source_type == SOURCE_TYPE_USER_UPLOAD:
            return f"{SOURCE_TYPE_USER_UPLOAD}:{self.upload_batch_id}"
        raise ValueError(f"source_type 只能是 {sorted(ALLOWED_REPORT_SOURCE_TYPES)} 其中之一")

    def to_dict(self) -> dict:
        return {
            "report_id": self.report_id,
            "source_type": self.source_type,
            "template_id": self.template_id,
            "upload_batch_id": self.upload_batch_id,
            "version": self.version,
            "generated_by": self.generated_by,
            "generated_at": self.generated_at.isoformat() if self.generated_at else None,
            "eligible_count_at_generation": self.eligible_count_at_generation,
            "pending_count_at_generation": self.pending_count_at_generation,
            "excluded_count_at_generation": self.excluded_count_at_generation,
            "status": self.status,
            "is_outdated": self.is_outdated,
            "error_detail": self.error_detail,
        }


@event.listens_for(Report, "before_insert")
@event.listens_for(Report, "before_update")
def _set_report_source_key(mapper, connection, target):
    """每次 INSERT / UPDATE 前自動算出 source_key，呼叫端不需要、
    也不應該自己組這個字串（避免格式跟這裡兜不起來，讓
    UniqueConstraint 又失效）。"""
    target.source_key = target.compute_source_key()


class Report_Aggregation(db.Model):
    __tablename__ = "Report_Aggregation"

    # 同一個 Report 版本內，(main_category, sub_category) 只會出現一次
    # （Primary 跟 Secondary 落在同一組 group 時直接合併累加，不是兩列）。
    __table_args__ = (
        db.UniqueConstraint(
            "report_id", "main_category", "sub_category",
            name="uq_report_aggregation_group",
        ),
    )

    aggregation_id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    report_id = db.Column(
        db.Integer,
        db.ForeignKey("Report.report_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    main_category = db.Column(db.String(100), nullable=False)
    sub_category = db.Column(db.String(100), nullable=False)

    # response_count：去重後的「受訪者數」（同一份原始回答只算一次）。
    # segment_count：實際落在這個 group 的 segment 數（可能大於 response_count）。
    response_count = db.Column(db.Integer, nullable=False, default=0)
    segment_count = db.Column(db.Integer, nullable=False, default=0)

    aggregated_summary = db.Column(db.Text, nullable=True)

    # 查表結果的快照（來自 services/subcategory_methodology.py），
    # 不是 Aggregation 階段重新讓 Gemini 選的。
    methodology = db.Column(db.String(100), nullable=True)
    citation = db.Column(db.Text, nullable=True)

    items = db.relationship(
        "Report_Aggregation_Item",
        backref="aggregation",
        cascade="all, delete-orphan",
    )

    def to_dict(self, include_items: bool = False) -> dict:
        data = {
            "aggregation_id": self.aggregation_id,
            "report_id": self.report_id,
            "main_category": self.main_category,
            "sub_category": self.sub_category,
            "response_count": self.response_count,
            "segment_count": self.segment_count,
            "aggregated_summary": self.aggregated_summary,
            "methodology": self.methodology,
            "citation": self.citation,
        }
        if include_items:
            data["items"] = [i.to_dict() for i in self.items]
        return data


class Report_Aggregation_Item(db.Model):
    __tablename__ = "Report_Aggregation_Item"

    item_id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    aggregation_id = db.Column(
        db.Integer,
        db.ForeignKey("Report_Aggregation.aggregation_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # 指回原始 classification 供除錯/追溯用；刻意用 SET NULL 而非
    # CASCADE——即使原始 Response_Classification 之後被刪除，這裡的
    # snapshot 內容（下面幾個欄位）仍然要繼續存在，不能因為原始資料
    # 被刪就讓 Report 內容跟著消失，這正是「Report 是快照」的核心要求。
    classification_id = db.Column(
        db.Integer,
        db.ForeignKey("Response_Classification.classification_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # ── snapshot 內容：產生當下的值，之後原始資料變了也不會跟著變 ──
    original_answer_text = db.Column(db.Text, nullable=False)
    matched_segment_text = db.Column(db.Text, nullable=False)
    effective_reasoning = db.Column(db.Text, nullable=True)

    # 供「同一份原始回答」去重使用的參照快照（見需求文件第十四節）。
    # survey 來源：response_id 有值；user_upload 來源：upload_batch_id +
    # uploaded_answer_id 有值。跟 Response_Classification 的 source
    # invariant 概念一致，但這裡不用 CheckConstraint 強制，因為這是
    # 快照資料，寫入時機在 Phase 5 service 內部一次性決定，不需要
    # DB 層再重複驗證一次已經在 Response_Classification 驗證過的規則。
    response_id = db.Column(
        db.Integer,
        db.ForeignKey("Survey_Response.response_id", ondelete="SET NULL"),
        nullable=True,
    )
    upload_batch_id = db.Column(db.String(50), nullable=True)
    uploaded_answer_id = db.Column(
        db.Integer,
        db.ForeignKey("Uploaded_Answer.id", ondelete="SET NULL"),
        nullable=True,
    )

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "aggregation_id": self.aggregation_id,
            "classification_id": self.classification_id,
            "original_answer_text": self.original_answer_text,
            "matched_segment_text": self.matched_segment_text,
            "effective_reasoning": self.effective_reasoning,
            "response_id": self.response_id,
            "upload_batch_id": self.upload_batch_id,
            "uploaded_answer_id": self.uploaded_answer_id,
        }
