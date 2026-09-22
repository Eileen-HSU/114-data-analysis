import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import Navbar from "../../components/feature/Navbar";
import { useAuth } from "../../hooks/AuthContext";
import { api } from "./ai-admin/shared/apiClient";
import { t, taxStatusText } from "./ai-admin/shared/taxStatus";
import CreateTopicSection from "./ai-admin/CreateTopicSection";
import "./ai-admin.css";

export default function AiAdminPage() {
  const navigate = useNavigate();
  const { user, isLoggedIn } = useAuth();
  const token = user?.token;
  const canAccess = isLoggedIn && user?.account_type === "admin";

  const [topics, setTopics] = useState([]);
  const [error, setError] = useState("");

  // 「排除舊版資料」：跟 topics 清單無關的獨立批次操作，狀態單獨管理，
  // 不動 topics/error 既有的 loading 邏輯。
  const [excludeLegacyBusy, setExcludeLegacyBusy] = useState(false);
  const [excludeLegacyMessage, setExcludeLegacyMessage] = useState("");

  const loadTopics = async () => {
    try {
      setTopics((await api("/api/admin/ai/taxonomy-topics", token)).topics);
    } catch (e) {
      setError(e.message);
    }
  };

  useEffect(() => {
    if (!canAccess) return;
    loadTopics();
  }, [canAccess]);

  const handleTopicCreated = (topicKey) => {
    navigate(`/admin/ai/topics/${topicKey}`);
  };

  const handleExcludeLegacy = async () => {
    const confirmed = window.confirm(
      t(
        "將排除所有沒有信心分數的舊版分類資料。原始分類紀錄會保留，但不再納入目前分析。是否繼續？",
        "This will exclude all legacy classifications without a confidence score. The original classification records will be kept, but they will no longer be included in current analysis. Continue?",
      ),
    );
    if (!confirmed) return;

    setExcludeLegacyBusy(true);
    setExcludeLegacyMessage("");
    setError("");
    try {
      const result = await api(
        "/api/classification/review/exclude-legacy",
        token,
        { method: "POST" },
      );
      setExcludeLegacyMessage(
        t(
          `已排除 ${result.affected_count} 筆舊版資料`,
          `Excluded ${result.affected_count} legacy classification(s)`,
        ),
      );
      // 成功後 reload：這批資料本來就跟 topics 卡片無關，reload
      // topics 清單是為了維持既有頁面「操作完成後重新整理畫面狀態」
      // 的一貫行為，不代表這個操作有改到任何 Topic/Taxonomy 資料。
      await loadTopics();
    } catch (e) {
      setError(e.message);
    } finally {
      setExcludeLegacyBusy(false);
    }
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
    <div className="topic-grid">
      {topics.map((topic) => (
        <article key={topic.topic_key} className="topic-card">
          <h2>{topic.title}</h2>
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
      <button onClick={() => navigate("/admin/ai/unassigned")}>{t("其他 / 未歸屬資料", "Other / Unassigned Data")}</button>
    </p>
    <section className="ai-admin-legacy-cleanup" style={{ marginTop: 24 }}>
      <button onClick={handleExcludeLegacy} disabled={excludeLegacyBusy}>
        {excludeLegacyBusy
          ? t("排除中…", "Excluding…")
          : t("排除舊版資料", "Exclude Legacy Data")}
      </button>
      {excludeLegacyMessage && <p className="ai-admin-legacy-cleanup-message">{excludeLegacyMessage}</p>}
    </section>
  </main></>;
}