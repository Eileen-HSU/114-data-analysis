"""

Human Review Conversation 的獨立 persistence，比照 Response_Classification /
Response_Segmentation_Status 的風格另外建表，不塞進既有的 Chat_History
（那是給問卷填答聊天室用的，跟「針對某一筆 Response_Classification 做
分類覆核」是完全不同的資料語意與生命週期）。

兩張表：
    Classification_Review：一列 = 針對某一筆 Response_Classification 的
        一次 review 會話（review session）。
    Classification_Review_Message：一列 = 該會話裡的一輪訊息（User 發的
        或 AI 回的）。role='assistant' 的訊息如果有附帶「這輪 AI 提出的
        candidate 分類」，會存在 candidate_* 欄位裡。

【重要】這兩張表本身只負責「儲存對話與 candidate 歷史」，不負責業務
規則判斷（例如 candidate 何時可以變成 final、taxonomy 合法性檢查等）。
那些屬於 Phase 3 services/review_service.py 與 services/review_ai_service.py
的職責，Phase 2 只先把資料結構立好。

Classification_Review.status 目前先給一個寬鬆的 String 欄位（不加
CheckConstraint），因為完整的狀態機（例如 in_progress / confirmed /
excluded 分別對應什麼、什麼時候可以轉換）屬於 Phase 3 service 邏輯的
一部分，不在本次「Models + schema compatibility」範圍內先寫死，避免
之後 Phase 3 定案時要跟著改 DB constraint。
"""

from extensions import db, taiwan_now


class Classification_Review(db.Model):
    __tablename__ = "Classification_Review"

    review_id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    # 一筆 Response_Classification 理論上可能被開啟多次 review session
    # （例如使用者中途離開、之後重新打開review），因此這裡「不」加
    # unique=True，「目前哪一個 session 才是有效中的 session」由 Phase 3
    # service 邏輯判斷（例如取最新一筆），不是 DB 層級的職責。
    classification_id = db.Column(
        db.Integer,
        db.ForeignKey("Response_Classification.classification_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # 發起這次 review 的使用者。Human Review 是 User 功能而非 Admin
    # 功能，ownership 檢查依據這個欄位 + classification 實際所屬的
    # survey/upload owner 是否一致（Phase 3 service 邏輯負責比對）。
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

    # 以下 candidate_* 欄位只有 role='assistant' 且該輪有提出新候選分類
    # 時才會有值；User 訊息、或 AI 該輪只是回應說明而未變更候選分類時，
    # 全部為 None。這裡刻意「不」用 CheckConstraint 強制
    # role!='assistant' 時必須為 None，因為那是資料寫入邏輯的職責
    # （Phase 3 review_service.py），不是 schema 該擋的事。
    #
    # candidate_main_category / candidate_secondary_main_category
    # 同樣是後端查表結果（不是 Gemini 直接輸出的欄位），跟
    # Response_Classification.secondary_main_category 的設計原則一致，
    # 只是這裡存的是「這一輪的候選」，不是正式的 AI original 或 final。
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
