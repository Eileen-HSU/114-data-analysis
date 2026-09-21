import { useEffect, useState } from "react";
import { api } from "./apiClient";
import { t, reviewFlagReasonText } from "./taxStatus";
import { useAuth } from "../../../../hooks/AuthContext";

const REVIEW_STATUSES = ["confirmed", "modified", "pending_review", "excluded"];

const REVIEW_STATUS_LABEL = {
  pending_review: t("待審核", "Pending review"),
  confirmed: t("已確認", "Confirmed"),
  modified: t("已修改", "Modified"),
  excluded: t("已排除", "Excluded"),
};

/**
 * onOpenReview(classificationId, mode)：mode="start" 代表點「開始
 * 審核」，會在 ReviewConversation 掛載時嘗試呼叫 start；mode="view"
 * 代表這筆已經是鎖定狀態（confirmed/modified/excluded），只是想
 * 唯讀查看資料跟審核歷史，不會去嘗試建立/搶佔 review session。
 *
 * refreshSignal：外部（ReviewPanel）在 ReviewConversation 裡完成
 * confirm-original / confirm-candidate / exclude 之後會遞增這個值，
 * 讓這裡自動重新載入，不需要使用者手動整理頁面。
 */
export default function ClassificationList({ topicParam, onOpenReview, refreshSignal }) {
  const { user } = useAuth();
  const token = user?.token;
  const [reviewStatus, setReviewStatus] = useState("");
  const [needsHumanReviewOnly, setNeedsHumanReviewOnly] = useState(false);
  const [classifications, setClassifications] = useState([]);
  const [error, setError] = useState("");
  // 「確認 AI 原始結果」／「排除此分類」這兩個快速動作直接在清單這裡
  // 打 API，不需要為此另外打開 ReviewConversation；用 classification_id
  // 當 key 各自記錄忙碌狀態跟錯誤訊息，避免一筆的錯誤訊息蓋到別筆。
  const [rowBusy, setRowBusy] = useState({});
  const [rowError, setRowError] = useState({});

  const load = async (status, needsReviewOnly) => {
    try {
      const params = new URLSearchParams();
      if (status) params.set("review_status", status);
      params.set("topic", topicParam);
      if (needsReviewOnly) params.set("needs_human_review", "true");
      setClassifications((await api(`/api/admin/ai/classifications?${params}`, token)).classifications);
    } catch (e) { setError(e.message); }
  };

  useEffect(() => { load(reviewStatus, needsHumanReviewOnly); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [topicParam, refreshSignal]);

  const runQuickAction = async (classificationId, path) => {
    setRowBusy((prev) => ({ ...prev, [classificationId]: true }));
    setRowError((prev) => ({ ...prev, [classificationId]: "" }));
    try {
      await api(path, token, { method: "POST" });
      await load(reviewStatus, needsHumanReviewOnly);
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

  return <div className="admin-card">
    {error && <p className="ai-admin-error">{error}<button onClick={() => setError("")}>×</button></p>}
    <div className="filter-row">
      <label>{t("審查狀態", "Review status")}
        <select value={reviewStatus} onChange={(e) => { setReviewStatus(e.target.value); load(e.target.value, needsHumanReviewOnly); }}>
          <option value="">{t("全部", "All")}</option>
          {REVIEW_STATUSES.map((x) => <option key={x}>{x}</option>)}
        </select>
      </label>
      <label>{t("優先程度", "Priority")}
        <select
          value={needsHumanReviewOnly ? "needs_review" : ""}
          onChange={(e) => { const v = e.target.value === "needs_review"; setNeedsHumanReviewOnly(v); load(reviewStatus, v); }}
        >
          <option value="">{t("全部", "All")}</option>
          <option value="needs_review">{t("需人工審查", "Needs human review")}</option>
        </select>
      </label>
    </div>
    {classifications.length === 0 && <p>{t("目前沒有符合條件的分類結果。", "No matching classifications.")}</p>}
    {classifications.map((row) => {
      const isPending = row.review_status === "pending_review";
      const isLocked = !isPending; // confirmed / modified / excluded
      const busy = Boolean(rowBusy[row.classification_id]);
      return (
        <article className="review-row" key={row.classification_id}>
          <p>
            <b className={`review-status-tag review-status-tag--${row.review_status}`}>
              {REVIEW_STATUS_LABEL[row.review_status] || row.review_status}
            </b>
            {" "}· {row.segment}
          </p>
          <p>{t("結果", "Effective")}: {row.effective_result.main_category} / {row.effective_result.sub_category}</p>
          <p>
            {t("信心分數", "Confidence")}: {typeof row.confidence === "number" ? row.confidence.toFixed(2) : "—"}
            {row.needs_human_review && (
              <span className="review-flag-badge">
                {" "}⚠ {t("需人工審查", "Needs human review")}
                {row.review_flag_reason && ` — ${reviewFlagReasonText(row.review_flag_reason)}`}
              </span>
            )}
          </p>
          {row.review_status === "modified" && (
            <details>
              <summary>{t("比較 AI 原始與人工審查最終結果", "Compare AI Original and Human Review Final")}</summary>
              {["main_category", "sub_category", "secondary_sub_category", "reasoning"].filter((k) => row[k] !== row[`final_${k}`]).map((k) => (
                <p key={k}><b>{k}</b><br />AI: {row[k] || "—"}<br />{t("人工", "Human")}: {row[`final_${k}`] || "—"}</p>
              ))}
              <button onClick={() => navigator.clipboard.writeText(`Response: ${row.segment}\nAI: ${JSON.stringify({ main_category: row.main_category, sub_category: row.sub_category, reasoning: row.reasoning })}\nHuman: ${JSON.stringify(row.effective_result)}`)}>
                {t("複製不一致案例", "Copy inconsistent case")}
              </button>
            </details>
          )}

          {rowError[row.classification_id] && (
            <p className="ai-admin-error">
              {rowError[row.classification_id]}
              <button onClick={() => setRowError((prev) => ({ ...prev, [row.classification_id]: "" }))}>×</button>
            </p>
          )}

          <div className="review-row-actions">
            {isPending && (
              <>
                <button onClick={() => onOpenReview(row.classification_id, "start")}>
                  {t("開始審核", "Start review")}
                </button>
                <button
                  disabled={busy}
                  onClick={() => runQuickAction(row.classification_id, `/api/classification/${row.classification_id}/review/confirm-original`)}
                >
                  {t("確認 AI 原始結果", "Confirm AI original")}
                </button>
                <button
                  disabled={busy}
                  className="review-btn-danger"
                  onClick={() => runQuickAction(row.classification_id, `/api/classification/${row.classification_id}/review/exclude`)}
                >
                  {t("排除此分類", "Exclude")}
                </button>
              </>
            )}
            {isLocked && (
              <button onClick={() => onOpenReview(row.classification_id, "view")}>
                {t("查看審核歷史", "View review history")}
              </button>
            )}
          </div>
        </article>
      );
    })}
  </div>;
}
