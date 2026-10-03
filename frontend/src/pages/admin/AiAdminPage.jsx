import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../../hooks/AuthContext";
import { api, peekCache } from "./ai-admin/shared/apiClient";
import { t } from "./ai-admin/shared/taxStatus";
import { SkeletonCards } from "./ai-admin/shared/StatusWidgets";
import { AdminPageHeader } from "./ai-admin/shared/AdminLayout";
import "./ai-admin.css";

// Admin 總覽：只放摘要。每張卡片一個數字、一句說明、一個前往處理的按鈕；
// 詳細操作都在左側各個頁面裡。
const OVERVIEW_URL = "/api/admin/ai/overview";
const REPORTS_URL = "/api/admin/ai/reports?page=1&page_size=1&needs_regeneration=true";
const STATUS_URL = "/api/admin/ai/system/status";

export default function AiAdminPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const token = user?.token;
  const [overview, setOverview] = useState(() => peekCache(OVERVIEW_URL) || null);
  const [reports, setReports] = useState(() => peekCache(REPORTS_URL) || null);
  const [status, setStatus] = useState(() => peekCache(STATUS_URL) || null);
  const [error, setError] = useState("");

  useEffect(() => {
    api(OVERVIEW_URL, token).then(setOverview).catch((e) => setError(e.message));
    api(REPORTS_URL, token).then(setReports).catch(() => setReports(null));
    api(STATUS_URL, token).then(setStatus).catch(() => setStatus(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const cannot = overview?.cannot_classify;
  const person = overview?.needs_person;
  const errorsOpen = status?.errors?.open_last_24h ?? 0;
  const dbOk = status?.database?.ok !== false;
  const bootFailed = status?.taxonomy_bootstrap?.status === "failed";
  const systemProblems = (dbOk ? 0 : 1) + (bootFailed ? 1 : 0) + errorsOpen;

  const cards = overview && [
    {
      key: "cannot", value: cannot.total, tone: cannot.total ? "alert" : "ok",
      title: t("無法分類", "Can't classify"),
      text: t(`判斷不出主題 ${cannot.unrouted}、分類失敗 ${cannot.failed}`, `${cannot.unrouted} without a topic, ${cannot.failed} failed`),
      action: t("前往處理", "Resolve"), to: "/admin/ai/review?view=unassigned",
    },
    {
      key: "review", value: person.total, tone: person.total ? "warn" : "ok",
      title: t("待人工審查", "Needs review"),
      text: (person.awaiting_second_opinion ?? 0) > 0
        ? t(`其中 ${person.awaiting_second_opinion} 筆等 AI 再確認`, `${person.awaiting_second_opinion} awaiting AI re-check`)
        : t("AI 不確定、需要人看的結果", "Results the AI wasn't sure about"),
      action: t("前往審查", "Review"), to: "/admin/ai/review?flagged=1",
    },
    {
      key: "candidates", value: person.new_category_groups, tone: person.new_category_groups ? "warn" : "ok",
      title: t("新類別候選", "New category candidates"),
      text: t("AI 提出、還沒決定的新類別（組）", "AI-proposed categories awaiting a decision"),
      action: t("前往決定", "Decide"), to: "/admin/ai/taxonomy?view=candidates",
    },
    {
      key: "reports", value: reports?.total ?? "—", tone: reports?.total ? "warn" : "ok",
      title: t("報告需更新", "Reports to update"),
      text: t("資料有變動、需要重新產生的報告", "Reports whose data changed"),
      action: t("前往報告", "Reports"), to: "/admin/ai/reports",
    },
    {
      key: "system", value: status ? systemProblems : "—", tone: systemProblems ? "alert" : "ok",
      title: t("系統異常", "System issues"),
      text: !status ? t("無法取得系統狀態", "System status unavailable")
        : !dbOk ? t("資料庫連線異常", "Database connection problem")
          : bootFailed ? t("分類架構初始化失敗", "Taxonomy bootstrap failed")
            : errorsOpen ? t(`最近 24 小時有 ${errorsOpen} 種錯誤未處理`, `${errorsOpen} unresolved error types in 24h`)
              : t("一切正常", "All good"),
      action: t("前往系統管理", "System"), to: "/admin/ai/system",
    },
  ];

  return <>
    <AdminPageHeader title={t("總覽", "Overview")}
      description={t("需要處理的事情摘要。點卡片進入對應頁面處理。", "What needs attention. Open a card to handle it.")} />
    {error && <p className="ai-admin-error">{error}<button onClick={() => setError("")}>×</button></p>}
    {!overview ? <SkeletonCards count={3} /> : (
      <div className="admin-summary-grid">
        {cards.map((card) => (
          <button key={card.key} className={`admin-summary-card admin-summary-card--${card.tone}`} onClick={() => navigate(card.to)}>
            <span className="admin-summary-title">{card.title}</span>
            <span className="admin-summary-value">{card.value}</span>
            <span className="admin-summary-text">{card.text}</span>
            <span className="admin-summary-action">{card.action} →</span>
          </button>
        ))}
      </div>
    )}
  </>;
}
