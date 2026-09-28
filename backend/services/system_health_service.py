"""
taxonomy bootstrap 的健康狀態（見 system_status.py）。

狀態：
    ok              有已發布的分類架構（bootstrap 建立、或早就有）
    created         本次啟動建立了 legacy 分類架構
    skipped_existing / concurrent_bootstrap  已經有分類架構，不需要 bootstrap
    disabled        TAXONOMY_BOOTSTRAP_ON_STARTUP=0（需要手動執行 CLI）
    lock_timeout    等不到跨 worker 的 bootstrap 鎖（另一個 worker 可能正在執行）
    failed          bootstrap 發生例外

bootstrap 失敗時分類流程不變：固定分類模式維持 fail-closed（沒有已發布的
分類架構就不分類）；開放式分類只有 AI 自動歸納真的成功才會分析；任何情況
都不會改用寫死在程式裡的 legacy 分類規則。
"""

from extensions import db, taiwan_now

COMPONENT_TAXONOMY_BOOTSTRAP = "taxonomy_bootstrap"
WARNING_STATUSES = ("failed", "lock_timeout")


def record_bootstrap_result(result=None, error=None, disabled=False):
    """寫入這次 bootstrap 的結果；自己 commit，寫入失敗不影響啟動。"""
    from models import System_Health_Status
    from services.safe_error import safe_error_summary

    try:
        row = db.session.get(System_Health_Status, COMPONENT_TAXONOMY_BOOTSTRAP)
        if row is None:
            row = System_Health_Status(component=COMPONENT_TAXONOMY_BOOTSTRAP, status="unknown")
            db.session.add(row)
        now = taiwan_now()
        row.last_run_at = now
        if disabled:
            row.status = "disabled"
            row.detail = {"reason": "TAXONOMY_BOOTSTRAP_ON_STARTUP=0"}
        elif error is not None:
            row.status = "failed"
            row.last_failure_at = now
            row.error_summary = safe_error_summary(error, limit=500)
            row.detail = {"error_type": type(error).__name__}
        else:
            status = (result or {}).get("status") or "unknown"
            row.status = status
            row.detail = {"created_topics": (result or {}).get("created_topics") or []}
            if status in WARNING_STATUSES:
                row.last_failure_at = now
                row.error_summary = "等不到跨 worker 的 bootstrap 鎖（另一個程序可能正在初始化）" if status == "lock_timeout" else row.error_summary
            else:
                row.last_success_at = now
                row.error_summary = None
        db.session.commit()
    except Exception as exc:  # 健康狀態寫不進去不能讓網站起不來
        db.session.rollback()
        print("[TAXONOMY_BOOTSTRAP][HEALTH_RECORD_FAILED]", safe_error_summary(exc))


def taxonomy_bootstrap_health() -> dict:
    """Admin API 用：記錄的狀態 + 目前實際的分類架構情況。"""
    from models import System_Health_Status, Taxonomy_Version
    from services.open_classification import open_mode_enabled

    row = db.session.get(System_Health_Status, COMPONENT_TAXONOMY_BOOTSTRAP)
    published = Taxonomy_Version.query.filter_by(status="published").count()
    any_version = Taxonomy_Version.query.count()
    recorded = row.to_dict() if row else {
        "component": COMPONENT_TAXONOMY_BOOTSTRAP, "status": "unknown", "last_run_at": None,
        "last_success_at": None, "last_failure_at": None, "error_summary": None, "detail": None,
    }
    warning = None
    if recorded["status"] in WARNING_STATUSES and any_version == 0:
        warning = "bootstrap_failed"
    elif published == 0:
        warning = "no_published_taxonomy"
    return {
        **recorded,
        "published_version_count": published,
        "taxonomy_empty": any_version == 0,
        "open_classification_enabled": open_mode_enabled(),
        "warning": warning,
    }
