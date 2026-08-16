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
"""

from extensions import db, taiwan_now


class Uploaded_Answer(db.Model):
    __tablename__ = "Uploaded_Answer"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    # 同一次上傳（一次只能上傳一個檔案）共用同一個值
    upload_batch_id = db.Column(db.String(50), nullable=False)

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
            "source_column": self.source_column,
            "row_index": self.row_index,
            "answer_text": self.answer_text,
            "question_type": self.question_type,
            "created_at": (
                self.created_at.isoformat() if self.created_at else None
            ),
        }