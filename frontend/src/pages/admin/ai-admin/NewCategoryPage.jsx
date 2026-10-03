import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTextPrompt } from "./shared/TextPromptDialog";
import Navbar from "../../../components/feature/Navbar";
import { useAuth } from "../../../hooks/AuthContext";
import { api } from "./shared/apiClient";
import { t } from "./shared/taxStatus";
import { errorMessage } from "./shared/reviewStates";
import { LoadingNotice } from "./shared/StatusWidgets";

// 開放式分類的「新類別候選」：AI 分類時提出、不在目前分類清單裡的類別。
// 採用 -> 加進該主題的分類架構草稿（到「分類架構」頁檢查後發布）；
// 合併 -> 這組回答改成某個既有類別。
export default function NewCategoryPage() {
  const [promptDialog, askText] = useTextPrompt();
  const navigate = useNavigate();
  const { user, isLoggedIn } = useAuth();
  const token = user?.token;
  const canAccess = isLoggedIn && user?.account_type === "admin";

  const [data, setData] = useState({ items: [] });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [rowState, setRowState] = useState({});
  const [targets, setTargets] = useState({}); // topic_key -> [{main_category, sub_category}]
  const [topics, setTopics] = useState([]);
  const [topicsLoading, setTopicsLoading] = useState(true);
  const [selected, setSelected] = useState({});
  const [mergeTargets, setMergeTargets] = useState({});
  const [topicTargets, setTopicTargets] = useState({});
  const [topicBusy, setTopicBusy] = useState({});
  const [batchMessage, setBatchMessage] = useState("");
  const requestSeq = useRef(0);

  const load = async ({ silent = false } = {}) => {
    const seq = ++requestSeq.current;
    if (!silent) setLoading(true);
    try {
      setError("");
      const result = await api("/api/admin/ai/new-categories", token);
      if (seq === requestSeq.current) setData(result);
    } catch (e) {
      if (seq === requestSeq.current) setError(errorMessage(e));
    } finally {
      if (seq === requestSeq.current) setLoading(false);
    }
  };

  useEffect(() => {
    if (canAccess) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canAccess]);

  const keyOf = (item) => `${item.topic_key}|${item.main_category}|${item.sub_category}`;
  const groupedItems = data.items.reduce((groups, item) => {
    (groups[item.topic_key || "unknown"] ||= []).push(item);
    return groups;
  }, {});
  const topicByKey = Object.fromEntries(topics.map((topic) => [topic.topic_key, topic]));

  useEffect(() => {
    if (!canAccess) return;
    api("/api/admin/ai/taxonomy-topics", token)
      .then((result) => setTopics(result.topics || []))
      .catch((e) => setError(errorMessage(e)))
      .finally(() => setTopicsLoading(false));
  }, [canAccess, token]);

  const loadTargets = async (item) => {
    if (targets[item.topic_key]) return;
    try {
      const state = await api(`/api/classification/${item.classification_ids[0]}/review`, token);
      setTargets((p) => ({ ...p, [item.topic_key]: (state.taxonomy_options || []).filter((o) => !o.proposed) }));
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  const run = async (item, fn, okText) => {
    const key = keyOf(item);
    setRowState((p) => ({ ...p, [key]: { ...(p[key] || {}), busy: true, message: null } }));
    try {
      const result = await fn();
      setRowState((p) => ({ ...p, [key]: { ...(p[key] || {}), busy: false, message: { ok: true, text: okText(result) } } }));
      await load({ silent: true });
    } catch (e) {
      setRowState((p) => ({ ...p, [key]: { ...(p[key] || {}), busy: false, message: { ok: false, text: errorMessage(e) } } }));
    }
  };

  const adopt = async (item) => {
    const definition = await askText({
      title: t(`把「${item.sub_category}」加入分類架構`, `Add "${item.sub_category}" to the taxonomy`),
      message: t(`會加入「${item.topic_title}」並立刻發布，這 ${item.count} 筆回答會一起確認，之後類似的回答也會直接歸到這一類。\n定義會被 AI 拿來判斷之後的回答，建議寫清楚「什麼樣的回覆算這一類」。`,
        `It is added to "${item.topic_title}" and published now. These ${item.count} answers are confirmed and similar answers will go here.\nThe AI uses the definition to classify future answers.`),
      placeholder: t(`留空會用：當回覆主要涉及「${item.sub_category}」相關內容時，歸入此類別。`, "Leave blank for a default definition"),
      confirmLabel: t("加入並發布", "Add and publish"),
      rows: 6,
    });
    if (definition === null) return;
    run(item, () => api("/api/admin/ai/new-categories/adopt", token, {
      method: "POST",
      body: JSON.stringify({
        topic_key: item.topic_key, main_category: item.main_category, sub_category: item.sub_category,
        definition: definition.trim() || undefined,
      }),
    }), (r) => {
      if (!r.published) {
        // 主題還沒有已發布的分類架構（AI 自動建立的主題）：後端只加進草稿
        return t(
          `這個主題還沒有已發布的分類架構，已先加入草稿 v${r.taxonomy_version.version_number}，回答維持待處理。`,
          `This topic has no published taxonomy yet, so it was added to draft v${r.taxonomy_version.version_number} and the answers stay pending.`,
        );
      }
      const skipped = r.skipped?.length
        ? t(`，${r.skipped.length} 筆未確認（${r.skipped[0].message}）`, `; ${r.skipped.length} not confirmed (${r.skipped[0].message})`)
        : "";
      return t(
        `已加入並發布 v${r.taxonomy_version.version_number}，${r.confirmed_count} 筆回答已確認${skipped}。`,
        `Added and published v${r.taxonomy_version.version_number}; ${r.confirmed_count} answers confirmed${skipped}.`,
      );
    });
  };

  const merge = (item) => {
    const target = rowState[keyOf(item)]?.target;
    if (!target) return;
    if (!window.confirm(t(`把 ${item.count} 筆「${item.sub_category}」改成既有類別「${target}」？`, `Move ${item.count} item(s) from "${item.sub_category}" to "${target}"?`))) return;
    run(item, () => api("/api/admin/ai/new-categories/merge", token, {
      method: "POST",
      body: JSON.stringify({
        topic_key: item.topic_key, main_category: item.main_category, sub_category: item.sub_category,
        target_sub_category: target,
      }),
    }), (r) => t(`已合併 ${r.merged_count} 筆`, `Merged ${r.merged_count} item(s)`)
      + (r.skipped?.length ? t(`，${r.skipped.length} 筆未處理（${r.skipped[0].message}）`, `, ${r.skipped.length} skipped (${r.skipped[0].message})`) : ""));
  };

  const mergeSelected = async (topicKey) => {
    const items = (groupedItems[topicKey] || []).filter((item) => selected[keyOf(item)]);
    const target = mergeTargets[topicKey];
    if (!items.length || !target) return;
    setBatchMessage("");
    let mergedCount = 0;
    const failures = [];
    const mergedKeys = [];
    for (const item of items) {
      try {
        const result = await api("/api/admin/ai/new-categories/merge", token, {
          method: "POST",
          body: JSON.stringify({
            topic_key: item.topic_key, main_category: item.main_category,
            sub_category: item.sub_category, target_sub_category: target,
          }),
        });
        mergedCount += result.merged_count || 0;
        mergedKeys.push(keyOf(item));
      } catch (e) {
        failures.push(`${item.sub_category}: ${errorMessage(e)}`);
      }
    }
    setSelected((state) => Object.fromEntries(
      Object.entries(state).filter(([key]) => !mergedKeys.includes(key)),
    ));
    setBatchMessage(t(
      `已合併 ${mergedCount} 筆${failures.length ? `；${failures.length} 組失敗：${failures.join("；")}` : ""}`,
      `Merged ${mergedCount} item(s)${failures.length ? `; ${failures.length} group(s) failed: ${failures.join("; ")}` : ""}`,
    ));
    await load({ silent: true });
  };

  const mergeAutoTopic = async (topicKey) => {
    const target = topicTargets[topicKey];
    if (!target) return;
    const source = topicByKey[topicKey];
    if (!window.confirm(t(
      `將「${source?.title || topicKey}」及其回答重新分類到所選主題？`,
      `Merge "${source?.title || topicKey}" and re-classify its answers into the selected topic?`,
    ))) return;
    setTopicBusy((state) => ({ ...state, [topicKey]: true }));
    setBatchMessage("");
    try {
      const result = await api(`/api/admin/ai/topics/${encodeURIComponent(topicKey)}/merge-into`, token, {
        method: "POST", body: JSON.stringify({ target_topic_key: target }),
      });
      setBatchMessage(t(
        `主題已合併；重新分類 ${result.moved_count} 筆，${result.skipped_count} 筆略過。`,
        `Topic merged; ${result.moved_count} re-classified, ${result.skipped_count} skipped.`,
      ));
      await Promise.all([
        load({ silent: true }),
        api("/api/admin/ai/taxonomy-topics", token).then((result) => setTopics(result.topics || [])),
      ]);
    } catch (e) {
      setBatchMessage(errorMessage(e));
    } finally {
      setTopicBusy((state) => ({ ...state, [topicKey]: false }));
    }
  };

  if (!canAccess) {
    return <><Navbar /><main className="ai-admin-empty"><h1>{t("僅管理者可存取 AI 管理介面", "AI admin access restricted to administrators")}</h1><button onClick={() => navigate("/workspace")}>{t("回到分析助理", "Back to Analysis Assistant")}</button></main></>;
  }

  return <>{promptDialog}<div className="admin-page">
    <h1>{t("新類別候選", "New Category Candidates")}</h1>
    <p><small>{t("AI 分類時遇到現有分類都不適合的內容，會提出新類別。採用會把它加入分類架構並立刻發布，這些回答一起確認；如果其實就是某個既有類別，請用合併。",
      "When no existing category fits, the AI proposes a new one. Adopting adds it to the taxonomy, publishes it and confirms these answers in one step. If it's really an existing category, merge it instead.")}</small></p>
    {error && <p className="ai-admin-error">{error}<button onClick={() => setError("")}>×</button></p>}
    {batchMessage && <p className="review-batch-message">{batchMessage}</p>}
    {loading && <LoadingNotice />}
    {!loading && data.items.length === 0 && <p className="review-empty-hint">{t("目前沒有待處理的新類別。", "No new categories waiting.")}</p>}

    {!loading && Object.entries(groupedItems).map(([topicKey, items]) => {
      const topic = topicByKey[topicKey];
      const undecidedTopic = topic
        ? topic.is_auto_topic && !topic.merged_into
        : topicKey.startsWith("auto_");
      const selectedItems = items.filter((item) => selected[keyOf(item)]);
      return <section key={topicKey} className="admin-section-block">
        <h2>{topic?.title || items[0].topic_title} <span className="admin-muted">({items.length})</span></h2>
        {undecidedTopic ? (
          <div className="admin-undecided">
            <p>{t(
              "先決定這個 AI 自動主題的歸屬。合併後系統會將主題下的回答重新分類，無須逐類處理。",
              "Decide where this auto topic belongs first. Merging re-classifies its answers, so categories do not need to be handled one by one.",
            )}</p>
            {topicsLoading && <p className="admin-muted">{t("載入可合併主題…", "Loading available topics…")}</p>}
            <select value={topicTargets[topicKey] || ""} disabled={topicsLoading || topicBusy[topicKey]}
              onChange={(e) => setTopicTargets((state) => ({ ...state, [topicKey]: e.target.value }))}>
              <option value="">{t("選擇正式主題…", "Choose an official topic…")}</option>
              {topics.filter((candidate) => candidate.topic_key !== topicKey && candidate.published_version && !candidate.merged_into)
                .map((candidate) => <option key={candidate.topic_key} value={candidate.topic_key}>{candidate.title}</option>)}
            </select>
            <button className="primary" disabled={!topicTargets[topicKey] || topicBusy[topicKey]}
              onClick={() => mergeAutoTopic(topicKey)}>
              {topicBusy[topicKey] ? t("處理中…", "Working…") : t("合併主題並重新分類", "Merge topic & re-classify")}
            </button>
          </div>
        ) : items.length > 1 && (
          <div className="admin-filter-bar">
            <label>
              <span>{t("將選取的新類別合併到", "Merge selected categories into")}</span>
              <select value={mergeTargets[topicKey] || ""} onFocus={() => loadTargets(items[0])}
                onChange={(e) => setMergeTargets((state) => ({ ...state, [topicKey]: e.target.value }))}>
                <option value="">{t("選擇既有類別…", "Choose an existing category…")}</option>
                {(targets[topicKey] || []).map((option) =>
                  <option key={option.sub_category} value={option.sub_category}>{option.main_category} / {option.sub_category}</option>)}
              </select>
            </label>
            <button disabled={!selectedItems.length || !mergeTargets[topicKey]} onClick={() => mergeSelected(topicKey)}>
              {t(`合併選取 ${selectedItems.length} 組`, `Merge ${selectedItems.length} selected`)}
            </button>
          </div>
        )}
        {!undecidedTopic && items.map((item) => {
      const key = keyOf(item);
      const state = rowState[key] || {};
      const options = targets[item.topic_key] || [];
      return (
        <article key={key} className="review-card">
          <div className="review-card-top">
            <b className="review-status-tag review-status-tag--in_review">{t(`${item.count} 筆`, `${item.count} item(s)`)}</b>
            {!undecidedTopic && items.length > 1 && <label>
              <input type="checkbox" checked={!!selected[key]}
                onChange={(e) => setSelected((state) => ({ ...state, [key]: e.target.checked }))} />
              {t("選取合併", "Select to merge")}
            </label>}
            <span className="review-card-segment">{item.main_category} / {item.sub_category}</span>
          </div>
          <div className="review-card-mid">
            <p><span className="review-field-label">{t("主題", "Topic")}</span>{item.topic_title}</p>
            {item.examples.map((ex, i) => <p key={i}><span className="review-field-label">{t("範例", "Example")}</span>{ex}</p>)}
            {item.reasons[0] && <p><span className="review-field-label">{t("AI 理由", "AI reasoning")}</span>{item.reasons[0]}</p>}
          </div>
          {state.message && <p className={state.message.ok ? "review-batch-message" : "ai-admin-error"}>{state.message.text}</p>}
          <div className="review-card-actions">
            <button className="review-btn-primary" disabled={state.busy} onClick={() => adopt(item)}>{t("加入分類架構", "Add to taxonomy")}</button>
            <select value={state.target || ""} disabled={state.busy}
              onFocus={() => loadTargets(item)}
              onChange={(e) => setRowState((p) => ({ ...p, [key]: { ...(p[key] || {}), target: e.target.value } }))}>
              <option value="">{t("合併到既有類別…", "Merge into existing…")}</option>
              {options.map((o) => <option key={o.sub_category} value={o.sub_category}>{o.main_category} / {o.sub_category}</option>)}
            </select>
            <button disabled={state.busy || !state.target} onClick={() => merge(item)}>{t("合併", "Merge")}</button>
          </div>
        </article>
      );
        })}
      </section>;
    })}
  </div></>;
}
