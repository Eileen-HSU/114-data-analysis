import { useEffect, useRef, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
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
  const navigate = useNavigate();
  const { user, isLoggedIn } = useAuth();
  const token = user?.token;
  const canAccess = isLoggedIn && user?.account_type === "admin";

  const [data, setData] = useState({ items: [] });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [rowState, setRowState] = useState({});
  const [targets, setTargets] = useState({}); // topic_key -> [{main_category, sub_category}]
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

  const adopt = (item) => {
    const definition = window.prompt(
      t(`把「${item.sub_category}」加進「${item.topic_title}」的分類架構草稿。\n請輸入這個類別的定義（可留空，之後在分類架構頁再補）：`,
        `Add "${item.sub_category}" to the draft taxonomy of "${item.topic_title}".\nDefinition (optional):`),
      "",
    );
    if (definition === null) return;
    run(item, () => api("/api/admin/ai/new-categories/adopt", token, {
      method: "POST",
      body: JSON.stringify({
        topic_key: item.topic_key, main_category: item.main_category, sub_category: item.sub_category,
        definition: definition.trim() || undefined,
      }),
    }), (r) => t(
      `已加入草稿 v${r.taxonomy_version.version_number}，請到該主題的「分類架構」檢查後發布；這些回答可在審查清單確認。`,
      `Added to draft v${r.taxonomy_version.version_number}. Review and publish it in the topic's Taxonomy tab.`,
    ));
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

  if (!canAccess) {
    return <><Navbar /><main className="ai-admin-empty"><h1>{t("僅管理者可存取 AI 管理介面", "AI admin access restricted to administrators")}</h1><button onClick={() => navigate("/workspace")}>{t("回到分析助理", "Back to Analysis Assistant")}</button></main></>;
  }

  return <><Navbar /><main className="ai-admin-page">
    <NavLink to="/admin/ai" className="back">← {t("所有主題", "All topics")}</NavLink>
    <h1>{t("新類別候選", "New Category Candidates")}</h1>
    <p><small>{t("AI 分類時遇到現有分類都不適合的內容，會提出新類別。採用後會加進該主題的分類架構草稿，發布後類似的回答就會直接歸到這一類；也可以合併到既有類別。",
      "When no existing category fits, the AI proposes a new one. Adopt it into the topic's draft taxonomy, or merge it into an existing category.")}</small></p>
    {error && <p className="ai-admin-error">{error}<button onClick={() => setError("")}>×</button></p>}
    {loading && <LoadingNotice />}
    {!loading && data.items.length === 0 && <p className="review-empty-hint">{t("目前沒有待處理的新類別。", "No new categories waiting.")}</p>}

    {!loading && data.items.map((item) => {
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
            <p><span className="review-field-label">{t("主題", "Topic")}</span>{item.topic_title}</p>
            {item.examples.map((ex, i) => <p key={i}><span className="review-field-label">{t("範例", "Example")}</span>{ex}</p>)}
            {item.reasons[0] && <p><span className="review-field-label">{t("AI 理由", "AI reasoning")}</span>{item.reasons[0]}</p>}
          </div>
          {state.message && <p className={state.message.ok ? "review-batch-message" : "ai-admin-error"}>{state.message.text}</p>}
          <div className="review-card-actions">
            <button className="review-btn-primary" disabled={state.busy} onClick={() => adopt(item)}>{t("採用為新類別", "Adopt as new category")}</button>
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
  </main></>;
}
