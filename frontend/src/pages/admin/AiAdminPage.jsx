import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import Navbar from "../../components/feature/Navbar";
import { useAuth } from "../../hooks/AuthContext";
import { apiUrl } from "../../lib/api";
import "./ai-admin.css";

const api = async (path, token, options = {}) => {
  const response = await fetch(apiUrl(path), { ...options, headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}`, ...(options.headers || {}) } });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || "Request failed");
  return body;
};

const statusTextEn = (value) => ({ validated: "Meets publish criteria", needs_validation: "Needs validation", published: "Published", not_published: "Not published" }[value] || value);
const statusTextZh = (value) => ({ validated: "符合發布標準", needs_validation: "需審核", published: "已發布", not_published: "未發布" }[value] || value);

const taxStatusTextEn = (value) => ({ no_taxonomy: "No taxonomy yet", draft: "Draft", in_review: "In review", published: "Published", draft_and_published: "Published + draft in progress" }[value] || value);
const taxStatusTextZh = (value) => ({ no_taxonomy: "尚無 taxonomy", draft: "草稿", in_review: "審核中", published: "已發布", draft_and_published: "已發布（另有草稿審核中）" }[value] || value);

const getLang = () => {
  if (typeof window !== "undefined") {
    try {
      const stored = localStorage.getItem("dataanalysis_language");
      if (stored) return stored.startsWith("zh") ? "zh" : "en";
    } catch (e) {
      /* ignore localStorage errors */
    }
  }
  return (typeof navigator !== "undefined" && navigator.language && navigator.language.startsWith("zh")) ? "zh" : "en";
};
const t = (zh, en) => (getLang() === "zh" ? zh : en);

const statusText = (value) => (getLang() === "zh" ? statusTextZh(value) : statusTextEn(value));
const taxStatusText = (value) => (getLang() === "zh" ? taxStatusTextZh(value) : taxStatusTextEn(value));

const TAX_EDITABLE_STATUSES = ["draft", "in_review"];

function TaxCategoryField({ cat, field, label, multiline, onSave }) {
  const Tag = multiline ? "textarea" : "input";
  return (
    <label className="tax-field">
      {label}
      <Tag
        defaultValue={cat[field] || ""}
        rows={multiline ? 2 : undefined}
        onBlur={(e) => {
          const value = e.target.value;
          if (value !== (cat[field] || "")) onSave(cat.category_id, { [field]: value || null });
        }}
      />
    </label>
  );
}


export default function AiAdminPage() {
  const navigate = useNavigate();
  const { user, isLoggedIn } = useAuth();
  const token = user?.token;
  const [tab, setTab] = useState("manage");
  const [topics, setTopics] = useState([]);
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [draft, setDraft] = useState("");
  const [step, setStep] = useState("edit");
  const [sandboxText, setSandboxText] = useState("");
  const [sandboxResult, setSandboxResult] = useState(null);
  const [validation, setValidation] = useState(null);
  const [classifications, setClassifications] = useState([]);
  const [reviewStatus, setReviewStatus] = useState("");
  const [reviewTopic, setReviewTopic] = useState("");
  const [systemTab, setSystemTab] = useState("taxonomy");
  const [systemData, setSystemData] = useState([]);
  const [error, setError] = useState("");
  // ── Taxonomy Management（Phase D）：跟上面 Prompt Candidate 的
  // state 完全分開，資料來源是 Topic/Taxonomy_Version/Taxonomy_Category，
  // 不共用 selected/detail/draft 等既有變數，避免混淆兩種「草稿」。
  const [taxTopics, setTaxTopics] = useState([]);
  const [taxSelectedTopic, setTaxSelectedTopic] = useState(null);
  const [taxVersion, setTaxVersion] = useState(null);
  const [taxShowGenerate, setTaxShowGenerate] = useState(false);
  const [taxGenForm, setTaxGenForm] = useState({ topic_key: "", topic_title: "", question_text: "", answer_texts: "", global_instructions: "", reference_topic_keys: "" });
  const canAccess = isLoggedIn && user?.account_type === "admin";

  const loadTopics = async () => { try { setTopics((await api("/api/admin/ai/topics", token)).topics); } catch (e) { setError(e.message); } };
  useEffect(() => { if (canAccess) loadTopics(); }, [canAccess]);

  const openTopic = async (key) => {
    try { const data = await api(`/api/admin/ai/topics/${key}`, token); setSelected(key); setDetail(data); setDraft(data.draft_content); setValidation(null); setSandboxResult(null); setStep("edit"); } catch (e) { setError(e.message); }
  };
  const save = async () => { try { const data = await api(`/api/admin/ai/topics/${selected}`, token, { method: "PUT", body: JSON.stringify({ draft_content: draft }) }); setDetail(data); setValidation(null); await loadTopics(); } catch (e) { setError(e.message); } };
  const sandbox = async () => { try { setSandboxResult((await api(`/api/admin/ai/topics/${selected}/sandbox`, token, { method: "POST", body: JSON.stringify({ answer_text: sandboxText }) })).result); } catch (e) { setError(e.message); } };
  const validate = async () => { try { const data = await api(`/api/admin/ai/topics/${selected}/validate`, token, { method: "POST" }); setValidation(data); setDetail((current) => ({ ...current, draft_validated: data.can_publish })); await loadTopics(); } catch (e) { setError(e.message); } };
  const publish = async () => { try { await api(`/api/admin/ai/topics/${selected}/publish`, token, { method: "POST" }); await openTopic(selected); await loadTopics(); } catch (e) { setError(e.message); } };
  const loadClassifications = async (status = reviewStatus, topic = reviewTopic) => { try { const params = new URLSearchParams(); if (status) params.set("review_status", status); if (topic) params.set("topic", topic); setClassifications((await api(`/api/admin/ai/classifications${params.size ? `?${params}` : ""}`, token)).classifications); } catch (e) { setError(e.message); } };
  useEffect(() => { if (canAccess && tab === "reviews") loadClassifications(); }, [canAccess, tab]);
  const loadSystem = async (kind) => { try { setSystemData((await api(`/api/admin/ai/${kind === "taxonomy" ? "taxonomy" : "golden-tests"}`, token))[kind === "taxonomy" ? "topics" : "cases"]); } catch (e) { setError(e.message); } };
  useEffect(() => { if (canAccess && tab === "system") loadSystem(systemTab); }, [canAccess, tab, systemTab]);

  // ── Taxonomy Management handlers ──
  const loadTaxTopics = async () => { try { setTaxTopics((await api("/api/admin/ai/taxonomy-topics", token)).topics); } catch (e) { setError(e.message); } };
  useEffect(() => { if (canAccess && tab === "taxonomy") loadTaxTopics(); }, [canAccess, tab]);

  const openTaxVersion = async (topicKey, versionId) => {
    try { const data = await api(`/api/admin/ai/topics/${topicKey}/taxonomy/${versionId}`, token); setTaxSelectedTopic(topicKey); setTaxVersion(data.taxonomy_version); } catch (e) { setError(e.message); }
  };
  const backToTaxList = async () => { setTaxSelectedTopic(null); setTaxVersion(null); setTaxShowGenerate(false); await loadTaxTopics(); };

  const saveTaxCategory = async (categoryId, fields) => {
    try {
      const data = await api(`/api/admin/ai/topics/${taxSelectedTopic}/taxonomy/${taxVersion.version_id}/categories/${categoryId}`, token, { method: "PUT", body: JSON.stringify(fields) });
      setTaxVersion((v) => ({ ...v, categories: v.categories.map((c) => (c.category_id === categoryId ? data.category : c)) }));
    } catch (e) { setError(e.message); }
  };
  const addTaxCategory = async () => {
    try {
      const data = await api(`/api/admin/ai/topics/${taxSelectedTopic}/taxonomy/${taxVersion.version_id}/categories`, token, { method: "POST", body: JSON.stringify({ main_category: t("新大類別", "New main category"), sub_category: t("新子類別", "New sub category"), definition: "" }) });
      setTaxVersion((v) => ({ ...v, categories: [...v.categories, data.category] }));
    } catch (e) { setError(e.message); }
  };
  const deleteTaxCategory = async (categoryId) => {
    try {
      await api(`/api/admin/ai/topics/${taxSelectedTopic}/taxonomy/${taxVersion.version_id}/categories/${categoryId}`, token, { method: "DELETE" });
      setTaxVersion((v) => ({ ...v, categories: v.categories.filter((c) => c.category_id !== categoryId) }));
    } catch (e) { setError(e.message); }
  };
  const moveTaxCategory = async (index, direction) => {
    const cats = [...taxVersion.categories];
    const target = index + direction;
    if (target < 0 || target >= cats.length) return;
    [cats[index], cats[target]] = [cats[target], cats[index]];
    try {
      const data = await api(`/api/admin/ai/topics/${taxSelectedTopic}/taxonomy/${taxVersion.version_id}/categories/reorder`, token, { method: "POST", body: JSON.stringify({ ordered_category_ids: cats.map((c) => c.category_id) }) });
      setTaxVersion((v) => ({ ...v, categories: data.categories }));
    } catch (e) { setError(e.message); }
  };
  const cloneTaxVersion = async () => {
    try { const data = await api(`/api/admin/ai/topics/${taxSelectedTopic}/taxonomy/${taxVersion.version_id}/clone`, token, { method: "POST" }); setTaxVersion(data.taxonomy_version); } catch (e) { setError(e.message); }
  };
  const publishTaxVersion = async () => {
    try { const data = await api(`/api/admin/ai/topics/${taxSelectedTopic}/taxonomy/${taxVersion.version_id}/publish`, token, { method: "POST" }); setTaxVersion(data.taxonomy_version); } catch (e) { setError(e.message); }
  };
  const runTaxGeneration = async () => {
    const key = taxGenForm.topic_key.trim() || taxSelectedTopic;
    if (!key) { setError(t("請先輸入 Topic Key", "Please enter a topic key")); return; }
    const answer_texts = taxGenForm.answer_texts.split("\n").map((s) => s.trim()).filter(Boolean);
    if (!answer_texts.length) { setError(t("請至少貼上一則回答", "Please paste at least one answer")); return; }
    const reference_topic_keys = taxGenForm.reference_topic_keys.split(",").map((s) => s.trim()).filter(Boolean);
    try {
      const data = await api(`/api/admin/ai/topics/${key}/taxonomy/generate`, token, {
        method: "POST",
        body: JSON.stringify({ topic_title: taxGenForm.topic_title || undefined, question_text: taxGenForm.question_text || undefined, global_instructions: taxGenForm.global_instructions || undefined, answer_texts, reference_topic_keys }),
      });
      setTaxSelectedTopic(key);
      setTaxVersion(data.taxonomy_version);
      setTaxShowGenerate(false);
    } catch (e) { setError(e.message); }
  };

  if (!canAccess) return <><Navbar /><main className="ai-admin-empty"><h1>{t("僅管理者可存取 AI 管理介面","AI admin access restricted to administrators")}</h1><button onClick={() => navigate("/workspace")}>{t("回到分析助理","Back to Analysis Assistant")}</button></main></>;
  return <><Navbar /><main className="ai-admin-page">
    <header><p className="eyebrow">{t("系統管理","INTERNAL ADMINISTRATION")}</p><h1>{t("AI 分類管理","AI Classification Administration")}</h1><p>{t("維護分類邏輯、監控分類品質，並管理低頻系統設定。","Maintain classification logic, monitor classification quality, and manage low-frequency system settings.")}</p></header>
    <nav className="ai-admin-tabs"><button className={tab === "manage" ? "active" : ""} onClick={() => setTab("manage")}>{t("Prompt 設定","Prompt Configuration")}</button><button className={tab === "taxonomy" ? "active" : ""} onClick={() => setTab("taxonomy")}>{t("Taxonomy 管理","Taxonomy Management")}</button><button className={tab === "reviews" ? "active" : ""} onClick={() => setTab("reviews")}>{t("AI 分類審查","AI Classification Review")}</button><button className={tab === "system" ? "active" : ""} onClick={() => setTab("system")}>{t("系統管理","System administration")}</button></nav>
    {error && <p className="ai-admin-error">{error}<button onClick={() => setError("")}>×</button></p>}
    {tab === "manage" && <section>
      {!selected ? <div className="topic-grid">{topics.map((topic) => <article key={topic.prompt_key} className="topic-card"><h2>{topic.prompt_key}</h2><p>{t("發布狀態：","Production status:")} <b>{statusText(topic.production_status)}</b></p><p>{t("候選狀態：","Candidate:")} <b>{statusText(topic.candidate_status)}</b></p><small>{t("最後修改：","Last modified:")} {topic.updated_at ? new Date(topic.updated_at).toLocaleString() : "—"}</small><div><button onClick={() => openTopic(topic.prompt_key)}>{t("查看設定","View settings")}</button><button className="primary" onClick={() => openTopic(topic.prompt_key)}>{t("繼續修改","Continue editing")}</button></div></article>)}</div> : <section className="candidate-workspace"><button className="back" onClick={() => setSelected(null)}>← {t("所有主題","All topics")}</button><h2>{selected} {t("候選工作區","Candidate workspace")}</h2><div className="stepper">{["edit", "test", "publish"].map((item, i) => <button key={item} className={step === item ? "active" : ""} onClick={() => setStep(item)} disabled={item === "publish" && !(validation?.can_publish || detail?.draft_validated)}>{i + 1}. {item === "edit" ? t("編輯","Edit") : item === "test" ? t("測試","Test") : t("發布","Publish")}</button>)}</div>
      {step === "edit" && <div className="admin-card"><details><summary>{t("查看目前生產設定（唯讀）","View current production setting (read-only)")}</summary><pre>{detail?.live_content}</pre></details><label>{t("候選內容","Candidate content")}<textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows="16" /></label><button className="primary" onClick={save}>{t("儲存變更（將使驗證結果失效）","Save changes (validation results will be invalidated)")}</button></div>}
      {step === "test" && <div className="admin-card"><h3>{t("沙盒快速執行","Sandbox quick run")}</h3><textarea value={sandboxText} onChange={(e) => setSandboxText(e.target.value)} placeholder={t("輸入單一開放式回應","Enter a single open-ended response")} rows="4" /><button onClick={sandbox}>{t("執行（不會寫入生產資料）","Run (does not write to production data)")}</button>{sandboxResult && <pre className="result">{JSON.stringify(sandboxResult, null, 2)}</pre>}<hr /><h3>{t("正式驗證：Golden 測試案例","Formal validation: Golden Test Cases")}</h3><button className="primary" onClick={validate}>{t("執行完整驗證","Run full validation")}</button>{validation && <><p className={validation.can_publish ? "pass" : "fail"}>{validation.can_publish ? t("符合發布標準","Meets publish criteria") : t("不符合發布標準","Does not meet publish criteria")} · {t("格式通過","Format valid")} {validation.format_valid_count}/{validation.total} · {t("Golden 準確率","Golden accuracy")} {(validation.accuracy_vs_golden * 100).toFixed(0)}%</p><div className="case-list">{validation.details.map((item, i) => <p key={i} className={item.is_correct ? "pass" : "fail"}>{item.is_correct ? "✓" : "×"} {t("預期","Expected")}: {item.expected_sub_category} / {t("結果","Result")}: {item.actual_sub_category}</p>)}</div></>}</div>}
      {step === "publish" && <div className="admin-card"><h3>{t("發布候選項","Publish Candidate")}</h3><p>{t("通過驗證的候選項將成為目前的生產設定。","Validated candidates will become the current production settings.")}</p><button className="primary" disabled={!(validation?.can_publish || detail?.draft_validated)} onClick={publish}>{t("發布為生產設定","Publish as production setting")}</button></div>}</section>}</section>}
    {tab === "taxonomy" && <section>
      {!taxSelectedTopic ? <>
        <div className="admin-card">
          <button onClick={() => setTaxShowGenerate((v) => !v)}>{taxShowGenerate ? t("收合","Collapse") : t("＋ 由回答產生新的 Taxonomy 草稿","＋ Generate a new taxonomy draft from answers")}</button>
          {taxShowGenerate && <div style={{ marginTop: 14 }}>
            <label>{t("Topic Key（新主題請填寫；既有主題請填入相同 topic_key）","Topic key (for a new topic; use the existing topic_key to add another draft)")}<input value={taxGenForm.topic_key} onChange={(e) => setTaxGenForm((f) => ({ ...f, topic_key: e.target.value }))} placeholder="e.g. workload_and_flexibility" /></label>
            <label>{t("Topic 標題（新主題必填）","Topic title (required for a new topic)")}<input value={taxGenForm.topic_title} onChange={(e) => setTaxGenForm((f) => ({ ...f, topic_title: e.target.value }))} /></label>
            <label>{t("問卷題目原文（選填）","Survey question text (optional)")}<input value={taxGenForm.question_text} onChange={(e) => setTaxGenForm((f) => ({ ...f, question_text: e.target.value }))} /></label>
            <label>{t("這批回答（每行一則）","Answers for this batch (one per line)")}<textarea rows="8" value={taxGenForm.answer_texts} onChange={(e) => setTaxGenForm((f) => ({ ...f, answer_texts: e.target.value }))} placeholder={t("貼上或輸入這批開放式回答，一行一則","Paste or type the open-ended answers, one per line")} /></label>
            <label>{t("額外分析原則（選填）","Additional analysis instructions (optional)")}<textarea rows="3" value={taxGenForm.global_instructions} onChange={(e) => setTaxGenForm((f) => ({ ...f, global_instructions: e.target.value }))} /></label>
            <label>{t("參考既有主題（選填，逗號分隔 topic_key，僅供格式範例）","Reference existing topics (optional, comma-separated topic_key, format example only)")}<input value={taxGenForm.reference_topic_keys} onChange={(e) => setTaxGenForm((f) => ({ ...f, reference_topic_keys: e.target.value }))} placeholder="leadership_and_dept, career_and_feedback" /></label>
            <button className="primary" onClick={runTaxGeneration}>{t("開始產生草稿","Generate draft")}</button>
          </div>}
        </div>
        <div className="topic-grid">{taxTopics.map((topic) => <article key={topic.topic_key} className="topic-card">
          <h2>{topic.topic_key}</h2>
          <p>{topic.title}</p>
          <p>{t("狀態：","Status:")} <b>{taxStatusText(topic.status)}</b></p>
          {topic.published_version && <small>{t("已發布","Published")}: v{topic.published_version.version_number}</small>}
          {topic.published_version && topic.latest_draft_version && <br />}
          {topic.latest_draft_version && <small>{t("草稿","Draft")}: v{topic.latest_draft_version.version_number} ({taxStatusText(topic.latest_draft_version.status)})</small>}
          <div>
            {topic.published_version && <button onClick={() => openTaxVersion(topic.topic_key, topic.published_version.version_id)}>{t("查看已發布版","View published")}</button>}
            {topic.latest_draft_version && <button className="primary" onClick={() => openTaxVersion(topic.topic_key, topic.latest_draft_version.version_id)}>{t("編輯草稿","Edit draft")}</button>}
          </div>
        </article>)}</div>
      </> : <section className="candidate-workspace">
        <button className="back" onClick={backToTaxList}>← {t("所有 Topic","All topics")}</button>
        <h2>{taxSelectedTopic} · v{taxVersion?.version_number} · {taxStatusText(taxVersion?.status)}</h2>
        <p><small>{t("來源：","Source:")} {taxVersion?.source} · {t("建立於：","Created:")} {taxVersion?.created_at ? new Date(taxVersion.created_at).toLocaleString() : "—"}{taxVersion?.published_at ? ` · ${t("發布於：","Published:")} ${new Date(taxVersion.published_at).toLocaleString()}` : ""}</small></p>
        <div style={{ display: "flex", gap: 10, margin: "14px 0" }}>
          {taxVersion?.status === "published" ? <button className="primary" onClick={cloneTaxVersion}>{t("建立新草稿版本（複製此版）","Create new draft (clone this version)")}</button>
            : <>{TAX_EDITABLE_STATUSES.includes(taxVersion?.status) && <button onClick={addTaxCategory}>{t("＋ 新增子類別","＋ Add category")}</button>}<button className="primary" onClick={publishTaxVersion}>{t("發布為正式 Taxonomy","Publish as production taxonomy")}</button></>}
        </div>
        {taxVersion?.status === "published" && <p className="tax-legacy-note">{t("已發布版本唯讀，不可直接編輯；如需修改請先建立新草稿版本。","Published versions are read-only. Create a new draft to make changes.")}</p>}
        {(taxVersion?.categories || []).map((cat, i) => {
          const editable = TAX_EDITABLE_STATUSES.includes(taxVersion.status);
          return <div className="admin-card" key={cat.category_id} style={{ marginBottom: 14 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <b>{i + 1}. {cat.main_category} / {cat.sub_category}</b>
              {editable && <span style={{ display: "flex", gap: 6 }}>
                <button onClick={() => moveTaxCategory(i, -1)} disabled={i === 0}>↑</button>
                <button onClick={() => moveTaxCategory(i, 1)} disabled={i === taxVersion.categories.length - 1}>↓</button>
                <button onClick={() => deleteTaxCategory(cat.category_id)}>{t("刪除","Delete")}</button>
              </span>}
            </div>
            {editable ? <div className="tax-field-grid">
              <TaxCategoryField cat={cat} field="main_category" label={t("大類別","Main category")} onSave={saveTaxCategory} />
              <TaxCategoryField cat={cat} field="sub_category" label={t("子類別","Sub category")} onSave={saveTaxCategory} />
              <TaxCategoryField cat={cat} field="definition" label={t("定義","Definition")} multiline onSave={saveTaxCategory} />
              <TaxCategoryField cat={cat} field="include_rules" label={t("納入規則","Include rules")} multiline onSave={saveTaxCategory} />
              <TaxCategoryField cat={cat} field="exclude_rules" label={t("排除規則","Exclude rules")} multiline onSave={saveTaxCategory} />
              <TaxCategoryField cat={cat} field="boundary_rules" label={t("與相近類別界線","Boundary rules")} multiline onSave={saveTaxCategory} />
              <TaxCategoryField cat={cat} field="methodology" label={t("方法論（可留白）","Methodology (optional)")} onSave={saveTaxCategory} />
              <TaxCategoryField cat={cat} field="citation" label={t("引用（可留白，不可捏造）","Citation (optional, never fabricate)")} onSave={saveTaxCategory} />
              {cat.source_raw_text && <p className="tax-legacy-note">{t("既有原文規則（僅供參考）：","Legacy raw rule text (reference only):")} {cat.source_raw_text}</p>}
            </div> : <div>
              <p>{t("定義","Definition")}: {cat.definition || cat.source_raw_text || "—"}</p>
              {cat.include_rules && <p>{t("納入規則","Include")}: {cat.include_rules}</p>}
              {cat.exclude_rules && <p>{t("排除規則","Exclude")}: {cat.exclude_rules}</p>}
              {cat.boundary_rules && <p>{t("界線","Boundary")}: {cat.boundary_rules}</p>}
              <p>{t("方法論","Methodology")}: {cat.methodology || "—"} · {t("引用","Citation")}: {cat.citation || "—"}</p>
            </div>}
          </div>;
        })}
      </section>}
    </section>}
    {tab === "reviews" && <section className="admin-card"><div className="filter-row"><label>{t("分類主題","Classification topic")} <select value={reviewTopic} onChange={(e) => { setReviewTopic(e.target.value); loadClassifications(reviewStatus, e.target.value); }}><option value="">{t("全部","All")}</option>{topics.map(x => <option key={x.prompt_key} value={x.prompt_key}>{x.prompt_key}</option>)}</select></label><label>{t("審查狀態","review_status")} <select value={reviewStatus} onChange={(e) => { setReviewStatus(e.target.value); loadClassifications(e.target.value, reviewTopic); }}><option value="">{t("全部","All")}</option>{["confirmed", "modified", "pending_review", "excluded"].map(x => <option key={x}>{x}</option>)}</select></label></div>{classifications.map((row) => <article className="review-row" key={row.classification_id}><p><b>{row.review_status}</b> · {row.segment}</p><p>{t("結果","Effective")}: {row.effective_result.main_category} / {row.effective_result.sub_category}</p>{row.review_status === "modified" && <details><summary>{t("比較 AI 原始與人工審查最終結果","Compare AI Original and Human Review Final")}</summary>{["main_category", "sub_category", "secondary_sub_category", "reasoning"].filter(k => row[k] !== row[`final_${k}`]).map(k => <p key={k}><b>{k}</b><br />AI: {row[k] || "—"}<br />{t("人工","Human")}: {row[`final_${k}`] || "—"}</p>)}<button onClick={() => navigator.clipboard.writeText(`Response: ${row.segment}\nAI: ${JSON.stringify({main_category: row.main_category, sub_category: row.sub_category, reasoning: row.reasoning})}\nHuman: ${JSON.stringify(row.effective_result)}`)}>{t("複製不一致案例","Copy inconsistent case")}</button></details>}</article>)}</section>}
    {tab === "system" && <section className="admin-card"><div className="subtabs"><button className={systemTab === "taxonomy" ? "active" : ""} onClick={() => setSystemTab("taxonomy")}>{t("分類法","Taxonomy")}</button><button className={systemTab === "golden" ? "active" : ""} onClick={() => setSystemTab("golden")}>{t("Golden 測試案例","Golden Test Cases")}</button></div>{systemTab === "taxonomy" ? systemData.map(topic => <details key={topic.prompt_key}><summary>{topic.prompt_key}</summary>{topic.subcategories.map(item => <article key={item.sub_category}><b>{item.main_category} / {item.sub_category}</b><p>{t("方法論：","Methodology:")} {item.methodology}</p><p>{t("引用：","Citation:")} {item.citation}</p></article>)}</details>) : <div className="case-list">{systemData.map((item, i) => <article key={i}><b>{item.prompt_key}</b><p>{t("輸入：","Input:")} {item.answer_text}</p><p>{t("預期：","Expected:")} {item.expected_sub_category}</p></article>)}</div>}</section>}
  </main></>;
}
