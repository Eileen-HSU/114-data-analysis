import { useEffect, useRef, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import Navbar from "../../../components/feature/Navbar";
import { useAuth } from "../../../hooks/AuthContext";
import { api, apiDownload } from "./shared/apiClient";
import { t } from "./shared/taxStatus";
import { errorMessage, outdatedReasonLabel } from "./shared/reviewStates";
import { FailureNotice, LoadingNotice } from "./shared/StatusWidgets";

const PAGE_SIZE = 20;

const reportStatusLabel = (status) => ({
  generating: t("產生中", "Generating"),
  completed: t("已完成", "Completed"),
  failed: t("產生失敗", "Failed"),
}[status] || status);

const formatTime = (value) => (value ? value.replace("T", " ").slice(0, 16) : "—");

// Report 管理：所有狀態（版本、outdated 原因、readiness、是否需要重新產生）
// 都來自後端 /api/admin/ai/reports（DB 依據），前端不自行推測。
export default function ReportAdminPage() {
  const navigate = useNavigate();
  const { user, isLoggedIn } = useAuth();
  const token = user?.token;
  const canAccess = isLoggedIn && user?.account_type === "admin";

  const [page, setPage] = useState(1);
  const [onlyNeedsRegen, setOnlyNeedsRegen] = useState(false);
  const [data, setData] = useState({ items: [], total: 0 });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState({});
  const [rowMessage, setRowMessage] = useState({});
  const [expanded, setExpanded] = useState(null);
  const [versions, setVersions] = useState({});

  const unitKey = (u) => `${u.source_type}:${u.identifier}`;

  const [loading, setLoading] = useState(false);
  const requestSeq = useRef(0);
  const load = async ({ silent = false } = {}) => {
    const seq = ++requestSeq.current;
    if (!silent) setLoading(true);
    try {
      setError("");
      const params = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) });
      if (onlyNeedsRegen) params.set("needs_regeneration", "true");
      const result = await api(`/api/admin/ai/reports?${params}`, token);
      if (seq === requestSeq.current) setData(result);
    } catch (e) {
      if (seq === requestSeq.current) setError(errorMessage(e));
    } finally {
      if (seq === requestSeq.current) setLoading(false);
    }
  };

  useEffect(() => {
    if (!canAccess) return;
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canAccess, page, onlyNeedsRegen]);

  const loadVersions = async (u) => {
    const detail = await api(`/api/admin/ai/reports/${u.source_type}/${encodeURIComponent(u.identifier)}`, token);
    setVersions((p) => ({ ...p, [unitKey(u)]: detail.versions || [] }));
  };

  const generate = async (u) => {
    const key = unitKey(u);
    setBusy((p) => ({ ...p, [key]: true }));
    setRowMessage((p) => ({ ...p, [key]: null }));
    try {
      const res = await api(`/api/admin/ai/reports/${u.source_type}/${encodeURIComponent(u.identifier)}/generate`, token, { method: "POST" });
      setRowMessage((p) => ({ ...p, [key]: { ok: true, text: t(`已產生 v${res.report.version}`, `Generated v${res.report.version}`) } }));
    } catch (e) {
      setRowMessage((p) => ({ ...p, [key]: { ok: false, text: errorMessage(e) } }));
    } finally {
      setBusy((p) => ({ ...p, [key]: false }));
      await load({ silent: true });
      if (expanded === key) await loadVersions(u);
    }
  };

  const download = async (u, report, fmt) => {
    const key = unitKey(u);
    try {
      await apiDownload(`/api/admin/ai/reports/detail/${report.report_id}/export?format=${fmt}`, token, `${u.label}_v${report.version}.${fmt}`);
    } catch (e) {
      setRowMessage((p) => ({ ...p, [key]: { ok: false, text: errorMessage(e) } }));
    }
  };

  const toggle = async (u) => {
    const key = unitKey(u);
    if (expanded === key) { setExpanded(null); return; }
    setExpanded(key);
    try { await loadVersions(u); } catch (e) { setError(errorMessage(e)); }
  };

  if (!canAccess) {
    return <><Navbar /><main className="ai-admin-empty"><h1>{t("僅管理者可存取 AI 管理介面", "AI admin access restricted to administrators")}</h1><button onClick={() => navigate("/workspace")}>{t("回到分析助理", "Back to Analysis Assistant")}</button></main></>;
  }

  const totalPages = Math.max(Math.ceil((data.total || 0) / PAGE_SIZE), 1);

  return <><Navbar /><main className="ai-admin-page">
    <NavLink to="/admin/ai" className="back">← {t("所有主題", "All topics")}</NavLink>
    <h1>{t("報告管理", "Report Management")}</h1>
    <p><small>{t("報告是產生當下的快照；人工審核、重新分類或 Taxonomy 發布後，舊報告會被標記為需要重新產生。",
      "Reports are snapshots. Review changes, re-classification or taxonomy publishing mark older reports as outdated.")}</small></p>
    {error && <p className="ai-admin-error">{error}<button onClick={() => setError("")}>×</button></p>}

    <label className="review-secondary-filter">
      <input type="checkbox" checked={onlyNeedsRegen} onChange={(e) => { setOnlyNeedsRegen(e.target.checked); setPage(1); }} />
      {t("只看需要重新產生的報告", "Only show reports that need regeneration")}
    </label>

    {loading && <LoadingNotice />}

    {!loading && data.items.length === 0 && <p className="review-empty-hint">{t("目前沒有任何分析資料。", "No analysis data yet.")}</p>}

    {!loading && data.items.map((u) => {
      const key = unitKey(u);
      const r = u.latest_report;
      const readiness = u.readiness || {};
      const msg = rowMessage[key];
      return (
        <article key={key} className="review-card">
          <div className="review-card-top">
            <b className={`review-status-tag review-status-tag--${u.needs_regeneration ? "pending_review" : "confirmed"}`}>
              {u.needs_regeneration ? t("需要重新產生", "Needs regeneration") : r ? t("最新", "Up to date") : t("尚無報告", "No report")}
            </b>
            <span className="review-card-segment">{u.label}（{u.source_type === "survey" ? t("問卷", "Survey") : t("上傳", "Upload")}）</span>
          </div>
          <div className="review-card-mid">
            <p><span className="review-field-label">{t("最新報告", "Latest report")}</span>
              {r ? `v${r.version} · ${reportStatusLabel(r.status)}` : "—"}</p>
            <p><span className="review-field-label">{t("Taxonomy 版本", "Taxonomy versions")}</span>
              {r?.taxonomy_version_ids?.length ? r.taxonomy_version_ids.join(", ") : "—"}</p>
            <p><span className="review-field-label">{t("建立 / 最後更新", "Created / updated")}</span>
              {formatTime(r?.generated_at)} / {formatTime(r?.updated_at)}</p>
            <p><span className="review-field-label">{t("資料就緒度", "Readiness")}</span>
              {t(`可用 ${readiness.eligible ?? 0}（已確認 ${readiness.confirmed ?? 0}、已修改 ${readiness.modified ?? 0}）・待處理 ${readiness.pending_review ?? 0}・已排除 ${readiness.excluded ?? 0}・失敗 ${readiness.failed ?? 0}`,
                `Eligible ${readiness.eligible ?? 0} (confirmed ${readiness.confirmed ?? 0}, modified ${readiness.modified ?? 0}) · pending ${readiness.pending_review ?? 0} · excluded ${readiness.excluded ?? 0} · failed ${readiness.failed ?? 0}`)}</p>
            {u.latest_completed_report?.is_outdated && (
              <p className="review-flag-badge">⚠ {t("已過期：", "Outdated: ")}{outdatedReasonLabel(u.latest_completed_report.outdated_reason)}（{formatTime(u.latest_completed_report.outdated_at)}）</p>
            )}
            {u.needs_regeneration && u.regeneration_reason && !u.latest_completed_report?.is_outdated && (
              <p className="review-flag-badge">{outdatedReasonLabel(u.regeneration_reason)}</p>
            )}
            {r?.status === "failed" && <FailureNotice failure={u.latest_failure} fallback={r.error_detail} />}
            {readiness.has_pending && <p><small>{t("仍有待處理的分類，報告只會包含已確認 / 已修改的結果。", "Pending items exist; only confirmed / modified results are included.")}</small></p>}
          </div>
          {msg && <p className={msg.ok ? "review-batch-message" : "ai-admin-error"}>{msg.text}</p>}
          <div className="review-card-actions">
            <button className="review-btn-primary" disabled={busy[key] || !readiness.can_generate} onClick={() => generate(u)}
              title={!readiness.can_generate ? t("沒有已確認的分類結果", "No confirmed classifications") : ""}>
              {busy[key] ? t("產生中…", "Generating…") : r ? t("重新產生", "Regenerate") : t("產生報告", "Generate")}
            </button>
            {u.latest_completed_report && (
              <>
                <button onClick={() => download(u, u.latest_completed_report, "xlsx")}>{t("下載 Excel", "Download Excel")}</button>
                <button onClick={() => download(u, u.latest_completed_report, "docx")}>{t("下載 Word", "Download Word")}</button>
              </>
            )}
            <button onClick={() => toggle(u)}>{expanded === key ? t("收合版本", "Hide versions") : t(`所有版本（${u.report_count}）`, `All versions (${u.report_count})`)}</button>
          </div>
          {expanded === key && (
            <ul>
              {(versions[key] || []).map((v) => (
                <li key={v.report_id}><small>
                  v{v.version} · {reportStatusLabel(v.status)} · {formatTime(v.generated_at)}
                  {v.is_outdated ? ` · ${t("已過期", "outdated")}（${outdatedReasonLabel(v.outdated_reason)}）` : ""}
                  {v.status === "failed" ? ` · ${v.error_detail}` : ""}
                  {v.status === "completed" && (
                    <> · <button onClick={() => download(u, v, "xlsx")}>Excel</button> <button onClick={() => download(u, v, "docx")}>Word</button></>
                  )}
                </small></li>
              ))}
            </ul>
          )}
        </article>
      );
    })}

    {data.total > PAGE_SIZE && (
      <div className="review-pagination">
        <button type="button" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>{t("上一頁", "Previous")}</button>
        <span>{t(`第 ${page} / ${totalPages} 頁（共 ${data.total} 筆）`, `Page ${page} / ${totalPages} (${data.total} total)`)}</span>
        <button type="button" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>{t("下一頁", "Next")}</button>
      </div>
    )}
  </main></>;
}
