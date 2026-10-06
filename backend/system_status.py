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


# ── 系統錯誤紀錄（見 services/error_log_service.py）──────────────────
# 伺服器非預期錯誤、背景工作錯誤、AI 呼叫失敗等，集中記在這裡，Admin 後台
# 可以查看、標記已處理或忽略。同一種錯誤（fingerprint 相同、還沒處理）
# 只會累加次數，不會洗版。message / detail 一律是去除 API key、token 後的內容。
ERROR_STATUS_OPEN = "open"
ERROR_STATUS_RESOLVED = "resolved"
ERROR_STATUS_IGNORED = "ignored"


class System_Error_Log(db.Model):
    __tablename__ = "System_Error_Log"

    error_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    fingerprint = db.Column(db.String(64), nullable=False, index=True)
    source = db.Column(db.String(100), nullable=False)        # request / logger 名稱 / background
    code = db.Column(db.String(60), nullable=False, index=True)
    message = db.Column(db.Text, nullable=False)
    detail = db.Column(db.Text, nullable=True)                # 去敏的 stack trace（截斷）
    path = db.Column(db.String(300), nullable=True)
    method = db.Column(db.String(10), nullable=True)
    status_code = db.Column(db.Integer, nullable=True)
    occurrence_count = db.Column(db.Integer, nullable=False, default=1)
    first_seen_at = db.Column(db.DateTime(timezone=True), nullable=False, default=taiwan_now)
    last_seen_at = db.Column(db.DateTime(timezone=True), nullable=False, default=taiwan_now, index=True)
    status = db.Column(db.String(20), nullable=False, default=ERROR_STATUS_OPEN, index=True)
    resolved_by_admin_id = db.Column(db.Integer, nullable=True)
    resolved_at = db.Column(db.DateTime(timezone=True), nullable=True)
    resolution_note = db.Column(db.Text, nullable=True)

    def to_dict(self, include_detail=False) -> dict:
        iso = lambda v: v.isoformat() if v else None  # noqa: E731
        data = {
            "error_id": self.error_id,
            "source": self.source,
            "code": self.code,
            "message": self.message,
            "path": self.path,
            "method": self.method,
            "status_code": self.status_code,
            "occurrence_count": self.occurrence_count,
            "first_seen_at": iso(self.first_seen_at),
            "last_seen_at": iso(self.last_seen_at),
            "status": self.status,
            "resolved_by_admin_id": self.resolved_by_admin_id,
            "resolved_at": iso(self.resolved_at),
            "resolution_note": self.resolution_note,
        }
        if include_detail:
            data["detail"] = self.detail
        return data
