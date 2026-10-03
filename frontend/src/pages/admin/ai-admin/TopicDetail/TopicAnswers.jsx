import { NavLink } from "react-router-dom";
import { useState } from "react";
import { api } from "../shared/apiClient";
import { AUTO_CONFIRMED_LABEL, errorMessage, isAutoConfirmed, stateLabel } from "../shared/reviewStates";
import { t } from "../shared/taxStatus";

export const answersUrl = (topicKey, params) =>
  `/api/admin/ai/topics/${encodeURIComponent(topicKey)}/answers?${new URLSearchParams(params).toString()}`;

export const loadTopicAnswers = (topicKey, token) => api(answersUrl(topicKey, { per_category: 5 }), token);

// 一則原始回答：片段 + 狀態；片段跟完整回答不同時可展開。
function AnswerItem({ item }) {
  const full = item.answer_text && item.answer_text !== item.segment_text;
  return (
    <li className="topic-answer-item">
      <span className="topic-answer-text">「{item.segment_text}」</span>
      {item.review_status && item.review_status !== "pending_review" && (
        isAutoConfirmed(item)
          ? <span className="review-status-tag review-status-tag--auto_confirmed">{AUTO_CONFIRMED_LABEL()}</span>
          : <span className={`review-status-tag review-status-tag--${item.review_status}`}>{stateLabel(item.review_status)}</span>
      )}
      {item.is_new_category && <span className="topic-tag">{t("AI 新類別", "New category")}</span>}
      {full && (
        <details>
          <summary>{t("完整回答", "Full answer")}</summary>
          <p>{item.answer_text}</p>
        </details>
      )}
    </li>
  );
}

/** 某個類別底下的原始回答（預設顯示 5 則，可展開全部）。 */
export function CategoryAnswers({ topicKey, token, group }) {
  const [all, setAll] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  if (!group || group.count === 0) {
    return <p className="topic-answers-empty">{t("目前沒有任何回答被分到這一類。", "No answers are in this category yet.")}</p>;
  }
  const items = all || group.items;

  const showAll = async () => {
    setLoading(true);
    setError("");
    try {
      const data = await api(answersUrl(topicKey, {
        per_category: 200, main_category: group.main_category, sub_category: group.sub_category,
      }), token);
      setAll(data.groups[0]?.items || []);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setLoading(false);
    }
  };

  // 這裡只是讓 Admin 編輯分類架構時參考實際回答（唯讀），預設收合；
  // 要修改分類請到「分類審核」分頁，避免兩個地方都像可以處理回答。
  return (
    <details className="topic-answers">
      <summary>{t(`這一類的回答（${group.count} 則，唯讀）`, `Answers in this category (${group.count}, read-only)`)}</summary>
      <p><small>{t("這裡只供參考。要修改某筆回答的分類，請到", "For reference only. To change an answer's category, use")}{" "}
        <NavLink to={`/admin/ai/topics/${topicKey}/review`}>{t("分類審核", "Review")}</NavLink>{t("。", ".")}</small></p>
      <ul>{items.map((item) => <AnswerItem key={item.classification_id} item={item} />)}</ul>
      {error && <p className="ai-admin-error">{error}</p>}
      {!all && group.count > group.items.length && (
        <button onClick={showAll} disabled={loading}>
          {loading ? t("載入中…", "Loading…") : t(`查看全部 ${group.count} 則`, `Show all ${group.count}`)}
        </button>
      )}
      {all && group.count > all.length && (
        <p><small>{t(`只列出前 ${all.length} 則。`, `Showing the first ${all.length}.`)}</small></p>
      )}
    </details>
  );
}

/** 主題的資料來源摘要：來自哪個欄位 / 題目、共幾則、審核進度。 */
export function TopicSourceSummary({ data }) {
  if (!data) return null;
  if (data.total_answers === 0) {
    return (
      <div className="admin-card topic-source-card">
        <p>{t("目前沒有任何回答被分到這個主題。", "No answers have been classified under this topic yet.")}</p>
      </div>
    );
  }
  return (
    <div className="admin-card topic-source-card">
      <h3>{t("這個主題的資料", "Data in this topic")}</h3>
      <p>
        {t("回答來自：", "Answers come from: ")}
        {data.sources.map((s, i) => (
          <span key={s.label}>
            {i > 0 && "、"}
            <b>「{s.label}」</b>{t(`（${s.answer_count} 則）`, ` (${s.answer_count})`)}
          </span>
        ))}
      </p>
      <p><small>
        {t(`共 ${data.total_answers} 則回答、${data.total_segments} 個片段`, `${data.total_answers} answers, ${data.total_segments} segments`)}
        {" · "}{t(`已人工確認 ${data.reviewed_count - (data.auto_confirmed_count || 0)}`, `${data.reviewed_count - (data.auto_confirmed_count || 0)} reviewed`)}
        {(data.auto_confirmed_count || 0) > 0 && <>{" · "}{t(`自動通過 ${data.auto_confirmed_count}`, `${data.auto_confirmed_count} auto-approved`)}</>}
        {data.excluded_count > 0 && ` · ${t(`已排除 ${data.excluded_count}`, `${data.excluded_count} excluded`)}`}
        {data.failed_count > 0 && ` · ${t(`處理失敗 ${data.failed_count}`, `${data.failed_count} failed`)}`}
      </small></p>
      <p><small>{t("每個類別下方都列出實際被分進去的原始回答，可以用來判斷類別合不合理、主題有沒有分錯。",
        "Each category below lists the actual answers in it, so you can judge whether the category and topic are right.")}</small></p>
    </div>
  );
}

/** 不在目前分類架構裡的類別（例如 AI 分類時新提出的）。 */
export function OtherCategoryAnswers({ topicKey, token, groups }) {
  if (!groups.length) return null;
  return (
    <div className="admin-card topic-other-groups">
      <h3>{t("不在這個版本分類架構裡的類別", "Categories not in this taxonomy version")}</h3>
      <p><small>{t("通常是 AI 分類時提出的新類別，或用其他版本分類的結果。新類別可以到「新類別候選」採用或合併。",
        "Usually new categories proposed by the AI, or results from another version. Handle new categories under New Category Candidates.")}</small></p>
      {groups.map((g) => (
        <div key={`${g.main_category}|${g.sub_category}`} className="topic-other-group">
          <b>{g.main_category || "—"} / {g.sub_category || "—"}</b>
          <CategoryAnswers topicKey={topicKey} token={token} group={g} />
        </div>
      ))}
    </div>
  );
}
