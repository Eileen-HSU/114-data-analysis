import { useState } from "react";
import { useParams } from "react-router-dom";
import ClassificationList from "../shared/ClassificationList";
import ReviewConversation from "./ReviewConversation";

export default function ReviewPanel() {
  const { topicKey } = useParams();
  // selected 為 null 時顯示清單；有值時顯示該筆的審核對話面板。
  // mode="start"：從「開始審核」進入，會嘗試 start；
  // mode="view"：從已鎖定狀態的「查看審核歷史」進入，純唯讀。
  const [selected, setSelected] = useState(null); // { classificationId, mode } | null
  // ReviewConversation 完成 confirm-original / confirm-candidate /
  // exclude 之後遞增這個值，讓 ClassificationList 自動重新載入，
  // 不需要使用者手動整理頁面。
  const [refreshSignal, setRefreshSignal] = useState(0);

  if (selected) {
    return (
      <ReviewConversation
        classificationId={selected.classificationId}
        mode={selected.mode}
        onClose={() => setSelected(null)}
        onChanged={() => setRefreshSignal((n) => n + 1)}
      />
    );
  }

  return (
    <ClassificationList
      topicParam={topicKey}
      refreshSignal={refreshSignal}
      onOpenReview={(classificationId, mode) => setSelected({ classificationId, mode })}
    />
  );
}
