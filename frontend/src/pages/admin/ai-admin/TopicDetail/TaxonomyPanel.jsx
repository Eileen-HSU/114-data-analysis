import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../shared/apiClient";
import { t, taxStatusText, TAX_EDITABLE_STATUSES } from "../shared/taxStatus";
import TaxCategoryField from "../shared/TaxCategoryField";
import { useAuth } from "../../../../hooks/AuthContext";

export default function TaxonomyPanel() {
  const { topicKey } = useParams();
  const { user } = useAuth();
  const token = user?.token;

  const [topicMeta, setTopicMeta] = useState(null); // 這個 topic 在 taxonomy-topics 列表裡的那一筆
  const [taxVersion, setTaxVersion] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  // 取得這個 topic 有哪些版本（沿用既有 taxonomy-topics 列表 API，前端篩出這一筆，
  // 不新增「單一 topic 版本清單」API——這次 IA 重構刻意不動 backend）
  const loadTopicMeta = async () => {
    try {
      const data = await api("/api/admin/ai/taxonomy-topics", token);
      const mine = (data.topics || []).find((x) => x.topic_key === topicKey);
      setTopicMeta(mine || null);
      return mine || null;
    } catch (e) {
      setError(e.message);
      return null;
    }
  };

  const openVersion = async (versionId) => {
    try {
      const data = await api(`/api/admin/ai/topics/${topicKey}/taxonomy/${versionId}`, token);
      setTaxVersion(data.taxonomy_version);
    } catch (e) {
      setError(e.message);
    }
  };

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setTaxVersion(null);
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

  const saveTaxCategory = async (categoryId, fields) => {
    try {
      const data = await api(`/api/admin/ai/topics/${topicKey}/taxonomy/${taxVersion.version_id}/categories/${categoryId}`, token, { method: "PUT", body: JSON.stringify(fields) });
      setTaxVersion((v) => ({ ...v, categories: v.categories.map((c) => (c.category_id === categoryId ? data.category : c)) }));
    } catch (e) { setError(e.message); }
  };
  const addTaxCategory = async () => {
    try {
      const data = await api(`/api/admin/ai/topics/${topicKey}/taxonomy/${taxVersion.version_id}/categories`, token, { method: "POST", body: JSON.stringify({ main_category: t("新大類別", "New main category"), sub_category: t("新子類別", "New sub category"), definition: "" }) });
      setTaxVersion((v) => ({ ...v, categories: [...v.categories, data.category] }));
    } catch (e) { setError(e.message); }
  };
  const deleteTaxCategory = async (categoryId) => {
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
    try {
      const data = await api(`/api/admin/ai/topics/${topicKey}/taxonomy/${taxVersion.version_id}/clone`, token, { method: "POST" });
      setTaxVersion(data.taxonomy_version);
      await loadTopicMeta();
    } catch (e) { setError(e.message); }
  };
  const publishTaxVersion = async () => {
    try {
      const data = await api(`/api/admin/ai/topics/${topicKey}/taxonomy/${taxVersion.version_id}/publish`, token, { method: "POST" });
      setTaxVersion(data.taxonomy_version);
      await loadTopicMeta();
    } catch (e) { setError(e.message); }
  };
  const deleteTaxVersion = async () => {
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

  if (loading) return <div className="admin-card"><p>{t("載入中...", "Loading...")}</p></div>;

  return <>
    {error && <p className="ai-admin-error">{error}<button onClick={() => setError("")}>×</button></p>}
    <h2>{topicMeta?.title || topicKey}</h2>

    {!topicMeta && <div className="admin-card"><p>{t("找不到這個主題。", "Topic not found.")}</p></div>}

    {topicMeta && !taxVersion && (
      <div className="admin-card"><p>{t("這個主題目前還沒有任何分類架構版本。", "This topic doesn't have any taxonomy version yet.")}</p></div>
    )}

    {topicMeta && taxVersion && <>
      {(topicMeta.published_version || topicMeta.latest_draft_version) && (
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

      <p><small>v{taxVersion.version_number} · {taxStatusText(taxVersion.status)} · {t("來源：", "Source:")} {taxVersion.source} · {t("建立於：", "Created:")} {taxVersion.created_at ? new Date(taxVersion.created_at).toLocaleString() : "—"}{taxVersion.published_at ? ` · ${t("發布於：", "Published:")} ${new Date(taxVersion.published_at).toLocaleString()}` : ""}</small></p>

      <div style={{ display: "flex", gap: 10, margin: "14px 0" }}>
        {taxVersion.status === "published" ? <button className="primary" onClick={cloneTaxVersion}>{t("建立新草稿版本（複製此版）", "Create new draft (clone this version)")}</button>
          : <>{TAX_EDITABLE_STATUSES.includes(taxVersion.status) && <button onClick={addTaxCategory}>{t("＋ 新增子類別", "＋ Add category")}</button>}<button className="primary" onClick={publishTaxVersion}>{t("發布為正式 Taxonomy", "Publish as production taxonomy")}</button></>}
        {taxVersion.status === "draft" && <button onClick={deleteTaxVersion}>{t("刪除草稿", "Delete draft")}</button>}
      </div>
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
          {editable ? <div className="tax-field-grid">
            <TaxCategoryField cat={cat} field="main_category" label={t("大類別", "Main category")} onSave={saveTaxCategory} />
            <TaxCategoryField cat={cat} field="sub_category" label={t("子類別", "Sub category")} onSave={saveTaxCategory} />
            <TaxCategoryField cat={cat} field="definition" label={t("定義", "Definition")} multiline onSave={saveTaxCategory} />
            <TaxCategoryField cat={cat} field="include_rules" label={t("納入規則", "Include rules")} multiline onSave={saveTaxCategory} />
            <TaxCategoryField cat={cat} field="exclude_rules" label={t("排除規則", "Exclude rules")} multiline onSave={saveTaxCategory} />
            <TaxCategoryField cat={cat} field="boundary_rules" label={t("與相近類別界線", "Boundary rules")} multiline onSave={saveTaxCategory} />
            <TaxCategoryField cat={cat} field="methodology" label={t("方法論（可留白）", "Methodology (optional)")} onSave={saveTaxCategory} />
            <TaxCategoryField cat={cat} field="citation" label={t("引用（可留白，不可捏造）", "Citation (optional, never fabricate)")} onSave={saveTaxCategory} />
            {cat.source_raw_text && <p className="tax-legacy-note">{t("既有原文規則（僅供參考）：", "Legacy raw rule text (reference only):")} {cat.source_raw_text}</p>}
          </div> : <div>
            <p>{t("定義", "Definition")}: {cat.definition || cat.source_raw_text || "—"}</p>
            {cat.include_rules && <p>{t("納入規則", "Include")}: {cat.include_rules}</p>}
            {cat.exclude_rules && <p>{t("排除規則", "Exclude")}: {cat.exclude_rules}</p>}
            {cat.boundary_rules && <p>{t("界線", "Boundary")}: {cat.boundary_rules}</p>}
            <p>{t("方法論", "Methodology")}: {cat.methodology || "—"} · {t("引用", "Citation")}: {cat.citation || "—"}</p>
          </div>}
        </div>;
      })}
    </>}
  </>;
}
