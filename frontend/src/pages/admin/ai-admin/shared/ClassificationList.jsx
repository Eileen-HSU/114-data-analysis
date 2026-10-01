import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "./apiClient";
import { t, reviewFlagReasonText } from "./taxStatus";
import { AUTO_CONFIRMED_LABEL, STATE_TABS, errorMessage, isAutoConfirmed, stateLabel } from "./reviewStates";
import { FailureNotice, LoadingNotice } from "./StatusWidgets";
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
export default function ClassificationList({
  topicParam, onOpenReview, refreshSignal, initialTab, initialConfirmedSource, initialNeedsReviewOnly = false,
}) {
  const { user } = useAuth();
  const token = user?.token;
  const navigate = useNavigate();

  const [activeTab, setActiveTab] = useState(STATE_TABS.includes(initialTab) ? initialTab : "pending_review");
  const [needsReviewOnly, setNeedsReviewOnly] = useState(Boolean(initialNeedsReviewOnly));
  // 「已確認」分頁的篩選：all / auto（只看自動通過，抽查用）/ human（只看人工確認）
  const [confirmedSource, setConfirmedSource] = useState(
    ["all", "auto", "human"].includes(initialConfirmedSource) ? initialConfirmedSource : "all",
  );
  const [backfillBusy, setBackfillBusy] = useState(false);
  const [page, setPage] = useState(1);
  const [data, setData] = useState({ classifications: [], total: 0, total_pages: 0, status_counts: {} });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const [rowBusy, setRowBusy] = useState({});
  const [rowError, setRowError] = useState({});

  const [selectedIds, setSelectedIds] = useState(() => new Set());
  const [batchBusy, setBatchBusy] = useState(false);
  const [batchMessage, setBatchMessage] = useState("");
  const [excludeLegacyBusy, setExcludeLegacyBusy] = useState(false);

  // 每次載入都有編號，只採用最後一次請求的結果：快速切換分頁時，較慢回來
  // 的舊請求不會蓋掉新分頁的資料。
  const requestSeq = useRef(0);
  // silent：操作（確認 / 排除 / 重新處理）完成後的重新讀取，不清空畫面，
  // 只有切換分頁 / 篩選 / 頁數才顯示「搜尋中」。
  const load = async ({ silent = false } = {}) => {
    const seq = ++requestSeq.current;
    if (!silent) setLoading(true);
    try {
      setError("");
      const params = new URLSearchParams({ state: activeTab, page: String(page), page_size: String(PAGE_SIZE) });
      if (topicParam) params.set("topic", topicParam);
      if (needsReviewOnly) params.set("needs_human_review", "true");
      if (activeTab === "confirmed" && confirmedSource !== "all") {
        params.set("auto_confirmed", confirmedSource === "auto" ? "true" : "false");
      }
      const result = await api(`/api/admin/ai/classifications?${params}`, token);
      if (seq === requestSeq.current) setData(result);
    } catch (e) {
      if (seq === requestSeq.current) setError(errorMessage(e));
    } finally {
      if (seq === requestSeq.current) setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [topicParam, refreshSignal, activeTab, needsReviewOnly, confirmedSource, page]);

  // 切換 topic / tab / 篩選 / 頁數時不保留上一個畫面的勾選：批次操作
  // 的對象永遠是「目前這一頁、使用者看得到並勾選的那些列」。
  useEffect(() => {
    setSelectedIds(new Set());
    setBatchMessage("");
  }, [topicParam, activeTab, needsReviewOnly, confirmedSource, page]);

  useEffect(() => { setPage(1); }, [topicParam]);

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

  const reopen = (row) => {
    const reason = window.prompt(
      t(
        `確定要重新開啟這筆「${stateLabel(row.review_status)}」分類的審核嗎？\n它會回到待處理，既有審核歷史保留；使用過這筆結果的報表會被標記為需要更新。\n\n請輸入重新開啟的原因：`,
        `Reopen this ${stateLabel(row.review_status)} classification? It returns to Pending, history is kept, and affected reports are marked outdated.\n\nReason:`,
      ),
      "",
    );
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
    setRowError({});
    try {
      const result = await api("/api/classification/review/batch-confirm", token, {
        method: "POST",
        body: JSON.stringify({ classification_ids: [...selectedIds], batch_id: newBatchId() }),
      });
      const skipped = result.skipped || [];
      setRowError(Object.fromEntries(skipped.map((s) => [s.classification_id, s.message])));
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

  const runExcludeLegacy = async () => {
    if (excludeLegacyBusy) return;
    setExcludeLegacyBusy(true);
    setBatchMessage("");
    setError("");
    try {
      const preview = await api("/api/classification/review/exclude-legacy/preview", token);
      if (preview.eligible_count === 0) {
        setBatchMessage(t("沒有符合條件的舊版資料。", "No eligible legacy data."));
        return;
      }
      const reasons = (preview.skipped_reasons || []).map((r) => `  • ${r.message}：${r.count}`).join("\n");
      if (!window.confirm(t(
        `將排除 ${preview.eligible_count} 筆舊版分類資料（沒有信心分數、沒有 taxonomy 版本、從未人工處理）。\n略過 ${preview.skipped_count} 筆：\n${reasons || "  （無）"}\n\n原始紀錄會保留，但不再納入分析。是否繼續？`,
        `Exclude ${preview.eligible_count} legacy classifications.\nSkipped ${preview.skipped_count}:\n${reasons || "  (none)"}\n\nRecords are kept but no longer analysed. Continue?`,
      ))) return;
      const result = await api("/api/classification/review/exclude-legacy", token, {
        method: "POST",
        body: JSON.stringify({ batch_id: newBatchId(), expected_ids: preview.eligible_ids }),
      });
      setBatchMessage(t(
        `已排除 ${result.affected_count} 筆舊版資料（批次 ${result.batch_id.slice(0, 8)}）`,
        `Excluded ${result.affected_count} legacy classification(s) (batch ${result.batch_id.slice(0, 8)})`,
      ));
      await load({ silent: true });
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setExcludeLegacyBusy(false);
    }
  };

  // 自動通過上線前就分析好的資料：先預覽筆數，確認後才寫入。
  const runAutoConfirmBackfill = async () => {
    if (backfillBusy) return;
    setBackfillBusy(true);
    setBatchMessage("");
    setError("");
    try {
      const preview = await api("/api/admin/ai/classifications/auto-confirm", token, {
        method: "POST", body: JSON.stringify({ dry_run: true }),
      });
      if (preview.eligible_count === 0) {
        setBatchMessage(t("沒有符合自動通過條件的待處理資料。", "No pending items meet the auto-approval rules."));
        return;
      }
      if (!window.confirm(t(
        `有 ${preview.eligible_count} 筆待處理的結果符合自動通過條件（信心 ≥ 0.75、類別在已發布的分類架構內、沒有需要人工判斷的問題）。\n\n要把它們改成「自動通過」嗎？之後仍可在「已確認 › 自動通過」重新審核。`,
        `${preview.eligible_count} pending items meet the auto-approval rules (confidence ≥ 0.75, category in the published taxonomy, nothing flagged).\n\nAuto-approve them? You can still re-review them under Confirmed › Auto-approved.`,
      ))) return;
      const result = await api("/api/admin/ai/classifications/auto-confirm", token, {
        method: "POST", body: JSON.stringify({ dry_run: false }),
      });
      setBatchMessage(t(`已自動通過 ${result.eligible_count} 筆。`, `Auto-approved ${result.eligible_count} items.`)
        + (result.limit_reached ? t("還有更多符合條件的資料，請再按一次。", " More remain; run it again.") : ""));
      await load({ silent: true });
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBackfillBusy(false);
    }
  };

  const totalPages = Math.max(data.total_pages || 0, 1);

  return (
    <div className="review-workbench">
      {error && <p className="ai-admin-error">{error}<button onClick={() => setError("")}>×</button></p>}

      <p className="review-workbench-intro">
        {t("AI 有把握、類別也在分類架構裡的結果會自動通過，這裡只剩需要人看的項目。標示「需人工審查」的請逐筆確認；自動通過的可在「已確認」分頁抽查。",
          "Confident results whose category is in the taxonomy are approved automatically, so only items that need a person are left here. Confirm flagged items one by one; spot-check auto-approved ones under Confirmed.")}
      </p>

      <div className="review-tabs" role="tablist">
        {STATE_TABS.map((state) => (
          <button key={state} role="tab" aria-selected={activeTab === state}
            className={`review-tab${activeTab === state ? " review-tab--active" : ""}`}
            onClick={() => { setActiveTab(state); setPage(1); }}>
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
              onClick={() => { setConfirmedSource(key); setPage(1); }}>
              {label}
            </button>
          ))}
        </div>
      )}

      <label className="review-secondary-filter">
        <input type="checkbox" checked={needsReviewOnly} onChange={(e) => { setNeedsReviewOnly(e.target.checked); setPage(1); }} />
        {t("只看需人工審查的項目", "Only show items needing human review")}
      </label>

      {activeTab === "pending_review" && (
        <div className="review-batch-bar">
          <div className="review-batch-selection">
            <b>{t(`已選 ${selectedCount} 筆`, `${selectedCount} selected`)}</b>
            <span>{t(`本頁 ${rows.length} 筆／共 ${data.total} 筆`, `${rows.length} on this page / ${data.total} total`)}</span>
          </div>
          <div className="review-batch-actions">
            <button type="button" disabled={batchBusy || excludeLegacyBusy} onClick={() => setSelectedIds(new Set(selectableRows.map((r) => r.classification_id)))}>
              {t("全選本頁", "Select this page")}
            </button>
            <button type="button" disabled={batchBusy || excludeLegacyBusy || highConfidenceRows.length === 0}
              onClick={() => setSelectedIds(new Set(highConfidenceRows.map((r) => r.classification_id)))}
              title={t(`選取本頁信心分數 ≥ ${HIGH_CONFIDENCE_THRESHOLD.toFixed(1)} 且不需人工審查的項目`, `Select items on this page with confidence ≥ ${HIGH_CONFIDENCE_THRESHOLD.toFixed(1)}`)}>
              {t(`選取高信心 (${highConfidenceRows.length})`, `Select high-confidence (${highConfidenceRows.length})`)}
            </button>
            <button type="button" disabled={batchBusy || excludeLegacyBusy || selectedCount === 0} onClick={() => setSelectedIds(new Set())}>
              {t("清除選取", "Clear")}
            </button>
            <button type="button" className="review-btn-primary" disabled={batchBusy || excludeLegacyBusy || selectedCount === 0} onClick={runBatchConfirm}>
              {batchBusy ? t("批次處理中…", "Processing…") : t(`批次維持 AI 分類 (${selectedCount})`, `Keep AI classification (${selectedCount})`)}
            </button>
            <button type="button" disabled={batchBusy || excludeLegacyBusy || backfillBusy} onClick={runAutoConfirmBackfill}
              title={t("把自動通過功能上線前就分析好、符合條件的待處理結果改成自動通過", "Apply auto-approval to pending items analysed before it was enabled")}>
              {backfillBusy ? t("處理中…", "Working…") : t("套用自動通過到既有資料", "Auto-approve existing items")}
            </button>
            <button type="button" className="review-btn-danger" disabled={batchBusy || excludeLegacyBusy || backfillBusy} onClick={runExcludeLegacy}>
              {excludeLegacyBusy ? t("處理中…", "Working…") : t("排除舊版資料", "Exclude Legacy Data")}
            </button>
          </div>
        </div>
      )}

      {batchMessage && <p className="review-batch-message">{batchMessage}</p>}

      {loading && <LoadingNotice />}

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
          onExclude={() => withRow(row.classification_id, () => api(`/api/classification/${row.classification_id}/review/exclude`, token, { method: "POST" }))}
          onStartReview={onOpenReview ? () => onOpenReview(row.classification_id, "start") : null}
          onViewHistory={onOpenReview ? () => onOpenReview(row.classification_id, "view") : null}
          onReopen={() => reopen(row)}
          onRetry={() => retry(row)}
          onOpenNewCategories={() => navigate("/admin/ai/new-categories")}
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
}) {
  const auto = isAutoConfirmed(row);
  // 自動通過的結果在畫面上當成獨立狀態：顯示 AI 判斷與信心分數，
  // 並可直接確認、重新審核或排除（後端不需要先重新開啟）。
  const state = auto ? "auto_confirmed" : (row.review_state || row.review_status);
  const effective = row.effective_result;
  const isPendingLike = state === "pending_review" || state === "in_review";
  const showsAiResult = isPendingLike || state === "auto_confirmed";
  const isNewCategory = row.status === "new_category";

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
          <p><span className="review-field-label">{t("AI 大類別", "AI main category")}</span>{row.main_category || "—"}</p>
          <p><span className="review-field-label">{t("AI 子類別", "AI sub category")}</span>{row.sub_category || "—"}</p>
          <p><span className="review-field-label">{t("信心分數", "Confidence")}</span>{typeof row.confidence === "number" ? row.confidence.toFixed(2) : "—"}</p>
          {row.needs_human_review && (
            <p className="review-flag-badge">⚠ {t("需人工審查", "Needs human review")}{row.review_flag_reason && ` — ${reviewFlagReasonText(row.review_flag_reason)}`}</p>
          )}
          {auto && (
            <p><small>{t("AI 有把握且類別在分類架構內，系統已自動通過。看起來正確可以按「確認無誤」；有疑問就重新審核。",
              "The AI was confident and the category is in the taxonomy, so it was approved automatically. Confirm it if it looks right, or re-review it.")}</small></p>
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
            <button className="review-btn-primary" disabled={busy} onClick={onAcceptOriginal}>{t("維持 AI 分類", "Keep AI classification")}</button>
            {onStartReview && <button disabled={busy} onClick={onStartReview}>{state === "in_review" ? t("繼續審核", "Continue review") : t("重新審核", "Re-review")}</button>}
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
