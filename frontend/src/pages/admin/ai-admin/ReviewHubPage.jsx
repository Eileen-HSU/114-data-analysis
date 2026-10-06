import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useAuth } from "../../../hooks/AuthContext";
import { api, peekCache } from "./shared/apiClient";
import { t } from "./shared/taxStatus";
import { isLegacyTechnicalTopic, topicDisplayName } from "./shared/reviewStates";
import { AdminPageHeader, AdminTabs } from "./shared/AdminLayout";
import ReviewPanel from "./TopicDetail/ReviewPanel";
import UnassignedReviewPage from "./UnassignedReviewPage";

// 分類審查：所有主題的審核集中在這裡，主題只是篩選條件；
// 「無法分類」（判斷不出主題、分類失敗）也在同一頁的另一個分頁。
const TOPICS_URL = "/api/admin/ai/taxonomy-topics";

export default function ReviewHubPage() {
  const { user } = useAuth();
  const token = user?.token;
  const [searchParams, setSearchParams] = useSearchParams();
  const legacyFailedView = searchParams.get("state") === "failed";
  const view = legacyFailedView || searchParams.get("view") === "unassigned" ? "unassigned" : "review";
  const topic = searchParams.get("topic") || "";
  const [topics, setTopics] = useState(() => peekCache(TOPICS_URL)?.topics || []);
  const [overview, setOverview] = useState(() => peekCache("/api/admin/ai/overview") || null);

  useEffect(() => {
    api(TOPICS_URL, token).then((d) => setTopics(d.topics || [])).catch(() => {});
    api("/api/admin/ai/overview", token).then(setOverview).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!legacyFailedView) return;
    setSearchParams({ view: "unassigned", kind: "failed" }, { replace: true });
  }, [legacyFailedView, setSearchParams]);

  const update = (patch) => {
    const next = new URLSearchParams(searchParams);
    Object.entries(patch).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
    // 切換篩選時不沿用首頁帶來的初始分頁參數
    ["state", "source", "flagged", "queue"].forEach((k) => { if ("topic" in patch || "view" in patch) next.delete(k); });
    setSearchParams(next, { replace: true });
  };
  const activeTopics = topics.filter((x) => !x.merged_into && !isLegacyTechnicalTopic(x));

  return <div className="admin-hub">
    <AdminPageHeader title={t("分類審查", "Review")}
      description={t("檢查與修正 AI 的分類結果。可以用主題篩選；無法分類的資料在另一個分頁。",
        "Check and correct AI classifications. Filter by topic; items that couldn't be classified are in the other tab.")} />
    <AdminTabs value={view} onChange={(key) => update({ view: key === "unassigned" ? "unassigned" : "" })} tabs={[
      { key: "review", label: t("待審查", "To review"), count: overview?.needs_person?.total },
      { key: "unassigned", label: t("無法分類", "Can't classify"), count: overview?.cannot_classify?.still_failed ?? overview?.cannot_classify?.total },
    ]} />
    {view === "review" ? <>
      <div className="admin-filter-bar">
        <label>
          <span>{t("主題", "Topic")}</span>
          <select value={topic} onChange={(e) => update({ topic: e.target.value })}>
            <option value="">{t("全部主題", "All topics")}</option>
            {activeTopics.map((x) => <option key={x.topic_key} value={x.topic_key}>{topicDisplayName(x)}</option>)}
          </select>
        </label>
      </div>
      <ReviewPanel key={topic || "all"} topic={topic} />
    </> : <>
      {(overview?.cannot_classify?.retrying ?? 0) > 0 && (
        <p className="admin-muted">{t(`系統會自動重試 ${overview.cannot_classify.retrying} 筆，不需要處理；重試仍失敗的才需要人工。`,
          `${overview.cannot_classify.retrying} items will be retried automatically. Only those that still fail need a person.`)}</p>
      )}
      {(overview?.auto_processing?.system_blocked ?? 0) > 0 && (
        <p className="admin-muted">{t(
          `${overview.auto_processing.system_blocked} 筆因 AI 金鑰／設定問題暫停，不列入人工分類決策；請由系統管理者修正設定後再重試。`,
          `${overview.auto_processing.system_blocked} items are blocked by AI key/configuration issues, not human classification work. Ask a system administrator to fix the configuration before retrying.`,
        )}</p>
      )}
      <UnassignedReviewPage />
    </>}
  </div>;
}
