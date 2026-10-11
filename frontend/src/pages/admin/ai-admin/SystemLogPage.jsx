import { useTextPrompt } from "./shared/TextPromptDialog";
import { BackgroundJobsPanel } from "./shared/BackgroundJobs";
import MaintenancePanel from "./shared/MaintenancePanel";
import { AdminPageHeader, AdminTabs } from "./shared/AdminLayout";
import { useEffect, useRef, useState } from "react";
import { NavLink, useNavigate, useSearchParams } from "react-router-dom";
import Navbar from "../../../components/feature/Navbar";
import { useAuth } from "../../../hooks/AuthContext";
import { api } from "./shared/apiClient";
import { t } from "./shared/taxStatus";
import { errorMessage } from "./shared/reviewStates";
import { LoadingNotice } from "./shared/StatusWidgets";
import "../ai-admin.css";

// 系統紀錄（手冊 4.3）：系統狀態、錯誤紀錄、操作紀錄。
// 後端：GET /api/admin/ai/system/status、/system/errors、/audit-logs（見 services/error_log_service.py、
// services/system_monitor_service.py）。
const PAGE_SIZE = 30;
const TABS = ["status", "jobs", "errors", "audit", "maintenance"];
const tabLabel = (tab) => ({
  status: t("系統狀態", "System status"),
  jobs: t("背景工作", "Background jobs"),
  errors: t("錯誤紀錄", "Error log"),
  audit: t("操作紀錄", "Activity log"),
  maintenance: t("資料維護", "Data maintenance"),
}[tab]);

// 錯誤代碼 -> 名稱與建議的處理方式（link：可以直接去修復的頁面）
const ERROR_CODES = {
  SERVER_ERROR: { zh: "伺服器錯誤", en: "Server error",
    fixZh: "打開明細看錯誤內容與發生位置。修正程式或設定後，按「標記已處理」。",
    fixEn: "Open the details to see what failed and where. After fixing the code or settings, mark it resolved." },
  LOGGED_ERROR: { zh: "程式記錄的錯誤", en: "Logged error",
    fixZh: "程式已經處理掉這個錯誤（使用者可能看到失敗訊息）。打開明細確認原因。",
    fixEn: "The app handled this error (users may have seen a failure). Open the details to check why." },
  AI_QUOTA_EXCEEDED: { zh: "AI 額度用完", en: "AI quota exceeded",
    fixZh: "Gemini 額度暫時用完。等額度恢復（通常一分鐘內），或升級付費方案；受影響的資料到「系統管理 › 背景工作」按「全部重試」。",
    fixEn: "Gemini quota ran out. Wait for it to recover or upgrade the plan, then use Retry all under System › Background jobs.",
    link: "/admin/ai/system?view=jobs" },
  AI_SERVICE_BUSY: { zh: "AI 服務忙碌", en: "AI service busy",
    fixZh: "Gemini 暫時過載，通常會自己恢復；受影響的資料到「系統管理 › 背景工作」按「全部重試」。",
    fixEn: "Gemini was overloaded and usually recovers on its own. Use Retry all under System › Background jobs.", link: "/admin/ai/system?view=jobs" },
  AI_TIMEOUT: { zh: "AI 回應逾時", en: "AI timeout",
    fixZh: "AI 太久沒有回應。受影響的資料到「系統管理 › 背景工作」按「全部重試」。",
    fixEn: "The AI took too long. Use Retry all under System › Background jobs.", link: "/admin/ai/system?view=jobs" },
  AI_AUTH_FAILED: { zh: "AI 金鑰無效", en: "AI key invalid",
    fixZh: "檢查主機環境變數 GEMINI_API_KEY／ADMIN_GEMINI_API_KEY 是否正確、是否過期，修正後重新部署。",
    fixEn: "Check GEMINI_API_KEY / ADMIN_GEMINI_API_KEY on the host, then redeploy." },
  AI_RESPONSE_INVALID: { zh: "AI 回應格式錯誤", en: "Invalid AI response",
    fixZh: "AI 回傳的格式不正確，網頁不受影響，資料會被標成分類失敗。到「分類審查 › 無法分類」重新處理或排除。",
    fixEn: "The AI returned a malformed response; the item was marked failed. Retry or exclude it under Review › Can't classify.",
    link: "/admin/ai/review?view=unassigned" },
  SEGMENTATION_INVALID: { zh: "拆段結果異常", en: "Invalid segmentation",
    fixZh: "AI 拆出來的片段對不上原文。到「分類審查 › 無法分類」重新處理或排除。",
    fixEn: "The AI's segments didn't match the original text. Retry or exclude it under Review › Can't classify.",
    link: "/admin/ai/review?view=unassigned" },
  PII_MASKING_FAILED: { zh: "個資遮蔽失敗", en: "PII masking failed",
    fixZh: "為了保護個資，這筆沒有送給 AI。到「分類審查 › 無法分類」查看並排除或重新處理。",
    fixEn: "For privacy this item was not sent to the AI. Review it under Review › Can't classify.", link: "/admin/ai/review?view=unassigned" },
};
const codeLabel = (code) => (ERROR_CODES[code] ? t(ERROR_CODES[code].zh, ERROR_CODES[code].en) : code);

const ACTIONS = {
  quick_confirm: ["快速確認", "Quick confirm"], batch_confirm: ["批次確認", "Batch confirm"],
  modify: ["修改分類", "Changed category"], exclude: ["排除", "Excluded"], reopen: ["重新開啟審核", "Reopened"],
  bulk_exclude: ["批次排除舊資料", "Excluded legacy data"], retry_failed: ["重新處理失敗資料", "Retried failed item"],
  reclassify: ["重新分類", "Reclassified"], reroute: ["重新判斷主題", "Re-routed topic"],
  assign_topic: ["指派主題", "Assigned topic"], merge_topic: ["合併主題", "Merged topic"],
  taxonomy_publish: ["發布分類架構", "Published taxonomy"], taxonomy_bootstrap: ["分類架構初始化", "Taxonomy bootstrap"],
  adopt_new_category: ["加入新類別", "Added new category"], merge_new_category: ["合併新類別", "Merged new category"],
  report_regenerate: ["重新產生報告", "Regenerated report"], auto_confirm_backfill: ["補做自動通過", "Auto-approved backlog"],
  second_opinion: ["AI 第二意見", "AI second opinion"],
};
const actionLabel = (action) => (ACTIONS[action] ? t(...ACTIONS[action]) : action);

const formatTime = (iso) => (iso ? new Date(iso).toLocaleString() : "—");

export default function SystemLogPage() {
  const navigate = useNavigate();
  const { user, isLoggedIn } = useAuth();
  const token = user?.token;
  const canAccess = isLoggedIn && user?.account_type === "admin";
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedTab = searchParams.get("view");
  const tab = TABS.includes(requestedTab) ? requestedTab : "status";
  const changeTab = (key) => setSearchParams(key === "status" ? {} : { view: key });

  if (!canAccess) return <><Navbar /><main className="ai-admin-empty"><h1>{t("僅管理者可存取 AI 管理介面", "AI admin access restricted to administrators")}</h1><button onClick={() => navigate("/workspace")}>{t("回到分析助理", "Back to Analysis Assistant")}</button></main></>;

  return <><div className="admin-page">
    <AdminPageHeader title={t("系統管理", "System")}
      description={t("系統狀態（資料庫、排程、分類架構初始化）、背景工作、錯誤紀錄、操作紀錄與低頻資料維護。",
        "System status (database, scheduler, taxonomy bootstrap), background jobs, errors, the activity log and occasional data maintenance.")} />
    <AdminTabs tabs={TABS.map((key) => ({ key, label: tabLabel(key) }))} value={tab}
      onChange={changeTab} />
    {tab === "jobs" && <BackgroundJobsPanel token={token} />}
    {tab === "status" && <StatusTab token={token} onShowErrors={() => changeTab("errors")} />}
    {tab === "errors" && <ErrorsTab token={token} navigate={navigate} />}
    {tab === "audit" && <AuditTab token={token} />}
    {tab === "maintenance" && <MaintenancePanel token={token} />}
  </div></>;
}


function StatusRow({ ok, label, children }) {
  return (
    <li className={`syslog-status-row syslog-status-row--${ok ? "ok" : "bad"}`}>
      <span className="syslog-status-dot" aria-hidden="true" />
      <div><b>{label}</b><p>{children}</p></div>
    </li>
  );
}

function StatusTab({ token, onShowErrors }) {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState("");
  const load = () => api("/api/admin/ai/system/status", token).then(setStatus).catch((e) => setError(errorMessage(e)));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, []);

  if (error) return <p className="ai-admin-error">{error}</p>;
  if (!status) return <LoadingNotice text={t("正在檢查系統狀態…", "Checking system status…")} />;
  const jobStatusLabel = (job) => (job.interrupted ? t("中斷", "interrupted") : {
    running: t("執行中", "running"), completed: t("已完成", "completed"), paused_quota: t("額度用完暫停", "paused (quota)"),
    cancelled: t("已停止", "stopped"), failed: t("發生錯誤", "error"),
  }[job.status] || job.status);
  const jobText = (job, name) => {
    if (!job) return t(`還沒執行過${name}。`, `${name} hasn't run yet.`);
    return t(`最近一次${name}：${jobStatusLabel(job)}（處理 ${job.processed} 筆，${formatTime(job.finished_at || job.heartbeat_at)}）`,
      `Last ${name}: ${jobStatusLabel(job)} (${job.processed} processed, ${formatTime(job.finished_at || job.heartbeat_at)})`);
  };
  const boot = status.taxonomy_bootstrap || {};
  return (
    <section className="admin-section">
      <ul className="syslog-status-list">
        <StatusRow ok={status.database.ok} label={t("資料庫", "Database")}>
          {status.database.ok ? t("連線正常。", "Connected.") : t("連不上資料庫，請檢查 DATABASE_URL 與資料庫服務。", "Can't reach the database. Check DATABASE_URL and the database service.")}
        </StatusRow>
        <StatusRow ok={status.ai.user_key_configured} label={t("AI（使用者分析）", "AI (user analysis)")}>
          {status.ai.user_key_configured ? t("已設定 GEMINI_API_KEY。", "GEMINI_API_KEY is set.") : t("沒有設定 GEMINI_API_KEY，AI 分析無法使用。", "GEMINI_API_KEY is missing; AI analysis won't work.")}
        </StatusRow>
        <StatusRow ok={status.ai.admin_key_configured} label={t("AI（管理員專用額度）", "AI (admin quota)")}>
          {status.ai.admin_key_configured
            ? t(`已設定 ADMIN_GEMINI_API_KEY。AI 再確認使用 ${status.ai.second_opinion_model}。`, `ADMIN_GEMINI_API_KEY is set. Re-checks use ${status.ai.second_opinion_model}.`)
            : t("沒有設定 ADMIN_GEMINI_API_KEY，管理員的操作會跟使用者共用額度。", "ADMIN_GEMINI_API_KEY is missing; admin actions share the user quota.")}
        </StatusRow>
        <StatusRow ok={status.mail.configured} label={t("寄信（Brevo）", "Email (Brevo)")}>
          {status.mail.configured ? t("已設定。", "Configured.") : t("沒有設定 BREVO_API_KEY／BREVO_FROM_EMAIL，驗證碼和忘記密碼信寄不出去。", "BREVO_API_KEY / BREVO_FROM_EMAIL missing; verification and reset emails can't be sent.")}
        </StatusRow>
        <StatusRow ok={status.scheduler.running} label={t("排程", "Scheduler")}>
          {status.scheduler.running
            ? t("執行中（AI 再確認每 10 分鐘、清理每天）。", "Running (AI re-check every 10 min, cleanup daily).")
            : t("這個伺服器程序的排程沒有在執行（本機開發模式下是正常的）。", "The scheduler isn't running in this server process (normal in local dev).")}
        </StatusRow>
        <StatusRow ok={boot.status !== "failed"} label={t("分類架構初始化", "Taxonomy bootstrap")}>
          {boot.status === "failed" ? t(`上次失敗：${boot.error_summary || ""}`, `Last run failed: ${boot.error_summary || ""}`) : t("正常。", "OK.")}
        </StatusRow>
        <StatusRow ok={status.errors.open === 0} label={t("錯誤", "Errors")}>
          {t(`最近 24 小時有 ${status.errors.open_last_24h} 種錯誤、總共 ${status.errors.open} 種還沒處理。`,
            `${status.errors.open_last_24h} error types in the last 24 hours; ${status.errors.open} unresolved in total.`)}
          {status.errors.open > 0 && <> <button className="link-button" onClick={onShowErrors}>{t("查看錯誤紀錄", "View errors")}</button></>}
        </StatusRow>
      </ul>
      <p><small>{jobText(status.background_jobs?.retry, t("全部重試", "retry"))}<br />
        {jobText(status.background_jobs?.second_opinion, t("AI 再確認", "AI re-check"))}</small></p>
      <p><small>{t(`檢查時間：${formatTime(status.checked_at)}`, `Checked at ${formatTime(status.checked_at)}`)}</small>{" "}
        <button className="link-button" onClick={load}>{t("重新檢查", "Check again")}</button></p>
    </section>
  );
}


function ErrorsTab({ token, navigate }) {
  const [promptDialog, askText] = useTextPrompt();
  const [filters, setFilters] = useState({ status: "open", code: "", q: "" });
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  // 錯誤明細：只對應目前打開的那一筆；status = loading | ok | error
  const [detailInfo, setDetailInfo] = useState(null);
  const detailSeq = useRef(0);
  const [busy, setBusy] = useState({});
  const [selected, setSelected] = useState(null); // 目前打開的錯誤（清單保持掛載，篩選與頁數不會掉）
  const seq = useRef(0);
  const statusText = (status) => ({ open: t("未處理", "Unresolved"), resolved: t("已處理", "Resolved"), ignored: t("已忽略", "Ignored") }[status] || status);

  const load = async () => {
    const mine = ++seq.current;
    const params = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) });
    Object.entries(filters).forEach(([k, v]) => { if (v) params.set(k, v); });
    try {
      const next = await api(`/api/admin/ai/system/errors?${params}`, token);
      if (mine === seq.current) setData(next);
    } catch (e) {
      setError(errorMessage(e));
    }
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [filters, page]);

  const loadDetail = async (id) => {
    const mine = ++detailSeq.current;
    setDetailInfo({ id, status: "loading" });
    try {
      const row = await api(`/api/admin/ai/system/errors/${id}`, token);
      if (mine === detailSeq.current) setDetailInfo({ id, status: "ok", data: row });
    } catch (e) {
      if (mine === detailSeq.current) setDetailInfo({ id, status: "error", message: errorMessage(e) });
    }
  };
  const openError = (row) => { setSelected(row); loadDetail(row.error_id); };
  const closeError = () => { detailSeq.current += 1; setDetailInfo(null); setSelected(null); };

  const setStatus = async (row, status) => {
    let note;
    if (status !== "open") {
      note = await askText(status === "resolved"
        ? { title: t("標記為已處理", "Mark as resolved"), placeholder: t("怎麼處理的？（可留空）", "How was it fixed? (optional)"),
          confirmLabel: t("標記已處理", "Resolve"), rows: 3 }
        : { title: t("忽略這個錯誤", "Ignore this error"), placeholder: t("為什麼忽略？（可留空）", "Why ignore it? (optional)"),
          confirmLabel: t("忽略", "Ignore"), rows: 3 });
      if (note === null) return;
    }
    setBusy((b) => ({ ...b, [row.error_id]: true }));
    try {
      await api(`/api/admin/ai/system/errors/${row.error_id}/status`, token, {
        method: "POST", body: JSON.stringify({ status, note }),
      });
      await load();
      setSelected((cur) => (cur && cur.error_id === row.error_id ? { ...cur, status, resolution_note: note || null } : cur));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy((b) => ({ ...b, [row.error_id]: false }));
    }
  };

  const update = (patch) => { setFilters((f) => ({ ...f, ...patch })); setPage(1); };

  return (
    <section className="admin-section">{promptDialog}
      {error && <p className="ai-admin-error" role="alert">{error}<button onClick={() => setError("")}>×</button></p>}
      {selected && (() => {
        const row = selected;
        const info = ERROR_CODES[row.code];
        return (
          <article className="syslog-error-detail">
            <button type="button" onClick={closeError}>{t("← 返回錯誤清單", "← Back to errors")}</button>
            <div className="syslog-error-line">
              <b className={`review-status-tag review-status-tag--${row.status === "open" ? "pending_review" : "confirmed"}`}>{statusText(row.status)}</b>
              <b>{codeLabel(row.code)}</b>
              <small>{t(`發生 ${row.occurrence_count} 次・最近 ${formatTime(row.last_seen_at)}`, `${row.occurrence_count}× · last ${formatTime(row.last_seen_at)}`)}</small>
            </div>
            <p className="syslog-message">{row.message}</p>
            {row.path && <p><small>{row.method} {row.path}{row.status_code ? ` → ${row.status_code}` : ""}</small></p>}
            {info && (
              <p className="syslog-fix"><small>{t("建議：", "Suggested fix: ")}{t(info.fixZh, info.fixEn)}</small>
                {info.link && <> <button className="link-button" onClick={() => navigate(info.link)}>{t("前往處理", "Go fix it")}</button></>}</p>
            )}
            {row.resolution_note && <p><small>{t("處理說明：", "Note: ")}{row.resolution_note}</small></p>}
            <h3>{t("詳細內容", "Details")}</h3>
            {(!detailInfo || detailInfo.id !== row.error_id || detailInfo.status === "loading") && <LoadingNotice text={t("載入明細…", "Loading details…")} />}
            {detailInfo?.id === row.error_id && detailInfo.status === "ok" && (
              <pre className="syslog-detail">{detailInfo.data.detail || t("沒有詳細內容。", "No details.")}</pre>
            )}
            {detailInfo?.id === row.error_id && detailInfo.status === "error" && (
              <p className="ai-admin-error" role="alert">{detailInfo.message}{" "}
                <button onClick={() => loadDetail(row.error_id)}>{t("重新讀取明細", "Reload details")}</button></p>
            )}
            <div className="review-card-actions">
              {row.status === "open" ? (
                <>
                  <button className="review-btn-primary" disabled={busy[row.error_id]} onClick={() => setStatus(row, "resolved")}>{t("標記已處理", "Mark resolved")}</button>
                  <button disabled={busy[row.error_id]} onClick={() => setStatus(row, "ignored")}>{t("忽略", "Ignore")}</button>
                </>
              ) : (
                <button disabled={busy[row.error_id]} onClick={() => setStatus(row, "open")}>{t("重新開啟", "Reopen")}</button>
              )}
            </div>
          </article>
        );
      })()}
      <div hidden={Boolean(selected)}>
      <div className="syslog-filters">
        <label>{t("狀態", "Status")}
          <select value={filters.status} onChange={(e) => update({ status: e.target.value })}>
            <option value="open">{t("未處理", "Unresolved")}</option>
            <option value="resolved">{t("已處理", "Resolved")}</option>
            <option value="ignored">{t("已忽略", "Ignored")}</option>
            <option value="">{t("全部", "All")}</option>
          </select>
        </label>
        <label>{t("類型", "Type")}
          <select value={filters.code} onChange={(e) => update({ code: e.target.value })}>
            <option value="">{t("全部", "All")}</option>
            {(data?.codes || []).map((c) => <option key={c} value={c}>{codeLabel(c)}</option>)}
          </select>
        </label>
        <label>{t("搜尋", "Search")}
          <input type="search" placeholder={t("訊息或網址", "Message or path")} defaultValue={filters.q}
            onKeyDown={(e) => { if (e.key === "Enter") update({ q: e.currentTarget.value.trim() }); }} />
        </label>
      </div>
      {!data && <LoadingNotice text={t("正在載入錯誤紀錄…", "Loading errors…")} />}
      {data && data.errors.length === 0 && (
        <p className="review-empty">{filters.status === "open" ? t("目前沒有未處理的錯誤。", "No unresolved errors.") : t("沒有符合條件的錯誤。", "No matching errors.")}</p>
      )}
      {data && data.errors.length > 0 && (
        <ul className="admin-list syslog-error-list">
          {data.errors.map((row) => (
            <li key={row.error_id}>
              <button type="button" className="syslog-error-row" onClick={() => openError(row)}>
                <span className="syslog-error-body">
                  <span className="syslog-error-line">
                    <b className={`review-status-tag review-status-tag--${row.status === "open" ? "pending_review" : "confirmed"}`}>{statusText(row.status)}</b>
                    <b>{codeLabel(row.code)}</b>
                    <small>{t(`${row.occurrence_count} 次・最近 ${formatTime(row.last_seen_at)}`, `${row.occurrence_count}× · last ${formatTime(row.last_seen_at)}`)}</small>
                  </span>
                  <span className="syslog-error-summary">{row.message}</span>
                </span>
                <span className="rpt-row-arrow" aria-hidden="true">›</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      <Pager page={page} totalPages={data?.total_pages || 1} onChange={setPage} />
      </div>
    </section>
  );
}


function AuditTab({ token }) {
  const [filters, setFilters] = useState({ action: "", admin_id: "", date_from: "", date_to: "" });
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState({});
  const seq = useRef(0);

  useEffect(() => {
    const mine = ++seq.current;
    const params = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) });
    Object.entries(filters).forEach(([k, v]) => { if (v) params.set(k, v); });
    api(`/api/admin/ai/audit-logs?${params}`, token)
      .then((next) => { if (mine === seq.current) { setData(next); setError(""); } })
      .catch((e) => setError(errorMessage(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters, page]);

  const update = (patch) => { setFilters((f) => ({ ...f, ...patch })); setPage(1); };
  const changes = (item) => {
    const before = item.before_state || {};
    const after = item.after_state || {};
    return [...new Set([...Object.keys(before), ...Object.keys(after)])]
      .filter((k) => JSON.stringify(before[k]) !== JSON.stringify(after[k]))
      .map((k) => ({ key: k, before: before[k], after: after[k] }));
  };
  const show = (v) => (v === null || v === undefined || v === "" ? "—" : typeof v === "object" ? JSON.stringify(v) : String(v));

  return (
    <section className="admin-section">
      {error && <p className="ai-admin-error" role="alert">{error}</p>}
      <div className="syslog-filters">
        <label>{t("動作", "Action")}
          <select value={filters.action} onChange={(e) => update({ action: e.target.value })}>
            <option value="">{t("全部", "All")}</option>
            {(data?.actions || []).map((a) => <option key={a} value={a}>{actionLabel(a)}</option>)}
          </select>
        </label>
        <label>{t("人員", "Who")}
          <select value={filters.admin_id} onChange={(e) => update({ admin_id: e.target.value })}>
            <option value="">{t("全部", "All")}</option>
            <option value="system">{t("系統（自動）", "System (automatic)")}</option>
            {(data?.admins || []).map((a) => <option key={a.admin_id} value={a.admin_id}>{a.admin_name}</option>)}
          </select>
        </label>
        <label>{t("從", "From")}<input type="date" value={filters.date_from} onChange={(e) => update({ date_from: e.target.value })} /></label>
        <label>{t("到", "To")}<input type="date" value={filters.date_to} onChange={(e) => update({ date_to: e.target.value })} /></label>
      </div>
      {!data && <LoadingNotice text={t("正在載入操作紀錄…", "Loading activity…")} />}
      {data && data.items.length === 0 && <p className="review-empty">{t("沒有符合條件的紀錄。", "No matching activity.")}</p>}
      {data && data.items.length > 0 && (
        <div className="syslog-table-wrap">
          <table className="syslog-table">
            <thead><tr>
              <th>{t("時間", "Time")}</th><th>{t("人員", "Who")}</th><th>{t("動作", "Action")}</th>
              <th>{t("對象", "Target")}</th><th>{t("原因", "Reason")}</th><th aria-label={t("變更", "Changes")} />
            </tr></thead>
            <tbody>
              {data.items.map((item) => {
                const diff = changes(item);
                return [
                  <tr key={item.audit_id}>
                    <td>{formatTime(item.created_at)}</td>
                    <td>{item.admin_name}</td>
                    <td>{actionLabel(item.action)}</td>
                    <td><small>{item.entity_type} #{item.entity_id}</small></td>
                    <td><small>{item.reason || "—"}</small></td>
                    <td>{diff.length > 0 && (
                      <button className="link-button" onClick={() => setOpen((o) => ({ ...o, [item.audit_id]: !o[item.audit_id] }))}>
                        {open[item.audit_id] ? t("收起", "Hide") : t(`變更 ${diff.length} 項`, `${diff.length} changes`)}
                      </button>
                    )}</td>
                  </tr>,
                  open[item.audit_id] && (
                    <tr key={`${item.audit_id}-diff`} className="syslog-diff-row"><td colSpan={6}>
                      <ul>{diff.map((d) => <li key={d.key}><code>{d.key}</code>：{show(d.before)} → {show(d.after)}</li>)}</ul>
                    </td></tr>
                  ),
                ];
              })}
            </tbody>
          </table>
        </div>
      )}
      <Pager page={page} totalPages={data?.total_pages || 1} onChange={setPage} />
    </section>
  );
}


function Pager({ page, totalPages, onChange }) {
  if (totalPages <= 1) return null;
  return (
    <div className="review-pagination">
      <button disabled={page <= 1} onClick={() => onChange(page - 1)}>{t("上一頁", "Previous")}</button>
      <span>{t(`第 ${page} / ${totalPages} 頁`, `Page ${page} of ${totalPages}`)}</span>
      <button disabled={page >= totalPages} onClick={() => onChange(page + 1)}>{t("下一頁", "Next")}</button>
    </div>
  );
}
