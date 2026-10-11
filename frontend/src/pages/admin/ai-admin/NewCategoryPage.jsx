import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
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


// 併入結果的補充說明：資料庫逾時（常見原因：同一批資料正被另一個請求處理）會被記為 DATABASE_BUSY；
// 連續逾時時後端會先中止（aborted），剩下的可以稍後再按「重試併入」，已處理的不會重做。
const mergeBusyNote = (result) => {
  const busy = (result.skipped || []).filter((s) => s.code === "DATABASE_BUSY").length;
  const concurrent = (result.skipped || []).filter((s) => s.code === "CONCURRENT_MODIFICATION").length;
  const parts = [];
  if (result.aborted) {
    parts.push(t(
      `資料庫忙碌，已先暫停，還有 ${result.unprocessed_count} 筆沒處理；請稍後再按「重試併入」（已處理的不會重做）`,
      `The database was busy, so processing was paused with ${result.unprocessed_count} answer(s) left; try "Retry merge" again later (finished ones are not redone).`,
    ));
  } else if (busy) {
    parts.push(t(`${busy} 筆因資料庫忙碌沒處理，可稍後再按「重試併入」`, `${busy} answer(s) were not processed because the database was busy; retry later.`));
  }
  if (concurrent) {
    parts.push(t(
      `${concurrent} 筆在處理期間被其他操作更動，沒有寫入，請稍後重試（可能有人同時在處理同一個主題）`,
      `${concurrent} answer(s) changed while processing and were not written; retry later (someone may be processing this topic).`,
    ));
  }
  return parts.length ? ` ${parts.join("；")}。` : "";
};

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

// AI 暫時主題的決策區：先看 AI 提出的實際內容 → 比較目標主題的分類架構 → 再決定去向。
// 只用現有 API：GET /topics/<key>/answers（回答彙總與範例；每類最多 200 筆）、
// GET /topics/<key>/taxonomy/<version_id>（已發布版本的分類與定義），不新增任何 AI 呼叫。
const ANSWERS_PAGE = 50;
const groupKeyOf = (item) => `${item.main_category}|${item.sub_category}`;

function AutoTopicDecision({
  token, topicKey, sourceName, items, topics, topicsLoading, target, onTargetChange, busy, onMerge, onKeep,
}) {
  const [summary, setSummary] = useState(null); // answers API 的彙總：total_segments
  const [choice, setChoice] = useState(""); // 處理方式：""（尚未選擇）| "merge" | "keep"；只是切換畫面，不會寫入任何資料
  const [opened, setOpened] = useState({}); // 候選群組 -> 是否展開回答（預設收合）
  const [expanded, setExpanded] = useState({}); // 候選群組 -> { items, count } | { error }
  const [taxonomies, setTaxonomies] = useState({}); // 目標主題 key -> { version, categories } | { error }

  useEffect(() => {
    let cancelled = false;
    api(`/api/admin/ai/topics/${encodeURIComponent(topicKey)}/answers?per_category=0`, token)
      .then((result) => { if (!cancelled) setSummary(result); })
      .catch(() => {}); // 只是用來顯示影響筆數；失敗時改用候選群組的筆數加總
    return () => { cancelled = true; };
  }, [topicKey, token]);

  const targetTopic = topics.find((candidate) => candidate.topic_key === target);
  const versionId = targetTopic?.published_version?.version_id;
  useEffect(() => {
    if (!target || !versionId || taxonomies[target]) return;
    setTaxonomies((state) => ({ ...state, [target]: { loading: true } }));
    api(`/api/admin/ai/topics/${encodeURIComponent(target)}/taxonomy/${versionId}`, token)
      .then((result) => setTaxonomies((state) => ({
        ...state, [target]: { version: result.taxonomy_version, categories: result.taxonomy_version?.categories || [] },
      })))
      .catch((e) => setTaxonomies((state) => ({ ...state, [target]: { error: errorMessage(e) } })));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target, versionId]);

  const toggleMore = async (item) => {
    const key = groupKeyOf(item);
    if (expanded[key]) { setExpanded((state) => ({ ...state, [key]: null })); return; }
    setExpanded((state) => ({ ...state, [key]: { loading: true } }));
    try {
      const params = new URLSearchParams({
        per_category: String(ANSWERS_PAGE), main_category: item.main_category ?? "", sub_category: item.sub_category ?? "",
      });
      const result = await api(`/api/admin/ai/topics/${encodeURIComponent(topicKey)}/answers?${params}`, token);
      const group = (result.groups || []).find((g) => g.main_category === item.main_category && g.sub_category === item.sub_category);
      setExpanded((state) => ({ ...state, [key]: { items: group?.items || [], count: group?.count ?? item.count } }));
    } catch (e) {
      setExpanded((state) => ({ ...state, [key]: { error: errorMessage(e) } }));
    }
  };

  // total_answers = 回答數；total_segments = 分類片段數（一則回答可能拆成多個片段），兩者不同。
  // 讀不到彙總時，只能用候選群組的筆數加總（也是片段數），不推估回答數。
  const segmentCount = summary?.total_segments ?? items.reduce((total, item) => total + Number(item.count || 0), 0);
  const impact = summary?.total_answers != null
    ? t(`${summary.total_answers} 筆回答（${segmentCount} 個分類片段）`, `${summary.total_answers} answer(s) (${segmentCount} classified segment(s))`)
    : t(`${segmentCount} 個分類片段`, `${segmentCount} classified segment(s)`);
  const targetName = target ? topicDisplayName(targetTopic || target) : "";
  const taxonomy = target ? taxonomies[target] : null;
  const byMain = (taxonomy?.categories || []).reduce((groups, category) => {
    (groups[category.main_category || "—"] ||= []).push(category);
    return groups;
  }, {});

  // 切換處理方式或取消選擇時一律清掉原本選的目標主題，避免帶著舊目標誤按確認。
  const selectChoice = (next) => { setChoice(next); onTargetChange(""); };
  const mergeTargets = topics.filter((candidate) => candidate.topic_key !== topicKey && candidate.published_version && !candidate.merged_into && !isLegacyTechnicalTopic(candidate));

  return (
    <div className="admin-topic-decision">
      <h3 className="admin-topic-decision__sub">{t("此主題的候選類別", "Candidate categories in this topic")}</h3>
      <ul className="admin-auto-contents">
        {items.map((item) => {
          const key = groupKeyOf(item);
          const more = expanded[key];
          return <li key={key}>
            <button type="button" className="admin-auto-contents__head" aria-expanded={Boolean(opened[key])}
              onClick={() => setOpened((state) => ({ ...state, [key]: !state[key] }))}>
              <span>{opened[key] ? "▾" : "▸"} {item.main_category} / {item.sub_category}</span>
              <small>{t(`${item.count} 個片段`, `${item.count} segment(s)`)}</small>
            </button>
            {opened[key] && <div className="admin-auto-contents__body">
              {!more && item.examples.map((example, index) => <p key={index} className="admin-auto-contents__example">{example}</p>)}
              {more?.loading && <p className="admin-muted">{t("載入回答…", "Loading answers…")}</p>}
              {more?.error && <p className="ai-admin-error" role="alert">{more.error}</p>}
              {more?.items && <>
                <ol className="admin-auto-contents__answers">
                  {more.items.map((answer) => <li key={answer.classification_id}>
                    {answer.segment_text}
                    {answer.source_question && <small>{answer.source_question}</small>}
                  </li>)}
                </ol>
                {more.count > more.items.length && <p className="admin-muted">{t(`僅列出前 ${more.items.length} 筆，共 ${more.count} 筆（API 每類最多回傳 200 筆）。`, `Showing the first ${more.items.length} of ${more.count} (the API returns at most 200 per category).`)}</p>}
              </>}
              {(more || item.count > item.examples.length) && (
                <button type="button" className="link-button" onClick={() => toggleMore(item)}>
                  {more ? t("只看範例", "Show examples only") : t(`查看更多（共 ${item.count} 個片段）`, `Show more (${item.count} segments)`)}
                </button>
              )}
            </div>}
          </li>;
        })}
      </ul>

      <fieldset className="admin-decision-choice" disabled={busy}>
        <legend>{t("處理方式", "What to do with this topic")}</legend>
        <label className={`choice${choice === "merge" ? " is-selected" : ""}`}>
          <input type="radio" name={`decision-${topicKey}`} value="merge" checked={choice === "merge"} onChange={() => selectChoice("merge")} />
          <span>{t("併入既有正式主題", "Merge into an existing official topic")}</span>
        </label>
        <label className={`choice${choice === "keep" ? " is-selected" : ""}`}>
          <input type="radio" name={`decision-${topicKey}`} value="keep" checked={choice === "keep"} onChange={() => selectChoice("keep")} />
          <span>{t("保留為正式主題", "Keep as an official topic")}</span>
        </label>
        {choice && <button type="button" className="link-button admin-decision-clear" onClick={() => selectChoice("")}>{t("取消選擇", "Clear selection")}</button>}
      </fieldset>

      {choice === "merge" && <div className="admin-decision-panel">
        <label>
          <span>{t("目標正式主題", "Target official topic")}</span>
          <select value={target} disabled={topicsLoading || busy} onChange={(e) => onTargetChange(e.target.value)}>
            <option value="">{topicsLoading ? t("載入正式主題…", "Loading official topics…") : t("選擇正式主題…", "Choose an official topic…")}</option>
            {mergeTargets.map((candidate) => <option key={candidate.topic_key} value={candidate.topic_key}>{topicDisplayName(candidate)}</option>)}
          </select>
        </label>
        {target && <div className="admin-topic-compare">
          <p className="admin-topic-compare__title">
            {taxonomy?.version
              ? t(`「${targetName}」目前的分類架構（v${taxonomy.version.version_number}，${taxonomy.categories.length} 類）`, `Current taxonomy of "${targetName}" (v${taxonomy.version.version_number}, ${taxonomy.categories.length} categories)`)
              : t(`「${targetName}」目前的分類架構`, `Current taxonomy of "${targetName}"`)}
          </p>
          {taxonomy?.loading && <p className="admin-muted">{t("載入分類架構…", "Loading taxonomy…")}</p>}
          {taxonomy?.error && <p className="ai-admin-error" role="alert">{taxonomy.error}</p>}
          {!versionId && <p className="admin-muted">{t("這個主題沒有已發布的分類架構可比較。", "This topic has no published taxonomy to compare.")}</p>}
          {Object.entries(byMain).map(([main, categories]) => <div key={main}>
            <b>{main}</b>
            <ul>{categories.map((category) => <li key={category.category_id}>
              <span>{category.sub_category}</span>
              <small>{category.definition || t("（沒有填寫定義）", "(no definition)")}</small>
            </li>)}</ul>
          </div>)}
        </div>}
        {target && <p className="admin-topic-decision__impact">
          {t(`確認後，會把「${sourceName}」約 ${impact} 逐則重新分類到「${targetName}」。這是預估範圍，實際處理筆數以完成後的結果為準：已人工確認的回答會跳過，個別重新分類失敗的會保留原結果。`,
            `On confirm, about ${impact} of "${sourceName}" are re-classified one by one into "${targetName}". This is an estimate; the actual counts are shown afterwards. Reviewed answers are skipped and any that fail to re-classify keep their previous result.`)}
        </p>}
        <div>
          <button type="button" className="primary" disabled={!target || busy} onClick={() => onMerge(impact)}>
            {busy ? t("處理中…", "Working…") : t("確認併入並重新分類", "Confirm merge & re-classify")}
          </button>
        </div>
      </div>}

      {choice === "keep" && <div className="admin-decision-panel">
        <p className="admin-muted">{t("到主題頁設定並發布這個主題的分類架構。", "Set up and publish this topic's taxonomy on the topic page.")}</p>
        <div><button type="button" className="primary" disabled={busy} onClick={onKeep}>{t("前往設定分類架構", "Set up taxonomy")}</button></div>
      </div>}
    </div>
  );
}

// 開放式分類的「新類別候選」：AI 分類時提出、不在目前分類清單裡的類別。
// 採用 -> 加進該主題的分類架構草稿（到「分類架構」頁檢查後發布）；
// 合併 -> 這組回答改成某個既有類別。
export default function NewCategoryPage() {
  const [promptDialog, askText] = useTextPrompt();
  const navigate = useNavigate();
  // 目前選中的主題放在網址 ?topic=：重新整理、瀏覽器返回與分享連結都能回到同一個畫面。
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedTopic = searchParams.get("topic") || "";
  const openTopic = (key) => {
    const next = new URLSearchParams(searchParams);
    next.set("topic", key);
    setSearchParams(next);
    window.scrollTo(0, 0);
  };
  const closeTopic = () => {
    const next = new URLSearchParams(searchParams);
    next.delete("topic");
    setSearchParams(next);
    window.scrollTo(0, 0);
  };
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
  const [batchKind, setBatchKind] = useState("ok"); // ok | warn（部分成功）| error
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
        // 全部處理完 → 引導到第 3 步：到分類審查確認結果
        ...(topicComplete && !message.to ? {
          to: `/admin/ai/review?topic=${encodeURIComponent(item.topic_key)}`,
          toLabel: t("到分類審查確認結果", "Check the result in Review"),
        } : {}),
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
    setBatchKind("ok");
    setActionNotice(null);
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
    setBatchKind(failures.length ? (mergedCount > 0 ? "warn" : "error") : skippedCount ? "warn" : "ok");
    setBatchMessage(t(
      `已合併 ${mergedCount} 筆${skippedCount ? `；${skippedCount} 筆因綁定版本沒有目標類別而略過` : ""}${failures.length ? `；${failures.length} 組失敗：${failures.join("；")}` : ""}`,
      `Merged ${mergedCount} item(s)${skippedCount ? `; ${skippedCount} skipped (target not in their bound version)` : ""}${failures.length ? `; ${failures.length} group(s) failed: ${failures.join("; ")}` : ""}`,
    ));
    if (topicComplete && !failures.length && !skippedCount) {
      setActionNotice({
        text: t("此主題的新類別已全部處理完成。", "All new category candidates for this topic are handled."),
        to: `/admin/ai/review?topic=${encodeURIComponent(topicKey)}`,
        toLabel: t("到分類審查確認結果", "Check the result in Review"),
      });
    }
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
    ) + mergeBusyNote(r));
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

  const mergeAutoTopic = async (topicKey, impact) => {
    const target = topicTargets[topicKey];
    if (!target) return;
    const source = topicByKey[topicKey];
    const sourceName = topicDisplayName(source || topicKey);
    const targetName = topicDisplayName(topicByKey[target] || target);
    if (!window.confirm(t(
      `將「${sourceName}」${impact ? `約 ${impact} ` : "的回答"}重新分類到「${targetName}」？\n這是預估範圍，實際處理筆數以完成後的結果為準；已人工確認的回答會跳過，個別失敗的會保留原結果。這個 AI 暫時主題會併入「${targetName}」。`,
      `Re-classify ${impact ? `about ${impact} of` : "the answers of"} "${sourceName}" into "${targetName}"?\nThis is an estimate; actual counts are shown afterwards. Reviewed answers are skipped and any that fail keep their previous result. This temporary AI topic is merged into "${targetName}".`,
    ))) return;
    setTopicBusy((state) => ({ ...state, [topicKey]: true }));
    setBatchMessage("");
    setBatchKind("ok");
    setActionNotice(null);
    try {
      const result = await api(`/api/admin/ai/topics/${encodeURIComponent(topicKey)}/merge-into`, token, {
        method: "POST", body: JSON.stringify({ target_topic_key: target }),
      });
      const targetName = topicDisplayName(topicByKey[target] || target);
      setBatchKind(result.skipped_count || result.aborted ? "warn" : "ok");
      setBatchMessage(t(
        `主題已併入「${targetName}」；重新分類 ${result.moved_count} 筆，${result.skipped_count} 筆略過。若目標主題出現新的候選類別，會列在下方，請接著處理。`,
        `Topic merged into "${targetName}"; ${result.moved_count} re-classified, ${result.skipped_count} skipped. Any new candidates under the target topic are listed below.`,
      ) + mergeBusyNote(result));
      setTopicTargets((state) => ({ ...state, [topicKey]: "" }));
      await Promise.all([
        load({ silent: true }),
        api("/api/admin/ai/taxonomy-topics", token).then((result) => setTopics(result.topics || [])),
      ]);
    } catch (e) {
      setBatchKind("error");
      setBatchMessage(errorMessage(e));
    } finally {
      setTopicBusy((state) => ({ ...state, [topicKey]: false }));
    }
  };

  // topics 還在載入、而且還找不到這個主題：先不判定（不退回只看 "auto_" 前綴，
  // 否則已發布的 auto_ 主題會在載入期間閃出「未決定」流程）。
  // 「未決定」= AI 暫時主題、還沒有正式發布版本、也沒被併入其他主題。
  // 已發布的 auto_ 主題已經是正式主題，走一般新類別候選流程。
  // topics 載入完成卻仍找不到該主題時，才退回前綴判斷。
  const classify = (topicKey, items) => {
    const topic = topicByKey[topicKey];
    const legacyTopic = isLegacyTechnicalTopic(topic || items[0].topic_title || topicKey);
    const topicPending = topicsLoading && !topic;
    const undecidedTopic = !topicPending && (topic
      ? topic.is_auto_topic && !topic.published_version && !topic.merged_into && !legacyTopic
      : topicKey.startsWith("auto_") && !legacyTopic);
    return { topic, legacyTopic, topicPending, undecidedTopic };
  };
  const statusOf = ({ topicPending, undecidedTopic }) => (topicPending
    ? { label: t("確認中…", "Checking…"), tag: "pending_review" }
    : undecidedTopic ? { label: t("AI 暫時", "AI temporary"), tag: "in_review" } : { label: t("正式", "Official"), tag: "confirmed" });

  if (!canAccess) {
    return <><Navbar /><main className="ai-admin-empty"><h1>{t("僅管理者可存取 AI 管理介面", "AI admin access restricted to administrators")}</h1><button onClick={() => navigate("/workspace")}>{t("回到分析助理", "Back to Analysis Assistant")}</button></main></>;
  }

  return <>{promptDialog}<div className="admin-page">
    <h1>{t("新類別候選", "New Category Candidates")}</h1>
    {!selectedTopic && <p className="admin-muted">{t("AI 遇到現有分類都不適合的內容時會提出新類別：採用＝加入分類架構並發布；合併＝改成既有類別。",
      "When no category fits, the AI proposes a new one. Adopt it to add and publish it, or merge it into an existing category.")}</p>}
    {error && <p className="ai-admin-error">{error}<button onClick={() => setError("")}>×</button></p>}
    {batchMessage && <p className={batchKind === "error" ? "ai-admin-error" : `review-batch-message${batchKind === "warn" ? " review-batch-message--warn" : ""}`}
      role={batchKind === "error" ? "alert" : "status"}>{batchMessage}</p>}
    {actionNotice && <p className="review-batch-message" role="status">
      {actionNotice.text}
      {actionNotice.to && <>{" "}<Link to={actionNotice.to}>{actionNotice.toLabel || t("前往完成草稿", "Finish the draft")}</Link></>}
    </p>}
    {loading && <LoadingNotice />}
    {!loading && !selectedTopic && data.items.length === 0 && <p className="review-empty-hint">
      {actionNotice
        ? t("所有新類別候選已處理完。", "All new category candidates have been handled.")
        : t("目前沒有待處理的新類別。", "No new categories waiting.")}
    </p>}

    {!loading && !selectedTopic && Object.keys(groupedItems).length > 0 && (
      <ul className="admin-topic-list" aria-label={t("有新類別候選的主題", "Topics with new category candidates")}>
        {Object.entries(groupedItems).map(([topicKey, items]) => {
          const info = classify(topicKey, items);
          const status = statusOf(info);
          const answerCount = items.reduce((total, item) => total + Number(item.count || 0), 0);
          return <li key={topicKey} className="admin-topic-row">
            <div className="admin-topic-row__main">
              <b>{topicDisplayName(info.topic || items[0].topic_title)}</b>
              <span className={`review-status-tag review-status-tag--${status.tag}`}>{status.label}</span>
            </div>
            <span className="admin-topic-row__meta">{t(`${items.length} 組新類別・${answerCount} 筆回答`, `${items.length} group(s) · ${answerCount} answer(s)`)}</span>
            <button type="button" className="primary" onClick={() => openTopic(topicKey)}>{t("查看詳情", "View details")}</button>
          </li>;
        })}
      </ul>
    )}

    {!loading && selectedTopic && !groupedItems[selectedTopic] && (
      <section className="admin-section-block">
        <button type="button" className="admin-back-link" onClick={closeTopic}>{t("← 返回主題清單", "← Back to topic list")}</button>
        <p className="review-empty-hint">{t("這個主題目前沒有待處理的新類別。", "This topic has no new category candidates waiting.")}</p>
        <Link to={`/admin/ai/review?topic=${encodeURIComponent(selectedTopic)}`}>{t("到分類審查確認結果 →", "Check the result in Review →")}</Link>
      </section>
    )}

    {!loading && selectedTopic && Object.entries(groupedItems).filter(([topicKey]) => topicKey === selectedTopic).map(([topicKey, items]) => {
      const { topic, legacyTopic, topicPending, undecidedTopic } = classify(topicKey, items);
      const selectedItems = items.filter((item) => selected[keyOf(item)]);
      const answerCount = items.reduce((total, item) => total + Number(item.count || 0), 0);
      const status = statusOf({ topicPending, undecidedTopic });
      return <section key={topicKey} className="admin-section-block">
        <button type="button" className="admin-back-link" onClick={closeTopic}>{t("← 返回主題清單", "← Back to topic list")}</button>
        <header className="admin-candidate-head">
          <div>
            <h2>{topicDisplayName(topic || items[0].topic_title)}</h2>
            <p className="admin-candidate-head__meta">
              <span className={`review-status-tag review-status-tag--${status.tag}`}>{status.label}</span>{" "}
              {t(`${items.length} 組新類別・${answerCount} 筆回答`, `${items.length} group(s) · ${answerCount} answer(s)`)}
            </p>
          </div>
          {!topicPending && !undecidedTopic && (
            <Link to={`/admin/ai/review?topic=${encodeURIComponent(topicKey)}`}>{t("到分類審查 →", "Open Review →")}</Link>
          )}
        </header>
        {legacyTopic && <details><summary>{t("技術資訊", "Technical details")}</summary><code>{topicKey}</code></details>}
        {topicPending ? (
          <LoadingNotice text={t("正在確認主題狀態…", "Checking topic status…")} />
        ) : undecidedTopic ? (
          <AutoTopicDecision
            token={token} topicKey={topicKey} sourceName={topicDisplayName(topic || items[0].topic_title)}
            items={items} topics={topics} topicsLoading={topicsLoading}
            target={topicTargets[topicKey] || ""}
            onTargetChange={(value) => setTopicTargets((state) => ({ ...state, [topicKey]: value }))}
            busy={Boolean(topicBusy[topicKey])}
            onMerge={(impact) => mergeAutoTopic(topicKey, impact)}
            onKeep={() => navigate(`/admin/ai/topics/${encodeURIComponent(topicKey)}`)}
          />
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
            <details>
              <summary>{t(`查看回答範例（${item.examples.length} 則）`, `View example answers (${item.examples.length})`)}</summary>
              {item.examples.map((ex, i) => <p key={i}><span className="review-field-label">{t("範例", "Example")}</span>{ex}</p>)}
            </details>
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

    {!loading && !selectedTopic && (data.residual_items || []).length > 0 && <section className="admin-section-block admin-residual" aria-label="residual-candidates">
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
