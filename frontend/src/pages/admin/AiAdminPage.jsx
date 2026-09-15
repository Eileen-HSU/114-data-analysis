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

const getLang = () => (typeof navigator !== "undefined" && navigator.language && navigator.language.startsWith("zh") ? "zh" : "en");
const lang = getLang();
const t = (zh, en) => (lang === "zh" ? zh : en);

const statusText = (value) => (lang === "zh" ? statusTextZh(value) : statusTextEn(value));


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

  if (!canAccess) return <><Navbar /><main className="ai-admin-empty"><h1>{t("僅管理者可存取 AI 管理介面","AI admin access restricted to administrators")}</h1><button onClick={() => navigate("/workspace")}>{t("回到分析助理","Back to Analysis Assistant")}</button></main></>;
  return <><Navbar /><main className="ai-admin-page">
    <header><p className="eyebrow">{t("系統管理","INTERNAL ADMINISTRATION")}</p><h1>{t("AI 分類管理","AI Classification Administration")}</h1><p>{t("維護分類邏輯、監控分類品質，並管理低頻系統設定。","Maintain classification logic, monitor classification quality, and manage low-frequency system settings.")}</p></header>
    <nav className="ai-admin-tabs"><button className={tab === "manage" ? "active" : ""} onClick={() => setTab("manage")}>{t("AI 管理","AI Administration")}</button><button className={tab === "reviews" ? "active" : ""} onClick={() => setTab("reviews")}>{t("AI 分類審查","AI Classification Review")}</button><button className={tab === "system" ? "active" : ""} onClick={() => setTab("system")}>{t("系統管理","System administration")}</button></nav>
    {error && <p className="ai-admin-error">{error}<button onClick={() => setError("")}>×</button></p>}
    {tab === "manage" && <section>
      {!selected ? <div className="topic-grid">{topics.map((topic) => <article key={topic.prompt_key} className="topic-card"><h2>{topic.prompt_key}</h2><p>{t("發布狀態：","Production status:")} <b>{statusText(topic.production_status)}</b></p><p>{t("候選狀態：","Candidate:")} <b>{statusText(topic.candidate_status)}</b></p><small>{t("最後修改：","Last modified:")} {topic.updated_at ? new Date(topic.updated_at).toLocaleString() : "—"}</small><div><button onClick={() => openTopic(topic.prompt_key)}>{t("查看設定","View settings")}</button><button className="primary" onClick={() => openTopic(topic.prompt_key)}>{t("繼續修改","Continue editing")}</button></div></article>)}</div> : <section className="candidate-workspace"><button className="back" onClick={() => setSelected(null)}>← {t("所有主題","All topics")}</button><h2>{selected} {t("候選工作區","Candidate workspace")}</h2><div className="stepper">{["edit", "test", "publish"].map((item, i) => <button key={item} className={step === item ? "active" : ""} onClick={() => setStep(item)} disabled={item === "publish" && !(validation?.can_publish || detail?.draft_validated)}>{i + 1}. {item === "edit" ? t("編輯","Edit") : item === "test" ? t("測試","Test") : t("發布","Publish")}</button>)}</div>
      {step === "edit" && <div className="admin-card"><details><summary>{t("查看目前生產設定（唯讀）","View current production setting (read-only)")}</summary><pre>{detail?.live_content}</pre></details><label>{t("候選內容","Candidate content")}<textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows="16" /></label><button className="primary" onClick={save}>{t("儲存變更（將使驗證結果失效）","Save changes (validation results will be invalidated)")}</button></div>}
      {step === "test" && <div className="admin-card"><h3>{t("沙盒快速執行","Sandbox quick run")}</h3><textarea value={sandboxText} onChange={(e) => setSandboxText(e.target.value)} placeholder={t("輸入單一開放式回應","Enter a single open-ended response")} rows="4" /><button onClick={sandbox}>{t("執行（不會寫入生產資料）","Run (does not write to production data)")}</button>{sandboxResult && <pre className="result">{JSON.stringify(sandboxResult, null, 2)}</pre>}<hr /><h3>{t("正式驗證：Golden 測試案例","Formal validation: Golden Test Cases")}</h3><button className="primary" onClick={validate}>{t("執行完整驗證","Run full validation")}</button>{validation && <><p className={validation.can_publish ? "pass" : "fail"}>{validation.can_publish ? t("符合發布標準","Meets publish criteria") : t("不符合發布標準","Does not meet publish criteria")} · {t("格式通過","Format valid")} {validation.format_valid_count}/{validation.total} · {t("Golden 準確率","Golden accuracy")} {(validation.accuracy_vs_golden * 100).toFixed(0)}%</p><div className="case-list">{validation.details.map((item, i) => <p key={i} className={item.is_correct ? "pass" : "fail"}>{item.is_correct ? "✓" : "×"} {t("預期","Expected")}: {item.expected_sub_category} / {t("結果","Result")}: {item.actual_sub_category}</p>)}</div></>}</div>}
      {step === "publish" && <div className="admin-card"><h3>{t("發布候選項","Publish Candidate")}</h3><p>{t("通過驗證的候選項將成為目前的生產設定。","Validated candidates will become the current production settings.")}</p><button className="primary" disabled={!(validation?.can_publish || detail?.draft_validated)} onClick={publish}>{t("發布為生產設定","Publish as production setting")}</button></div>}</section>}</section>}
    {tab === "reviews" && <section className="admin-card"><div className="filter-row"><label>{t("分類主題","Classification topic")} <select value={reviewTopic} onChange={(e) => { setReviewTopic(e.target.value); loadClassifications(reviewStatus, e.target.value); }}><option value="">{t("全部","All")}</option>{topics.map(x => <option key={x.prompt_key} value={x.prompt_key}>{x.prompt_key}</option>)}</select></label><label>{t("審查狀態","review_status")} <select value={reviewStatus} onChange={(e) => { setReviewStatus(e.target.value); loadClassifications(e.target.value, reviewTopic); }}><option value="">{t("全部","All")}</option>{["confirmed", "modified", "pending_review", "excluded"].map(x => <option key={x}>{x}</option>)}</select></label></div>{classifications.map((row) => <article className="review-row" key={row.classification_id}><p><b>{row.review_status}</b> · {row.segment}</p><p>{t("結果","Effective")}: {row.effective_result.main_category} / {row.effective_result.sub_category}</p>{row.review_status === "modified" && <details><summary>{t("比較 AI 原始與人工審查最終結果","Compare AI Original and Human Review Final")}</summary>{["main_category", "sub_category", "secondary_sub_category", "reasoning"].filter(k => row[k] !== row[`final_${k}`]).map(k => <p key={k}><b>{k}</b><br />AI: {row[k] || "—"}<br />{t("人工","Human")}: {row[`final_${k}`] || "—"}</p>)}<button onClick={() => navigator.clipboard.writeText(`Response: ${row.segment}\nAI: ${JSON.stringify({main_category: row.main_category, sub_category: row.sub_category, reasoning: row.reasoning})}\nHuman: ${JSON.stringify(row.effective_result)}`)}>{t("複製不一致案例","Copy inconsistent case")}</button></details>}</article>)}</section>}
    {tab === "system" && <section className="admin-card"><div className="subtabs"><button className={systemTab === "taxonomy" ? "active" : ""} onClick={() => setSystemTab("taxonomy")}>{t("分類法","Taxonomy")}</button><button className={systemTab === "golden" ? "active" : ""} onClick={() => setSystemTab("golden")}>{t("Golden 測試案例","Golden Test Cases")}</button></div>{systemTab === "taxonomy" ? systemData.map(topic => <details key={topic.prompt_key}><summary>{topic.prompt_key}</summary>{topic.subcategories.map(item => <article key={item.sub_category}><b>{item.main_category} / {item.sub_category}</b><p>{t("方法論：","Methodology:")} {item.methodology}</p><p>{t("引用：","Citation:")} {item.citation}</p></article>)}</details>) : <div className="case-list">{systemData.map((item, i) => <article key={i}><b>{item.prompt_key}</b><p>{t("輸入：","Input:")} {item.answer_text}</p><p>{t("預期：","Expected:")} {item.expected_sub_category}</p></article>)}</div>}</section>}
  </main></>;
}
