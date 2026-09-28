import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import Navbar from "../../components/feature/Navbar";
import { useAuth } from "../../hooks/AuthContext";
import { api } from "./ai-admin/shared/apiClient";
import { t, taxStatusText } from "./ai-admin/shared/taxStatus";
import CreateTopicSection from "./ai-admin/CreateTopicSection";
import { LoadingNotice } from "./ai-admin/shared/StatusWidgets";
import "./ai-admin.css";

export default function AiAdminPage() {
  const navigate = useNavigate();
  const { user, isLoggedIn } = useAuth();
  const token = user?.token;
  const canAccess = isLoggedIn && user?.account_type === "admin";

  const [topics, setTopics] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const loadTopics = async () => {
    setLoading(true);
    try {
      setTopics((await api("/api/admin/ai/taxonomy-topics", token)).topics);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!canAccess) return;
    loadTopics();
  }, [canAccess]);

  const handleTopicCreated = (topicKey) => {
    navigate(`/admin/ai/topics/${topicKey}`);
  };

  if (!canAccess) return <><Navbar /><main className="ai-admin-empty"><h1>{t("僅管理者可存取 AI 管理介面", "AI admin access restricted to administrators")}</h1><button onClick={() => navigate("/workspace")}>{t("回到分析助理", "Back to Analysis Assistant")}</button></main></>;

  return <><Navbar /><main className="ai-admin-page">
    <header>
      <p className="eyebrow">{t("系統管理", "INTERNAL ADMINISTRATION")}</p>
      <h1>{t("AI 分類管理", "AI Classification Administration")}</h1>
      <p>{t("管理各分析主題的分類架構，並審核 AI 分類結果。", "Manage each topic's taxonomy and review AI classification results.")}</p>
    </header>
    {error && <p className="ai-admin-error">{error}<button onClick={() => setError("")}>×</button></p>}
    <CreateTopicSection token={token} onCreated={handleTopicCreated} />
    {loading && <LoadingNotice text={t("正在載入分析主題…", "Loading topics…")} />}
    <div className="topic-grid">
      {topics.map((topic) => (
        <article key={topic.topic_key} className={`topic-card${topic.merged_into ? " topic-card--merged" : ""}`}>
          <h2>{topic.title}</h2>
          {(topic.is_auto_topic || topic.merged_into) && (
            <p className="topic-card-tags">
              {topic.is_auto_topic && <span className="topic-tag">{t("AI 自動主題", "Auto topic")}</span>}
              {topic.merged_into && <span className="topic-tag topic-tag--merged">
                {t("已併入", "Merged into")} {topics.find((x) => x.topic_key === topic.merged_into)?.title || topic.merged_into}
              </span>}
            </p>
          )}
          <p>{t("狀態：", "Status:")} <b>{taxStatusText(topic.status)}</b></p>
          {topic.published_version && <small>{t("已發布", "Published")}: v{topic.published_version.version_number}</small>}
          {topic.published_version && topic.latest_draft_version && <br />}
          {topic.latest_draft_version && <small>{t("草稿", "Draft")}: v{topic.latest_draft_version.version_number} ({taxStatusText(topic.latest_draft_version.status)})</small>}
          <div>
            <button className="primary" onClick={() => navigate(`/admin/ai/topics/${topic.topic_key}`)}>{t("管理", "Manage")}</button>
          </div>
        </article>
      ))}
    </div>
    <p style={{ marginTop: 24 }}>
      <button onClick={() => navigate("/admin/ai/unassigned")}>{t("其他 / 未歸屬資料", "Other / Unassigned Data")}</button>{" "}
      <button onClick={() => navigate("/admin/ai/reports")}>{t("報告管理", "Report Management")}</button>{" "}
      <button onClick={() => navigate("/admin/ai/new-categories")}>{t("新類別候選", "New Category Candidates")}</button>
    </p>
  </main></>;
}
