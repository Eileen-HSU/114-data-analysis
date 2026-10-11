import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import Navbar from "../../../components/feature/Navbar";
import { useAuth } from "../../../hooks/AuthContext";
import { api, apiDownload } from "./shared/apiClient";
import { t } from "./shared/taxStatus";
import { errorMessage, outdatedReasonLabel } from "./shared/reviewStates";
import { AdminPageHeader } from "./shared/AdminLayout";
import { FailureNotice, LoadingNotice } from "./shared/StatusWidgets";

const PAGE_SIZE = 20;

const reportStatusLabel = (status) => ({
  generating: t("產生中", "Generating"),
  completed: t("已完成", "Completed"),
  failed: t("產生失敗", "Failed"),
}[status] || status);

const formatTime = (value) => (value ? value.replace("T", " ").slice(0, 16) : "—");
const unitKey = (u) => `${u.source_type}:${u.identifier}`;
const sourceLabel = (type) => (type === "survey" ? t("問卷", "Survey") : t("上傳", "Upload"));
const unitPath = (key) => {
  const i = key.indexOf(":");
  return `/api/admin/ai/reports/${key.slice(0, i)}/${encodeURIComponent(key.slice(i + 1))}`;
};

// 狀態只是把後端回傳的旗標（最新報告狀態、是否過期、needs_regeneration）轉成畫面標籤，不自行推算。
function unitState(u) {
  const r = u.latest_report;
  if (!r) return { key: "none", label: t("尚未產生", "Not generated"), note: u.readiness?.can_generate ? "" : t("目前沒有可納入報告的分類結果", "No classification results to report yet") };
  if (r.status === "generating") return { key: "generating", label: t("產生中", "Generating") };
  if (r.status === "failed") return { key: "failed", label: t("產生失敗", "Generation failed"), note: t("需要重新產生", "Needs regeneration") };
  if (u.latest_completed_report?.is_outdated) return { key: "outdated", label: t("已過期", "Outdated"), note: t("需要重新產生", "Needs regeneration") };
  if (u.needs_regeneration) return { key: "regen", label: t("需要重新產生", "Needs regeneration") };
  return { key: "ok", label: t("已完成", "Up to date") };
}

function StateTag({ state }) {
  return <b className={`rpt-tag rpt-tag--${state.key}`}>{state.label}</b>;
}

// Report 管理：所有狀態（版本、outdated 原因、readiness、是否需要重新產生）
// 都來自後端 /api/admin/ai/reports（DB 依據），前端不自行推測。
// 網址：?page= / ?regen=1 / ?unit=<source_type>:<identifier>（詳情）/ ?report=<report_id>（查看某版本統計）
export default function ReportAdminPage() {
  const navigate = useNavigate();
  const { user, isLoggedIn } = useAuth();
  const token = user?.token;
  const canAccess = isLoggedIn && user?.account_type === "admin";
  const [searchParams, setSearchParams] = useSearchParams();
  const page = Math.max(parseInt(searchParams.get("page") || "1", 10) || 1, 1);
  const onlyNeedsRegen = searchParams.get("regen") === "1";
  const unitParam = searchParams.get("unit") || "";
  const reportParam = searchParams.get("report") || "";

  const [data, setData] = useState({ items: [], total: 0 });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState({});
  const [message, setMessage] = useState({});
  const [downloading, setDownloading] = useState("");
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [viewed, setViewed] = useState(null); // { report_id, aggregations } | { report_id, error }
  const busyRef = useRef(new Set());
  const requestSeq = useRef(0);
  const detailSeq = useRef(0);

  const setParams = (patch, { push = false } = {}) => {
    const next = new URLSearchParams(searchParams);
    Object.entries(patch).forEach(([k, v]) => (v ? next.set(k, String(v)) : next.delete(k)));
    setSearchParams(next, { replace: !push });
  };

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
    if (!canAccess || unitParam) return;
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canAccess, page, onlyNeedsRegen, unitParam]);

  const loadDetail = async (key, { silent = false } = {}) => {
    const seq = ++detailSeq.current;
    if (!silent) { setDetailLoading(true); setDetail(null); }
    setDetailError("");
    try {
      const result = await api(unitPath(key), token);
      if (seq === detailSeq.current) setDetail(result);
    } catch (e) {
      if (seq === detailSeq.current) setDetailError(errorMessage(e));
    } finally {
      if (seq === detailSeq.current) setDetailLoading(false);
    }
  };

  useEffect(() => {
    if (!canAccess) return;
    if (!unitParam) { detailSeq.current += 1; setDetail(null); setViewed(null); return; }
    loadDetail(unitParam);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canAccess, unitParam]);

  // ?report= 必須屬於目前報告來源的 versions；null = 還在等詳情載入
  const reportBelongs = reportParam && detail ? (detail.versions || []).some((v) => String(v.report_id) === reportParam) : null;
  // ?report= 指定的版本：讀取該版本的分類統計（既有 /reports/detail/<id>）；不屬於目前來源就不載入
  useEffect(() => {
    if (!canAccess || !unitParam || !reportParam || reportBelongs !== true) { setViewed(null); return undefined; }
    let cancelled = false;
    setViewed(null);
    api(`/api/admin/ai/reports/detail/${encodeURIComponent(reportParam)}`, token)
      .then((r) => { if (!cancelled) setViewed({ report_id: reportParam, aggregations: r.aggregations || [] }); })
      .catch((e) => { if (!cancelled) setViewed({ report_id: reportParam, error: errorMessage(e) }); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canAccess, unitParam, reportParam, reportBelongs]);

  const generate = async (u) => {
    const key = unitKey(u);
    if (busyRef.current.has(key)) return; // 進行中不重複送出
    busyRef.current.add(key);
    setBusy((p) => ({ ...p, [key]: true }));
    setMessage((p) => ({ ...p, [key]: null }));
    try {
      const res = await api(`${unitPath(key)}/generate`, token, { method: "POST" });
      setMessage((p) => ({ ...p, [key]: { ok: true, text: t(`已產生 v${res.report.version}`, `Generated v${res.report.version}`) } }));
    } catch (e) {
      setMessage((p) => ({ ...p, [key]: { ok: false, text: errorMessage(e), failure: e.body?.failure } }));
    } finally {
      busyRef.current.delete(key);
      setBusy((p) => ({ ...p, [key]: false }));
      if (unitParam === key) await loadDetail(key, { silent: true });
      else await load({ silent: true });
    }
  };

  const download = async (u, report, fmt) => {
    const key = unitKey(u);
    const id = `${report.report_id}:${fmt}`;
    if (downloading) return;
    setDownloading(id);
    setMessage((p) => ({ ...p, [key]: null }));
    try {
      await apiDownload(`/api/admin/ai/reports/detail/${report.report_id}/export?format=${fmt}`, token, `${u.label}_v${report.version}.${fmt}`);
    } catch (e) {
      setMessage((p) => ({ ...p, [key]: { ok: false, text: errorMessage(e) } }));
    } finally {
      setDownloading("");
    }
  };

  if (!canAccess) {
    return <><Navbar /><main className="ai-admin-empty"><h1>{t("僅管理者可存取 AI 管理介面", "AI admin access restricted to administrators")}</h1><button onClick={() => navigate("/workspace")}>{t("回到分析助理", "Back to Analysis Assistant")}</button></main></>;
  }

  const totalPages = Math.max(Math.ceil((data.total || 0) / PAGE_SIZE), 1);
  const generateButton = (u, key) => {
    const readiness = u.readiness || {};
    return <button className="review-btn-primary" disabled={busy[key] || !readiness.can_generate} onClick={() => generate(u)}>
      {busy[key] ? t("產生中…", "Generating…") : u.latest_report ? t("重新產生", "Regenerate") : t("產生報告", "Generate")}
    </button>;
  };
  const noticeFor = (key) => {
    const msg = message[key];
    if (!msg) return null;
    if (msg.ok) return <p className="review-batch-message review-batch-message--ok" role="status">✓ {msg.text}</p>;
    return msg.failure ? <FailureNotice failure={msg.failure} fallback={msg.text} /> : <p className="ai-admin-error" role="alert">{msg.text}</p>;
  };

  // ─────────────── 詳情 ───────────────
  if (unitParam) {
    const u = detail;
    const key = unitParam;
    const back = () => setParams({ unit: "", report: "" }, { push: true });
    return <div className="admin-hub">
      <AdminPageHeader title={u ? u.label : t("報告詳情", "Report detail")}
        actions={<button onClick={back}>{t("← 返回報告清單", "← Back to reports")}</button>} />
      {detailError && <p className="ai-admin-error" role="alert">{detailError}<button onClick={() => loadDetail(key)}>{t("重新讀取", "Retry")}</button></p>}
      {detailLoading && <LoadingNotice text={t("載入中…", "Loading…")} />}
      {u && (() => {
        const state = unitState(u);
        const readiness = u.readiness || {};
        const completed = u.latest_completed_report;
        const versions = u.versions || [];
        const latestValidId = completed && !completed.is_outdated ? completed.report_id : null;
        return <>
          <section className="rpt-summary">
            <div className="rpt-summary-head">
              <StateTag state={state} />
              <span className="admin-muted">{sourceLabel(u.source_type)} · {t("最新 ", "Latest ")}{u.latest_report ? `v${u.latest_report.version}` : "—"}</span>
              <span className="rpt-actions">{generateButton(u, key)}</span>
            </div>
            {!readiness.can_generate && <p className="admin-muted">{t("目前沒有可納入報告的分類結果，所以無法產生報告。", "There are no classification results to include, so a report can't be generated.")}</p>}
            {u.needs_regeneration && u.regeneration_reason && (
              <p className="review-flag-badge">⚠ {outdatedReasonLabel(u.regeneration_reason)}</p>
            )}
            {u.latest_report?.status === "failed" && completed && (
              <p className="rpt-warn">{t(`最新一次產生失敗（v${u.latest_report.version}），但仍有先前完成的報告 v${completed.version}：${completed.is_outdated ? "已過期，內容不是最新分類結果" : "目前仍有效"}。可在下方查看或下載。`,
                `The latest attempt (v${u.latest_report.version}) failed, but an earlier completed report v${completed.version} exists: ${completed.is_outdated ? "outdated, not the latest classifications" : "still current"}. You can view or download it below.`)}</p>
            )}
            {completed?.is_outdated && u.latest_report?.status !== "failed" && (
              <p className="rpt-warn">{t(`最近一份完成的報告 v${completed.version} 已過期（${formatTime(completed.outdated_at)}），內容不是最新分類結果；請重新產生。`,
                `The latest completed report v${completed.version} is outdated (${formatTime(completed.outdated_at)}) and no longer reflects the latest classifications. Regenerate it.`)}</p>
            )}
            {readiness.has_pending && (
              <p className="rpt-warn">{t(`目前有 ${readiness.pending_review} 筆分類尚待審核。待審結果也會納入報告，審核完成後報告可能需要重新產生。`,
                `${readiness.pending_review} classification(s) are still pending review. Pending results are included in the report and it may need regenerating after review.`)}{" "}
                <Link to="/admin/ai/review">{t("前往分類審查 →", "Go to review →")}</Link></p>
            )}
            {u.latest_report?.status === "failed" && <FailureNotice failure={u.latest_failure} fallback={u.latest_report.error_detail} />}
            {noticeFor(key)}
            <p className="admin-muted rpt-stats">
              {t(`資料現況：納入報告 ${readiness.eligible ?? 0}（待審 ${readiness.pending_review ?? 0}、已確認 ${readiness.confirmed ?? 0}、已修改 ${readiness.modified ?? 0}）・已排除 ${readiness.excluded ?? 0}・失敗 ${readiness.failed ?? 0}`,
                `Current data: included ${readiness.eligible ?? 0} (pending ${readiness.pending_review ?? 0}, confirmed ${readiness.confirmed ?? 0}, modified ${readiness.modified ?? 0}) · excluded ${readiness.excluded ?? 0} · failed ${readiness.failed ?? 0}`)}
            </p>
          </section>

          <section className="admin-section-block">
            <h2>{t(`報告版本（${versions.length}）`, `Report versions (${versions.length})`)}</h2>
            {versions.length === 0 && <p className="admin-muted">{t("還沒有產生過報告。", "No report has been generated yet.")}</p>}
            {reportParam && reportBelongs === false && (
              <p className="rpt-warn" role="alert">{t("網址中的報告版本不屬於這個報告來源，沒有載入分類統計。", "The report in the URL doesn't belong to this source, so no breakdown was loaded.")}{" "}
                <button onClick={() => setParams({ report: "" })}>{t("清除", "Clear")}</button></p>
            )}
            <ul className="admin-list">
              {versions.map((v) => {
                const outdated = v.status === "completed" && v.is_outdated;
                const tag = v.status === "completed" ? (outdated ? "outdated" : "ok") : v.status === "failed" ? "failed" : "generating";
                const open = String(v.report_id) === reportParam;
                return <li key={v.report_id} className={`rpt-version${outdated ? " rpt-version--outdated" : ""}`}>
                  <div className="rpt-version-head">
                    <b>v{v.version}</b>
                    <b className={`rpt-tag rpt-tag--${tag}`}>{outdated ? t("已過期", "Outdated") : reportStatusLabel(v.status)}</b>
                    {v.report_id === latestValidId && <span className="topic-tag topic-tag--live">{t("最新有效", "Current")}</span>}
                    <span className="admin-muted">{formatTime(v.generated_at)}</span>
                    <span className="rpt-actions">
                      {v.status === "completed" && <>
                        <button disabled={Boolean(downloading)} onClick={() => download(u, v, "xlsx")}>
                          {downloading === `${v.report_id}:xlsx` ? t("下載中…", "Downloading…") : t(`下載 Excel · v${v.version}`, `Download Excel · v${v.version}`)}
                        </button>
                        <button disabled={Boolean(downloading)} onClick={() => download(u, v, "docx")}>
                          {downloading === `${v.report_id}:docx` ? t("下載中…", "Downloading…") : t(`下載 Word · v${v.version}`, `Download Word · v${v.version}`)}
                        </button>
                        <button aria-pressed={open} onClick={() => setParams({ report: open ? "" : v.report_id })}>
                          {open ? t("收合統計", "Hide breakdown") : t("分類統計", "Breakdown")}
                        </button>
                      </>}
                    </span>
                  </div>
                  <p className="admin-muted rpt-version-meta">
                    {t(`產生時納入 ${v.eligible_count_at_generation ?? 0}・待審 ${v.pending_count_at_generation ?? 0}・排除 ${v.excluded_count_at_generation ?? 0}`,
                      `At generation: included ${v.eligible_count_at_generation ?? 0} · pending ${v.pending_count_at_generation ?? 0} · excluded ${v.excluded_count_at_generation ?? 0}`)}
                    {v.taxonomy_version_ids?.length ? ` · ${t("分類架構版本", "Taxonomy")} ${v.taxonomy_version_ids.join(", ")}` : ""}
                  </p>
                  {outdated && <p className="rpt-warn">{t("已過期：", "Outdated: ")}{outdatedReasonLabel(v.outdated_reason)}（{formatTime(v.outdated_at)}）</p>}
                  {v.status === "failed" && v.error_detail && <p className="ai-admin-error">{v.error_detail}</p>}
                  {open && (
                    <div className="rpt-breakdown">
                      {!viewed && <LoadingNotice text={t("載入統計…", "Loading breakdown…")} />}
                      {viewed?.error && <p className="ai-admin-error" role="alert">{viewed.error}</p>}
                      {viewed?.aggregations && (viewed.aggregations.length === 0
                        ? <p className="admin-muted">{t("這份報告沒有分類統計。", "This report has no breakdown.")}</p>
                        : <table className="rpt-table"><thead><tr>
                          <th>{t("大類別", "Main")}</th><th>{t("子類別", "Sub")}</th><th>{t("回答數", "Answers")}</th><th>{t("片段數", "Segments")}</th>
                        </tr></thead><tbody>
                          {viewed.aggregations.map((a) => <tr key={a.aggregation_id}><td>{a.main_category}</td><td>{a.sub_category}</td><td>{a.response_count}</td><td>{a.segment_count}</td></tr>)}
                        </tbody></table>)}
                    </div>
                  )}
                </li>;
              })}
            </ul>
          </section>
        </>;
      })()}
    </div>;
  }

  // ─────────────── 清單 ───────────────
  return <div className="admin-hub">
    <AdminPageHeader title={t("報告管理", "Report Management")}
      description={t("報告是產生當下的快照；審核、重新分類或分類架構發布後，舊報告會被標記為過期。",
        "Reports are snapshots; review changes, re-classification or taxonomy publishing mark older reports as outdated.")} />
    {error && <p className="ai-admin-error" role="alert">{error}<button onClick={() => load()}>{t("重新讀取", "Retry")}</button></p>}

    <label className="review-secondary-filter">
      <input type="checkbox" checked={onlyNeedsRegen} onChange={(e) => setParams({ regen: e.target.checked ? "1" : "", page: "" })} />
      {t("只看需要重新產生的報告", "Only show reports that need regeneration")}
    </label>

    {loading && <LoadingNotice />}
    {!loading && !error && data.items.length === 0 && <p className="review-empty-hint">{onlyNeedsRegen ? t("沒有需要重新產生的報告。", "No reports need regeneration.") : t("目前沒有任何分析資料。", "No analysis data yet.")}</p>}

    {!loading && data.items.length > 0 && (
      <ul className="admin-list">
        {data.items.map((u) => {
          const key = unitKey(u);
          const r = u.latest_report;
          const state = unitState(u);
          const pending = u.readiness?.pending_review ?? 0;
          const hints = [
            state.key === "failed" && u.latest_completed_report
              && t(`仍有 v${u.latest_completed_report.version}（${u.latest_completed_report.is_outdated ? "已過期" : "目前有效"}）`,
                `v${u.latest_completed_report.version} still available (${u.latest_completed_report.is_outdated ? "outdated" : "current"})`),
            state.key === "outdated" && u.latest_completed_report?.outdated_reason && outdatedReasonLabel(u.latest_completed_report.outdated_reason),
            state.key === "regen" && u.regeneration_reason && outdatedReasonLabel(u.regeneration_reason),
            state.key === "none" && state.note,
            pending > 0 && t(`待審 ${pending} 筆`, `${pending} pending review`),
          ].filter(Boolean);
          return <li key={key}>
            <button type="button" className="rpt-row-btn" title={u.label} onClick={() => setParams({ unit: key }, { push: true })}>
              <span className="rpt-row-body">
                <span className="rpt-row-title">{u.label}</span>
                <span className="rpt-row-line">
                  <StateTag state={state} />
                  <span>{sourceLabel(u.source_type)}</span>
                  <span>{r ? `${t("最新", "Latest")} v${r.version} · ${formatTime(r.generated_at)}` : t("尚無版本", "No versions")}</span>
                </span>
                {hints.length > 0 && <span className="rpt-row-hint">{hints.join(" · ")}</span>}
              </span>
              <span className="rpt-row-arrow" aria-hidden="true">›</span>
            </button>
          </li>;
        })}
      </ul>
    )}

    {data.total > PAGE_SIZE && (
      <div className="review-pagination">
        <button type="button" disabled={page <= 1} onClick={() => setParams({ page: page - 1 > 1 ? page - 1 : "" })}>{t("上一頁", "Previous")}</button>
        <span>{t(`第 ${page} / ${totalPages} 頁（共 ${data.total} 筆）`, `Page ${page} / ${totalPages} (${data.total} total)`)}</span>
        <button type="button" disabled={page >= totalPages} onClick={() => setParams({ page: page + 1 })}>{t("下一頁", "Next")}</button>
      </div>
    )}
  </div>;
}
