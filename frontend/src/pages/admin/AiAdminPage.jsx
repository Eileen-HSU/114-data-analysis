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
  const [overview, setOverview] = useState(null);
  const [newCategories, setNewCategories] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [bootstrapHealth, setBootstrapHealth] = useState(null);
  const [systemStatus, setSystemStatus] = useState(null);
  // 兩個背景工作：全部重試（無法分類）、AI 再確認（低信心）
  const bulk = useBackgroundJob("/api/admin/ai/unassigned/retry-all", token, setError, () => loadAll());
  const recheck = useBackgroundJob("/api/admin/ai/second-opinion", token, setError, () => loadAll());

  const loadAll = async () => {
    setLoading(true);
    try {
      const [topicData, overviewData, candidateData] = await Promise.all([
        api("/api/admin/ai/taxonomy-topics", token),
        api("/api/admin/ai/overview", token),
        api("/api/admin/ai/new-categories", token),
      ]);
      setTopics(topicData.topics);
      setOverview(overviewData);
      setNewCategories(candidateData.items || []);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!canAccess) return;
    loadAll();
    bulk.reload();
    recheck.reload();
    // 分類架構初始化（bootstrap）狀態：失敗不會讓網站停掉，所以要在這裡明顯提醒
    api("/api/admin/ai/system/status", token).then(setSystemStatus).catch(() => setSystemStatus(null));
    api("/api/admin/ai/system/health", token)
      .then((d) => setBootstrapHealth(d.taxonomy_bootstrap || null))
      .catch(() => setBootstrapHealth(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canAccess]);

  const handleTopicCreated = (topicKey) => {
    navigate(`/admin/ai/topics/${topicKey}`);
  };

  if (!canAccess) return <><Navbar /><main className="ai-admin-empty"><h1>{t("僅管理者可存取 AI 管理介面", "AI admin access restricted to administrators")}</h1><button onClick={() => navigate("/workspace")}>{t("回到分析助理", "Back to Analysis Assistant")}</button></main></>;

  const topicCounts = (key) => overview?.topics?.[key] || {
    needs_judgement: 0, other_pending: 0, low_confidence: 0, auto_confirmed: 0, new_category_groups: 0,
  };
  const pendingOf = (key) => topicCounts(key).needs_judgement + topicCounts(key).other_pending;
  const byTodo = (a, b) => pendingOf(b.topic_key) - pendingOf(a.topic_key) || a.title.localeCompare(b.title);
  const activeTopics = topics.filter((topic) => !topic.merged_into);
  const officialTopics = activeTopics.filter((topic) => !topic.is_auto_topic).sort(byTodo);
  const autoTopics = activeTopics.filter((topic) => topic.is_auto_topic).sort(byTodo);
  const mergedTopics = topics.filter((topic) => topic.merged_into);
  const autoTopicKeys = new Set(autoTopics.map((topic) => topic.topic_key));
  const decidedCandidates = newCategories.filter((item) => !autoTopicKeys.has(item.topic_key));
  const undecidedByTopic = autoTopics
    .map((topic) => ({ topic, items: newCategories.filter((item) => item.topic_key === topic.topic_key) }))
    .filter((group) => group.items.length > 0);
  const titleOf = (key) => topics.find((x) => x.topic_key === key)?.title || key;
  const scrollToTopics = () => document.getElementById("ai-admin-topics")?.scrollIntoView({ behavior: "smooth" });

  return <><Navbar /><main className="ai-admin-page">
    <header>
      <p className="eyebrow">{t("系統管理", "INTERNAL ADMINISTRATION")}</p>
      <h1>{t("AI 分類管理", "AI Classification Administration")}</h1>
    </header>
    {error && <p className="ai-admin-error">{error}<button onClick={() => setError("")}>×</button></p>}
    <BootstrapWarning health={bootstrapHealth} />
    {loading && <LoadingNotice text={t("正在載入待辦事項…", "Loading what needs attention…")} />}
    {systemStatus && (systemStatus.errors.open_last_24h > 0 || !systemStatus.database.ok) && (
      <p className="admin-system-alert" role="status">
        {!systemStatus.database.ok
          ? t("資料庫連線異常，部分功能可能無法使用。", "The database connection has a problem; some features may not work.")
          : t(`最近 24 小時有 ${systemStatus.errors.open_last_24h} 種系統錯誤還沒處理。`,
            `${systemStatus.errors.open_last_24h} system error types in the last 24 hours are unresolved.`)}
        {" "}<button className="link-button" onClick={() => navigate("/admin/ai/system")}>{t("查看系統紀錄", "View system logs")}</button>
      </p>
    )}

    {overview && (
      <section className="admin-todo" aria-labelledby="admin-todo-title">
        <div className="admin-section-head">
          <h2 id="admin-todo-title">{t("今天需要處理的事", "What needs attention")}</h2>
          <p>{t("依急迫程度排列，從左邊開始處理。", "Ordered by urgency. Start from the left.")}</p>
        </div>
        <div className="admin-todo-grid">
          <article className="admin-todo-card admin-todo-card--urgent">
            <p className="admin-todo-step">{t("第 1 步：最優先", "Step 1: most urgent")}</p>
            <p className="admin-todo-figure"><b>{overview.cannot_classify.total}</b>{t(" 筆無法分類", " can't be classified")}</p>
            <p>{t("這些回答目前沒有任何結果：", "These answers have no result yet: ")}
              {t(`判斷不出主題 ${overview.cannot_classify.unrouted}、分類失敗 ${overview.cannot_classify.failed}。`,
                `${overview.cannot_classify.unrouted} without a topic, ${overview.cannot_classify.failed} failed.`)}</p>
            <JobStatus data={bulk.data} labels={RETRY_LABELS} />
            <div className="admin-todo-actions">
              {bulk.running ? (
                <button disabled={bulk.busy || bulk.data.job.cancel_requested} onClick={bulk.cancel}>
                  {bulk.data.job.cancel_requested ? t("停止中…", "Stopping…") : t("停止", "Stop")}
                </button>
              ) : (
                <button className="primary" disabled={bulk.busy || overview.cannot_classify.total === 0}
                  onClick={() => bulk.start(t(
                    `要在背景把這 ${overview.cannot_classify.total} 筆重新分析一次嗎？\n\n會使用 Gemini 額度。系統會自動配合額度調整速度，額度不足時會放慢或自動暫停。執行期間可以離開這個頁面，隨時回來看進度。`,
                    `Re-analyse these ${overview.cannot_classify.total} items in the background?\n\nThis uses Gemini quota. The speed adjusts automatically and pauses if quota runs out. You can leave this page.`,
                  ))}>
                  {bulk.busy ? t("處理中…", "Working…") : t("全部重試", "Retry all")}
                </button>
              )}
              <button disabled={overview.cannot_classify.total === 0} onClick={() => navigate("/admin/ai/unassigned")}>
                {t("逐筆查看", "View one by one")}
              </button>
            </div>
          </article>

          <article className="admin-todo-card admin-todo-card--judge">
            <p className="admin-todo-step">{t("第 2 步：需要人判斷", "Step 2: needs a person")}</p>
            <p className="admin-todo-figure"><b>{overview.needs_person.total}</b>{t(" 筆待審核", " waiting for review")}</p>
            <ul className="admin-todo-chips">
              {(overview.needs_person.awaiting_second_opinion ?? 0) > 0 && (
                <li>{t(`等 AI 再確認 ${overview.needs_person.awaiting_second_opinion}`, `Awaiting AI re-check ${overview.needs_person.awaiting_second_opinion}`)}</li>
              )}
              {(overview.needs_person.ai_disagreement ?? 0) > 0 && (
                <li>{t(`兩次 AI 不一致 ${overview.needs_person.ai_disagreement}`, `AI checks disagree ${overview.needs_person.ai_disagreement}`)}</li>
              )}
              <li>{t(`新類別 ${overview.needs_person.new_category_groups} 組`, `${overview.needs_person.new_category_groups} new categories`)}</li>
              {overview.needs_person.other_pending > 0 && (
                <li>{t(`暫定分類或舊資料 ${overview.needs_person.other_pending}`, `Provisional or older ${overview.needs_person.other_pending}`)}</li>
              )}
            </ul>
            <p>{t("低信心的結果會由更強的 AI 自動再確認（每 10 分鐘），兩次一致就自動通過，不一致的才需要你看。",
              "Low-confidence results are re-checked by a stronger AI every 10 minutes. If both agree it's approved automatically; only disagreements need you.")}</p>
            <JobStatus data={recheck.data} labels={RECHECK_LABELS} />
            <div className="admin-todo-actions">
              {recheck.running ? (
                <button disabled={recheck.busy || recheck.data.job.cancel_requested} onClick={recheck.cancel}>
                  {recheck.data.job.cancel_requested ? t("停止中…", "Stopping…") : t("停止再確認", "Stop re-check")}
                </button>
              ) : (overview.needs_person.awaiting_second_opinion ?? 0) > 0 && (
                <button disabled={recheck.busy}
                  onClick={() => recheck.start(t(
                    `要立刻讓 AI 再確認 ${overview.needs_person.awaiting_second_opinion} 筆低信心的結果嗎？\n\n不按的話，系統也會每 10 分鐘自動處理。`,
                    `Re-check ${overview.needs_person.awaiting_second_opinion} low-confidence results now?\n\nIf you don't, the system does it automatically every 10 minutes.`,
                  ))}>
                  {recheck.busy ? t("處理中…", "Working…") : t("立刻讓 AI 再確認", "Re-check with AI now")}
                </button>
              )}
              <button className="primary" disabled={overview.needs_person.total === 0} onClick={scrollToTopics}>{t("依主題審核", "Review by topic")}</button>
              {overview.needs_person.new_category_groups > 0 && (
                <button onClick={() => document.getElementById("ai-admin-new-categories")?.scrollIntoView({ behavior: "smooth" })}>
                  {t("處理新類別", "Handle new categories")}
                </button>
              )}
            </div>
          </article>

          <article className="admin-todo-card admin-todo-card--auto">
            <p className="admin-todo-step">{t("第 3 步：可以抽查", "Step 3: spot-check")}</p>
            <p className="admin-todo-figure"><b>{overview.auto_confirmed.total}</b>{t(" 筆已自動通過", " auto-approved")}</p>
            <p>{t("AI 信心 ≥ 0.75，而且類別在已發布的分類架構裡。已計入報告，有疑問隨時可以重新審核。",
              "Confidence ≥ 0.75 and the category is in the published taxonomy. Counted in reports; re-review any time.")}</p>
            <div className="admin-todo-actions">
              <button disabled={overview.auto_confirmed.total === 0} onClick={scrollToTopics}>{t("依主題抽查", "Spot-check by topic")}</button>
            </div>
          </article>
        </div>
      </section>
    )}

    {(decidedCandidates.length > 0 || undecidedByTopic.length > 0) && (
      <section id="ai-admin-new-categories" className="admin-section">
        <div className="admin-section-head">
          <h2>{t("AI 提出的新類別", "New categories proposed by the AI")}</h2>
          <p>{t("每一組選一個動作就完成，回答會同時更新。", "One action per group; the answers update with it.")}</p>
        </div>

        {decidedCandidates.length > 0 && (
          <div className="admin-subsection">
            <h3>{t("主題已確定：可以直接決定", "Topic decided: ready to decide")}</h3>
            <ul className="admin-candidate-list">
              {decidedCandidates.slice(0, 5).map((item) => (
                <li key={`${item.topic_key}|${item.main_category}|${item.sub_category}`}>
                  <div>
                    <b>{item.sub_category}</b>
                    <small>{t(`${item.count} 筆 · ${titleOf(item.topic_key)}`, `${item.count} · ${titleOf(item.topic_key)}`)}</small>
                  </div>
                  {item.examples?.[0] && <q>{item.examples[0]}</q>}
                </li>
              ))}
            </ul>
            <button className="primary" onClick={() => navigate("/admin/ai/new-categories")}>
              {decidedCandidates.length > 5
                ? t(`處理全部 ${decidedCandidates.length} 組`, `Handle all ${decidedCandidates.length} groups`)
                : t("加入、合併或排除", "Add, merge or exclude")}
            </button>
          </div>
        )}

        {undecidedByTopic.length > 0 && (
          <div className="admin-subsection">
            <h3>{t("主題還沒確定：要先決定主題", "Topic not decided yet: decide the topic first")}</h3>
            {undecidedByTopic.map(({ topic, items }) => (
              <div key={topic.topic_key} className="admin-undecided">
                <p><b>{t(`「${topic.title}」是 AI 自動建立的主題，底下有 ${items.length} 個新類別`,
                  `"${topic.title}" is an auto topic with ${items.length} new ${items.length === 1 ? "category" : "categories"}`)}</b></p>
                <ul className="admin-todo-chips">{items.map((item) => <li key={item.sub_category}>{item.sub_category}</li>)}</ul>
                <p>{t("這個主題的分類架構也是 AI 自己歸納、還沒有人審過的，所以現在沒有可靠的類別能合併。先把主題併入正式主題（或發布成正式主題），再處理這些新類別。",
                  "This topic's taxonomy was drafted by the AI and hasn't been reviewed, so there's nothing reliable to merge into yet. Merge the topic into an official one (or publish it as official) first.")}</p>
                <button className="primary" onClick={() => navigate(`/admin/ai/topics/${topic.topic_key}`)}>{t("先處理這個主題", "Handle this topic first")}</button>
              </div>
            ))}
          </div>
        )}
      </section>
    )}

    <section id="ai-admin-topics" className="admin-section">
      <div className="admin-section-head">
        <h2>{t("正式主題", "Official topics")}</h2>
        <p>{t("有待辦的排在前面。沒有待辦的主題不用點進去。", "Topics with work come first. Topics with nothing to do can be skipped.")}</p>
      </div>
      <div className="topic-grid">
        {officialTopics.map((topic) => (
          <TopicCard key={topic.topic_key} topic={topic} counts={topicCounts(topic.topic_key)} navigate={navigate} />
        ))}
      </div>
    </section>

    {autoTopics.length > 0 && (
      <section className="admin-section">
        <div className="admin-section-head">
          <h2>{t(`AI 自動建立的主題（${autoTopics.length}）`, `Auto topics (${autoTopics.length})`)}</h2>
          <p>{t("題目不屬於任何正式主題時，AI 會暫時建立一個。建議併入正式主題，或在分類架構頁發布成正式主題。",
            "When a question fits no official topic, the AI creates a temporary one. Merge it into an official topic, or publish it as official from its Taxonomy page.")}</p>
        </div>
        <ul className="admin-auto-topics">
          {autoTopics.map((topic) => {
            const counts = topicCounts(topic.topic_key);
            return (
              <li key={topic.topic_key}>
                <div>
                  <b>{topic.title}</b>
                  <small>
                    {topic.published_version ? t("已發布", "Published") : t("暫定分類中", "Provisional taxonomy")}
                    {pendingOf(topic.topic_key) > 0 && t(` · 待審 ${pendingOf(topic.topic_key)}`, ` · ${pendingOf(topic.topic_key)} pending`)}
                    {counts.new_category_groups > 0 && t(` · 新類別 ${counts.new_category_groups} 組`, ` · ${counts.new_category_groups} new categories`)}
                  </small>
                </div>
                <div className="admin-auto-topic-actions">
                  <button onClick={() => navigate(`/admin/ai/topics/${topic.topic_key}`)}>{t("併入正式主題或發布", "Merge or publish")}</button>
                  {pendingOf(topic.topic_key) > 0 && (
                    <button onClick={() => navigate(`/admin/ai/topics/${topic.topic_key}/review`)}>{t("審核回答", "Review answers")}</button>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      </section>
    )}

    {mergedTopics.length > 0 && (
      <details className="admin-section admin-merged">
        <summary>{t(`已併入其他主題（${mergedTopics.length}）`, `Merged into other topics (${mergedTopics.length})`)}</summary>
        <ul>
          {mergedTopics.map((topic) => (
            <li key={topic.topic_key}>
              <button className="link-button" onClick={() => navigate(`/admin/ai/topics/${topic.topic_key}`)}>{topic.title}</button>
              {" → "}{titleOf(topic.merged_into)}
            </li>
          ))}
        </ul>
      </details>
    )}

    <section className="admin-section">
      <CreateTopicSection token={token} onCreated={handleTopicCreated} />
      <p className="admin-secondary-links">
        <button onClick={() => navigate("/admin/ai/unassigned")}>{t("其他 / 未歸屬資料", "Other / Unassigned Data")}</button>
        <button onClick={() => navigate("/admin/ai/new-categories")}>{t("新類別候選", "New Category Candidates")}</button>
        <button onClick={() => navigate("/admin/ai/reports")}>{t("報告管理", "Report Management")}</button>
        <button onClick={() => navigate("/admin/ai/system")}>
          {t("系統紀錄", "System logs")}
          {systemStatus?.errors?.open > 0 && <span className="review-tab-count">{systemStatus.errors.open}</span>}
        </button>
      </p>
    </section>
  </main></>;
}


// 背景工作（全部重試、AI 再確認）共用：開始、停止、執行中每 5 秒更新進度，結束時通知首頁重新整理。
function useBackgroundJob(path, token, setError, onFinished) {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const running = data?.job?.status === "running" && !data.job.interrupted;

  const reload = async () => {
    try {
      setData(await api(path, token));
    } catch {
      setData(null);
    }
  };

  useEffect(() => {
    if (!running) return undefined;
    const timer = setInterval(async () => {
      const next = await api(path, token).catch(() => null);
      if (!next) return;
      setData(next);
      if (next.job?.status !== "running") onFinished();
    }, 5000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running]);

  const call = async (suffix) => {
    setBusy(true);
    try {
      await api(`${path}${suffix}`, token, { method: "POST" });
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
      reload();
    }
  };

  return {
    data, busy, running, reload,
    start: (confirmText) => { if (window.confirm(confirmText)) call(""); },
    cancel: () => call("/cancel"),
  };
}

const RETRY_LABELS = {
  running: (j) => t(`正在重試… ${j.processed} / ${j.total_at_start}`, `Retrying… ${j.processed} / ${j.total_at_start}`),
  counts: (j) => t(`成功 ${j.succeeded}、仍失敗 ${j.still_failed}${j.skipped ? `、跳過 ${j.skipped}` : ""}`,
    `${j.succeeded} fixed, ${j.still_failed} still failing${j.skipped ? `, ${j.skipped} skipped` : ""}`),
  name: () => t("全部重試", "retry"),
};
const RECHECK_LABELS = {
  running: (j) => t(`AI 正在再確認… ${j.processed} / ${j.total_at_start}`, `AI re-checking… ${j.processed} / ${j.total_at_start}`),
  counts: (j) => t(`一致並自動通過 ${j.succeeded}、不一致 ${j.still_failed}`,
    `${j.succeeded} agreed and approved, ${j.still_failed} disagreed`),
  name: () => t("AI 再確認", "AI re-check"),
};

// 背景工作的進度／上一次的結果。沒有任何紀錄時不顯示。
function JobStatus({ data, labels }) {
  const job = data?.job;
  if (!job) return null;
  const counts = labels.counts(job);
  if (job.status === "running" && !job.interrupted) {
    const percent = job.total_at_start ? Math.min(100, Math.round((job.processed / job.total_at_start) * 100)) : 0;
    return (
      <div className="admin-bulk-status" role="status" aria-live="polite">
        <p><b>{labels.running(job)}</b></p>
        <div className="admin-bulk-bar"><span style={{ width: `${percent}%` }} /></div>
        <p><small>{counts}{job.quota_waits > 0 && t("。AI 額度不足，已自動放慢速度。", ". AI quota is tight, so it slowed down.")}</small></p>
      </div>
    );
  }
  const name = labels.name();
  const summary = {
    completed: t(`上次${name}已完成：${counts}。`, `Last ${name} finished: ${counts}.`),
    paused_quota: t(`上次${name}因 AI 額度用完自動暫停（${counts}）。額度恢復後再按一次即可接續。`,
      `Last ${name} paused because the AI quota ran out (${counts}). Run it again once quota is back.`),
    cancelled: t(`上次${name}已停止（${counts}）。`, `Last ${name} was stopped (${counts}).`),
    failed: t(`上次${name}發生錯誤（${counts}）。可以再按一次。`, `Last ${name} hit an error (${counts}). Try again.`),
  }[job.status];
  const text = job.interrupted
    ? t(`上次${name}中斷了（${counts}），可以再按一次接續，已處理好的不會重做。`,
      `The last ${name} was interrupted (${counts}). Run it again to continue; finished items won't be redone.`)
    : summary;
  return text ? <p className="admin-bulk-status"><small>{text}</small></p> : null;
}


// 正式主題卡片：直接顯示待辦，沒有待辦就說沒有，不用點進去找。
function TopicCard({ topic, counts, navigate }) {
  const pending = counts.needs_judgement + counts.other_pending;
  const base = `/admin/ai/topics/${topic.topic_key}`;
  return (
    <article className={`topic-card${pending > 0 ? " topic-card--todo" : ""}`}>
      <h3>{topic.title}</h3>
      <p className="topic-card-tags">
        {topic.published_version
          ? <span className="topic-tag">{t(`使用中 v${topic.published_version.version_number}`, `Live v${topic.published_version.version_number}`)}</span>
          : <span className="topic-tag">{taxStatusText(topic.status)}</span>}
        {topic.latest_draft_version && (
          <span className="topic-tag topic-tag--draft">{t(`草稿 v${topic.latest_draft_version.version_number}`, `Draft v${topic.latest_draft_version.version_number}`)}</span>
        )}
      </p>
      <p className="topic-card-counts">
        {pending > 0
          ? <>
            {counts.needs_judgement > 0 && <span className="topic-count topic-count--judge">{t(`待判斷 ${counts.needs_judgement}`, `${counts.needs_judgement} to judge`)}</span>}
            {counts.other_pending > 0 && <span className="topic-count">{t(`其他待審 ${counts.other_pending}`, `${counts.other_pending} other pending`)}</span>}
          </>
          : <span className="topic-count topic-count--done">{t("沒有待辦", "Nothing to do")}</span>}
        {counts.auto_confirmed > 0 && <span className="topic-count">{t(`自動通過 ${counts.auto_confirmed}`, `${counts.auto_confirmed} auto-approved`)}</span>}
      </p>
      <div>
        {pending > 0 && (
          <button className="primary" onClick={() => navigate(`${base}/review${counts.needs_judgement > 0 ? "?flagged=1" : ""}`)}>
            {t("審核", "Review")}
          </button>
        )}
        {counts.auto_confirmed > 0 && (
          <button onClick={() => navigate(`${base}/review?state=confirmed&source=auto`)}>{t("抽查自動通過", "Spot-check auto-approved")}</button>
        )}
        <button onClick={() => navigate(base)}>{t("分類架構", "Taxonomy")}</button>
      </div>
    </article>
  );
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
