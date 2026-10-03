import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTextPrompt } from "./shared/TextPromptDialog";
import Navbar from "../../../components/feature/Navbar";
import { useAuth } from "../../../hooks/AuthContext";
import { api } from "./shared/apiClient";
import { t } from "./shared/taxStatus";
import { errorMessage, isLegacyTechnicalTopic, topicDisplayName } from "./shared/reviewStates";
import { LoadingNotice } from "./shared/StatusWidgets";

// 排除的影響：對話框、殘留區塊都用同一句，後端也要求明確確認（acknowledged）
const excludeImpactText = () => t(
  "排除後，這些回答將不再納入分析、彙整、匯出與報告。此操作可透過 reopen 復原。",
  "After exclusion, these answers are no longer included in analysis, summaries, exports and reports. This can be undone with reopen.",
);

const residualReasonLabel = (reason, mergedInto, topicName) => ({
  legacy: t("舊版資料", "Legacy data"),
  no_topic: t("找不到所屬主題", "No owning topic"),
  topic_missing: t("主題已不存在", "Topic no longer exists"),
  topic_merged: t(`主題已併入「${topicName(mergedInto)}」`, `Topic merged into "${topicName(mergedInto)}"`),
}[reason] || reason);

const versionStatusLabel = (status) => ({
  published: t("已發布", "Published"),
  draft: t("草稿", "Draft"),
  in_review: t("審核中", "In review"),
  archived: t("已封存", "Archived"),
}[status] || status || "-");

const versionTag = (version) => (version.version_number != null ? `v${version.version_number}` : `#${version.version_id ?? "?"}`);

// 合併失敗（略過）的原因：目標類別不在該筆綁定的版本內時，說清楚而不是只丟「請從清單中選擇」
const skippedReason = (skipped) => (skipped?.[0]?.code === "INVALID_CATEGORY"
  ? t("目標類別不在該筆回答綁定的分類架構版本內", "the target category is not in the taxonomy version this answer is bound to")
  : skipped?.[0]?.message);

// 下拉選項：valid_rows < row_total 代表部分回答（綁定的版本沒有這個類別）合併時會被略過
const mergeTargetOptions = (info) => (info?.categories || []).map((category) => {
  const total = info.row_total || 0;
  const unusable = total > 0 && category.valid_rows === 0;
  const partial = total > 0 && category.valid_rows < total;
  return <option key={category.category_id ?? category.sub_category} value={category.sub_category} disabled={unusable}>
    {category.main_category} / {category.sub_category}
    {unusable
      ? t("（這些回答綁定的版本沒有此類別，無法合併）", " (not in the bound version; cannot merge)")
      : partial ? t(`（僅適用 ${category.valid_rows}/${total} 筆）`, ` (valid for ${category.valid_rows}/${total})`) : ""}
  </option>;
});

// 下拉上方：目前顯示的是哪個 Topic / 版本、版本不一致警告、主題去向提示
function MergeTargetNotice({ info, loading }) {
  if (loading && !info) return <small>{t("載入可合併的類別…", "Loading categories…")}</small>;
  if (!info) return null;
  const bound = (info.bound_versions || []).map((v) => `${versionTag(v)} × ${v.row_count}`).join("、");
  const topicPath = `/admin/ai/topics/${encodeURIComponent(info.topic_key)}`;
  return <div className="admin-merge-target-notice">
    <p><strong>{t(
      `目前顯示：${info.topic_title} · ${info.version_number != null ? `v${info.version_number}` : "-"} · ${versionStatusLabel(info.version_status)} · 共 ${info.category_count} 個既有類別`,
      `Showing: ${info.topic_title} · ${info.version_number != null ? `v${info.version_number}` : "-"} · ${versionStatusLabel(info.version_status)} · ${info.category_count} existing categories`,
    )}</strong></p>
    {info.target_source === "bound_fallback" && <p><small>{t(
      "這個主題目前沒有可用的最新分類架構，改列這批回答綁定的版本。",
      "This topic has no current usable taxonomy; showing the version these answers are bound to.",
    )}</small></p>}
    {!info.bound_versions_consistent && <p className="ai-admin-error" role="alert">{t(
      `這一組回答綁定了不同版本的分類架構（${bound}）。合併時會逐筆驗證，目標類別不在該筆綁定版本內的回答會被略過並回報。`,
      `These answers are bound to different taxonomy versions (${bound}). Each answer is validated on merge; those whose version lacks the target are skipped and reported.`,
    )}</p>}
    {info.bound_versions_consistent && info.rows_on_other_version > 0 && <p><small>{t(
      `這些回答綁定的是 ${bound}，不是目前顯示的版本；標示「僅適用」的類別，部分回答合併時會被略過。`,
      `These answers are bound to ${bound}, not the version shown; categories marked as partially valid will skip some answers on merge.`,
    )}</small></p>}
    <p><small>{t("如果這其實屬於其他主題，請先處理主題去向。", "If this actually belongs to another topic, handle the topic first.")}{" "}
      {info.merged_into
        ? t(`此主題已併入「${info.merged_into}」。`, `This topic was merged into "${info.merged_into}".`)
        : info.has_published
          ? <>{t("這是已發布的正式主題，不能整個併入其他主題；請到分類審核對單筆回答使用「移到其他主題」。", "This is a published topic and cannot be merged as a whole; use \"Move to another topic\" on single answers in Review.")}{" "}
            <Link to={`/admin/ai/review?topic=${encodeURIComponent(info.topic_key)}`}>{t("前往分類審核", "Open Review")}</Link></>
          : <>{t("這是尚未發布的 AI 主題，請到主題頁使用「併入其他主題」。", "This is an unpublished AI topic; use \"Merge into another topic\" on the topic page.")}{" "}
            <Link to={topicPath}>{t("前往主題頁", "Open topic")}</Link></>}
    </small></p>
  </div>;
}

// 開放式分類的「新類別候選」：AI 分類時提出、不在目前分類清單裡的類別。
// 採用 -> 加進該主題的分類架構草稿（到「分類架構」頁檢查後發布）；
// 合併 -> 這組回答改成某個既有類別。
export default function NewCategoryPage() {
  const [promptDialog, askText] = useTextPrompt();
  const navigate = useNavigate();
  const { user, isLoggedIn } = useAuth();
  const token = user?.token;
  const canAccess = isLoggedIn && user?.account_type === "admin";

  const [data, setData] = useState({ items: [], residual_items: [] });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [rowState, setRowState] = useState({});
  const [targets, setTargets] = useState({}); // 群組 key（或 topic:<key>）-> merge-targets API 回應
  const [targetsLoading, setTargetsLoading] = useState({});
  const [topics, setTopics] = useState([]);
  const [topicsLoading, setTopicsLoading] = useState(true);
  const [selected, setSelected] = useState({});
  const [mergeTargets, setMergeTargets] = useState({});
  const [topicTargets, setTopicTargets] = useState({});
  const [topicBusy, setTopicBusy] = useState({});
  const [batchMessage, setBatchMessage] = useState("");
  const [actionNotice, setActionNotice] = useState(null);
  const [residualState, setResidualState] = useState({}); // residualKey -> { busy, message }
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

  // 專用 merge-targets API：以候選群組的 topic 為基準（不再借用單筆審核的 taxonomy_options）。
  // group 帶 main/sub 時只統計該群組；只帶 topic 時（批次）統計整個主題的待處理候選。
  const loadTargets = async (cacheKey, { topic_key: topicKey, main_category: main, sub_category: sub }) => {
    if (!topicKey) {
      setError(t("這個新類別候選沒有所屬主題，無法列出可合併的類別。", "This candidate has no topic, so merge targets cannot be listed."));
      return;
    }
    if (targets[cacheKey] || targetsLoading[cacheKey]) return;
    setTargetsLoading((p) => ({ ...p, [cacheKey]: true }));
    try {
      const params = new URLSearchParams({ topic: topicKey });
      if (main !== undefined) params.set("main_category", main ?? "");
      if (sub !== undefined) params.set("sub_category", sub ?? "");
      const info = await api(`/api/admin/ai/new-categories/merge-targets?${params.toString()}`, token);
      setTargets((p) => ({ ...p, [cacheKey]: info }));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setTargetsLoading((p) => ({ ...p, [cacheKey]: false }));
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
      setTargets({}); // 採用 / 合併後版本或候選可能變了，下拉重新取得
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
      + (r.skipped?.length ? t(`，${r.skipped.length} 筆未處理（${skippedReason(r.skipped)}）`, `, ${r.skipped.length} skipped (${skippedReason(r.skipped)})`) : ""));
  };

  const mergeSelected = async (topicKey) => {
    const items = (groupedItems[topicKey] || []).filter((item) => selected[keyOf(item)]);
    const target = mergeTargets[topicKey];
    if (!items.length || !target) return;
    setBatchMessage("");
    let mergedCount = 0;
    let skippedCount = 0;
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
        skippedCount += result.skipped?.length || 0;
        mergedKeys.push(keyOf(item));
      } catch (e) {
        failures.push(`${item.sub_category}: ${errorMessage(e)}`);
      }
    }
    setSelected((state) => Object.fromEntries(
      Object.entries(state).filter(([key]) => !mergedKeys.includes(key)),
    ));
    setTargets({});
    const refreshed = await load({ silent: true });
    const topicComplete = Boolean(refreshed) && !refreshed.items.some((item) => item.topic_key === topicKey);
    setBatchMessage(t(
      `已合併 ${mergedCount} 筆${skippedCount ? `；${skippedCount} 筆因綁定版本沒有目標類別而略過` : ""}${failures.length ? `；${failures.length} 組失敗：${failures.join("；")}` : ""}`,
      `Merged ${mergedCount} item(s)${skippedCount ? `; ${skippedCount} skipped (target not in their bound version)` : ""}${failures.length ? `; ${failures.length} group(s) failed: ${failures.join("; ")}` : ""}`,
    ) + (topicComplete && !failures.length && !skippedCount
      ? ` ${t("此主題的新類別已全部處理完成。", "All new category candidates for this topic are handled.")}`
      : ""));
  };

  // ── 殘留／舊候選：重試併入 / 排除 ──
  const residualKeyOf = (item) => `residual|${keyOf(item)}`;
  const topicName = (key) => topicDisplayName(topicByKey[key] || key || "");

  const runResidual = async (item, fn, okText) => {
    const key = residualKeyOf(item);
    setActionNotice(null);
    setResidualState((p) => ({ ...p, [key]: { busy: true, message: null } }));
    try {
      const result = await fn();
      const text = okText(result);
      setResidualState((p) => ({ ...p, [key]: { busy: false, message: { ok: true, text } } }));
      setTargets({});
      await load({ silent: true });
      setActionNotice({ text }); // 卡片處理完會從清單消失，訊息放在頁面頂端才不會跟著不見
    } catch (e) {
      setResidualState((p) => ({ ...p, [key]: { busy: false, message: { ok: false, text: errorMessage(e) } } }));
    }
  };

  // 重試併入：沿用既有的「整個主題併入」流程，處理仍留在來源主題的回答（整個主題，不只這一組）
  const retryMerge = (item) => {
    const target = item.merged_into;
    if (!item.topic_key || !target) return;
    if (!window.confirm(t(
      `重新處理仍留在「${topicName(item.topic_key)}」的回答，併入「${topicName(target)}」？\n會逐則重新分類；已人工確認的回答會跳過。這會處理整個主題，不只這一組。`,
      `Re-process the answers still left in "${topicName(item.topic_key)}" and merge them into "${topicName(target)}"?\nEach answer is re-classified; reviewed answers are skipped. This applies to the whole topic, not just this group.`,
    ))) return;
    runResidual(item, () => api(`/api/admin/ai/topics/${encodeURIComponent(item.topic_key)}/merge-into`, token, {
      method: "POST", body: JSON.stringify({ target_topic_key: target }),
    }), (r) => t(
      `已重試併入：重新分類 ${r.moved_count} 筆，${r.skipped_count} 筆略過。`,
      `Retry finished: ${r.moved_count} re-classified, ${r.skipped_count} skipped.`,
    ));
  };

  // 排除：強提示（對話框 + 後端 acknowledged），可用 reopen 復原
  const excludeResidual = (item) => {
    if (!window.confirm(`${t(
      `排除「${item.main_category} / ${item.sub_category}」的 ${item.count} 筆回答？`,
      `Exclude ${item.count} answer(s) in "${item.main_category} / ${item.sub_category}"?`,
    )}\n\n${excludeImpactText()}`)) return;
    runResidual(item, () => api("/api/admin/ai/new-categories/exclude", token, {
      method: "POST",
      body: JSON.stringify({
        topic_key: item.topic_key, main_category: item.main_category, sub_category: item.sub_category,
        acknowledged: true,
      }),
    }), (r) => t(
      `已排除 ${r.success_count} 筆`
        + (r.skipped_count ? `；${r.skipped_count} 筆未處理（${r.skipped[0].message}）` : "")
        + (r.failed_count ? `；${r.failed_count} 筆失敗（${r.failed[0].message}）` : "")
        + "。",
      `Excluded ${r.success_count}`
        + (r.skipped_count ? `; ${r.skipped_count} skipped (${r.skipped[0].message})` : "")
        + (r.failed_count ? `; ${r.failed_count} failed (${r.failed[0].message})` : "")
        + ".",
    ));
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
      // topics 還在載入、而且還找不到這個主題：先不判定（不退回只看 "auto_" 前綴，
      // 否則已發布的 auto_ 主題會在載入期間閃出「未決定」流程）。
      const topicPending = topicsLoading && !topic;
      // 「未決定」= AI 暫時主題、還沒有正式發布版本、也沒被併入其他主題。
      // 已發布的 auto_ 主題已經是正式主題，走一般新類別候選流程。
      // topics 載入完成卻仍找不到該主題時，才退回前綴判斷。
      const undecidedTopic = !topicPending && (topic
        ? topic.is_auto_topic && !topic.published_version && !topic.merged_into && !legacyTopic
        : topicKey.startsWith("auto_") && !legacyTopic);
      const selectedItems = items.filter((item) => selected[keyOf(item)]);
      const answerCount = items.reduce((total, item) => total + Number(item.count || 0), 0);
      return <section key={topicKey} className="admin-section-block">
        <div className="admin-candidate-summary">
          <h2>{topicDisplayName(topic || items[0].topic_title)}</h2>
          <p className="admin-candidate-summary__count">
            {t(`這個主題有 ${items.length} 組 AI 提出的新類別，涉及 ${answerCount} 筆回答，需要你決定如何處理。`,
              `This topic has ${items.length} AI-proposed category group(s) across ${answerCount} answer(s) that need a decision.`)}
          </p>
          <p>{topicPending
            ? t("正在確認這個主題的狀態…", "Checking the status of this topic…")
            : undecidedTopic
            ? t("先決定這個 AI 暫時主題的去向；完成主題決策後，再判斷底下的候選類別。",
              "Decide the destination of this temporary AI topic first; review its candidate categories after the topic decision.")
            : t("AI 提出了這些不在目前分類架構中的類別，請判斷它們是新類別，還是應合併到既有類別。",
              "These AI-proposed categories are not in the current taxonomy. Decide whether each is new or belongs in an existing category.")}</p>
        </div>
        {legacyTopic && <details><summary>{t("技術資訊", "Technical details")}</summary><code>{topicKey}</code></details>}
        {topicPending ? (
          <LoadingNotice text={t("正在確認主題狀態…", "Checking topic status…")} />
        ) : undecidedTopic ? (
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
                  {topics.filter((candidate) => candidate.topic_key !== topicKey && candidate.published_version && !candidate.merged_into && !isLegacyTechnicalTopic(candidate))
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
            {selectedItems.length >= 2 && <MergeTargetNotice info={targets[`topic:${topicKey}`]} loading={targetsLoading[`topic:${topicKey}`]} />}
            {selectedItems.length >= 2 && <div className="admin-filter-bar admin-batch-select__actions">
              <label>
                <span>{t(`將 ${selectedItems.length} 組合併到既有類別`, `Merge ${selectedItems.length} selected groups into`)}</span>
                <select value={mergeTargets[topicKey] || ""} onFocus={() => loadTargets(`topic:${topicKey}`, { topic_key: topicKey === "unknown" ? null : topicKey })}
                  onChange={(e) => setMergeTargets((state) => ({ ...state, [topicKey]: e.target.value }))}>
                  <option value="">{t("選擇既有類別…", "Choose an existing category…")}</option>
                  {mergeTargetOptions(targets[`topic:${topicKey}`])}
                </select>
              </label>
              <button disabled={!mergeTargets[topicKey]} onClick={() => mergeSelected(topicKey)}>
                {t(`合併選取 ${selectedItems.length} 組`, `Merge ${selectedItems.length} selected`)}
              </button>
            </div>}
          </details>
        )}
        {!topicPending && !undecidedTopic && items.map((item) => {
      const key = keyOf(item);
      const state = rowState[key] || {};
      const targetInfo = targets[key];
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
              if (!state.mergeOpen) loadTargets(key, item);
            }}>{t("合併到既有類別", "Merge into existing category")}</button>
            {state.mergeOpen && <div className="admin-candidate-merge">
              <MergeTargetNotice info={targetInfo} loading={targetsLoading[key]} />
              <label>
                <span>{t("選擇要合併到的類別", "Choose the category to merge into")}</span>
                <select value={state.target || ""} disabled={state.busy}
                  onChange={(e) => setRowState((p) => ({ ...p, [key]: { ...(p[key] || {}), target: e.target.value } }))}>
                  <option value="">{t("選擇既有類別…", "Choose an existing category…")}</option>
                  {mergeTargetOptions(targetInfo)}
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

    {!loading && (data.residual_items || []).length > 0 && <section className="admin-section-block admin-residual" aria-label="residual-candidates">
      <h2>{t(`殘留／舊候選（${data.residual_items.length} 組）`, `Leftover / legacy candidates (${data.residual_items.length})`)}</h2>
      <p><small>{t(
        "這些不是目前需要決策的新類別，所以不計入「新類別候選」數量：舊版資料、找不到主題，或主題已被合併後仍留下來的回答。可以重試併入（主題已合併時），或排除。",
        "These are not current decisions, so they are not counted as new category candidates: legacy data, answers without a topic, or answers left behind after their topic was merged. Retry the merge (when the topic is merged) or exclude them.",
      )}</small></p>
      <p className="ai-admin-error" role="note"><strong>{excludeImpactText()}</strong></p>
      {data.residual_items.map((item) => {
        const key = residualKeyOf(item);
        const state = residualState[key] || {};
        return <article key={key} className="review-card admin-residual-card">
          <div className="review-card-top">
            <b className="review-status-tag review-status-tag--in_review">{t(`${item.count} 筆`, `${item.count} item(s)`)}</b>
            <span className="review-card-segment">{item.main_category} / {item.sub_category}</span>
            <small>{item.topic_key ? topicName(item.topic_key) : t("（沒有所屬主題）", "(no topic)")}</small>
          </div>
          <p><small>{(item.residual_reasons || []).map((reason) => residualReasonLabel(reason, item.merged_into, topicName)).join("、")}</small></p>
          <div className="review-card-mid">
            {item.examples.map((ex, i) => <p key={i}><span className="review-field-label">{t("範例", "Example")}</span>{ex}</p>)}
          </div>
          {state.message && <p className={state.message.ok ? "review-batch-message" : "ai-admin-error"}>{state.message.text}</p>}
          <div className="review-card-actions">
            {item.merged_into && item.topic_key && <button type="button" disabled={state.busy} onClick={() => retryMerge(item)}>
              {t("重試併入", "Retry merge")}
            </button>}
            <button type="button" disabled={state.busy} onClick={() => excludeResidual(item)}>
              {t("排除", "Exclude")}
            </button>
          </div>
        </article>;
      })}
    </section>}
  </div></>;
}
