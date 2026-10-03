import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
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

const SECTIONS = [
  { key: "auto", title: t("系統自動處理中", "Handled automatically") },
  { key: "decide", title: t("需要人工決策", "Needs your decision") },
  { key: "report", title: t("報告", "Reports") },
  { key: "system", title: t("系統", "System") },
];

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

  const auto = overview?.auto_processing;
  const decide = overview?.needs_decision;
  const errorsOpen = status?.errors?.open_last_24h ?? 0;
  const dbOk = status?.database?.ok !== false;
  const bootFailed = status?.taxonomy_bootstrap?.status === "failed";
  const systemProblems = (dbOk ? 0 : 1) + (bootFailed ? 1 : 0) + errorsOpen;
  const tone = (n, kind) => (n ? kind : "ok");

  // 系統自動處理中：不需要人，排程會處理（AI 再確認、舊資料自動通過、無法分類自動重試）
  // 需要人工決策：只有例外。新類別、暫定主題以群組／主題為單位，一次一個決策
  const cards = overview && [
    {
      key: "recheck", group: "auto", value: auto.awaiting_second_opinion + auto.awaiting_auto_confirm, tone: "auto",
      title: t("等待 AI 再確認", "Awaiting AI re-check"),
      text: auto.awaiting_auto_confirm > 0
        ? t(`低信心 ${auto.awaiting_second_opinion}、符合條件待自動通過 ${auto.awaiting_auto_confirm}`, `${auto.awaiting_second_opinion} low confidence, ${auto.awaiting_auto_confirm} awaiting auto-approval`)
        : t("低信心結果，AI 判斷一致會自動通過", "Low-confidence results; auto-approved if the AI agrees"),
    },
    {
      key: "retrying", group: "auto", value: auto.unassigned_retrying, tone: "auto",
      title: t("無法分類自動重試", "Auto-retrying unclassified"),
      text: t("系統排程重試中，不需要處理", "The system retries these automatically"),
    },
    {
      key: "disagree", group: "decide", value: decide.ai_disagreement, tone: tone(decide.ai_disagreement, "warn"),
      title: t("AI 判斷不一致", "AI disagreement"),
      text: t("兩次 AI 判斷不同，逐筆選一個", "Two AI passes differ; pick one"),
      action: t("前往審查", "Review"), to: "/admin/ai/review?queue=ai_disagreement",
    },
    {
      key: "candidates", group: "decide", value: decide.new_category_groups, tone: tone(decide.new_category_groups, "warn"),
      title: t("新類別候選", "New category candidates"),
      text: t("以群組為單位，一次決定一組", "Decide one group at a time"),
      action: t("前往決定", "Decide"), to: "/admin/ai/taxonomy?view=candidates",
    },
    {
      key: "retryFailed", group: "decide", value: decide.retry_failed, tone: tone(decide.retry_failed, "alert"),
      title: t("自動重試仍失敗", "Still failing after retry"),
      text: t(`無法分類 ${decide.unassigned_retry_failed}、AI 再確認失敗 ${decide.second_opinion_failed}`,
        `${decide.unassigned_retry_failed} unclassified, ${decide.second_opinion_failed} re-check failed`),
      action: t("前往處理", "Resolve"),
      to: decide.unassigned_retry_failed > 0 ? "/admin/ai/review?view=unassigned" : "/admin/ai/review?queue=second_opinion_failed",
    },
    ...(decide.other + decide.provisional_topics > 0 ? [{
      key: "other", group: "decide", value: decide.other + decide.provisional_topics, tone: "warn",
      title: t("其他需確認", "Other items"),
      text: t(`分類不完整等 ${decide.other}、待決策的 AI 自動主題 ${decide.provisional_topics}`,
        `${decide.other} incomplete etc., ${decide.provisional_topics} auto topics to decide`),
      action: t("前往審查", "Review"), to: decide.other > 0 ? "/admin/ai/review?queue=other" : "/admin/ai/taxonomy",
    }] : []),
    {
      key: "reports", group: "report", value: reports?.total ?? "—", tone: reports?.total ? "warn" : "ok",
      title: t("報告需更新", "Reports to update"),
      text: t("資料有變動、需要重新產生的報告", "Reports whose data changed"),
      action: t("前往報告", "Reports"), to: "/admin/ai/reports",
    },
    {
      key: "system", group: "system", value: status ? systemProblems : "—", tone: systemProblems ? "alert" : "ok",
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
      description={t("系統會自動處理大部分資料，這裡只需要處理例外。", "The system handles most data. Only exceptions need you.")} />
    {error && <p className="ai-admin-error">{error}<button onClick={() => setError("")}>×</button></p>}
    {!overview ? <SkeletonCards count={3} /> : (
      <>
        {SECTIONS.map((section) => (
          <section key={section.key} className="admin-summary-section">
            <h2 className="admin-summary-section-title">{section.title}</h2>
            <div className="admin-summary-grid">
              {cards.filter((card) => card.group === section.key).map((card) => (
                card.to ? (
                  <button key={card.key} className={`admin-summary-card admin-summary-card--${card.tone}`} onClick={() => navigate(card.to)}>
                    <span className="admin-summary-title">{card.title}</span>
                    <span className="admin-summary-value">{card.value}</span>
                    <span className="admin-summary-text">{card.text}</span>
                    <span className="admin-summary-action">{card.action} →</span>
                  </button>
                ) : (
                  <div key={card.key} className={`admin-summary-card admin-summary-card--${card.tone}`}>
                    <span className="admin-summary-title">{card.title}</span>
                    <span className="admin-summary-value">{card.value}</span>
                    <span className="admin-summary-text">{card.text}</span>
                  </div>
                )
              ))}
            </div>
            {section.key === "auto" && (
              <p className="admin-muted admin-spotcheck">
                {t(`已自動確認 ${overview.auto_confirmed.total} 筆`, `${overview.auto_confirmed.total} auto-approved`)}
                {" · "}<Link to="/admin/ai/review?state=confirmed&source=auto">{t("抽查（不需逐筆確認）", "Spot-check (no need to confirm each)")}</Link>
              </p>
            )}
          </section>
        ))}
      </>
    )}
  </>;
}
