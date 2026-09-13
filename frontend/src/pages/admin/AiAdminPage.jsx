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

const statusText = (value) => ({ validated: "已達發布條件", needs_validation: "待驗證", published: "正式使用中", not_published: "尚未發布" }[value] || value);

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
  const canAccess = isLoggedIn && user?.role === "admin";

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

  if (!canAccess) return <><Navbar /><main className="ai-admin-empty"><h1>AI 後台僅限管理員使用</h1><button onClick={() => navigate("/workspace")}>返回分析助理</button></main></>;
  return <><Navbar /><main className="ai-admin-page">
    <header><p className="eyebrow">INTERNAL ADMINISTRATION</p><h1>AI 分類管理後台</h1><p>維護分類邏輯、監督分類品質與管理低頻系統設定。</p></header>
    <nav className="ai-admin-tabs"><button className={tab === "manage" ? "active" : ""} onClick={() => setTab("manage")}>AI 管理</button><button className={tab === "reviews" ? "active" : ""} onClick={() => setTab("reviews")}>AI 分類檢視</button><button className={tab === "system" ? "active" : ""} onClick={() => setTab("system")}>系統管理</button></nav>
    {error && <p className="ai-admin-error">{error}<button onClick={() => setError("")}>×</button></p>}
    {tab === "manage" && <section>
      {!selected ? <div className="topic-grid">{topics.map((topic) => <article key={topic.prompt_key} className="topic-card"><h2>{topic.prompt_key}</h2><p>正式設定：<b>{statusText(topic.production_status)}</b></p><p>Candidate：<b>{statusText(topic.candidate_status)}</b></p><small>最後異動：{topic.updated_at ? new Date(topic.updated_at).toLocaleString() : "—"}</small><div><button onClick={() => openTopic(topic.prompt_key)}>查看設定</button><button className="primary" onClick={() => openTopic(topic.prompt_key)}>繼續修改</button></div></article>)}</div> : <section className="candidate-workspace"><button className="back" onClick={() => setSelected(null)}>← 所有分類主題</button><h2>{selected} Candidate 工作區</h2><div className="stepper">{["edit", "test", "publish"].map((item, i) => <button key={item} className={step === item ? "active" : ""} onClick={() => setStep(item)} disabled={item === "publish" && !(validation?.can_publish || detail?.draft_validated)}>{i + 1}. {item === "edit" ? "Edit" : item === "test" ? "Test" : "Publish"}</button>)}</div>
      {step === "edit" && <div className="admin-card"><details><summary>查看目前正式設定（唯讀）</summary><pre>{detail?.live_content}</pre></details><label>Candidate 內容<textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows="16" /></label><button className="primary" onClick={save}>儲存變更（驗證結果將失效）</button></div>}
      {step === "test" && <div className="admin-card"><h3>Sandbox 快速試跑</h3><textarea value={sandboxText} onChange={(e) => setSandboxText(e.target.value)} placeholder="輸入單筆開放式回答" rows="4" /><button onClick={sandbox}>執行（不寫入正式資料）</button>{sandboxResult && <pre className="result">{JSON.stringify(sandboxResult, null, 2)}</pre>}<hr /><h3>正式驗證：Golden Test Cases</h3><button className="primary" onClick={validate}>執行整組驗證</button>{validation && <><p className={validation.can_publish ? "pass" : "fail"}>{validation.can_publish ? "已達發布條件" : "未達發布條件"} · 格式正確 {validation.format_valid_count}/{validation.total} · Golden 準確率 {(validation.accuracy_vs_golden * 100).toFixed(0)}%</p><div className="case-list">{validation.details.map((item, i) => <p key={i} className={item.is_correct ? "pass" : "fail"}>{item.is_correct ? "✓" : "×"} 預期：{item.expected_sub_category}／結果：{item.actual_sub_category}</p>)}</div></>}</div>}
      {step === "publish" && <div className="admin-card"><h3>發布 Candidate</h3><p>通過驗證的 Candidate 將成為目前正式設定。</p><button className="primary" disabled={!(validation?.can_publish || detail?.draft_validated)} onClick={publish}>發布為正式設定</button></div>}</section>}</section>}
    {tab === "reviews" && <section className="admin-card"><div className="filter-row"><label>分類主題 <select value={reviewTopic} onChange={(e) => { setReviewTopic(e.target.value); loadClassifications(reviewStatus, e.target.value); }}><option value="">全部</option>{topics.map(x => <option key={x.prompt_key} value={x.prompt_key}>{x.prompt_key}</option>)}</select></label><label>review_status <select value={reviewStatus} onChange={(e) => { setReviewStatus(e.target.value); loadClassifications(e.target.value, reviewTopic); }}><option value="">全部</option>{["confirmed", "modified", "pending_review", "excluded"].map(x => <option key={x}>{x}</option>)}</select></label></div>{classifications.map((row) => <article className="review-row" key={row.classification_id}><p><b>{row.review_status}</b> · {row.segment}</p><p>Effective：{row.effective_result.main_category} / {row.effective_result.sub_category}</p>{row.review_status === "modified" && <details><summary>比較 AI Original 與 Human Review Final</summary>{["main_category", "sub_category", "secondary_sub_category", "reasoning"].filter(k => row[k] !== row[`final_${k}`]).map(k => <p key={k}><b>{k}</b><br />AI：{row[k] || "—"}<br />Human：{row[`final_${k}`] || "—"}</p>)}<button onClick={() => navigator.clipboard.writeText(`回答：${row.segment}\nAI：${JSON.stringify({main_category: row.main_category, sub_category: row.sub_category, reasoning: row.reasoning})}\nHuman：${JSON.stringify(row.effective_result)}`)}>複製不一致案例</button></details>}</article>)}</section>}
    {tab === "system" && <section className="admin-card"><div className="subtabs"><button className={systemTab === "taxonomy" ? "active" : ""} onClick={() => setSystemTab("taxonomy")}>分類架構</button><button className={systemTab === "golden" ? "active" : ""} onClick={() => setSystemTab("golden")}>Golden Test Cases</button></div>{systemTab === "taxonomy" ? systemData.map(topic => <details key={topic.prompt_key}><summary>{topic.prompt_key}</summary>{topic.subcategories.map(item => <article key={item.sub_category}><b>{item.main_category} / {item.sub_category}</b><p>Methodology：{item.methodology}</p><p>Citation：{item.citation}</p></article>)}</details>) : <div className="case-list">{systemData.map((item, i) => <article key={i}><b>{item.prompt_key}</b><p>輸入：{item.answer_text}</p><p>Expected：{item.expected_sub_category}</p></article>)}</div>}</section>}
  </main></>;
}
