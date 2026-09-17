"""

Taxonomy 核心資料層（Phase A）。

目的：讓「結構化 taxonomy 資料」有唯一真相來源，取代目前分裂在
services/classify_v2.py 的 DEFAULT_PROMPT_* 散文規則，與
services/subcategory_methodology.py 的 SUBCATEGORY_METHODOLOGY 查表
兩個地方的狀態（見需求文件第 3、5 節）。

三層 normalized 結構：

    Topic                    一個分析主題（例如 leadership_and_dept）
      -> Taxonomy_Version    同一個 Topic 可以有多版（draft/in_review/
                              published/archived），不會直接覆寫正式版
           -> Taxonomy_Category  一版 taxonomy 底下的每一個
                                   main_category / sub_category

【本次 Phase A 的設計取捨，供下一階段接續參考】

1. Topic 為什麼是新表，不是重用 Prompt_Template：
   Prompt_Template（prompt_key 為 PK）draft_content / live_content
   都是 nullable=False，語意是「一段可直接送進 Gemini 的 prompt 文字」，
   建立一筆 Prompt_Template 就被強迫要有完整 prompt 內容。但一個新
   Topic 在完成 Taxonomy Generation、人工審核、發布之前，本來就不
   該有任何 prompt 內容——這是需求文件第 5 節「Prompt 是如何使用
   taxonomy，Taxonomy 是實際分類資料，兩者必須分開」的核心要求。
   因此 Topic 是一個獨立、輕量的身份表，只記錄「有這個分析主題」，
   不涉及 prompt 文字本身；Prompt_Template 未來（Phase B）如何跟
   Topic 對應，留給下一階段決定，這次不動 Prompt_Template。

2. Topic 沒有 status 欄位：
   需求文件第 7 節要 Admin Topic List 顯示「no taxonomy / generating /
   review / published」，但這個狀態其實是「這個 Topic 底下最新一版
   Taxonomy_Version 處於什麼狀態」的衍生結果，不是 Topic 本身的
   固有屬性。存成 Topic 的欄位，會產生第二份需要手動同步的真相來源
   （這正是這次重構要避免的問題），所以刻意不存，改成由後續階段
   （Phase D Admin 服務層）查詢 Taxonomy_Version 即時算出。

3. Taxonomy_Version.version_number 不是全域自增：
   同一個 Topic 的版本序號要是 1, 2, 3...，用
   UniqueConstraint(topic_key, version_number) 保證同一 Topic 不會有
   重複版號；version_number 本身由呼叫端（migration script /
   未來 Phase C 的 generation service）在建立前查詢
   max(version_number)+1 決定，這裡不用 event listener 自動計算
   （不像 report.py 的 source_key 是純字串組合，這裡需要先查 DB
   目前最大值，屬於服務層邏輯，不適合放在 model 的 before_insert）。

4. 「只能有一個 published 版本」不是 DB 層 constraint：
   MySQL 不支援 partial unique index，沒辦法用 DB constraint 表達
   「同一 topic_key 下 status='published' 最多一列」。這個規則會在
   Phase B/D 的 publish service 裡用「發布新版時，先把同 topic 的舊
   published 版本轉成 archived」的方式在應用層保證，比照
   services/prompt_admin_service.py 現有「draft_validated 由服務層
   維護」的做法，這裡先不做。

5. Taxonomy_Category 的 definition / include_rules / exclude_rules /
   boundary_rules 為什麼在 migration 完後大多是 NULL：
   既有 DEFAULT_PROMPT_LEADERSHIP / DEFAULT_PROMPT_CAREER 裡每個子
   類別只有「一整段散文」，同時混雜了 include 判斷、跟其他類別的
   排除／邊界說明，沒有天然的段落邊界可以切成 definition / include /
   exclude / boundary 四個獨立欄位。依需求文件第 11 節「不要自行補
   不存在於來源中的規則」，migration 不猜測怎麼切分，改成把整段原文
   完整存進 source_raw_text（見下方欄位），definition 等四個結構化
   欄位留 NULL，交給 Phase D 人工審核時參考原文手動拆分、填入。
   secondary/次要類別規則（GLOBAL_RULES 與各 prompt 內的「次要類別
   規則」段落）不屬於任何單一 sub_category，也不搬進這裡，留在
   Prompt_Template（Phase B 再決定歸屬）。

尚未處理、留給後續階段（不在本次 Phase A 範圍內）：
    - Response_Classification 尚未新增 taxonomy version FK（需求文件
      D 節提到「可能需要」，但要先確認 schema，且會牽動 production
      classification flow，屬於 Phase B 範圍）。
    - Taxonomy Generation（AI 產生 draft）、Admin review/publish UI、
      Golden Test 版本綁定，分別是 Phase C / D / E。
"""

from sqlalchemy import CheckConstraint, event

from extensions import db, taiwan_now


# ── Taxonomy_Version 狀態 ────────────────────────────────────────
# 刻意不用「candidate」這個詞：Prompt_Template 的沙盒草稿機制
# （services/prompt_admin_service.py、routes/admin/ai_admin.py 的
# candidate_status）已經用 candidate 代表「prompt draft」，跟這裡
# taxonomy 版本的語意不同，混用會造成命名撞義（需求文件第 3 節 E）。
TAXONOMY_VERSION_STATUS_DRAFT = "draft"
TAXONOMY_VERSION_STATUS_IN_REVIEW = "in_review"
TAXONOMY_VERSION_STATUS_PUBLISHED = "published"
TAXONOMY_VERSION_STATUS_ARCHIVED = "archived"
ALLOWED_TAXONOMY_VERSION_STATUSES = {
    TAXONOMY_VERSION_STATUS_DRAFT,
    TAXONOMY_VERSION_STATUS_IN_REVIEW,
    TAXONOMY_VERSION_STATUS_PUBLISHED,
    TAXONOMY_VERSION_STATUS_ARCHIVED,
}

# ── Taxonomy_Version 來源（僅供追溯，不影響行為）───────────────────
TAXONOMY_VERSION_SOURCE_MIGRATED_LEGACY = "migrated_legacy"
TAXONOMY_VERSION_SOURCE_AI_GENERATED = "ai_generated"
TAXONOMY_VERSION_SOURCE_MANUAL = "manual"
ALLOWED_TAXONOMY_VERSION_SOURCES = {
    TAXONOMY_VERSION_SOURCE_MIGRATED_LEGACY,
    TAXONOMY_VERSION_SOURCE_AI_GENERATED,
    TAXONOMY_VERSION_SOURCE_MANUAL,
}


class Topic(db.Model):
    """一個分析主題的身份表。目前既有的 leadership_and_dept /
    career_and_feedback 只是第一批既有案例，未來任何新問卷題目都
    可以是新的 Topic，topic_key 不綁死在這兩個既有字串上。"""

    __tablename__ = "Topic"

    # 沿用既有 question_type / prompt_key 同一套字串 key（例如
    # "leadership_and_dept"），長度比照 Prompt_Template.prompt_key。
    topic_key = db.Column(db.String(50), primary_key=True)

    # 人類可讀名稱，例如「主管領導和部門合作」。
    title = db.Column(db.String(200), nullable=False)

    # 對應的問卷題目原文（Stage A 產生 taxonomy 需要的輸入之一，
    # 見需求文件第 1 節），允許 NULL：不是所有 Topic 建立當下都
    # 一定已經有明確題目文字。
    question_text = db.Column(db.Text, nullable=True)

    description = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), default=taiwan_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), default=taiwan_now, onupdate=taiwan_now
    )

    taxonomy_versions = db.relationship(
        "Taxonomy_Version", backref="topic", cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict:
        return {
            "topic_key": self.topic_key,
            "title": self.title,
            "question_text": self.question_text,
            "description": self.description,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Taxonomy_Version(db.Model):
    __tablename__ = "Taxonomy_Version"

    __table_args__ = (
        CheckConstraint(
            f"status IN ({','.join(repr(s) for s in sorted(ALLOWED_TAXONOMY_VERSION_STATUSES))})",
            name="chk_taxonomy_version_status",
        ),
        CheckConstraint(
            f"source IN ({','.join(repr(s) for s in sorted(ALLOWED_TAXONOMY_VERSION_SOURCES))})",
            name="chk_taxonomy_version_source",
        ),
        db.UniqueConstraint(
            "topic_key", "version_number", name="uq_taxonomy_version_topic_number"
        ),
    )

    version_id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    topic_key = db.Column(
        db.String(50),
        db.ForeignKey("Topic.topic_key", ondelete="CASCADE"),
        nullable=False,
    )

    # 同一 Topic 底下 1, 2, 3...；由呼叫端（migration script /
    # 未來 generation service）在建立前查詢目前最大值決定，
    # 見本檔開頭說明第 3 點。
    version_number = db.Column(db.Integer, nullable=False)

    status = db.Column(
        db.String(20), nullable=False, default=TAXONOMY_VERSION_STATUS_DRAFT
    )
    source = db.Column(db.String(30), nullable=False)

    # 這一版 taxonomy 生成/整理時使用的系統級分析原則或說明，
    # 例如 migration 時可以填「沿用 DEFAULT_PROMPT_LEADERSHIP + 
    # SUBCATEGORY_METHODOLOGY」，Phase C 的 AI 生成則填當時用的
    # inductive analysis instructions 摘要。純文字備註，不是 prompt
    # 本身（prompt 仍由 Phase B 決定的機制另外組出）。
    methodology_note = db.Column(db.Text, nullable=True)

    created_by = db.Column(
        db.Integer, db.ForeignKey("Admin.admin_id", ondelete="SET NULL"), nullable=True
    )
    created_at = db.Column(db.DateTime(timezone=True), default=taiwan_now)
    published_at = db.Column(db.DateTime(timezone=True), nullable=True)
    archived_at = db.Column(db.DateTime(timezone=True), nullable=True)

    categories = db.relationship(
        "Taxonomy_Category",
        backref="taxonomy_version",
        cascade="all, delete-orphan",
        order_by="Taxonomy_Category.sort_order",
    )

    def to_dict(self, include_categories: bool = False) -> dict:
        data = {
            "version_id": self.version_id,
            "topic_key": self.topic_key,
            "version_number": self.version_number,
            "status": self.status,
            "source": self.source,
            "methodology_note": self.methodology_note,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "archived_at": self.archived_at.isoformat() if self.archived_at else None,
        }
        if include_categories:
            data["categories"] = [c.to_dict() for c in self.categories]
        return data


@event.listens_for(Taxonomy_Version, "before_insert")
@event.listens_for(Taxonomy_Version, "before_update")
def _validate_taxonomy_version(mapper, connection, target):
    if target.status not in ALLOWED_TAXONOMY_VERSION_STATUSES:
        raise ValueError(f"status 只能是 {sorted(ALLOWED_TAXONOMY_VERSION_STATUSES)} 其中之一")
    if target.source not in ALLOWED_TAXONOMY_VERSION_SOURCES:
        raise ValueError(f"source 只能是 {sorted(ALLOWED_TAXONOMY_VERSION_SOURCES)} 其中之一")


class Taxonomy_Category(db.Model):
    __tablename__ = "Taxonomy_Category"

    __table_args__ = (
        db.UniqueConstraint(
            "version_id", "main_category", "sub_category",
            name="uq_taxonomy_category_version_subcategory",
        ),
    )

    category_id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    version_id = db.Column(
        db.Integer,
        db.ForeignKey("Taxonomy_Version.version_id", ondelete="CASCADE"),
        nullable=False,
    )

    main_category = db.Column(db.String(100), nullable=False)
    # 既有 sub_category 字串含編號前綴（例如「A1 工作與生活邊界」），
    # 長度比照 Response_Classification.sub_category 的 String(100)，
    # 但既有最長字串（例如「A6 職涯發展與回饋制度」）留有餘裕。
    sub_category = db.Column(db.String(150), nullable=False)

    definition = db.Column(db.Text, nullable=True)
    include_rules = db.Column(db.Text, nullable=True)
    exclude_rules = db.Column(db.Text, nullable=True)
    boundary_rules = db.Column(db.Text, nullable=True)

    # 沿用 SUBCATEGORY_METHODOLOGY 既有查表結果；methodology 長度比照
    # Response_Classification.methodology 的 String(100)。
    methodology = db.Column(db.String(100), nullable=True)
    citation = db.Column(db.Text, nullable=True)

    # migration 專用：來源尚未拆分的完整原文段落。見本檔開頭說明第 5
    # 點，Phase D 人工審核時的參考依據，不是拿來給 Gemini 讀的正式
    # 欄位。AI 新產生的 taxonomy（Phase C）不會有這個欄位的內容。
    source_raw_text = db.Column(db.Text, nullable=True)

    # 畫面顯示順序（既有 main_category 內的相對順序），由呼叫端維護，
    # 不是自動遞增的插入順序。
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    created_at = db.Column(db.DateTime(timezone=True), default=taiwan_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), default=taiwan_now, onupdate=taiwan_now
    )

    def to_dict(self) -> dict:
        return {
            "category_id": self.category_id,
            "version_id": self.version_id,
            "main_category": self.main_category,
            "sub_category": self.sub_category,
            "definition": self.definition,
            "include_rules": self.include_rules,
            "exclude_rules": self.exclude_rules,
            "boundary_rules": self.boundary_rules,
            "methodology": self.methodology,
            "citation": self.citation,
            "source_raw_text": self.source_raw_text,
            "sort_order": self.sort_order,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
