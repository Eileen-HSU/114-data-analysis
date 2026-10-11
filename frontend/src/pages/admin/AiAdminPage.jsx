import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../../hooks/AuthContext";
import { api, peekCache } from "./ai-admin/shared/apiClient";
import { t } from "./ai-admin/shared/taxStatus";
import { SkeletonCards } from "./ai-admin/shared/StatusWidgets";
import { AdminPageHeader } from "./ai-admin/shared/AdminLayout";
import "./ai-admin.css";

// Admin 總覽（Dashboard）：上方四張主要指標卡，中間「優先處理」只列數量大於 0 的待辦，
// 下方「系統背景處理中」不需要人工。數字全部取自後端，前端不推估；詳細操作都在左側各個頁面裡。
const OVERVIEW_URL = "/api/admin/ai/overview";
const REPORTS_URL = "/api/admin/ai/reports?page=1&page_size=1&needs_regeneration=true";
const STATUS_URL = "/api/admin/ai/system/status";

export default function AiAdminPage() {
  const { user } = useAuth();
  const token = user?.token;
  const [overview, setOverview] = useState(() => peekCache(OVERVIEW_URL) || null);
  const [reports, setReports] = useState(() => peekCache(REPORTS_URL) || null);
  const [status, setStatus] = useState(() => peekCache(STATUS_URL) || null);
  const [error, setError] = useState("");
  const [overviewLoading, setOverviewLoading] = useState(false);

  const loadOverview = async () => {
    setOverviewLoading(true);
    setError("");
    try {
      setOverview(await api(OVERVIEW_URL, token));
    } catch (e) {
      setError(e.message);
    } finally {
      setOverviewLoading(false);
    }
  };

  useEffect(() => {
    loadOverview();
    api(REPORTS_URL, token).then(setReports).catch(() => setReports(null));
    api(STATUS_URL, token).then(setStatus).catch(() => setStatus(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const auto = overview?.auto_processing;
  const decide = overview?.needs_decision;
  const person = overview?.needs_person;
  const cannot = overview?.cannot_classify;
  const errorsOpen = status?.errors?.open ?? 0;
  const dbOk = status?.database?.ok !== false;
  const bootFailed = status?.taxonomy_bootstrap?.status === "failed";
  const systemProblems = (dbOk ? 0 : 1) + (bootFailed ? 1 : 0) + errorsOpen;

  // 數字全部直接取自後端 overview / reports / system status，前端不推估。
  // value 為 null 代表「無法取得」（不是 0）。
  const reportsValue = reports ? reports.total : null;
  const systemValue = status ? systemProblems : null;
  const items = overview && [
    {
      key: "pending", value: person.total,
      title: t("待審分類", "Classifications to review"),
      text: t("需要逐筆人工確認的分類結果", "Results that need a person, one by one"),
      to: "/admin/ai/review",
      subs: [
        { key: "disagree", value: decide.ai_disagreement, title: t("AI 判斷不一致", "AI disagreement"), to: "/admin/ai/review?queue=ai_disagreement" },
        { key: "recheckFailed", value: decide.second_opinion_failed, title: t("AI 二次確認失敗", "AI re-check failed"), to: "/admin/ai/review?queue=second_opinion_failed" },
        ...(decide.other > 0 ? [{ key: "other", value: decide.other, title: t("其他需確認（分類不完整等）", "Other (incomplete classifications etc.)"), to: "/admin/ai/review?queue=other" }] : []),
      ],
    },
    {
      key: "unassigned", value: cannot.still_failed,
      title: t("無法分類", "Can't classify"),
      text: t(`自動重試後仍失敗；共 ${cannot.total} 筆無法分類，其餘由系統重試`, `Still failing after retry; ${cannot.total} unclassified in total, the rest are retried automatically`),
      to: "/admin/ai/review?view=unassigned",
    },
    {
      key: "candidates", value: decide.new_category_groups,
      title: t("新類別候選", "New category candidates"),
      text: t("以群組為單位，一次決定一組", "Decide one group at a time"),
      to: "/admin/ai/taxonomy?view=candidates",
    },
    {
      key: "provisional", value: decide.undecided_auto_topics ?? null, unavailableText: t("無法取得主題狀態", "Topic status unavailable"),
      title: t("待決策 AI 暫時主題", "Auto topics to decide"),
      text: t("決定併入既有主題或正式採用", "Merge into a topic or adopt it"),
      to: "/admin/ai/taxonomy?filter=auto",
    },
    {
      key: "reports", value: reportsValue, unavailableText: t("無法取得報告狀態", "Report status unavailable"),
      title: t("需要重新產生的報告", "Reports to regenerate"),
      text: t("資料有變動的報告", "Reports whose data changed"),
      to: "/admin/ai/reports?regen=1",
    },
    {
      key: "system", value: systemValue, danger: true, unavailableText: t("無法取得系統狀態", "System status unavailable"),
      title: t("系統異常", "System issues"),
      text: !dbOk ? t("資料庫連線異常", "Database connection problem")
        : bootFailed ? t("分類架構初始化失敗", "Taxonomy bootstrap failed")
          : errorsOpen ? t(`有 ${errorsOpen} 種錯誤尚未處理`, `${errorsOpen} unresolved error types`)
            : t("一切正常", "All good"),
      to: dbOk && !bootFailed && errorsOpen > 0 ? "/admin/ai/system?view=errors" : "/admin/ai/system",
    },
  ];
  const byKey = (key) => items.find((x) => x.key === key);
  const unavailable = (item) => item.value === null;
  const active = (item) => unavailable(item) || Number(item.value) > 0;
  const shown = (item) => (unavailable(item) ? "—" : item.value);
  const topCards = overview && ["pending", "candidates", "provisional", "system"].map(byKey);
  const priority = overview && items.filter(active);
  const zeroLinks = overview && items.filter((x) => !active(x)).flatMap((x) => [x, ...(x.subs || [])]);
  const nothingToDo = overview && priority.length === 0;

  return <>
    <AdminPageHeader title={t("總覽", "Overview")}
      description={t("先處理需要人工的項目；系統自動處理的不用管。", "Handle what needs a person first; the system takes care of the rest.")} />
    {error && <p className="ai-admin-error" role="alert">{error}<button onClick={() => setError("")}>×</button></p>}
    {!overview ? (
      <>
        <SkeletonCards count={3} />
        <button className="admin-link-button" disabled={overviewLoading} onClick={loadOverview}>
          {overviewLoading ? t("重試中…", "Retrying…") : t("重試載入總覽", "Retry overview")}
        </button>
      </>
    ) : (
      <>
        <div className="ov-cards">
          {topCards.map((item) => (
            <Link key={item.key} to={item.to} className={`ov-card${active(item) ? " ov-card--active" : ""}${item.danger && active(item) ? " ov-card--danger" : ""}`}>
              <span className="ov-card-title">{item.title}</span>
              <b className="ov-card-value">{shown(item)}</b>
              <span className="ov-card-text">{unavailable(item) ? item.unavailableText : item.text}</span>
            </Link>
          ))}
        </div>

        <section className="admin-summary-section">
          <h2 className="admin-summary-section-title">{t("優先處理", "Priority")}</h2>
          {nothingToDo && <p className="review-batch-message review-batch-message--ok" role="status">✓ {t("目前沒有需要處理的項目。", "Nothing needs your attention right now.")}</p>}
          {priority.length > 0 && (
            <ul className="admin-list ov-list">
              {priority.map((item) => (
                <li key={item.key}>
                  <Link to={item.to} className={`ov-row${unavailable(item) ? " ov-row--muted" : ""}`}>
                    <span className="ov-row-body">
                      <span className="ov-row-title">{item.title}</span>
                      <span className="ov-row-text">{unavailable(item) ? item.unavailableText : item.text}</span>
                    </span>
                    <b className="ov-row-count">{shown(item)}</b>
                    <span className="ov-row-arrow" aria-hidden="true">›</span>
                  </Link>
                  {item.subs && Number(item.value) > 0 && (
                    <details className="ov-subs">
                      <summary>{t("查看細項", "Breakdown")}</summary>
                      <ul>
                        {item.subs.map((sub) => (
                          <li key={sub.key}><Link to={sub.to}><span>{sub.title}</span><b>{sub.value}</b></Link></li>
                        ))}
                      </ul>
                    </details>
                  )}
                </li>
              ))}
            </ul>
          )}
          {zeroLinks.length > 0 && (
            <details className="ov-zero">
              <summary>{t(`目前沒有待辦的項目（${zeroLinks.length}）`, `Nothing to do here (${zeroLinks.length})`)}</summary>
              <ul>
                {zeroLinks.map((item) => (
                  <li key={item.key}><Link to={item.to}><span>{item.title}</span><b>0</b></Link></li>
                ))}
              </ul>
            </details>
          )}
        </section>

        <section className="admin-summary-section">
          <h2 className="admin-summary-section-title">{t("系統背景處理中（不需要處理）", "Handled automatically (no action needed)")}</h2>
          <div className="ov-auto">
            <div className="ov-auto-item">
              <span>{t("等待 AI 再確認", "Awaiting AI re-check")}</span>
              <b>{auto.awaiting_second_opinion + auto.awaiting_auto_confirm}</b>
              <small>{auto.awaiting_auto_confirm > 0
                ? t(`低信心 ${auto.awaiting_second_opinion}、待自動通過 ${auto.awaiting_auto_confirm}`, `${auto.awaiting_second_opinion} low confidence, ${auto.awaiting_auto_confirm} awaiting auto-approval`)
                : t("低信心結果，AI 判斷一致會自動通過", "Low-confidence results; auto-approved if the AI agrees")}</small>
            </div>
            <div className="ov-auto-item">
              <span>{t("無法分類自動重試", "Auto-retrying unclassified")}</span>
              <b>{auto.unassigned_retrying}</b>
              <small>{t("系統排程重試中", "Retried by the scheduler")}</small>
            </div>
            <div className="ov-auto-item">
              <span>{t("已自動確認", "Auto-approved")}</span>
              <b>{overview.auto_confirmed.total}</b>
              <small><Link to="/admin/ai/review?state=confirmed&source=auto">{t("抽查（不需逐筆確認）", "Spot-check (no need to confirm each)")}</Link></small>
            </div>
          </div>
        </section>
      </>
    )}
  </>;
}
