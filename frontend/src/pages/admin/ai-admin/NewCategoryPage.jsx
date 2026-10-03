import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTextPrompt } from "./shared/TextPromptDialog";
import Navbar from "../../../components/feature/Navbar";
import { useAuth } from "../../../hooks/AuthContext";
import { api } from "./shared/apiClient";
import { t } from "./shared/taxStatus";
import { errorMessage, isLegacyTechnicalTopic, topicDisplayName } from "./shared/reviewStates";
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
  const [actionNotice, setActionNotice] = useState(null);
  const requestSeq = useRef(0);

  const load = async ({ silent = false } = {}) => {
    const seq = ++requestSeq.current;
    if (!silent) setLoading(true);
    try {
      setError("");
      const result = await api("/api/admin/ai/new-categories", token);
      if (seq === requestSeq.current) setData(result);
      return result;
    } catch (e) {
      if (seq === requestSeq.current) setError(errorMessage(e));
      return null;
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
    setActionNotice(null);
    setRowState((p) => ({ ...p, [key]: { ...(p[key] || {}), busy: true, message: null } }));
    try {
      const result = await fn();
      const notice = okText(result);
      const message = typeof notice === "string" ? { text: notice } : notice;
      setRowState((p) => ({ ...p, [key]: { ...(p[key] || {}), busy: false, message: { ok: true, text: message.text } } }));
      const refreshed = await load({ silent: true });
      const topicComplete = Boolean(refreshed) && !refreshed.items.some((candidate) => candidate.topic_key === item.topic_key);
      setActionNotice({
        ...message,
        text: topicComplete
          ? `${message.text} ${t("此主題的新類別已全部處理完成。", "All new category candidates for this topic are handled.")}`
          : message.text,
      });
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
        return {
          text: t(
            `這個主題還沒有已發布的分類架構，已先加入草稿 v${r.taxonomy_version.version_number}，回答維持待處理。`,
            `This topic has no published taxonomy yet, so it was added to draft v${r.taxonomy_version.version_number} and the answers stay pending.`,
          ),
          to: `/admin/ai/topics/${encodeURIComponent(item.topic_key)}`,
        };
      }
      const skipped = r.skipped?.length
        ? t(`，${r.skipped.length} 筆未確認（${r.skipped[0].message}）`, `; ${r.skipped.length} not confirmed (${r.skipped[0].message})`)
        : "";
      return {
        text: t(
          `已加入並發布 v${r.taxonomy_version.version_number}，${r.confirmed_count} 筆回答已確認${skipped}。`,
          `Added and published v${r.taxonomy_version.version_number}; ${r.confirmed_count} answers confirmed${skipped}.`,
        ),
      };
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
    const refreshed = await load({ silent: true });
    const topicComplete = Boolean(refreshed) && !refreshed.items.some((item) => item.topic_key === topicKey);
    setBatchMessage(t(
      `已合併 ${mergedCount} 筆${failures.length ? `；${failures.length} 組失敗：${failures.join("；")}` : ""}`,
      `Merged ${mergedCount} item(s)${failures.length ? `; ${failures.length} group(s) failed: ${failures.join("; ")}` : ""}`,
    ) + (topicComplete && !failures.length
      ? ` ${t("此主題的新類別已全部處理完成。", "All new category candidates for this topic are handled.")}`
      : ""));
  };

  const mergeAutoTopic = async (topicKey) => {
    const target = topicTargets[topicKey];
    if (!target) return;
    const source = topicByKey[topicKey];
    if (!window.confirm(t(
      `將「${topicDisplayName(source || topicKey)}」及其回答重新分類到所選主題？`,
      `Merge "${topicDisplayName(source || topicKey)}" and re-classify its answers into the selected topic?`,
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
    {actionNotice && <p className="review-batch-message" role="status">
      {actionNotice.text}
      {actionNotice.to && <>{" "}<Link to={actionNotice.to}>{t("前往完成草稿", "Finish the draft")}</Link></>}
    </p>}
    {loading && <LoadingNotice />}
    {!loading && data.items.length === 0 && <p className="review-empty-hint">
      {actionNotice
        ? t("所有新類別候選已處理完。", "All new category candidates have been handled.")
        : t("目前沒有待處理的新類別。", "No new categories waiting.")}
    </p>}

    {!loading && Object.entries(groupedItems).map(([topicKey, items]) => {
      const topic = topicByKey[topicKey];
      const legacyTopic = isLegacyTechnicalTopic(topic || items[0].topic_title || topicKey);
      const undecidedTopic = topic
        ? topic.is_auto_topic && !topic.merged_into && !legacyTopic
        : topicKey.startsWith("auto_") && !legacyTopic;
      const selectedItems = items.filter((item) => selected[keyOf(item)]);
      const answerCount = items.reduce((total, item) => total + Number(item.count || 0), 0);
      return <section key={topicKey} className="admin-section-block">
        <div className="admin-candidate-summary">
          <h2>{topicDisplayName(topic || items[0].topic_title)}</h2>
          <p className="admin-candidate-summary__count">
            {t(`這個主題有 ${items.length} 組 AI 提出的新類別，涉及 ${answerCount} 筆回答，需要你決定如何處理。`,
              `This topic has ${items.length} AI-proposed category group(s) across ${answerCount} answer(s) that need a decision.`)}
          </p>
          <p>{undecidedTopic
            ? t("先決定這個 AI 暫時主題的去向；完成主題決策後，再判斷底下的候選類別。",
              "Decide the destination of this temporary AI topic first; review its candidate categories after the topic decision.")
            : t("AI 提出了這些不在目前分類架構中的類別，請判斷它們是新類別，還是應合併到既有類別。",
              "These AI-proposed categories are not in the current taxonomy. Decide whether each is new or belongs in an existing category.")}</p>
        </div>
        {legacyTopic && <details><summary>{t("技術資訊", "Technical details")}</summary><code>{topicKey}</code></details>}
        {undecidedTopic ? (
          <div className="admin-undecided">
            <strong>{t("這是 AI 暫時建立的主題，尚未正式採用。", "This topic was created temporarily by AI and has not been adopted.")}</strong>
            <p>{t("請先決定主題去向，再處理底下的新類別。", "Decide what happens to the topic before reviewing its proposed categories.")}</p>
            <div className="admin-auto-topic-actions">
              <label>
                <span>{t("A. 併入既有正式主題", "A. Merge into an existing official topic")}</span>
                {topicsLoading && <small>{t("載入正式主題…", "Loading official topics…")}</small>}
                <select value={topicTargets[topicKey] || ""} disabled={topicsLoading || topicBusy[topicKey]}
                  onChange={(e) => setTopicTargets((state) => ({ ...state, [topicKey]: e.target.value }))}>
                  <option value="">{t("選擇正式主題…", "Choose an official topic…")}</option>
                  {topics.filter((candidate) => candidate.topic_key !== topicKey && candidate.published_version && !candidate.merged_into && !candidate.is_auto_topic && !isLegacyTechnicalTopic(candidate))
                    .map((candidate) => <option key={candidate.topic_key} value={candidate.topic_key}>{topicDisplayName(candidate)}</option>)}
                </select>
              </label>
              <button className="primary" disabled={!topicTargets[topicKey] || topicBusy[topicKey]}
                onClick={() => mergeAutoTopic(topicKey)}>
                {topicBusy[topicKey] ? t("處理中…", "Working…") : t("併入正式主題並重新分類", "Merge into official topic & re-classify")}
              </button>
              <div className="admin-auto-topic-keep">
                <span>{t("B. 保留為正式主題", "B. Keep as an official topic")}</span>
                <button type="button" disabled={topicBusy[topicKey]}
                  onClick={() => navigate(`/admin/ai/topics/${encodeURIComponent(topicKey)}`)}>
                  {t("保留此主題並完成分類架構", "Keep topic & complete its taxonomy")}
                </button>
              </div>
            </div>
          </div>
        ) : items.length > 1 && (
          <details className="admin-batch-select">
            <summary>{t("需要一次整理多組？展開批次選取", "Handling multiple groups? Expand batch selection")}</summary>
            <div className="admin-batch-select__items">
              {items.map((item) => <label key={keyOf(item)}>
                <input type="checkbox" checked={!!selected[keyOf(item)]}
                  onChange={(e) => setSelected((state) => ({ ...state, [keyOf(item)]: e.target.checked }))} />
                {item.main_category} / {item.sub_category}
              </label>)}
            </div>
            {selectedItems.length >= 2 && <div className="admin-filter-bar admin-batch-select__actions">
              <label>
                <span>{t(`將 ${selectedItems.length} 組合併到既有類別`, `Merge ${selectedItems.length} selected groups into`)}</span>
                <select value={mergeTargets[topicKey] || ""} onFocus={() => loadTargets(items[0])}
                  onChange={(e) => setMergeTargets((state) => ({ ...state, [topicKey]: e.target.value }))}>
                  <option value="">{t("選擇既有類別…", "Choose an existing category…")}</option>
                  {(targets[topicKey] || []).map((option) =>
                    <option key={option.sub_category} value={option.sub_category}>{option.main_category} / {option.sub_category}</option>)}
                </select>
              </label>
              <button disabled={!mergeTargets[topicKey]} onClick={() => mergeSelected(topicKey)}>
                {t(`合併選取 ${selectedItems.length} 組`, `Merge ${selectedItems.length} selected`)}
              </button>
            </div>}
          </details>
        )}
        {!undecidedTopic && items.map((item) => {
      const key = keyOf(item);
      const state = rowState[key] || {};
      const options = targets[item.topic_key] || [];
      return (
        <article key={key} className="review-card">
          <div className="review-card-top">
            <b className="review-status-tag review-status-tag--in_review">{t(`${item.count} 筆`, `${item.count} item(s)`)}</b>
            <span className="review-card-segment">{item.main_category} / {item.sub_category}</span>
          </div>
          <div className="review-card-mid">
            {item.examples.map((ex, i) => <p key={i}><span className="review-field-label">{t("範例", "Example")}</span>{ex}</p>)}
            {item.reasons[0] && <details><summary>{t("查看 AI 判斷補充", "View AI reasoning")}</summary><p>{item.reasons[0]}</p></details>}
          </div>
          {state.message && <p className={state.message.ok ? "review-batch-message" : "ai-admin-error"}>{state.message.text}</p>}
          <div className="review-card-actions">
            <button className="review-btn-primary" disabled={state.busy} onClick={() => adopt(item)}>{t("採用為新類別", "Adopt as new category")}</button>
            <button type="button" disabled={state.busy} onClick={() => {
              setRowState((previous) => ({ ...previous, [key]: { ...(previous[key] || {}), mergeOpen: !previous[key]?.mergeOpen } }));
              if (!state.mergeOpen) loadTargets(item);
            }}>{t("合併到既有類別", "Merge into existing category")}</button>
            {state.mergeOpen && <div className="admin-candidate-merge">
              <label>
                <span>{t("選擇要合併到的類別", "Choose the category to merge into")}</span>
                <select value={state.target || ""} disabled={state.busy}
                  onChange={(e) => setRowState((p) => ({ ...p, [key]: { ...(p[key] || {}), target: e.target.value } }))}>
                  <option value="">{t("選擇既有類別…", "Choose an existing category…")}</option>
                  {options.map((o) => <option key={o.sub_category} value={o.sub_category}>{o.main_category} / {o.sub_category}</option>)}
                </select>
              </label>
              <button disabled={state.busy || !state.target} onClick={() => merge(item)}>{t("確認合併", "Confirm merge")}</button>
            </div>}
          </div>
        </article>
      );
        })}
      </section>;
    })}
  </div></>;
}
