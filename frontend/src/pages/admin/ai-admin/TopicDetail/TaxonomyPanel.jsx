import { useEffect, useRef, useState } from "react";
import { NavLink, useParams } from "react-router-dom";
import { api, peekCache } from "../shared/apiClient";
import { SkeletonCards } from "../shared/StatusWidgets";
import { t, taxStatusText, TAX_EDITABLE_STATUSES } from "../shared/taxStatus";
import TaxCategoryField from "../shared/TaxCategoryField";
import TopicMovePicker from "../shared/TopicMovePicker";
import { CategoryAnswers, OtherCategoryAnswers, TopicSourceSummary, answersUrl, loadTopicAnswers } from "./TopicAnswers";
import { useAuth } from "../../../../hooks/AuthContext";
import { topicDisplayName } from "../shared/reviewStates";

export default function TaxonomyPanel() {
  const { topicKey } = useParams();
  const { user } = useAuth();
  const token = user?.token;

  // 抓過的資料先拿來立刻顯示（首頁、上次進來時抓的），背景再更新
  const cached = () => {
    const meta = (peekCache("/api/admin/ai/taxonomy-topics")?.topics || []).find((x) => x.topic_key === topicKey) || null;
    const versionId = meta?.latest_draft_version?.version_id ?? meta?.published_version?.version_id;
    const version = versionId ? peekCache(`/api/admin/ai/topics/${topicKey}/taxonomy/${versionId}`)?.taxonomy_version : null;
    return { meta, version: version || null, answers: peekCache(answersUrl(topicKey, { per_category: 5 })) || null };
  };
  const initial = cached();
  const [topicMeta, setTopicMeta] = useState(initial.meta); // 這個 topic 在 taxonomy-topics 列表裡的那一筆
  const [taxVersion, setTaxVersion] = useState(initial.version);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(!(initial.meta && initial.version));
  const [answersLoading, setAnswersLoading] = useState(false);
  const [mergedTargetTitle, setMergedTargetTitle] = useState("");
  const [mergeResultText, setMergeResultText] = useState("");
  const [unmerging, setUnmerging] = useState(false);
  const [unmergeResultText, setUnmergeResultText] = useState("");
  const [versionsFailed, setVersionsFailed] = useState(false); // 完整版本清單讀取失敗：顯示提示與重新讀取
  const [archivedOpen, setArchivedOpen] = useState(false); // 封存版本清單的展開狀態（由管理員控制）
  const versionsSeq = useRef(0);
  const [versions, setVersions] = useState(null); // 這個主題的全部版本（含封存），讀取失敗時退回只用 published / draft
  const [answers, setAnswers] = useState(initial.answers); // 這個主題底下的原始回答（證據）
  // 還沒完成的欄位儲存。發布／複製／刪除前要先等它們做完：欄位是「離開輸入框」
  // 才儲存，打完字直接按發布時，儲存跟發布會同時送出，發布可能先完成。
  const pendingSaves = useRef(new Set());
  const flushPendingSaves = async () => {
    if (document.activeElement && typeof document.activeElement.blur === "function") document.activeElement.blur();
    await Promise.allSettled([...pendingSaves.current]);
  };

  const loadAnswers = async () => {
    setAnswersLoading(true);
    try {
      setAnswers(await loadTopicAnswers(topicKey, token));
    } catch {
      setAnswers(null); // 原始回答載入失敗不影響分類架構編輯
    } finally {
      setAnswersLoading(false);
    }
  };

  // 取得這個 topic 有哪些版本（沿用既有 taxonomy-topics 列表 API，前端篩出這一筆，
  // 不新增「單一 topic 版本清單」API——這次 IA 重構刻意不動 backend）
  const loadTopicMeta = async () => {
    try {
      const data = peekCache("/api/admin/ai/taxonomy-topics")
        || await api("/api/admin/ai/taxonomy-topics", token);
      const mine = (data.topics || []).find((x) => x.topic_key === topicKey);
      setTopicMeta(mine || null);
      if (mine?.merged_into) {
        const target = (data.topics || []).find((x) => x.topic_key === mine.merged_into);
        setMergedTargetTitle(topicDisplayName(target || mine.merged_into));
      }
      return mine || null;
    } catch (e) {
      setError(e.message);
      return null;
    }
  };

  const loadVersions = async () => {
    const seq = ++versionsSeq.current; // 切換主題後，舊主題的回應不得覆蓋
    try {
      const data = await api(`/api/admin/ai/topics/${topicKey}/taxonomy`, token);
      if (seq !== versionsSeq.current) return;
      setVersions(data.versions || null);
      setVersionsFailed(false);
    } catch {
      if (seq !== versionsSeq.current) return;
      setVersions(null);
      setVersionsFailed(true);
    }
  };

  const openVersion = async (versionId) => {
    try {
      const path = `/api/admin/ai/topics/${topicKey}/taxonomy/${versionId}`;
      const data = peekCache(path) || await api(path, token);
      setTaxVersion(data.taxonomy_version);
    } catch (e) {
      setError(e.message);
    }
  };

  useEffect(() => {
    let cancelled = false;
    const now = cached();
    setTopicMeta(now.meta);
    setTaxVersion(now.version);
    setAnswers(now.answers);
    setAnswersLoading(false);
    setLoading(!(now.meta && now.version));
    setMergeResultText("");
    setUnmergeResultText("");
    setMergedTargetTitle("");
    setVersions(null);
    setVersionsFailed(false);
    setArchivedOpen(false);
    setError("");
    loadVersions();
    (async () => {
      const meta = await loadTopicMeta();
      if (cancelled || !meta) { setLoading(false); return; }
      // 預設顯示：有草稿優先顯示草稿（那是需要 Admin 動作的版本），
      // 否則顯示已發布版本。
      const defaultVersionId = meta.latest_draft_version?.version_id ?? meta.published_version?.version_id;
      if (defaultVersionId) await openVersion(defaultVersionId);
      if (!cancelled) setLoading(false);
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [topicKey]);

  const saveTaxCategory = (categoryId, fields) => {
    const run = (async () => {
      const data = await api(`/api/admin/ai/topics/${topicKey}/taxonomy/${taxVersion.version_id}/categories/${categoryId}`, token, { method: "PUT", body: JSON.stringify(fields) });
      setTaxVersion((v) => ({ ...v, categories: v.categories.map((c) => (c.category_id === categoryId ? data.category : c)) }));
    })();
    pendingSaves.current.add(run);
    run.catch((e) => setError(e.message)).finally(() => pendingSaves.current.delete(run));
    return run; // 欄位用它顯示「已儲存／儲存失敗」
  };
  const addTaxCategory = async () => {
    try {
      const data = await api(`/api/admin/ai/topics/${topicKey}/taxonomy/${taxVersion.version_id}/categories`, token, { method: "POST", body: JSON.stringify({ main_category: t("新大類別", "New main category"), sub_category: t("新子類別", "New sub category"), definition: "" }) });
      setTaxVersion((v) => ({ ...v, categories: [...v.categories, data.category] }));
    } catch (e) { setError(e.message); }
  };
  const deleteTaxCategory = async (categoryId) => {
    const cat = taxVersion.categories.find((c) => c.category_id === categoryId);
    if (!window.confirm(t(`確定要刪除「${cat?.main_category} / ${cat?.sub_category}」嗎？`,
      `Delete "${cat?.main_category} / ${cat?.sub_category}"?`))) return;
    try {
      await api(`/api/admin/ai/topics/${topicKey}/taxonomy/${taxVersion.version_id}/categories/${categoryId}`, token, { method: "DELETE" });
      setTaxVersion((v) => ({ ...v, categories: v.categories.filter((c) => c.category_id !== categoryId) }));
    } catch (e) { setError(e.message); }
  };
  const moveTaxCategory = async (index, direction) => {
    const cats = [...taxVersion.categories];
    const target = index + direction;
    if (target < 0 || target >= cats.length) return;
    [cats[index], cats[target]] = [cats[target], cats[index]];
    try {
      const data = await api(`/api/admin/ai/topics/${topicKey}/taxonomy/${taxVersion.version_id}/categories/reorder`, token, { method: "POST", body: JSON.stringify({ ordered_category_ids: cats.map((c) => c.category_id) }) });
      setTaxVersion((v) => ({ ...v, categories: data.categories }));
    } catch (e) { setError(e.message); }
  };
  const cloneTaxVersion = async () => {
    await flushPendingSaves();
    try {
      const data = await api(`/api/admin/ai/topics/${topicKey}/taxonomy/${taxVersion.version_id}/clone`, token, { method: "POST" });
      setTaxVersion(data.taxonomy_version);
      await loadTopicMeta();
      loadVersions();
    } catch (e) { setError(e.message); }
  };
  // 跟目前上線的版本比較，列出這次改了什麼，發布前讓 Admin 確認
  const describeChanges = async () => {
    const live = topicMeta?.published_version;
    if (!live || live.version_id === taxVersion.version_id) return "";
    try {
      const data = await api(`/api/admin/ai/topics/${topicKey}/taxonomy/${live.version_id}`, token);
      const before = new Map((data.taxonomy_version.categories || []).map((c) => [c.sub_category, c]));
      const after = new Map((taxVersion.categories || []).map((c) => [c.sub_category, c]));
      const fields = ["main_category", "definition", "include_rules", "exclude_rules", "boundary_rules"];
      const added = [...after.keys()].filter((k) => !before.has(k));
      const removed = [...before.keys()].filter((k) => !after.has(k));
      const changed = [...after.keys()].filter((k) => before.has(k)
        && fields.some((f) => (before.get(k)[f] || "") !== (after.get(k)[f] || "")));
      const list = (names) => names.slice(0, 5).join("、") + (names.length > 5 ? "…" : "");
      const lines = [
        added.length && t(`新增 ${added.length}：${list(added)}`, `Added ${added.length}: ${list(added)}`),
        removed.length && t(`刪除 ${removed.length}：${list(removed)}`, `Removed ${removed.length}: ${list(removed)}`),
        changed.length && t(`修改 ${changed.length}：${list(changed)}`, `Changed ${changed.length}: ${list(changed)}`),
      ].filter(Boolean);
      return lines.length ? `\n\n${t(`跟目前上線的 v${live.version_number} 相比：`, `Compared with live v${live.version_number}:`)}\n${lines.join("\n")}`
        : `\n\n${t(`跟目前上線的 v${live.version_number} 內容相同。`, `Same as live v${live.version_number}.`)}`;
    } catch {
      return "";
    }
  };

  const publishTaxVersion = async () => {
    await flushPendingSaves();
    const changes = await describeChanges();
    if (!window.confirm(t(
      `確定要發布 v${taxVersion.version_number} 嗎？\n發布後，之後的分類都會用這個版本，目前上線的版本會封存，相關報告會標記為需要更新。${changes}`,
      `Publish v${taxVersion.version_number}? Future classifications use it, the live version is archived and related reports are marked outdated.${changes}`,
    ))) return;
    try {
      const data = await api(`/api/admin/ai/topics/${topicKey}/taxonomy/${taxVersion.version_id}/publish`, token, { method: "POST" });
      setTaxVersion(data.taxonomy_version);
      await loadTopicMeta();
      loadVersions();
    } catch (e) { setError(e.message); }
  };
  const deleteTaxVersion = async () => {
    await flushPendingSaves();
    if (!window.confirm(t("確定要刪除此草稿版本嗎？刪除後無法復原。", "Are you sure you want to delete this draft version? This cannot be undone."))) return;
    try {
      await api(`/api/admin/ai/topics/${topicKey}/taxonomy/${taxVersion.version_id}`, token, { method: "DELETE" });
      setTaxVersion(null);
      loadVersions();
      const meta = await loadTopicMeta();
      if (meta) {
        const nextVersionId = meta.latest_draft_version?.version_id ?? meta.published_version?.version_id;
        if (nextVersionId) await openVersion(nextVersionId);
      }
    } catch (e) { setError(e.message); }
  };

  // 整個主題併入另一個主題（後端會重新分類底下的回答，已人工定案的跳過並回報）
  const mergeTopic = async (target) => {
    const result = await api(`/api/admin/ai/topics/${topicKey}/merge-into`, token, {
      method: "POST",
      body: JSON.stringify({ target_topic_key: target.topic_key }),
    });
    setMergedTargetTitle(topicDisplayName(target));
    setTaxVersion(null);
    await loadTopicMeta();
    await loadAnswers();
    const skipped = result.skipped || [];
    const text = t(`已併入「${topicDisplayName(target)}」，重新分類 ${result.moved_count} 則回答`, `Merged into "${topicDisplayName(target)}", re-classified ${result.moved_count} answer(s)`)
      + (skipped.length ? t(`；${skipped.length} 則未處理（${skipped[0].message}）`, `; ${skipped.length} skipped (${skipped[0].message})`) : "")
      + (result.aborted ? t(
        `。資料庫忙碌，已先暫停，還有 ${result.unprocessed_count} 則沒處理；請稍後到「新類別候選」的殘留區塊按「重試併入」（已處理的不會重做）`,
        `. The database was busy, so processing paused with ${result.unprocessed_count} answer(s) left; use "Retry merge" in the leftover section later (finished ones are not redone).`,
      ) : "");
    setMergeResultText(text);
    return text;
  };

  // 解除合併：只清空 merged_into，只影響之後的新資料；已重新分類到目標主題的回答不會移回、
  // 既有分類結果不會還原（後端 POST /topics/{key}/unmerge）。
  const unmergeTopic = async () => {
    if (!window.confirm(`${t("解除這個主題的合併？", "Undo the merge of this topic?")}\n\n${t(
      "解除後只影響之後的新資料；已重新分類到目標主題的既有回答不會自動移回。",
      "Undoing only affects new data from now on; existing answers already re-classified into the target topic are not moved back automatically.",
    )}`)) return;
    setUnmerging(true);
    setUnmergeResultText("");
    try {
      const result = await api(`/api/admin/ai/topics/${encodeURIComponent(topicKey)}/unmerge`, token, { method: "POST" });
      setMergeResultText("");
      setTaxVersion(null);
      const meta = await loadTopicMeta();
      const versionId = meta?.latest_draft_version?.version_id ?? meta?.published_version?.version_id;
      if (versionId) await openVersion(versionId);
      await loadAnswers();
      const restored = result.restored_version_ids?.length || 0;
      setUnmergeResultText(t(
        `已解除合併。已重新分類到目標主題的 ${result.answers_staying_on_target} 筆回答不會自動移回，只有之後的新資料會依這個主題處理。`
          + (restored ? `已恢復 ${restored} 個草稿版本。` : "未恢復舊草稿（來源已有分類架構版本，或沒有可恢復的紀錄）。"),
        `Merge undone. ${result.answers_staying_on_target} answer(s) already re-classified into the target topic are not moved back; only new data follows this topic from now on.`
          + (restored ? ` ${restored} draft version(s) restored.` : " No old draft was restored (the topic already has a taxonomy version, or there is nothing to restore)."),
      ));
    } catch (e) {
      setError(e.message);
    } finally {
      setUnmerging(false);
    }
  };

  // 類別 -> 這一類的原始回答；不在目前版本分類架構裡的類別另外列出
  const groupKey = (main, sub) => `${main || ""}|${sub || ""}`;
  const groupFor = (cat) => (answers?.groups || []).find((g) => groupKey(g.main_category, g.sub_category) === groupKey(cat.main_category, cat.sub_category))
    || { main_category: cat.main_category, sub_category: cat.sub_category, count: 0, items: [] };
  const taxKeys = new Set((taxVersion?.categories || []).map((c) => groupKey(c.main_category, c.sub_category)));
  const otherGroups = (answers?.groups || []).filter((g) => !taxKeys.has(groupKey(g.main_category, g.sub_category)));

  const versionLabel = (status) => ({ published: t("使用中", "Live"), draft: t("草稿", "Draft"), in_review: t("審核中", "In review"), archived: t("封存", "Archived") }[status] || status);
  // 版本清單：優先用完整清單（含封存），讀取失敗時只列出目前上線與最新草稿
  const versionButtons = (() => {
    const list = versions || [topicMeta?.published_version, topicMeta?.latest_draft_version]
      .filter(Boolean).map((v) => ({ ...v, status: v.status || (v.version_id === topicMeta?.published_version?.version_id ? "published" : "draft") }));
    const rank = { draft: 0, in_review: 0, published: 1 };
    return {
      main: list.filter((v) => v.status !== "archived").sort((a, b) => (rank[a.status] ?? 2) - (rank[b.status] ?? 2) || b.version_number - a.version_number),
      archived: list.filter((v) => v.status === "archived").sort((a, b) => b.version_number - a.version_number),
    };
  })();
  const editableNow = Boolean(taxVersion) && TAX_EDITABLE_STATUSES.includes(taxVersion.status);

  if (loading) return <SkeletonCards count={4} />;

  return <>
    {error && <p className="ai-admin-error">{error}<button onClick={() => setError("")}>×</button></p>}

    {!topicMeta && <div className="admin-card"><p>{t("找不到這個主題。", "Topic not found.")}</p></div>}

    {topicMeta?.merged_into && (
      <div className="admin-card topic-merged-banner">
        <p>{t(`這個主題已併入「${mergedTargetTitle}」。之後同樣的欄位 / 題目會直接用「${mergedTargetTitle}」的分類架構。`,
          `This topic was merged into "${mergedTargetTitle}". Future uploads of the same column use that taxonomy.`)}</p>
        {mergeResultText && <p className="review-batch-message">{mergeResultText}</p>}
        <NavLink to={`/admin/ai/topics/${topicMeta.merged_into}`}>{t("前往該主題 →", "Open that topic →")}</NavLink>
        {" "}
        <button type="button" disabled={unmerging} onClick={unmergeTopic}>
          {unmerging ? t("處理中…", "Working…") : t("解除合併", "Undo merge")}
        </button>
        <p><small>{t("解除後只影響之後的新資料；已重新分類到目標主題的既有回答不會自動移回。", "Undoing only affects new data from now on; answers already re-classified into the target topic are not moved back.")}</small></p>
      </div>
    )}
    {unmergeResultText && <p className="review-batch-message" role="status">{unmergeResultText}</p>}

    {topicMeta && !topicMeta.merged_into && <TopicSourceSummary data={answers} />}

    {topicMeta && !topicMeta.merged_into && !topicMeta.published_version && (
      <div className="admin-card topic-merge-card">
        <h3>{t("這個主題分錯了？整個併入其他主題", "Wrong topic? Merge it into another topic")}</h3>
        <p className="review-empty-hint">{topicMeta.is_auto_topic
          ? t("這是 AI 自動建立的主題。如果這些回答其實屬於某個既有主題，可以整個併過去：底下的回答會用目標主題的分類架構重新分類，這個主題的暫定分類會封存，之後同樣的欄位也會直接歸到目標主題。",
            "This topic was created automatically. If these answers belong to an existing topic, merge it: answers are re-classified with the target taxonomy, this provisional taxonomy is archived, and future uploads of the same column go to the target.")
          : t("這個主題還沒有正式發布的分類架構。併入後，底下的回答會用目標主題的分類架構重新分類，之後同樣的欄位 / 題目也會直接歸到目標主題。",
            "This topic has no published taxonomy. After merging, its answers are re-classified with the target taxonomy and future uploads go to the target.")}
        </p>
        <TopicMovePicker token={token} currentTopicKey={topicKey} mode="topic" onMove={mergeTopic} />
      </div>
    )}

    {topicMeta && !taxVersion && !topicMeta.merged_into && (
      <div className="admin-card"><p>{t("這個主題目前還沒有任何分類架構版本。", "This topic doesn't have any taxonomy version yet.")}</p></div>
    )}

    {topicMeta && taxVersion && <>
      <div className="tax-version-bar">
        <b>{t("版本", "Version")}</b>
        {versionButtons.main.map((v) => (
          <button key={v.version_id} type="button" aria-pressed={taxVersion.version_id === v.version_id}
            className={`tax-ver${taxVersion.version_id === v.version_id ? " tax-ver--active" : ""}`}
            onClick={() => openVersion(v.version_id)}>
            v{v.version_number} {versionLabel(v.status)}
          </button>
        ))}
        {versionButtons.archived.length > 0 && (
          <details className="tax-ver-archived" open={archivedOpen} onToggle={(e) => setArchivedOpen(e.currentTarget.open)}>
            <summary>{t(`封存版本（${versionButtons.archived.length}）`, `Archived (${versionButtons.archived.length})`)}</summary>
            {versionButtons.archived.map((v) => (
              <button key={v.version_id} type="button" aria-pressed={taxVersion.version_id === v.version_id}
                className={`tax-ver${taxVersion.version_id === v.version_id ? " tax-ver--active" : ""}`}
                onClick={() => openVersion(v.version_id)}>
                v{v.version_number} {versionLabel(v.status)}
              </button>
            ))}
          </details>
        )}
      </div>
      {versionsFailed && (
        <p className="tax-mode tax-mode--archived" role="status">
          {t("完整版本清單讀取失敗，目前只顯示使用中與最新草稿。", "Couldn't load the full version list; showing only the live version and latest draft.")}{" "}
          <button type="button" onClick={loadVersions}>{t("重新讀取", "Retry")}</button>
        </p>
      )}
      <p className={`tax-mode tax-mode--${taxVersion.status === "published" ? "live" : editableNow ? "draft" : "archived"}`} role="status">
        {taxVersion.status === "published"
          ? t(`目前查看：使用中的 v${taxVersion.version_number}。這是正式版本，唯讀；要修改請先建立新草稿。`, `Viewing live v${taxVersion.version_number}. Read-only — create a new draft to make changes.`)
          : editableNow
            ? t(`目前查看：${taxStatusText(taxVersion.status)} v${taxVersion.version_number}。可以編輯，發布後才會用於分類。`, `Viewing ${taxStatusText(taxVersion.status)} v${taxVersion.version_number}. Editable; it is used for classification only after publishing.`)
            : t(`目前查看：封存的 v${taxVersion.version_number}。唯讀，僅供歷史參照。`, `Viewing archived v${taxVersion.version_number}. Read-only, for history only.`)}
      </p>

      <p><small>v{taxVersion.version_number} · {taxStatusText(taxVersion.status)} · {t("來源：", "Source:")} {({ manual: t("手動建立", "Manual"), ai_generated: t("AI 產生", "AI generated"),
          migrated_legacy: t("舊版轉入", "Migrated") })[taxVersion.source] || taxVersion.source} · {t("建立於：", "Created:")} {taxVersion.created_at ? new Date(taxVersion.created_at).toLocaleString() : "—"}{taxVersion.published_at ? ` · ${t("發布於：", "Published:")} ${new Date(taxVersion.published_at).toLocaleString()}` : ""}</small></p>

      <div className="tax-actions">
        {taxVersion.status === "published" && <button className="primary" onClick={cloneTaxVersion}>{t("建立新草稿版本（複製此版）", "Create new draft (clone this version)")}</button>}
        {editableNow && <>
          <button onClick={addTaxCategory}>{t("＋ 新增子類別", "＋ Add category")}</button>
          <button className="primary" onClick={publishTaxVersion}>{t("發布這個版本", "Publish as production taxonomy")}</button>
        </>}
        {taxVersion.status === "draft" && <button className="review-btn-danger tax-danger" onClick={deleteTaxVersion}>{t("刪除草稿", "Delete draft")}</button>}
      </div>
      {!answers && <button onClick={loadAnswers} disabled={answersLoading}>
        {answersLoading ? t("載入回答範例…", "Loading answer examples…") : t("載入回答範例", "Load answer examples")}
      </button>}

      {(taxVersion.categories || []).map((cat, i) => {
        const editable = TAX_EDITABLE_STATUSES.includes(taxVersion.status);
        return <div className="admin-card tax-cat-card" key={cat.category_id}>
          <div className="tax-cat-head">
            <b>{i + 1}. {cat.main_category} / {cat.sub_category}</b>
            {editable && <span className="tax-cat-tools">
              <button onClick={() => moveTaxCategory(i, -1)} disabled={i === 0}>↑</button>
              <button onClick={() => moveTaxCategory(i, 1)} disabled={i === taxVersion.categories.length - 1}>↓</button>
              <button className="review-btn-danger tax-danger" onClick={() => deleteTaxCategory(cat.category_id)}>{t("刪除", "Delete")}</button>
            </span>}
          </div>
          {answers && <CategoryAnswers topicKey={topicKey} token={token} group={groupFor(cat)} />}
          {editable ? <div className="tax-field-grid">
            <TaxCategoryField cat={cat} field="main_category" label={t("大類別", "Main category")} onSave={saveTaxCategory} />
            <TaxCategoryField cat={cat} field="sub_category" label={t("子類別", "Sub category")} onSave={saveTaxCategory} />
            <TaxCategoryField cat={cat} field="definition" label={t("定義", "Definition")} multiline onSave={saveTaxCategory} />
            <details className="tax-more">
              <summary>{t("更多規則（納入、排除、界線、方法論、引用）", "More rules (include, exclude, boundary, methodology, citation)")}</summary>
              <TaxCategoryField cat={cat} field="include_rules" label={t("納入規則", "Include rules")} multiline onSave={saveTaxCategory} />
              <TaxCategoryField cat={cat} field="exclude_rules" label={t("排除規則", "Exclude rules")} multiline onSave={saveTaxCategory} />
              <TaxCategoryField cat={cat} field="boundary_rules" label={t("與相近類別界線", "Boundary rules")} multiline onSave={saveTaxCategory} />
              <TaxCategoryField cat={cat} field="methodology" label={t("方法論（可留白）", "Methodology (optional)")} onSave={saveTaxCategory} />
              <TaxCategoryField cat={cat} field="citation" label={t("引用（可留白，不可捏造）", "Citation (optional, never fabricate)")} onSave={saveTaxCategory} />
              {cat.source_raw_text && <p className="tax-legacy-note">{t("既有原文規則（僅供參考）：", "Legacy raw rule text (reference only):")} {cat.source_raw_text}</p>}
            </details>
          </div> : <div>
            <p>{t("定義", "Definition")}: {cat.definition || cat.source_raw_text || "—"}</p>
            {cat.include_rules && <p>{t("納入規則", "Include")}: {cat.include_rules}</p>}
            {cat.exclude_rules && <p>{t("排除規則", "Exclude")}: {cat.exclude_rules}</p>}
            {cat.boundary_rules && <p>{t("界線", "Boundary")}: {cat.boundary_rules}</p>}
            <p>{t("方法論", "Methodology")}: {cat.methodology || "—"} · {t("引用", "Citation")}: {cat.citation || "—"}</p>
          </div>}
        </div>;
      })}

      {answers && <OtherCategoryAnswers topicKey={topicKey} token={token} groups={otherGroups} />}
    </>}
  </>;
}
