import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { useAuth } from "../../../../hooks/AuthContext";
import { peekCache } from "../shared/apiClient";
import { SkeletonCards } from "../shared/StatusWidgets";
import { t } from "../shared/taxStatus";
import { CategoryAnswers, TopicSourceSummary, answersUrl, loadTopicAnswers } from "./TopicAnswers";

// 主題 → 回答範例：每個類別底下實際被分進去的原始回答（唯讀），沿用既有 API 與元件。
export default function AnswersPanel() {
  const { topicKey } = useParams();
  const { user } = useAuth();
  const token = user?.token;
  const [data, setData] = useState(() => peekCache(answersUrl(topicKey, { per_category: 5 })) || null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setFailed(false);
    loadTopicAnswers(topicKey, token).then(setData).catch(() => setFailed(true));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [topicKey]);

  if (failed && !data) return <div className="admin-card"><p>{t("回答範例載入失敗。", "Failed to load answers.")}</p></div>;
  if (!data) return <SkeletonCards count={3} />;

  return <>
    <TopicSourceSummary data={data} />
    {(data.groups || []).map((g) => (
      <div className="admin-card" key={`${g.main_category}|${g.sub_category}`} style={{ marginBottom: 14 }}>
        <b>{g.main_category || "—"} / {g.sub_category || "—"}</b>
        <CategoryAnswers topicKey={topicKey} token={token} group={g} />
      </div>
    ))}
  </>;
}
