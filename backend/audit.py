"""
Admin_Audit_Log：Admin 對分類結果 / taxonomy / report 的每一個會改變
資料的操作都留下一筆獨立、可查詢的稽核紀錄。

設計原則：
    - 不依賴 Classification_Review_Message（聊天訊息不是 audit record）。
    - before_state / after_state 存 JSON 快照（只放跟這次操作相關的欄位），
      事後可以完整回答「誰、什麼時候、把什麼從 A 改成 B、為什麼」。
    - batch_id：批次操作（batch confirm / bulk exclude）的每一筆紀錄共用
      同一個 batch_id，也作為重試的冪等鍵。
    - 寫入由 services/audit_service.py 集中處理，只 add 不 commit，跟被
      稽核的資料變更在同一個 transaction 裡一起成功或一起 rollback。
"""

from extensions import db, taiwan_now


class Admin_Audit_Log(db.Model):
    __tablename__ = "Admin_Audit_Log"

    audit_id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    action = db.Column(db.String(50), nullable=False, index=True)
    entity_type = db.Column(db.String(50), nullable=False)
    entity_id = db.Column(db.String(100), nullable=False)

    # 不設 FK：Admin 帳號被刪除後，稽核紀錄仍必須完整保留。
    admin_id = db.Column(db.Integer, nullable=True, index=True)

    before_state = db.Column(db.JSON, nullable=True)
    after_state = db.Column(db.JSON, nullable=True)
    reason = db.Column(db.Text, nullable=True)
    batch_id = db.Column(db.String(64), nullable=True, index=True)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=taiwan_now)

    __table_args__ = (
        db.Index("ix_admin_audit_entity", "entity_type", "entity_id"),
    )

    def to_dict(self) -> dict:
        return {
            "audit_id": self.audit_id,
            "action": self.action,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "admin_id": self.admin_id,
            "before_state": self.before_state,
            "after_state": self.after_state,
            "reason": self.reason,
            "batch_id": self.batch_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
