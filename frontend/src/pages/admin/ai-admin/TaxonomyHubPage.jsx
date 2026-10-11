import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../../../hooks/AuthContext";
import { api, peekCache, prefetch } from "./shared/apiClient";
import { t, taxStatusText } from "./shared/taxStatus";
import { isLegacyTechnicalTopic, topicDisplayName } from "./shared/reviewStates";
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
  const [search, setSearch] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const searchSeq = useRef(0);

  useEffect(() => {
    api(OVERVIEW_URL, token).then(setOverview).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => setSearchQuery(search.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    const seq = ++searchSeq.current;
    const path = searchQuery ? `${TOPICS_URL}?q=${encodeURIComponent(searchQuery)}` : TOPICS_URL;
    api(path, token)
      .then((result) => {
        if (seq === searchSeq.current) {
          setTopics(result.topics || []);
          setError("");
        }
      })
      .catch((e) => { if (seq === searchSeq.current) setError(e.message); });
  }, [searchQuery, token]);

  const counts = (key) => overview?.topics?.[key] || {};
  // 只算需要人工逐筆處理的；系統自動處理中的、新類別（另有群組數）不算
  const pending = (key) => counts(key).needs_judgement || 0;
  const byTodo = (a, b) => pending(b.topic_key) - pending(a.topic_key) || a.title.localeCompare(b.title);
  const all = topics || [];
  const legacy = all.filter((x) => !x.merged_into && isLegacyTechnicalTopic(x));
  // 「AI 自動主題」= AI 暫時建立、還沒有正式發布版本的主題。auto_ 開頭的主題一旦發布，已經是正式主題，
  // 要放進「正式主題」，按鈕也不該再叫「決定去向」。
  const isUndecidedAuto = (x) => !!x.is_auto_topic && !x.published_version;
  const official = all.filter((x) => !x.merged_into && !isUndecidedAuto(x) && !isLegacyTechnicalTopic(x)).sort(byTodo);
  const auto = all.filter((x) => !x.merged_into && isUndecidedAuto(x) && !isLegacyTechnicalTopic(x)).sort(byTodo);
  const merged = all.filter((x) => x.merged_into);
  const titleOf = (key) => topicDisplayName(all.find((x) => x.topic_key === key) || key);

  const FILTERS = ["all", "official", "auto"];
  const filter = FILTERS.includes(searchParams.get("filter")) ? searchParams.get("filter") : "all";
  const setFilter = (key) => setSearchParams(key === "all" ? {} : { filter: key }, { replace: true });
  const listed = [...official, ...legacy, ...auto];
  const shown = filter === "official" ? [...official, ...legacy] : filter === "auto" ? auto : listed;
  const filterCount = { all: listed.length, official: official.length + legacy.length, auto: auto.length };
  const filterLabel = { all: t("全部", "All"), official: t("正式主題", "Official"), auto: t("AI 暫時主題", "AI temporary") };

  const row = (topic) => {
    const undecided = isUndecidedAuto(topic);
    const groups = counts(topic.topic_key).new_category_groups || 0;
    const name = topicDisplayName(topic);
    return (
      <li key={topic.topic_key}>
        <button type="button" className="rpt-row-btn" title={name}
          onMouseEnter={() => prefetchTopic(topic, token)} onFocus={() => prefetchTopic(topic, token)}
          onClick={() => navigate(`/admin/ai/topics/${topic.topic_key}`)}>
          <span className="rpt-row-body">
            <span className="rpt-row-title">{name}</span>
            <span className="rpt-row-line">
              <span className={`rpt-tag ${undecided ? "rpt-tag--regen" : isLegacyTechnicalTopic(topic) ? "rpt-tag--none" : "rpt-tag--ok"}`}>
                {undecided ? t("AI 暫時", "AI temporary") : isLegacyTechnicalTopic(topic) ? t("舊資料", "Legacy") : t("正式", "Official")}
              </span>
              {topic.published_version
                ? <span className="topic-tag topic-tag--live">{t(`使用中 v${topic.published_version.version_number}`, `Live v${topic.published_version.version_number}`)}</span>
                : <span className="topic-tag">{t("尚未發布", "Not published")}</span>}
              {topic.latest_draft_version
                ? <span className="topic-tag topic-tag--draft">{t(`草稿 v${topic.latest_draft_version.version_number}`, `Draft v${topic.latest_draft_version.version_number}`)}</span>
                : !topic.published_version && <span>{taxStatusText(topic.status)}</span>}
              {groups > 0 && <span>{t(`新類別 ${groups} 組`, `${groups} new categories`)}</span>}
              {pending(topic.topic_key) > 0 && <span>{t(`待審查 ${pending(topic.topic_key)}`, `${pending(topic.topic_key)} to review`)}</span>}
              {isLegacyTechnicalTopic(topic) && <code className="tax-row-key">{topic.topic_key}</code>}
            </span>
          </span>
          <span className="rpt-row-arrow" aria-hidden="true">›</span>
        </button>
      </li>
    );
  };

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
      <div className="admin-filter-bar">
        <label>
          <span>{t("搜尋主題", "Search topics")}</span>
          <input type="search" value={search} onChange={(e) => setSearch(e.target.value)}
            placeholder={t("輸入主題名稱或代碼", "Name or topic key")} />
        </label>
      </div>
      {showCreate && (
        <section className="admin-panel">
          <CreateTopicSection token={token} onCreated={(key) => navigate(`/admin/ai/topics/${key}`)} />
        </section>
      )}
      <div className="tax-filter" role="group" aria-label={t("主題類型", "Topic type")}>
        {FILTERS.map((key) => (
          <button key={key} type="button" aria-pressed={filter === key}
            className={`tax-filter-btn${filter === key ? " tax-filter-btn--active" : ""}`} onClick={() => setFilter(key)}>
            {filterLabel[key]}<span className="admin-tab-count">{filterCount[key]}</span>
          </button>
        ))}
      </div>
      {shown.length ? <ul className="admin-list">{shown.map(row)}</ul>
        : <p className="admin-muted">{searchQuery ? t("沒有符合搜尋的主題。", "No topics match the search.")
          : filter === "auto" ? t("目前沒有 AI 暫時主題。", "No AI temporary topics.") : t("還沒有正式主題。", "No official topics yet.")}</p>}
      {merged.length > 0 && (
        <details className="admin-section-block">
          <summary>{t(`已合併主題（${merged.length}）`, `Merged topics (${merged.length})`)}</summary>
          <ul className="admin-list">
            {merged.map((topic) => (
              <li key={topic.topic_key}>
                <button type="button" className="rpt-row-btn" title={topicDisplayName(topic)} onClick={() => navigate(`/admin/ai/topics/${topic.topic_key}`)}>
                  <span className="rpt-row-body">
                    <span className="rpt-row-title">{topicDisplayName(topic)}</span>
                    <span className="rpt-row-line">{t(`已併入「${titleOf(topic.merged_into)}」`, `Merged into "${titleOf(topic.merged_into)}"`)}</span>
                  </span>
                  <span className="rpt-row-arrow" aria-hidden="true">›</span>
                </button>
              </li>
            ))}
          </ul>
        </details>
      )}
    </>}
  </div>;
}
