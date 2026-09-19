import { useEffect, useState } from "react";
import { api } from "./apiClient";
import { t } from "./taxStatus";
import { useAuth } from "../../../../hooks/AuthContext";

const REVIEW_STATUSES = ["confirmed", "modified", "pending_review", "excluded"];

export default function ClassificationList({ topicParam }) {
  const { user } = useAuth();
  const token = user?.token;
  const [reviewStatus, setReviewStatus] = useState("");
  const [classifications, setClassifications] = useState([]);
  const [error, setError] = useState("");

  const load = async (status) => {
    try {
      const params = new URLSearchParams();
      if (status) params.set("review_status", status);
      params.set("topic", topicParam);
      setClassifications((await api(`/api/admin/ai/classifications?${params}`, token)).classifications);
    } catch (e) { setError(e.message); }
  };

  useEffect(() => { load(reviewStatus); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [topicParam]);

  return <div className="admin-card">
    {error && <p className="ai-admin-error">{error}<button onClick={() => setError("")}>×</button></p>}
    <div className="filter-row">
      <label>{t("審查狀態", "Review status")}
        <select value={reviewStatus} onChange={(e) => { setReviewStatus(e.target.value); load(e.target.value); }}>
          <option value="">{t("全部", "All")}</option>
          {REVIEW_STATUSES.map((x) => <option key={x}>{x}</option>)}
        </select>
      </label>
    </div>
    {classifications.length === 0 && <p>{t("目前沒有符合條件的分類結果。", "No matching classifications.")}</p>}
    {classifications.map((row) => (
      <article className="review-row" key={row.classification_id}>
        <p><b>{row.review_status}</b> · {row.segment}</p>
        <p>{t("結果", "Effective")}: {row.effective_result.main_category} / {row.effective_result.sub_category}</p>
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
      </article>
    ))}
  </div>;
}
