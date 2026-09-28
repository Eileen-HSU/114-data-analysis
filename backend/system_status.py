"""
System_Health_Status：背景 / 啟動流程的健康狀態（目前用在 taxonomy bootstrap）。

bootstrap 失敗不阻止網站啟動（登入、既有資料都要能用），但不能只留在
log 裡：每次執行的結果寫在這裡，Admin API / AI 管理頁顯示明顯警告。
error_summary 一律是 services/safe_error.py 處理過的摘要（不含 stack
trace、API key、token）。
"""

from extensions import db, taiwan_now


class System_Health_Status(db.Model):
    __tablename__ = "System_Health_Status"

    component = db.Column(db.String(50), primary_key=True)
    status = db.Column(db.String(30), nullable=False)
    last_run_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_success_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_failure_at = db.Column(db.DateTime(timezone=True), nullable=True)
    error_summary = db.Column(db.Text, nullable=True)
    detail = db.Column(db.JSON, nullable=True)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=True, default=taiwan_now, onupdate=taiwan_now)

    def to_dict(self) -> dict:
        iso = lambda v: v.isoformat() if v else None  # noqa: E731
        return {
            "component": self.component,
            "status": self.status,
            "last_run_at": iso(self.last_run_at),
            "last_success_at": iso(self.last_success_at),
            "last_failure_at": iso(self.last_failure_at),
            "error_summary": self.error_summary,
            "detail": self.detail,
        }
