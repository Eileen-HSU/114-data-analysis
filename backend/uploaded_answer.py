"""

外部 Excel/CSV 上傳的原始文字保存層，角色對應 survey 來源的
Survey_Response：不管 question_type routing 判斷不判斷得出來，
原始 answer_text 都先進這張表，不會因為判斷不出來就整批丟棄。

v1 採單表設計（不拆 Upload_Batch）：question_type / source_column
在同一批次的每一列重複儲存，因為目前一次上傳只有一個檔案、一個
文字欄位，重複儲存的成本很低；等未來上傳量變大有需要，再考慮
拆成批次表 + 列表兩張表。

question_type 為 NULL，代表這批資料目前無法自動 routing、待處理，
不另外增加 status 欄位表達這件事。

user_id：Human Review 權限判斷需要知道「這批上傳是誰的」，因此補上
這個欄位當作 user_upload 來源的 ownership 依據（對應 survey 來源用
Survey_Template.user_id 判斷 ownership 的方式）。

    欄位設計為 nullable=True，只是為了相容 migration 之前就存在的
    舊資料列（那些列沒有機會補回真正的上傳者）。這不代表新資料可以
    沒有 owner——routes/classifications/classification.py 的上傳路由
    從這次 migration 之後，一律要求先通過 verify_token() 才能呼叫，
    並強制把 authenticated user_id 寫入這個欄位；路由層本身就不允許
    產生 user_id 為 None 的新列，nullable=True 純粹是資料庫層級對
    舊資料的相容設計，不是允許新資料略過 owner 的後門。
"""

from extensions import db, taiwan_now


class Uploaded_Answer(db.Model):
    __tablename__ = "Uploaded_Answer"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    # 同一次上傳（一次只能上傳一個檔案）共用同一個值
    upload_batch_id = db.Column(db.String(50), nullable=False)

    # 上傳者。nullable=True 僅為相容 migration 前的舊資料，見上方模組
    # docstring 說明；新資料一律由 route 層強制帶入，不會是 None。
    # 不加 ondelete="CASCADE"：使用者刪除帳號不應該連帶砍掉已上傳並
    # 分類完成的資料，比照 User_Verification 的作法改用 SET NULL。
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