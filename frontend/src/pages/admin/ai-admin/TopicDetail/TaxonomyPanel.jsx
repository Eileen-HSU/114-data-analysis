import { useEffect, useRef, useState } from "react";
import { NavLink, useParams } from "react-router-dom";
import { api, peekCache } from "../shared/apiClient";
import { SkeletonCards } from "../shared/StatusWidgets";
import { t, taxStatusText, TAX_EDITABLE_STATUSES } from "../shared/taxStatus";
import TaxCategoryField from "../shared/TaxCategoryField";
import TopicMovePicker from "../shared/TopicMovePicker";
import { CategoryAnswers, OtherCategoryAnswers, TopicSourceSummary, answersUrl, loadTopicAnswers } from "./TopicAnswers";
import { useAuth } from "../../../../hooks/AuthContext";

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
        setMergedTargetTitle(target?.title || mine.merged_into);
      }
      return mine || null;
    } catch (e) {
      setError(e.message);
      return null;
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
    setMergedTargetTitle("");
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
    } catch (e) { setError(e.message); }
  };
  const deleteTaxVersion = async () => {
    await flushPendingSaves();
    if (!window.confirm(t("確定要刪除此草稿版本嗎？刪除後無法復原。", "Are you sure you want to delete this draft version? This cannot be undone."))) return;
    try {
      await api(`/api/admin/ai/topics/${topicKey}/taxonomy/${taxVersion.version_id}`, token, { method: "DELETE" });
      setTaxVersion(null);
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
    setMergedTargetTitle(target.title || target.topic_key);
    setTaxVersion(null);
    await loadTopicMeta();
    await loadAnswers();
    const skipped = result.skipped || [];
    const text = t(`已併入「${target.title}」，重新分類 ${result.moved_count} 則回答`, `Merged into "${target.title}", re-classified ${result.moved_count} answer(s)`)
      + (skipped.length ? t(`；${skipped.length} 則未處理（${skipped[0].message}）`, `; ${skipped.length} skipped (${skipped[0].message})`) : "");
    setMergeResultText(text);
    return text;
  };

  // 類別 -> 這一類的原始回答；不在目前版本分類架構裡的類別另外列出
  const groupKey = (main, sub) => `${main || ""}|${sub || ""}`;
  const groupFor = (cat) => (answers?.groups || []).find((g) => groupKey(g.main_category, g.sub_category) === groupKey(cat.main_category, cat.sub_category))
    || { main_category: cat.main_category, sub_category: cat.sub_category, count: 0, items: [] };
  const taxKeys = new Set((taxVersion?.categories || []).map((c) => groupKey(c.main_category, c.sub_category)));
  const otherGroups = (answers?.groups || []).filter((g) => !taxKeys.has(groupKey(g.main_category, g.sub_category)));

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
      </div>
    )}

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
      {topicMeta.published_version && topicMeta.latest_draft_version
        && topicMeta.published_version.version_id !== topicMeta.latest_draft_version.version_id && (
        <div className="admin-card" style={{ marginBottom: 14, display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
          <b>{t("查看版本：", "View version:")}</b>
          {topicMeta.published_version && (
            <button className={taxVersion.version_id === topicMeta.published_version.version_id ? "primary" : ""} onClick={() => openVersion(topicMeta.published_version.version_id)}>
              {t("已發布", "Published")} v{topicMeta.published_version.version_number}
            </button>
          )}
          {topicMeta.latest_draft_version && (
            <button className={taxVersion.version_id === topicMeta.latest_draft_version.version_id ? "primary" : ""} onClick={() => openVersion(topicMeta.latest_draft_version.version_id)}>
              {t("草稿", "Draft")} v{topicMeta.latest_draft_version.version_number} ({taxStatusText(topicMeta.latest_draft_version.status)})
            </button>
          )}
        </div>
      )}

      <p><small>v{taxVersion.version_number} · {taxStatusText(taxVersion.status)} · {t("來源：", "Source:")} {({ manual: t("手動建立", "Manual"), ai_generated: t("AI 產生", "AI generated"),
          migrated_legacy: t("舊版轉入", "Migrated") })[taxVersion.source] || taxVersion.source} · {t("建立於：", "Created:")} {taxVersion.created_at ? new Date(taxVersion.created_at).toLocaleString() : "—"}{taxVersion.published_at ? ` · ${t("發布於：", "Published:")} ${new Date(taxVersion.published_at).toLocaleString()}` : ""}</small></p>

      <div style={{ display: "flex", gap: 10, margin: "14px 0" }}>
        {taxVersion.status === "published" ? <button className="primary" onClick={cloneTaxVersion}>{t("建立新草稿版本（複製此版）", "Create new draft (clone this version)")}</button>
          : <>{TAX_EDITABLE_STATUSES.includes(taxVersion.status) && <button onClick={addTaxCategory}>{t("＋ 新增子類別", "＋ Add category")}</button>}<button className="primary" onClick={publishTaxVersion}>{t("發布這個版本", "Publish as production taxonomy")}</button></>}
        {taxVersion.status === "draft" && <button onClick={deleteTaxVersion}>{t("刪除草稿", "Delete draft")}</button>}
      </div>
      {!answers && <button onClick={loadAnswers} disabled={answersLoading}>
        {answersLoading ? t("載入回答範例…", "Loading answer examples…") : t("載入回答範例", "Load answer examples")}
      </button>}
      {taxVersion.status === "published" && <p className="tax-legacy-note">{t("已發布版本唯讀，不可直接編輯；如需修改請先建立新草稿版本。", "Published versions are read-only. Create a new draft to make changes.")}</p>}

      {(taxVersion.categories || []).map((cat, i) => {
        const editable = TAX_EDITABLE_STATUSES.includes(taxVersion.status);
        return <div className="admin-card" key={cat.category_id} style={{ marginBottom: 14 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <b>{i + 1}. {cat.main_category} / {cat.sub_category}</b>
            {editable && <span style={{ display: "flex", gap: 6 }}>
              <button onClick={() => moveTaxCategory(i, -1)} disabled={i === 0}>↑</button>
              <button onClick={() => moveTaxCategory(i, 1)} disabled={i === taxVersion.categories.length - 1}>↓</button>
              <button onClick={() => deleteTaxCategory(cat.category_id)}>{t("刪除", "Delete")}</button>
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
