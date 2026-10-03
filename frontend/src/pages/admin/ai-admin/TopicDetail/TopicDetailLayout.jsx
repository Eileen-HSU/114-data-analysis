import { useEffect, useState } from "react";
import { NavLink, Outlet, useParams, useNavigate } from "react-router-dom";
import Navbar from "../../../../components/feature/Navbar";
import { useAuth } from "../../../../hooks/AuthContext";
import { api } from "../shared/apiClient";
import { t } from "../shared/taxStatus";

export default function TopicDetailLayout() {
  const { topicKey } = useParams();
  const navigate = useNavigate();
  const { user, isLoggedIn } = useAuth();
  const canAccess = isLoggedIn && user?.account_type === "admin";
  const [topic, setTopic] = useState(null);

  // 每個分頁都顯示目前在哪個主題（原本只有「分類架構」分頁看得到）
  useEffect(() => {
    if (!canAccess) return;
    setTopic(null);
    api("/api/admin/ai/taxonomy-topics", user.token)
      .then((data) => setTopic((data.topics || []).find((x) => x.topic_key === topicKey) || null))
      .catch(() => setTopic(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canAccess, topicKey]);

  if (!canAccess) {
    return <><Navbar /><main className="ai-admin-empty"><h1>{t("僅管理者可存取 AI 管理介面", "AI admin access restricted to administrators")}</h1><button onClick={() => navigate("/workspace")}>{t("回到分析助理", "Back to Analysis Assistant")}</button></main></>;
  }

  return <><Navbar /><main className="ai-admin-page topic-detail-layout">
    <NavLink to="/admin/ai" className="back">← {t("AI 管理首頁", "AI admin home")}</NavLink>
    <div className="topic-detail-header">
      <h1>{topic?.title || topicKey}</h1>
      {topic?.is_auto_topic && <span className="topic-tag">{t("AI 自動主題", "Auto topic")}</span>}
      {topic?.published_version
        ? <span className="topic-tag">{t(`使用中 v${topic.published_version.version_number}`, `Live v${topic.published_version.version_number}`)}</span>
        : topic && <span className="topic-tag topic-tag--draft">{t("尚未發布", "Not published")}</span>}
    </div>
    <nav className="topic-detail-tabs">
      <NavLink to={`/admin/ai/topics/${topicKey}`} end>{t("分類架構", "Taxonomy")}</NavLink>
      <NavLink to={`/admin/ai/topics/${topicKey}/review`}>{t("分類審核", "Review")}</NavLink>
      <NavLink to={`/admin/ai/topics/${topicKey}/sandbox`}>{t("沙盒測試", "Sandbox")}</NavLink>
    </nav>
    <Outlet />
  </main></>;
}
