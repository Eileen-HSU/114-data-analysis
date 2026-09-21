import { useEffect, useMemo, useState } from "react";
import { api } from "./apiClient";
import { t, reviewFlagReasonText } from "./taxStatus";
import { useAuth } from "../../../../hooks/AuthContext";

const STATUS_TABS = [
  { value: "pending_review", label: t("待處理", "Pending") },
  { value: "confirmed", label: t("已確認", "Confirmed") },
  { value: "modified", label: t("已修改", "Modified") },
  { value: "excluded", label: t("已排除", "Excluded") },
];

const HIGH_CONFIDENCE_THRESHOLD = 0.9;
const BATCH_CONCURRENCY = 5;

export default function ClassificationList({ topicParam, onOpenReview, refreshSignal }) {
  const { user } = useAuth();
  const token = user?.token;

  const [activeTab, setActiveTab] = useState("pending_review");
  const [needsReviewOnly, setNeedsReviewOnly] = useState(false);
  const [allClassifications, setAllClassifications] = useState([]);
  const [error, setError] = useState("");

  const [rowBusy, setRowBusy] = useState({});
  const [rowError, setRowError] = useState({});

  const [selectedIds, setSelectedIds] = useState(() => new Set());
  const [batchBusy, setBatchBusy] = useState(false);
  const [batchMessage, setBatchMessage] = useState("");

  const load = async () => {
    try {
      setError("");
      const params = new URLSearchParams({ topic: topicParam });
      const result = await api(`/api/admin/ai/classifications?${params}`, token);
      setAllClassifications(result.classifications || []);
    } catch (e) {
      setError(e.message);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [topicParam, refreshSignal]);

  // 切換 topic / tab 時不要保留上一個畫面的勾選。
  useEffect(() => {
    setSelectedIds(new Set());
    setBatchMessage("");
  }, [topicParam, activeTab]);

  const counts = useMemo(() => {
    const c = { pending_review: 0, confirmed: 0, modified: 0, excluded: 0 };
    allClassifications.forEach((row) => {
      if (row.review_status in c) c[row.review_status] += 1;
    });
    return c;
  }, [allClassifications]);

  const visibleRows = useMemo(() => {
    let rows = allClassifications.filter((row) => row.review_status === activeTab);
    if (needsReviewOnly) {
      rows = rows.filter((row) => row.needs_human_review);
    }
    return rows;
  }, [allClassifications, activeTab, needsReviewOnly]);

  const visiblePendingRows = useMemo(
    () => visibleRows.filter((row) => row.review_status === "pending_review"),
    [visibleRows],
  );

  const highConfidenceRows = useMemo(
    () => visiblePendingRows.filter(
      (row) =>
        typeof row.confidence === "number" &&
        row.confidence >= HIGH_CONFIDENCE_THRESHOLD &&
        !row.needs_human_review,
    ),
    [visiblePendingRows],
  );

  const selectedCount = selectedIds.size;

  const toggleSelected = (classificationId) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(classificationId)) next.delete(classificationId);
      else next.add(classificationId);
      return next;
    });
  };

  const selectAllVisible = () => {
    setSelectedIds(new Set(visiblePendingRows.map((row) => row.classification_id)));
  };

  const selectHighConfidence = () => {
    setSelectedIds(new Set(highConfidenceRows.map((row) => row.classification_id)));
  };

  const clearSelection = () => {
    setSelectedIds(new Set());
  };

  const reopenConfirmed = async (classificationId) => {
    const confirmed = window.confirm(
      t(
        "確定要重新開啟這筆分類的審核嗎？\n\n這筆會從「已確認」回到待處理，既有審核歷史會保留；若已有報表使用過這筆結果，該報表會被標記為需要更新。",
        "Reopen this classification for review?\n\nIt will return from Confirmed to Pending, existing review history will be preserved, and reports that used this result will be marked outdated.",
      ),
    );

    if (!confirmed) return;

    setRowBusy((prev) => ({ ...prev, [classificationId]: true }));
    setRowError((prev) => ({ ...prev, [classificationId]: "" }));

    try {
      await api(
        `/api/classification/${classificationId}/review/reopen`,
        token,
        { method: "POST" },
      );
      await load();
      onOpenReview(classificationId, "start");
    } catch (e) {
      const message = e.status === 409 && e.body?.reviewing_admin_id
        ? t(
          `此分類目前由 ${e.body.reviewing_admin_name || `Admin #${e.body.reviewing_admin_id}`} 審核中，暫時無法重新開啟。`,
          `Currently being reviewed by ${e.body.reviewing_admin_name || `Admin #${e.body.reviewing_admin_id}`}, so it cannot be reopened right now.`,
        )
        : e.message;

      setRowError((prev) => ({ ...prev, [classificationId]: message }));
    } finally {
      setRowBusy((prev) => ({ ...prev, [classificationId]: false }));
    }
  };

  const runQuickAction = async (classificationId, path) => {
    setRowBusy((prev) => ({ ...prev, [classificationId]: true }));
    setRowError((prev) => ({ ...prev, [classificationId]: "" }));

    try {
      await api(path, token, { method: "POST" });
      setSelectedIds((prev) => {
        const next = new Set(prev);
        next.delete(classificationId);
        return next;
      });
      await load();
    } catch (e) {
      const message = e.status === 409 && e.body?.reviewing_admin_id
        ? t(
          `此分類目前由 ${e.body.reviewing_admin_name || `Admin #${e.body.reviewing_admin_id}`} 審核中，暫時無法操作。`,
          `Currently being reviewed by ${e.body.reviewing_admin_name || `Admin #${e.body.reviewing_admin_id}`}, cannot act on it right now.`,
        )
        : e.message;

      setRowError((prev) => ({ ...prev, [classificationId]: message }));
    } finally {
      setRowBusy((prev) => ({ ...prev, [classificationId]: false }));
    }
  };

  const runBatchConfirm = async () => {
    if (selectedCount === 0 || batchBusy) return;

    const confirmed = window.confirm(
      t(
        `確定要一次維持這 ${selectedCount} 筆 AI 分類嗎？\n\n確認後，這些分類會標記為「已確認」，並沿用目前 AI 原始分類結果。`,
        `Keep the current AI classification for ${selectedCount} selected items?\n\nThey will be marked as confirmed and keep the original AI result.`,
      ),
    );

    if (!confirmed) return;

    const ids = [...selectedIds];
    setBatchBusy(true);
    setBatchMessage("");
    setRowError({});

    let successCount = 0;
    const failed = [];

    // 避免一次打 50~100 個 request，把 API 壓爆；每批最多 5 個並行。
    for (let i = 0; i < ids.length; i += BATCH_CONCURRENCY) {
      const batch = ids.slice(i, i + BATCH_CONCURRENCY);

      const results = await Promise.allSettled(
        batch.map((classificationId) =>
          api(
            `/api/classification/${classificationId}/review/confirm-original`,
            token,
            { method: "POST" },
          ),
        ),
      );

      results.forEach((result, index) => {
        const classificationId = batch[index];

        if (result.status === "fulfilled") {
          successCount += 1;
          return;
        }

        const e = result.reason;
        const message = e?.status === 409 && e?.body?.reviewing_admin_id
          ? t(
            `目前由 ${e.body.reviewing_admin_name || `Admin #${e.body.reviewing_admin_id}`} 審核中。`,
            `Currently being reviewed by ${e.body.reviewing_admin_name || `Admin #${e.body.reviewing_admin_id}`}.`,
          )
          : (e?.message || t("操作失敗", "Action failed"));

        failed.push({ classificationId, message });
      });
    }

    if (failed.length > 0) {
      setRowError((prev) => {
        const next = { ...prev };
        failed.forEach(({ classificationId, message }) => {
          next[classificationId] = message;
        });
        return next;
      });

      setBatchMessage(
        t(
          `已確認 ${successCount} 筆，${failed.length} 筆失敗；失敗項目會保留在待處理清單中。`,
          `${successCount} confirmed, ${failed.length} failed. Failed items remain pending.`,
        ),
      );
    } else {
      setBatchMessage(
        t(
          `已成功確認 ${successCount} 筆分類。`,
          `${successCount} classifications confirmed successfully.`,
        ),
      );
    }

    setSelectedIds(new Set(failed.map((item) => item.classificationId)));
    await load();
    setBatchBusy(false);
  };

  return (
    <div className="review-workbench">
      {error && (
        <p className="ai-admin-error">
          {error}
          <button onClick={() => setError("")}>×</button>
        </p>
      )}

      <p className="review-workbench-intro">
        {t(
          "請快速確認 AI 分類結果；可勾選多筆一次維持 AI 分類，有疑問的項目再進入重新審核。",
          "Review AI classifications quickly: batch-confirm items that look correct, and re-review only the questionable ones.",
        )}
      </p>

      <div className="review-tabs" role="tablist">
        {STATUS_TABS.map((tab) => (
          <button
            key={tab.value}
            role="tab"
            aria-selected={activeTab === tab.value}
            className={`review-tab${activeTab === tab.value ? " review-tab--active" : ""}`}
            onClick={() => setActiveTab(tab.value)}
          >
            {tab.label}
            <span className="review-tab-count">{counts[tab.value]}</span>
          </button>
        ))}
      </div>

      <label className="review-secondary-filter">
        <input
          type="checkbox"
          checked={needsReviewOnly}
          onChange={(e) => {
            setNeedsReviewOnly(e.target.checked);
            setSelectedIds(new Set());
          }}
        />
        {t("只看需人工審查的項目", "Only show items needing human review")}
      </label>

      {activeTab === "pending_review" && visiblePendingRows.length > 0 && (
        <div className="review-batch-bar">
          <div className="review-batch-selection">
            <b>
              {t(
                `已選 ${selectedCount} 筆`,
                `${selectedCount} selected`,
              )}
            </b>
            <span>
              {t(
                `目前顯示 ${visiblePendingRows.length} 筆`,
                `${visiblePendingRows.length} currently shown`,
              )}
            </span>
          </div>

          <div className="review-batch-actions">
            <button
              type="button"
              disabled={batchBusy}
              onClick={selectAllVisible}
            >
              {t("全選目前顯示", "Select visible")}
            </button>

            <button
              type="button"
              disabled={batchBusy || highConfidenceRows.length === 0}
              onClick={selectHighConfidence}
              title={t(
                `選取信心分數 ≥ ${HIGH_CONFIDENCE_THRESHOLD.toFixed(1)} 且不需人工審查的項目`,
                `Select items with confidence ≥ ${HIGH_CONFIDENCE_THRESHOLD.toFixed(1)} that do not need human review`,
              )}
            >
              {t(
                `選取高信心 (${highConfidenceRows.length})`,
                `Select high-confidence (${highConfidenceRows.length})`,
              )}
            </button>

            <button
              type="button"
              disabled={batchBusy || selectedCount === 0}
              onClick={clearSelection}
            >
              {t("清除選取", "Clear")}
            </button>

            <button
              type="button"
              className="review-btn-primary"
              disabled={batchBusy || selectedCount === 0}
              onClick={runBatchConfirm}
            >
              {batchBusy
                ? t("批次處理中…", "Processing…")
                : t(
                  `批次維持 AI 分類 (${selectedCount})`,
                  `Keep AI classification (${selectedCount})`,
                )}
            </button>
          </div>
        </div>
      )}

      {batchMessage && (
        <p className="review-batch-message">{batchMessage}</p>
      )}

      {visibleRows.length === 0 && (
        <p className="review-empty-hint">
          {activeTab === "pending_review"
            ? t("目前沒有待處理的分類結果。", "Nothing pending right now.")
            : t("這個狀態底下目前沒有符合條件的分類結果。", "No matching classifications under this status.")}
        </p>
      )}

      {visibleRows.map((row) => (
        <ClassificationCard
          key={row.classification_id}
          row={row}
          selectable={row.review_status === "pending_review"}
          selected={selectedIds.has(row.classification_id)}
          onToggleSelected={() => toggleSelected(row.classification_id)}
          busy={Boolean(rowBusy[row.classification_id]) || batchBusy}
          error={rowError[row.classification_id]}
          onDismissError={() => setRowError((prev) => ({
            ...prev,
            [row.classification_id]: "",
          }))}
          onAcceptOriginal={() => runQuickAction(
            row.classification_id,
            `/api/classification/${row.classification_id}/review/confirm-original`,
          )}
          onExclude={() => runQuickAction(
            row.classification_id,
            `/api/classification/${row.classification_id}/review/exclude`,
          )}
          onStartReview={() => onOpenReview(row.classification_id, "start")}
          onViewHistory={() => onOpenReview(row.classification_id, "view")}
          onReopen={() => reopenConfirmed(row.classification_id)}
        />
      ))}
    </div>
  );
}

const STATUS_BADGE_LABEL = {
  pending_review: t("待處理", "Pending"),
  confirmed: t("已確認", "Confirmed"),
  modified: t("已修改", "Modified"),
  excluded: t("已排除", "Excluded"),
};

function ClassificationCard({
  row,
  selectable,
  selected,
  onToggleSelected,
  busy,
  error,
  onDismissError,
  onAcceptOriginal,
  onExclude,
  onStartReview,
  onViewHistory,
  onReopen,
}) {
  const status = row.review_status;

  return (
    <article className={`review-card${selected ? " review-card--selected" : ""}`}>
      <div className="review-card-top">
        {selectable && (
          <label
            className="review-card-select"
            title={t("選取這筆分類", "Select this classification")}
          >
            <input
              type="checkbox"
              checked={selected}
              disabled={busy}
              onChange={onToggleSelected}
            />
            <span className="sr-only">
              {t("選取這筆分類", "Select this classification")}
            </span>
          </label>
        )}

        <b className={`review-status-tag review-status-tag--${status}`}>
          {STATUS_BADGE_LABEL[status] || status}
        </b>

        <span className="review-card-segment">{row.segment}</span>
      </div>

      {status === "pending_review" && (
        <div className="review-card-mid">
          <p>
            <span className="review-field-label">{t("AI 大類別", "AI main category")}</span>
            {row.main_category || "—"}
          </p>
          <p>
            <span className="review-field-label">{t("AI 子類別", "AI sub category")}</span>
            {row.sub_category || "—"}
          </p>
          <p>
            <span className="review-field-label">{t("信心分數", "Confidence")}</span>
            {typeof row.confidence === "number" ? row.confidence.toFixed(2) : "—"}
          </p>

          {row.needs_human_review && (
            <p className="review-flag-badge">
              ⚠ {t("需人工審查", "Needs human review")}
              {row.review_flag_reason && ` — ${reviewFlagReasonText(row.review_flag_reason)}`}
            </p>
          )}
        </div>
      )}

      {status === "confirmed" && (
        <div className="review-card-mid">
          <p>
            <span className="review-field-label">{t("最終結果", "Final result")}</span>
            {row.effective_result.main_category} / {row.effective_result.sub_category}
          </p>
        </div>
      )}

      {status === "modified" && (
        <div className="review-card-mid">
          <p>
            <span className="review-field-label">{t("AI 原始", "AI original")}</span>
            {row.main_category} / {row.sub_category}
          </p>
          <p>
            <span className="review-field-label">{t("最終結果", "Final result")}</span>
            {row.effective_result.main_category} / {row.effective_result.sub_category}
          </p>
        </div>
      )}

      {error && (
        <p className="ai-admin-error">
          {error}
          <button onClick={onDismissError}>×</button>
        </p>
      )}

      {status === "pending_review" && (
        <div className="review-card-actions">
          <button className="review-btn-primary" disabled={busy} onClick={onAcceptOriginal}>
            {t("維持 AI 分類", "Keep AI classification")}
          </button>
          <button disabled={busy} onClick={onStartReview}>
            {t("重新審核", "Re-review")}
          </button>
          <button disabled={busy} className="review-btn-danger" onClick={onExclude}>
            {t("不納入分析", "Exclude from analysis")}
          </button>
        </div>
      )}

      {status === "confirmed" && (
        <div className="review-card-actions">
          <button disabled={busy} onClick={onViewHistory}>
            {t("查看審核紀錄", "View review history")}
          </button>
          <button
            disabled={busy}
            className="review-btn-reopen"
            onClick={onReopen}
          >
            {t("重新開啟審核", "Reopen review")}
          </button>
        </div>
      )}

      {status === "modified" && (
        <div className="review-card-actions">
          <button onClick={onViewHistory}>
            {t("查看審核紀錄", "View review history")}
          </button>
        </div>
      )}
    </article>
  );
}
