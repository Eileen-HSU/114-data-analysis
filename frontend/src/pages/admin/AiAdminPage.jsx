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
  const [bootstrapHealth, setBootstrapHealth] = useState(null);

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
    // 分類架構初始化（bootstrap）狀態：失敗不會讓網站停掉，所以要在這裡明顯提醒
    api("/api/admin/ai/system/health", token)
      .then((d) => setBootstrapHealth(d.taxonomy_bootstrap || null))
      .catch(() => setBootstrapHealth(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
    <BootstrapWarning health={bootstrapHealth} />
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


// 分類架構初始化（taxonomy bootstrap）警告：只給管理員看，錯誤摘要已由後端去除敏感資訊
function BootstrapWarning({ health }) {
  if (!health || !health.warning) return null;
  const when = health.last_failure_at || health.last_run_at;
  return (
    <div className="ai-admin-health-warning" role="alert">
      <b>
        {health.warning === "bootstrap_failed"
          ? t("⚠ 分類架構初始化失敗", "⚠ Taxonomy bootstrap failed")
          : t("⚠ 目前沒有任何已發布的分類架構", "⚠ No published taxonomy yet")}
      </b>
      <p>
        {health.open_classification_enabled
          ? t("上傳的資料只有在 AI 自動歸納分類架構成功時才會分析；不會改用程式內建的舊分類規則。",
            "Uploads are analysed only if the AI succeeds in deriving a taxonomy; built-in legacy rules are never used as a fallback.")
          : t("固定分類模式：在發布分類架構之前，上傳的資料只會保存、不會分類。",
            "Fixed-taxonomy mode: uploads are saved but not classified until a taxonomy is published.")}
      </p>
      <p><small>
        {t("狀態", "Status")}: {health.status}
        {when ? ` · ${t("時間", "Time")}: ${new Date(when).toLocaleString()}` : ""}
        {health.error_summary ? ` · ${t("原因", "Reason")}: ${health.error_summary}` : ""}
      </small></p>
      <p><small>{t("處理方式：確認資料庫連線後重新啟動後端，或執行 flask bootstrap-taxonomy；也可以直接建立並發布主題的分類架構。",
        "Fix: check the database connection and restart the backend, or run `flask bootstrap-taxonomy`; you can also create and publish a topic taxonomy directly.")}</small></p>
    </div>
  );
}
