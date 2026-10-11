import { useEffect, useState } from "react";
import { Navigate, NavLink, Outlet, useLocation, useParams, useNavigate } from "react-router-dom";
import Navbar from "../../../../components/feature/Navbar";
import { useAuth } from "../../../../hooks/AuthContext";
import { api, peekCache } from "../shared/apiClient";
import { t } from "../shared/taxStatus";
import { isLegacyTechnicalTopic, topicDisplayName } from "../shared/reviewStates";
import { AdminBreadcrumb } from "../shared/AdminLayout";

export default function TopicDetailLayout() {
  const { topicKey } = useParams();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const { user, isLoggedIn } = useAuth();
  const canAccess = isLoggedIn && user?.account_type === "admin";
  const TOPICS_URL = "/api/admin/ai/taxonomy-topics";
  const findTopic = (data) => (data?.topics || []).find((x) => x.topic_key === topicKey) || null;
  // 首頁抓過主題清單的話，標題直接顯示，不用等
  const [topic, setTopic] = useState(() => findTopic(peekCache(TOPICS_URL)));

  // 每個分頁都顯示目前在哪個主題（原本只有「分類架構」分頁看得到）
  useEffect(() => {
    if (!canAccess) return;
    const cachedTopics = peekCache(TOPICS_URL);
    setTopic(findTopic(cachedTopics));
    if (!cachedTopics) {
      api(TOPICS_URL, user.token).then((data) => setTopic(findTopic(data))).catch(() => {});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canAccess, topicKey]);

  if (!canAccess) {
    return <><Navbar /><main className="ai-admin-empty"><h1>{t("僅管理者可存取 AI 管理介面", "AI admin access restricted to administrators")}</h1><button onClick={() => navigate("/workspace")}>{t("回到分析助理", "Back to Analysis Assistant")}</button></main></>;
  }

  // 目前在主題的哪個次頁（分類架構頁本身不加最後一段）
  const subPage = pathname.endsWith("/sandbox") ? t("沙盒測試", "Sandbox / Test")
    : pathname.endsWith("/answers") ? t("回答範例", "Answers") : null;

  return <><div className="admin-page">
    <AdminBreadcrumb items={[
      { label: t("分類架構", "Taxonomy"), to: "/admin/ai/taxonomy" },
      { label: topicDisplayName(topic || topicKey), to: subPage ? `/admin/ai/topics/${topicKey}` : undefined },
      ...(subPage ? [{ label: subPage }] : []),
    ]} />
    <div className="topic-detail-header">
      <h1>{topic ? topicDisplayName(topic) : <span className="admin-skeleton-line" aria-label={t("載入中", "Loading")} />}</h1>
      {isLegacyTechnicalTopic(topic || topicKey) && <details><summary>{t("技術資訊", "Technical details")}</summary><code>{topic?.topic_key || topicKey}</code></details>}
      {topic?.is_auto_topic && !isLegacyTechnicalTopic(topic || topicKey) && <span className="topic-tag">{t("AI 自動主題", "Auto topic")}</span>}
      {topic?.published_version
        ? <span className="topic-tag">{t(`使用中 v${topic.published_version.version_number}`, `Live v${topic.published_version.version_number}`)}</span>
        : topic && <span className="topic-tag">{t("尚未發布", "Not published")}</span>}
      {topic?.latest_draft_version && <span className="topic-tag topic-tag--draft">{t(`草稿 v${topic.latest_draft_version.version_number}`, `Draft v${topic.latest_draft_version.version_number}`)}</span>}
      <NavLink className="admin-link-button" to={`/admin/ai/review?topic=${encodeURIComponent(topicKey)}`}>
        {t("審查這個主題的分類 →", "Review this topic →")}
      </NavLink>
    </div>
    <nav className="topic-detail-tabs">
      <NavLink to={`/admin/ai/topics/${topicKey}`} end>{t("分類架構", "Taxonomy")}</NavLink>
      <NavLink to={`/admin/ai/topics/${topicKey}/answers`}>{t("回答範例", "Answers")}</NavLink>
      <NavLink to={`/admin/ai/topics/${topicKey}/sandbox`}>{t("沙盒測試", "Sandbox / Test")}</NavLink>
    </nav>
    <Outlet />
  </div></>;
}

// 舊網址 /admin/ai/topics/:topicKey/review -> 分類審查（以主題篩選）
export function TopicReviewRedirect() {
  const { topicKey } = useParams();
  return <Navigate to={`/admin/ai/review?topic=${encodeURIComponent(topicKey)}`} replace />;
}
