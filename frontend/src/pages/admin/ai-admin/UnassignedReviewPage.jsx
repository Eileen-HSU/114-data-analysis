import { useEffect, useRef, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import Navbar from "../../../components/feature/Navbar";
import { useAuth } from "../../../hooks/AuthContext";
import { api } from "./shared/apiClient";
import { t } from "./shared/taxStatus";
import { UNASSIGNED_KINDS, errorMessage, unassignedKindLabel, unroutedReasonLabel } from "./shared/reviewStates";
import { FailureNotice, LoadingNotice } from "./shared/StatusWidgets";

const PAGE_SIZE = 30;

// 未分類 / 失敗資料（後端 services/admin_recovery_service.py 定義）：
//   unrouted     ：上傳回答沒有任何分類結果（找不到主題、taxonomy 不可用、routing 失敗…）
//   failed       ：分類失敗（跟「沒有主題」是不同問題，分開處理）
//   legacy_other ：舊流程 question_id = other 的分類結果
// 所有指派 / 重新處理都直接寫入 DB，完成後重新向後端讀取。
export default function UnassignedReviewPage() {
  const navigate = useNavigate();
  const { user, isLoggedIn } = useAuth();
  const token = user?.token;
  const canAccess = isLoggedIn && user?.account_type === "admin";

  const [kind, setKind] = useState("unrouted");
  const [page, setPage] = useState(1);
  const [data, setData] = useState({ items: [], total: 0, counts: {} });
  const [topics, setTopics] = useState([]);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState({});
  const [rowError, setRowError] = useState({});
  const [detail, setDetail] = useState(null);

  const [loading, setLoading] = useState(false);
  const requestSeq = useRef(0);
  // silent：操作（確認 / 排除 / 重新處理）完成後的重新讀取，不清空畫面，
  // 只有切換分頁 / 篩選 / 頁數才顯示「搜尋中」。
  const load = async ({ silent = false } = {}) => {
    const seq = ++requestSeq.current;
    if (!silent) setLoading(true);
    try {
      setError("");
      const result = await api(`/api/admin/ai/unassigned?kind=${kind}&page=${page}&page_size=${PAGE_SIZE}`, token);
      if (seq === requestSeq.current) setData(result);
    } catch (e) {
      if (seq === requestSeq.current) setError(errorMessage(e));
    } finally {
      if (seq === requestSeq.current) setLoading(false);
    }
  };

  useEffect(() => {
    if (!canAccess) return;
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canAccess, kind, page]);

  useEffect(() => {
    if (!canAccess) return;
    api("/api/admin/ai/taxonomy-topics", token)
      .then((res) => setTopics((res.topics || []).filter((tp) => tp.published_version)))
      .catch((e) => setError(errorMessage(e)));
  }, [canAccess, token]);

  const run = async (key, fn, successText) => {
    setBusy((p) => ({ ...p, [key]: true }));
    setRowError((p) => ({ ...p, [key]: "" }));
    setMessage("");
    try {
      const result = await fn();
      setMessage(typeof successText === "function" ? successText(result) : successText);
      await load({ silent: true });
    } catch (e) {
      setRowError((p) => ({ ...p, [key]: errorMessage(e) }));
      await load({ silent: true });
    } finally {
      setBusy((p) => ({ ...p, [key]: false }));
    }
  };

  const resultText = (result) => (result?.succeeded === false
    ? t(`已送出分類，但處理失敗：${result.failure?.message || ""}`, `Classification ran but failed: ${result.failure?.message_en || ""}`)
    : t("已完成分類，結果已進入該主題的審查清單。", "Classified; results are now in the topic's review list."));

  const assign = (item, topicKey, versionId) => run(
    `a${item.id}`,
    () => api(`/api/admin/ai/unassigned/answers/${item.id}/assign`, token, {
      method: "POST", body: JSON.stringify({ topic_key: topicKey, taxonomy_version_id: versionId || undefined }),
    }),
    resultText,
  );

  const reroute = (item) => run(
    `a${item.id}`,
    () => api(`/api/admin/ai/unassigned/answers/${item.id}/reroute`, token, { method: "POST" }),
    (r) => (r.routed ? resultText(r) : t(`仍然判斷不出主題：${unroutedReasonLabel(r.routing_status)}`, `Still no topic: ${unroutedReasonLabel(r.routing_status)}`)),
  );

  const reclassify = (item, topicKey) => run(
    `c${item.classification_id}`,
    () => api(`/api/admin/ai/classifications/${item.classification_id}/${item.kind === "failed" && !topicKey ? "retry" : "reclassify"}`, token, {
      method: "POST", body: JSON.stringify(topicKey ? { topic_key: topicKey } : {}),
    }),
    resultText,
  );

  const openDetail = async (item) => {
    try {
      if (item.kind === "unrouted") {
        setDetail({ title: t("回答處理紀錄", "Answer history"), data: await api(`/api/admin/ai/unassigned/answers/${item.id}`, token) });
      } else {
        setDetail({ title: t("處理嘗試紀錄", "Attempt history"), data: await api(`/api/admin/ai/classifications/${item.classification_id}/attempts`, token) });
      }
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  if (!canAccess) {
    return <><Navbar /><main className="ai-admin-empty"><h1>{t("僅管理者可存取 AI 管理介面", "AI admin access restricted to administrators")}</h1><button onClick={() => navigate("/workspace")}>{t("回到分析助理", "Back to Analysis Assistant")}</button></main></>;
  }

  const totalPages = Math.max(Math.ceil((data.total || 0) / PAGE_SIZE), 1);

  return <><Navbar /><main className="ai-admin-page">
    <NavLink to="/admin/ai" className="back">← {t("所有主題", "All topics")}</NavLink>
    <h1>{t("其他 / 未歸屬資料", "Other / Unassigned Data")}</h1>
    <p><small>{t("系統判斷不出主題、主題沒有可用分類架構、分類失敗，以及舊版「其他」資料都會出現在這裡。可以指派主題、重新判斷主題或重新處理。",
      "Answers without a topic, topics without a usable taxonomy, failed classifications and legacy \"other\" data. Assign a topic, re-route or reprocess.")}</small></p>
    {error && <p className="ai-admin-error">{error}<button onClick={() => setError("")}>×</button></p>}
    {message && <p className="review-batch-message">{message}</p>}

    <div className="review-tabs" role="tablist">
      {UNASSIGNED_KINDS.map((k) => (
        <button key={k} role="tab" aria-selected={kind === k} className={`review-tab${kind === k ? " review-tab--active" : ""}`}
          onClick={() => { setKind(k); setPage(1); setMessage(""); }}>
          {unassignedKindLabel(k)}<span className="review-tab-count">{data.counts?.[k] ?? 0}</span>
        </button>
      ))}
    </div>

    {loading && <LoadingNotice />}

    {!loading && data.items.length === 0 && <p className="review-empty-hint">{t("這個分類底下目前沒有資料。", "Nothing here right now.")}</p>}

    {!loading && data.items.map((item) => {
      const key = item.kind === "unrouted" ? `a${item.id}` : `c${item.classification_id}`;
      return (
        <UnassignedCard key={key} item={item} topics={topics} busy={!!busy[key]} error={rowError[key]}
          onDismissError={() => setRowError((p) => ({ ...p, [key]: "" }))}
          onAssign={(topicKey, versionId) => assign(item, topicKey, versionId)}
          onReroute={() => reroute(item)}
          onReclassify={(topicKey) => reclassify(item, topicKey)}
          onDetail={() => openDetail(item)} />
      );
    })}

    {data.total > PAGE_SIZE && (
      <div className="review-pagination">
        <button type="button" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>{t("上一頁", "Previous")}</button>
        <span>{t(`第 ${page} / ${totalPages} 頁（共 ${data.total} 筆）`, `Page ${page} / ${totalPages} (${data.total} total)`)}</span>
        <button type="button" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>{t("下一頁", "Next")}</button>
      </div>
    )}

    {detail && (
      <section className="review-card">
        <div className="review-card-top"><b>{detail.title}</b><button onClick={() => setDetail(null)}>×</button></div>
        {(detail.data.audit || []).length === 0 && <p><small>{t("尚無操作紀錄", "No actions yet")}</small></p>}
        <ul>
          {(detail.data.audit || []).map((a) => (
            <li key={a.audit_id}><small>{a.created_at} — {a.action}（Admin #{a.admin_id ?? "system"}）{a.reason ? `：${a.reason}` : ""}</small></li>
          ))}
        </ul>
        {(detail.data.attempts || detail.data.classifications || []).map((c) => (
          <p key={c.classification_id}><small>#{c.classification_id} {c.status} / {c.review_status} — {c.main_category || "—"} / {c.sub_category || "—"}</small></p>
        ))}
      </section>
    )}
  </main></>;
}

function UnassignedCard({ item, topics, busy, error, onDismissError, onAssign, onReroute, onReclassify, onDetail }) {
  const [topicKey, setTopicKey] = useState("");
  const selectedTopic = topics.find((tp) => tp.topic_key === topicKey);

  return (
    <article className="review-card">
      <div className="review-card-top">
        <b className={`review-status-tag review-status-tag--${item.kind === "failed" ? "failed" : "pending_review"}`}>
          {unassignedKindLabel(item.kind)}
        </b>
        <span className="review-card-segment">{item.kind === "unrouted" ? item.answer_text : item.segment}</span>
      </div>
      <div className="review-card-mid">
        <p><span className="review-field-label">{t("原因", "Reason")}</span>
          {item.kind === "failed" ? t("分類處理失敗", "Classification failed") : unroutedReasonLabel(item.reason)}</p>
        {item.failure && <FailureNotice failure={item.failure} />}
        <p><span className="review-field-label">{t("處理狀態", "Processing status")}</span>{item.processing_status}</p>
        {item.source_column && <p><span className="review-field-label">{t("來源欄位", "Source column")}</span>{item.source_column}（{t("第", "row ")}{(item.row_index ?? 0) + 1}{t(" 列", "")}）</p>}
      </div>
      {error && <p className="ai-admin-error">{error}<button onClick={onDismissError}>×</button></p>}
      <div className="review-card-actions">
        <select value={topicKey} disabled={busy} onChange={(e) => setTopicKey(e.target.value)}>
          <option value="">{item.kind === "failed" ? t("沿用原主題", "Keep original topic") : t("選擇主題…", "Choose a topic…")}</option>
          {topics.map((tp) => <option key={tp.topic_key} value={tp.topic_key}>{tp.title}</option>)}
        </select>
        {selectedTopic && <small>{t("使用已發布版本", "Uses published version")} v{selectedTopic.published_version.version_number}</small>}
        {item.kind === "unrouted" && (
          <>
            <button className="review-btn-primary" disabled={busy || !topicKey} onClick={() => onAssign(topicKey, selectedTopic?.published_version?.version_id)}>
              {busy ? t("處理中…", "Working…") : t("指派主題並分類", "Assign & classify")}
            </button>
            <button disabled={busy} onClick={onReroute}>{t("重新判斷主題", "Re-route")}</button>
          </>
        )}
        {item.kind === "failed" && (
          <button className="review-btn-primary" disabled={busy} onClick={() => onReclassify(topicKey || null)}>
            {busy ? t("處理中…", "Working…") : t("重新處理", "Retry")}
          </button>
        )}
        {item.kind === "legacy_other" && (
          <button className="review-btn-primary" disabled={busy || !topicKey} onClick={() => onReclassify(topicKey)}>
            {busy ? t("處理中…", "Working…") : t("指派主題並重新分類", "Assign topic & re-classify")}
          </button>
        )}
        <button disabled={busy} onClick={onDetail}>{t("查看紀錄", "History")}</button>
      </div>
    </article>
  );
}
