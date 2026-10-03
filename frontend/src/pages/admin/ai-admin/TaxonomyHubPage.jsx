import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../../../hooks/AuthContext";
import { api, peekCache, prefetch } from "./shared/apiClient";
import { t, taxStatusText } from "./shared/taxStatus";
import { SkeletonCards } from "./shared/StatusWidgets";
import { AdminPageHeader, AdminTabs } from "./shared/AdminLayout";
import CreateTopicSection from "./CreateTopicSection";
import NewCategoryPage from "./NewCategoryPage";

// 分類架構：正式主題、AI 自動主題、已合併主題、建立主題，以及新類別候選。
const TOPICS_URL = "/api/admin/ai/taxonomy-topics";
const OVERVIEW_URL = "/api/admin/ai/overview";

function prefetchTopic(topic, token) {
  const versionId = topic.latest_draft_version?.version_id ?? topic.published_version?.version_id;
  if (versionId) prefetch(`/api/admin/ai/topics/${topic.topic_key}/taxonomy/${versionId}`, token);
}

export default function TaxonomyHubPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const token = user?.token;
  const [searchParams, setSearchParams] = useSearchParams();
  const view = searchParams.get("view") === "candidates" ? "candidates" : "topics";
  const [topics, setTopics] = useState(() => peekCache(TOPICS_URL)?.topics || null);
  const [overview, setOverview] = useState(() => peekCache(OVERVIEW_URL) || null);
  const [showCreate, setShowCreate] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api(TOPICS_URL, token).then((d) => setTopics(d.topics || [])).catch((e) => setError(e.message));
    api(OVERVIEW_URL, token).then(setOverview).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const counts = (key) => overview?.topics?.[key] || {};
  // 只算需要人工逐筆處理的；系統自動處理中的、新類別（另有群組數）不算
  const pending = (key) => counts(key).needs_judgement || 0;
  const byTodo = (a, b) => pending(b.topic_key) - pending(a.topic_key) || a.title.localeCompare(b.title);
  const all = topics || [];
  const official = all.filter((x) => !x.merged_into && !x.is_auto_topic).sort(byTodo);
  const auto = all.filter((x) => !x.merged_into && x.is_auto_topic).sort(byTodo);
  const merged = all.filter((x) => x.merged_into);
  const titleOf = (key) => all.find((x) => x.topic_key === key)?.title || key;

  const row = (topic) => (
    <li key={topic.topic_key} className="admin-row" onMouseEnter={() => prefetchTopic(topic, token)}>
      <div className="admin-row-main">
        <b>{topic.title}</b>
        <span className="admin-muted">
          {topic.published_version
            ? t(`使用中 v${topic.published_version.version_number}`, `Live v${topic.published_version.version_number}`)
              + (topic.latest_draft_version ? t(` · 草稿 v${topic.latest_draft_version.version_number}`, ` · draft v${topic.latest_draft_version.version_number}`) : "")
            : topic.latest_draft_version
              ? t(`未發布 · 草稿 v${topic.latest_draft_version.version_number}`, `Not published · draft v${topic.latest_draft_version.version_number}`)
              : taxStatusText(topic.status)}
          {pending(topic.topic_key) > 0 && t(` · 待審查 ${pending(topic.topic_key)}`, ` · ${pending(topic.topic_key)} to review`)}
          {(counts(topic.topic_key).new_category_groups || 0) > 0
            && t(` · 新類別 ${counts(topic.topic_key).new_category_groups} 組`, ` · ${counts(topic.topic_key).new_category_groups} new categories`)}
        </span>
      </div>
      <button onClick={() => navigate(`/admin/ai/topics/${topic.topic_key}`)}>{t("管理", "Manage")}</button>
    </li>
  );

  return <div className="admin-hub">
    <AdminPageHeader title={t("分類架構", "Taxonomy")}
      description={t("管理每個主題的分類架構，以及決定 AI 提出的新類別。", "Manage each topic's taxonomy and decide on AI-proposed categories.")}
      actions={view === "topics" && <button className="primary" onClick={() => setShowCreate((v) => !v)}>
        {showCreate ? t("取消建立", "Cancel") : t("＋ 建立主題", "＋ New topic")}</button>} />
    <AdminTabs value={view} onChange={(key) => setSearchParams(key === "candidates" ? { view: "candidates" } : {}, { replace: true })} tabs={[
      { key: "topics", label: t("主題", "Topics"), count: topics ? official.length + auto.length : null },
      { key: "candidates", label: t("新類別候選", "New category candidates"), count: overview?.needs_person?.new_category_groups },
    ]} />
    {error && <p className="ai-admin-error">{error}<button onClick={() => setError("")}>×</button></p>}

    {view === "candidates" ? <NewCategoryPage /> : !topics ? <SkeletonCards count={3} /> : <>
      {showCreate && (
        <section className="admin-panel">
          <CreateTopicSection token={token} onCreated={(key) => navigate(`/admin/ai/topics/${key}`)} />
        </section>
      )}
      <section className="admin-section-block">
        <h2>{t(`正式主題（${official.length}）`, `Official topics (${official.length})`)}</h2>
        {official.length ? <ul className="admin-list">{official.map(row)}</ul>
          : <p className="admin-muted">{t("還沒有正式主題。", "No official topics yet.")}</p>}
      </section>
      {auto.length > 0 && (
        <section className="admin-section-block">
          <h2>{t(`AI 自動主題（${auto.length}）`, `Auto topics (${auto.length})`)}</h2>
          <p className="admin-muted">{t("題目不屬於任何正式主題時 AI 暫時建立的主題。可以在主題頁併入正式主題，或發布成正式主題。",
            "Created when a question fits no official topic. Merge into an official topic or publish it from the topic page.")}</p>
          <ul className="admin-list">{auto.map(row)}</ul>
        </section>
      )}
      {merged.length > 0 && (
        <details className="admin-section-block">
          <summary>{t(`已合併主題（${merged.length}）`, `Merged topics (${merged.length})`)}</summary>
          <ul className="admin-list">
            {merged.map((topic) => (
              <li key={topic.topic_key} className="admin-row">
                <div className="admin-row-main"><b>{topic.title}</b>
                  <span className="admin-muted">{t(`已併入「${titleOf(topic.merged_into)}」`, `Merged into "${titleOf(topic.merged_into)}"`)}</span></div>
                <button onClick={() => navigate(`/admin/ai/topics/${topic.topic_key}`)}>{t("查看", "View")}</button>
              </li>
            ))}
          </ul>
        </details>
      )}
    </>}
  </div>;
}
