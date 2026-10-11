import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTextPrompt } from "./TextPromptDialog";
import { api, peekCache } from "./apiClient";
import { t, reviewFlagReasonText } from "./taxStatus";
import { AUTO_CONFIRMED_LABEL, STATE_TABS, errorMessage, isAutoConfirmed, stateLabel } from "./reviewStates";
import { FailureNotice, SkeletonCards } from "./StatusWidgets";
import { useAuth } from "../../../../hooks/AuthContext";

const HIGH_CONFIDENCE_THRESHOLD = 0.9;
const PAGE_SIZE = 50;

const newBatchId = () => (
  typeof crypto !== "undefined" && crypto.randomUUID
    ? crypto.randomUUID().replace(/-/g, "")
    : `${Date.now()}${Math.random().toString(16).slice(2)}`
);

// 分頁、計數、篩選全部由後端處理（GET /api/admin/ai/classifications 回傳
// total / status_counts），畫面上的數字永遠是「全部符合條件的資料」，不是
// 目前頁面。所有操作成功後都重新向後端讀取，不在前端假裝修改 state。
// 篩選條件（state / source / queue / topic）以網址為唯一來源，由父層傳入；
// 本元件只負責依這些值讀取資料，網址變動（返回、首頁連結）會立即反映。
export default function ClassificationList({
  topicParam, onOpenReview, refreshSignal, tab, source, onFilterChange, queue = "human",
}) {
  const [promptDialog, askText] = useTextPrompt();
  const { user } = useAuth();
  const token = user?.token;
  const navigate = useNavigate();

  const activeTab = STATE_TABS.includes(tab) ? tab : "pending_review";
  // 「已確認」分頁的篩選：all / auto（只看自動通過，抽查用）/ human（只看人工確認）
  const confirmedSource = ["all", "auto", "human"].includes(source) ? source : "all";
  // 頁數綁定在「篩選組合」上：篩選一變，頁數自動回到第 1 頁，
  // 不會先用舊頁數發出一次多餘的請求。
  const filterKey = [topicParam || "", activeTab, confirmedSource, activeTab === "pending_review" ? queue : ""].join("|");
  const [pageState, setPageState] = useState({ key: filterKey, page: 1 });
  const page = pageState.key === filterKey ? pageState.page : 1;
  const setPage = (next) => setPageState((prev) => {
    const current = prev.key === filterKey ? prev.page : 1;
    return { key: filterKey, page: typeof next === "function" ? next(current) : next };
  });
  const buildUrl = () => {
    const params = new URLSearchParams({ state: activeTab, page: String(page), page_size: String(PAGE_SIZE) });
    if (topicParam) params.set("topic", topicParam);
    // 待審只留需要人工逐筆處理的；系統自動處理中（等 AI 再確認、等自動通過）、新類別群組不列在這裡
    if (activeTab === "pending_review") params.set("queue", queue);
    if (activeTab === "confirmed" && confirmedSource !== "all") {
      params.set("auto_confirmed", confirmedSource === "auto" ? "true" : "false");
    }
    return `/api/admin/ai/classifications?${params}`;
  };
  const listUrl = buildUrl();
  const EMPTY = { classifications: [], total: 0, total_pages: 0, status_counts: {} };
  // 抓過的就先顯示；沒抓過的一開始就是「載入中」，不會先閃出「沒有資料」
  const [data, setData] = useState(() => peekCache(listUrl) || EMPTY);
  const [loading, setLoading] = useState(() => !peekCache(listUrl));
  const [error, setError] = useState("");

  const [rowBusy, setRowBusy] = useState({});
  const [rowError, setRowError] = useState({});

  const [selectedIds, setSelectedIds] = useState(() => new Set());
  const [batchBusy, setBatchBusy] = useState(false);
  const [batchMessage, setBatchMessage] = useState("");
  const [batchWarn, setBatchWarn] = useState(false); // 部分成功／失敗：用警示色，不要像全部成功

  // 每次載入都有編號，只採用最後一次請求的結果：快速切換分頁時，較慢回來
  // 的舊請求不會蓋掉新分頁的資料。
  const requestSeq = useRef(0);
  // silent：操作（確認 / 排除 / 重新處理）完成後的重新讀取，不清空畫面，
  // 只有切換分頁 / 篩選 / 頁數才顯示「搜尋中」。
  const load = async ({ silent = false } = {}) => {
    const seq = ++requestSeq.current;
    const url = listUrl;
    const cached = peekCache(url);
    // 切換篩選時一律先換掉畫面：有快取就顯示快取（背景更新），沒有就清空並顯示載入中，
    // 避免短暫顯示上一個篩選的舊資料。
    if (!silent) setData(cached || EMPTY);
    if (!silent) setLoading(!cached);
    try {
      setError("");
      const result = await api(url, token);
      if (seq === requestSeq.current) setData(result);
    } catch (e) {
      if (seq === requestSeq.current) setError(errorMessage(e));
    } finally {
      if (seq === requestSeq.current) setLoading(false);
    }
  };

  // listUrl 已包含 topic / state / source / queue / 頁數，任何一項變動都會重新讀取；
  // refreshSignal 用於審核對話完成後的重新整理（背景更新，不清空畫面）。
  const lastUrl = useRef(listUrl);
  useEffect(() => {
    const silent = lastUrl.current === listUrl && refreshSignal > 0;
    lastUrl.current = listUrl;
    load({ silent });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [listUrl, refreshSignal]);

  // 切換 topic / tab / 篩選 / 頁數時不保留上一個畫面的勾選：批次操作
  // 的對象永遠是「目前這一頁、使用者看得到並勾選的那些列」。
  useEffect(() => {
    setSelectedIds(new Set());
    setBatchMessage("");
    setBatchWarn(false);
    setRowError({});
  }, [listUrl]);

  const rows = data.classifications || [];
  const counts = data.status_counts || {};
  // 只有一般待處理的項目可以勾選批次確認；後端也會逐筆拒絕其他的：
  //   - in_review：有人正在審核
  //   - needs_human_review：低信心、分類不完整等需要人看的，要逐筆確認
  //   - AI 新類別：要到「新類別候選」加入、合併或排除
  const selectableRows = useMemo(() => rows.filter((row) => (
    row.review_state === "pending_review" && !row.needs_human_review && row.status !== "new_category"
  )), [rows]);
  const highConfidenceRows = useMemo(
    () => selectableRows.filter((row) => typeof row.confidence === "number" && row.confidence >= HIGH_CONFIDENCE_THRESHOLD && !row.needs_human_review),
    [selectableRows],
  );
  const selectedCount = selectedIds.size;

  const toggleSelected = (id) => setSelectedIds((prev) => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  // 開啟逐筆審核時，一併交出「本頁接下來還需要處理的項目」，審完可直接接著處理下一筆。
  // 只包含一般待處理的項目（不含正在被審核、AI 新類別）。順序：目前這筆之後，
  // 再接本頁前面還沒處理的，不會漏掉。
  const nextQueueAfter = (id) => {
    const index = rows.findIndex((row) => row.classification_id === id);
    return [...rows.slice(index + 1), ...rows.slice(0, Math.max(index, 0))]
      .filter((row) => row.review_state === "pending_review" && row.status !== "new_category")
      .map((row) => row.classification_id);
  };

  const withRow = async (id, fn) => {
    setRowBusy((p) => ({ ...p, [id]: true }));
    setRowError((p) => ({ ...p, [id]: "" }));
    try {
      await fn();
      await load({ silent: true });
    } catch (e) {
      setRowError((p) => ({ ...p, [id]: errorMessage(e) }));
    } finally {
      setRowBusy((p) => ({ ...p, [id]: false }));
    }
  };

  // 兩次 AI 判斷不一致時，一鍵採用第二意見（等同手動指定那個類別）
  const adoptSecondOpinion = (row) => withRow(row.classification_id, () => api(
    `/api/classification/${row.classification_id}/review/confirm-manual`, token, {
      method: "POST",
      body: JSON.stringify({
        sub_category: row.second_opinion_sub_category,
        reasoning: `採用 AI 第二意見：${row.second_opinion_reasoning || ""}`.trim(),
      }),
    },
  ));

  const reopen = async (row) => {
    const reason = await askText({
      title: t(`重新開啟這筆「${stateLabel(row.review_status)}」的審核`, `Reopen this ${stateLabel(row.review_status)} item`),
      message: t("它會回到待處理，既有審核歷史保留。原本是「已修改」或「已排除」的話，使用過這筆結果的報表會被標記為需要更新。",
        "It returns to Pending and history is kept. If it was modified or excluded, affected reports are marked outdated."),
      placeholder: t("重新開啟的原因（可留空）", "Reason (optional)"),
      confirmLabel: t("重新開啟", "Reopen"),
      rows: 3,
    });
    if (reason === null) return;
    withRow(row.classification_id, async () => {
      await api(`/api/classification/${row.classification_id}/review/reopen`, token, {
        method: "POST", body: JSON.stringify({ reason: reason.trim() || undefined }),
      });
      if (onOpenReview) onOpenReview(row.classification_id, "start");
    });
  };

  const retry = (row) => withRow(row.classification_id, async () => {
    const result = await api(`/api/admin/ai/classifications/${row.classification_id}/retry`, token, { method: "POST" });
    setBatchWarn(!result.succeeded);
    setBatchMessage(result.succeeded
      ? t("已重新處理，新的分類結果在「待處理」。", "Reprocessed; the new result is under Pending.")
      : t(`重新處理仍然失敗${result.kept_previous ? "，原本的結果維持不變" : ""}：${result.failure?.message || ""}`,
        `Retry still failed${result.kept_previous ? "; the previous result was kept" : ""}: ${result.failure?.message_en || ""}`));
  });

  const runBatchConfirm = async () => {
    if (selectedCount === 0 || batchBusy) return;
    if (!window.confirm(t(
      `確定要一次維持這 ${selectedCount} 筆 AI 分類嗎？（只會處理目前頁面勾選的項目）`,
      `Keep the AI classification for the ${selectedCount} selected items on this page?`,
    ))) return;
    setBatchBusy(true);
    setBatchMessage("");
    setBatchWarn(false);
    setRowError({});
    try {
      const result = await api("/api/classification/review/batch-confirm", token, {
        method: "POST",
        body: JSON.stringify({ classification_ids: [...selectedIds], batch_id: newBatchId() }),
      });
      const skipped = result.skipped || [];
      setRowError(Object.fromEntries(skipped.map((s) => [s.classification_id, s.message])));
      setBatchWarn(skipped.length > 0);
      setBatchMessage(skipped.length
        ? t(`已確認 ${result.confirmed_count} 筆，${skipped.length} 筆未處理（原因標示在各項目上）。`,
          `${result.confirmed_count} confirmed, ${skipped.length} skipped (reasons shown on each item).`)
        : t(`已成功確認 ${result.confirmed_count} 筆分類。`, `${result.confirmed_count} classifications confirmed.`));
      setSelectedIds(new Set(skipped.map((s) => s.classification_id)));
      await load({ silent: true });
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBatchBusy(false);
    }
  };

  const totalPages = Math.max(data.total_pages || 0, 1);
  // 處理完後後面的頁數可能消失：頁數超出範圍時退回最後一頁，不要顯示空白的「沒有資料」。
  useEffect(() => {
    if (!loading && page > totalPages) setPage(totalPages);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading, page, totalPages]);

  return (
    <div className="review-workbench">{promptDialog}
      {error && <p className="ai-admin-error">{error}<button onClick={() => setError("")}>×</button></p>}

      <p className="review-workbench-intro">
        {t("這裡只列需要人看的項目；AI 有把握的結果已自動通過，可在「已確認」分頁抽查。",
          "Only items that need a person are listed; confident results are auto-approved (spot-check them under Confirmed).")}
      </p>

      <div className="review-tabs" role="tablist">
        {STATE_TABS.map((state) => (
          <button key={state} role="tab" aria-selected={activeTab === state}
            className={`review-tab${activeTab === state ? " review-tab--active" : ""}`}
            onClick={() => onFilterChange?.({ state, source: state === "confirmed" ? confirmedSource : "all" })}>
            {stateLabel(state)}
            <span className="review-tab-count">{counts[state] ?? 0}</span>
          </button>
        ))}
      </div>
      {activeTab === "pending_review" && (counts.in_review ?? 0) > 0 && (
        <p className="review-secondary-filter"><small>{t(`其中 ${counts.in_review} 筆正在審核中`, `${counts.in_review} of these are currently in review`)}</small></p>
      )}

      {activeTab === "confirmed" && (
        <div className="review-tabs review-tabs--sub" role="tablist" aria-label={t("確認方式", "Approved by")}>
          {[
            ["all", t("全部", "All")],
            ["auto", `${AUTO_CONFIRMED_LABEL()} (${data.auto_confirmed_count ?? 0})`],
            ["human", t("人工確認", "Confirmed by admin")],
          ].map(([key, label]) => (
            <button key={key} role="tab" aria-selected={confirmedSource === key}
              className={`review-tab${confirmedSource === key ? " review-tab--active" : ""}`}
              onClick={() => onFilterChange?.({ state: "confirmed", source: key })}>
              {label}
            </button>
          ))}
        </div>
      )}


      {activeTab === "pending_review" && (
        <div className="review-batch-bar">
          <div className="review-batch-selection">
            <b>{t(`已選 ${selectedCount} 筆`, `${selectedCount} selected`)}</b>
            <span>{t(`本頁 ${rows.length} 筆／共 ${data.total} 筆`, `${rows.length} on this page / ${data.total} total`)}</span>
          </div>
          <div className="review-batch-actions">
            <button type="button" disabled={batchBusy} onClick={() => setSelectedIds(new Set(selectableRows.map((r) => r.classification_id)))}>
              {t("全選本頁", "Select this page")}
            </button>
            <button type="button" disabled={batchBusy || highConfidenceRows.length === 0}
              onClick={() => setSelectedIds(new Set(highConfidenceRows.map((r) => r.classification_id)))}
              title={t(`選取本頁信心分數 ≥ ${HIGH_CONFIDENCE_THRESHOLD.toFixed(1)} 且不需人工審核的項目`, `Select items on this page with confidence ≥ ${HIGH_CONFIDENCE_THRESHOLD.toFixed(1)}`)}>
              {t(`選取高信心 (${highConfidenceRows.length})`, `Select high-confidence (${highConfidenceRows.length})`)}
            </button>
            <button type="button" disabled={batchBusy || selectedCount === 0} onClick={() => setSelectedIds(new Set())}>
              {t("清除選取", "Clear")}
            </button>
            <button type="button" className="review-btn-primary" disabled={batchBusy || selectedCount === 0} onClick={runBatchConfirm}>
              {batchBusy ? t("批次處理中…", "Processing…") : t(`批次維持 AI 分類 (${selectedCount})`, `Keep AI classification (${selectedCount})`)}
            </button>
          </div>
        </div>
      )}

      {batchMessage && <p className={`review-batch-message${batchWarn ? " review-batch-message--warn" : ""}`} role="status">{batchMessage}</p>}

      {loading && <SkeletonCards />}

      {!loading && rows.length === 0 && (
        <p className="review-empty-hint">
          {activeTab === "pending_review" ? t("目前沒有待處理的分類結果。", "Nothing pending right now.")
            : t("這個狀態底下目前沒有符合條件的分類結果。", "No matching classifications under this status.")}
        </p>
      )}

      {!loading && rows.map((row) => (
        <ClassificationCard
          key={row.classification_id}
          row={row}
          selectable={selectableRows.some((r) => r.classification_id === row.classification_id)}
          selected={selectedIds.has(row.classification_id)}
          onToggleSelected={() => toggleSelected(row.classification_id)}
          busy={Boolean(rowBusy[row.classification_id]) || batchBusy}
          error={rowError[row.classification_id]}
          onDismissError={() => setRowError((p) => ({ ...p, [row.classification_id]: "" }))}
          onAcceptOriginal={() => withRow(row.classification_id, () => api(`/api/classification/${row.classification_id}/review/confirm-original`, token, { method: "POST" }))}
          onExclude={() => {
            if (!window.confirm(t("確定不納入分析？這筆不會進入統計與報表，之後可在「已排除」重新開啟。", "Exclude from analysis? It is left out of statistics and reports; you can reopen it under Excluded."))) return;
            withRow(row.classification_id, () => api(`/api/classification/${row.classification_id}/review/exclude`, token, { method: "POST" }));
          }}
          onStartReview={onOpenReview ? () => onOpenReview(row.classification_id, "start", { queue: nextQueueAfter(row.classification_id) }) : null}
          onViewHistory={onOpenReview ? () => onOpenReview(row.classification_id, "view") : null}
          onReopen={() => reopen(row)}
          onRetry={() => retry(row)}
          onOpenNewCategories={() => navigate("/admin/ai/taxonomy?view=candidates")}
          onAdoptSecondOpinion={() => adoptSecondOpinion(row)}
        />
      ))}

      {data.total > PAGE_SIZE && (
        <div className="review-pagination">
          <button type="button" disabled={page <= 1 || loading} onClick={() => setPage((p) => p - 1)}>{t("上一頁", "Previous")}</button>
          <span>{t(`第 ${page} / ${totalPages} 頁（共 ${data.total} 筆）`, `Page ${page} / ${totalPages} (${data.total} total)`)}</span>
          <button type="button" disabled={page >= totalPages || loading} onClick={() => setPage((p) => p + 1)}>{t("下一頁", "Next")}</button>
        </div>
      )}
    </div>
  );
}

function ClassificationCard({
  row, selectable, selected, onToggleSelected, busy, error, onDismissError,
  onAcceptOriginal, onExclude, onStartReview, onViewHistory, onReopen, onRetry, onOpenNewCategories,
  onAdoptSecondOpinion,
}) {
  const auto = isAutoConfirmed(row);
  // 自動通過的結果在畫面上當成獨立狀態：顯示 AI 判斷與信心分數，
  // 並可直接確認、重新審核或排除（後端不需要先重新開啟）。
  const state = auto ? "auto_confirmed" : (row.review_state || row.review_status);
  const effective = row.effective_result;
  const isPendingLike = state === "pending_review" || state === "in_review";
  const showsAiResult = isPendingLike || state === "auto_confirmed";
  const isNewCategory = row.status === "new_category";
  const aiDisagreed = row.second_opinion_status === "disagreed";

  return (
    <article className={`review-card${selected ? " review-card--selected" : ""}`}>
      <div className="review-card-top">
        {selectable && (
          <label className="review-card-select" title={t("選取這筆分類", "Select this classification")}>
            <input type="checkbox" checked={selected} disabled={busy} onChange={onToggleSelected} />
            <span className="sr-only">{t("選取這筆分類", "Select this classification")}</span>
          </label>
        )}
        <b className={`review-status-tag review-status-tag--${state}`}>{auto ? AUTO_CONFIRMED_LABEL() : stateLabel(state)}</b>
        <span className="review-card-segment">{row.segment}</span>
      </div>

      {state === "in_review" && row.active_review && (
        <p className="review-flag-badge">
          {t(`${row.active_review.admin_name || `Admin #${row.active_review.admin_id}`} 審核中`, `In review by ${row.active_review.admin_name || `Admin #${row.active_review.admin_id}`}`)}
        </p>
      )}

      {state === "failed" && (
        <div className="review-card-mid">
          <span className="review-field-label">{t("失敗原因", "Failure")}</span>
          <FailureNotice failure={row.failure} fallback={t("未提供錯誤訊息", "No error detail")} />
        </div>
      )}

      {showsAiResult && (
        <div className="review-card-mid">
          <p className="review-ai-line">
            <span className="review-field-label">{t("AI 判斷", "AI result")}</span>
            <b>{row.main_category || "—"} / {row.sub_category || "—"}</b>
            <span className="review-confidence-chip">{t("信心", "Conf.")} {typeof row.confidence === "number" ? row.confidence.toFixed(2) : "—"}</span>
          </p>
          {row.needs_human_review && (
            <p className="review-flag-badge">⚠ {t("待審原因", "Why pending")}：{row.review_flag_reason ? reviewFlagReasonText(row.review_flag_reason) : t("需人工審核", "Needs human review")}</p>
          )}
          {auto && (
            <p><small>{row.second_opinion_status === "agreed"
              ? t("第一次 AI 沒有把握，但更強的模型再判斷一次結果相同，系統已自動通過。有疑問可以重新審核。",
                "The first pass was unsure, but a stronger model independently reached the same answer, so it was approved automatically. Re-review it if in doubt.")
              : t("AI 有把握且類別在分類架構內，系統已自動通過。看起來正確可以按「確認無誤」；有疑問就重新審核。",
                "The AI was confident and the category is in the taxonomy, so it was approved automatically. Confirm it if it looks right, or re-review it.")}</small></p>
          )}
          {aiDisagreed && (
            <div className="review-second-opinion">
              <p><span className="review-field-label">{t("AI 第二意見", "AI second opinion")}</span>
                {row.second_opinion_sub_category
                  ? `${row.second_opinion_main_category} / ${row.second_opinion_sub_category}`
                  : t("認為清單裡的類別都不適合", "None of the categories fit")}</p>
              {row.second_opinion_reasoning && <p><small>{row.second_opinion_reasoning}</small></p>}
            </div>
          )}
        </div>
      )}

      {state === "confirmed" && effective && (
        <div className="review-card-mid">
          <p><span className="review-field-label">{t("最終結果", "Final result")}</span>{effective.main_category} / {effective.sub_category}</p>
        </div>
      )}

      {state === "modified" && (
        <div className="review-card-mid">
          <p><span className="review-field-label">{t("AI 原始", "AI original")}</span>{row.main_category} / {row.sub_category}</p>
          {effective && <p><span className="review-field-label">{t("最終結果", "Final result")}</span>{effective.main_category} / {effective.sub_category}</p>}
        </div>
      )}

      {state === "excluded" && (
        <div className="review-card-mid">
          <p><span className="review-field-label">{t("AI 原始", "AI original")}</span>{row.main_category || "—"} / {row.sub_category || "—"}</p>
          <p><small>{t("不納入任何統計、報表與匯出。", "Not included in any statistics, reports or exports.")}</small></p>
        </div>
      )}

      {error && <p className="ai-admin-error">{error}<button onClick={onDismissError}>×</button></p>}

      <div className="review-card-actions">
        {isPendingLike && isNewCategory && (
          <>
            <button className="review-btn-primary" disabled={busy} onClick={onOpenNewCategories}>{t("到新類別候選處理", "Open New Category Candidates")}</button>
            {onStartReview && <button disabled={busy} onClick={onStartReview}>{state === "in_review" ? t("繼續審核", "Continue review") : t("改成既有類別", "Assign an existing category")}</button>}
            <button disabled={busy} className="review-btn-danger" onClick={onExclude}>{t("不納入分析", "Exclude from analysis")}</button>
          </>
        )}
        {state === "auto_confirmed" && (
          <>
            <button className="review-btn-primary" disabled={busy} onClick={onAcceptOriginal}>{t("確認無誤", "Confirm")}</button>
            {onStartReview && <button disabled={busy} onClick={onStartReview}>{t("重新審核", "Re-review")}</button>}
            <button disabled={busy} className="review-btn-danger" onClick={onExclude}>{t("不納入分析", "Exclude from analysis")}</button>
          </>
        )}
        {isPendingLike && !isNewCategory && (
          <>
            {aiDisagreed && row.second_opinion_sub_category && (
              <button className="review-btn-primary" disabled={busy} onClick={onAdoptSecondOpinion}>
                {t("採用第二意見", "Use second opinion")}
              </button>
            )}
            <button className={aiDisagreed ? "" : "review-btn-primary"} disabled={busy} onClick={onAcceptOriginal}>
              {aiDisagreed ? t("維持第一次的分類", "Keep first classification") : t("維持 AI 分類", "Keep AI classification")}
            </button>
            {onStartReview && <button disabled={busy} onClick={onStartReview}>{state === "in_review" ? t("繼續審核", "Continue review") : t("審核／修改", "Review / modify")}</button>}
            <button disabled={busy} className="review-btn-danger" onClick={onExclude}>{t("不納入分析", "Exclude from analysis")}</button>
          </>
        )}
        {state === "failed" && (
          <>
            <button className="review-btn-primary" disabled={busy} onClick={onRetry}>{t("重新處理", "Retry")}</button>
            <button disabled={busy} className="review-btn-danger" onClick={onExclude}>{t("不納入分析", "Exclude from analysis")}</button>
          </>
        )}
        {["confirmed", "modified", "excluded"].includes(state) && (
          <>
            {onViewHistory && <button disabled={busy} onClick={onViewHistory}>{t("查看審核紀錄", "View review history")}</button>}
            <button disabled={busy} className="review-btn-reopen" onClick={onReopen}>{t("重新開啟審核", "Reopen review")}</button>
          </>
        )}
      </div>
    </article>
  );
}
