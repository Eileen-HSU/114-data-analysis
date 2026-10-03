import { useEffect, useRef, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import ClassificationList from "../shared/ClassificationList";
import ReviewConversation from "./ReviewConversation";

export default function ReviewPanel({ topic }) {
  // 分類審查頁傳入 topic（篩選條件，空字串代表全部主題）；舊的主題內路由沿用網址參數
  const params = useParams();
  const topicKey = topic !== undefined ? (topic || undefined) : params.topicKey;
  // 從首頁連過來時可以指定初始分頁，例如 ?state=confirmed&source=auto（抽查自動通過）
  // 或 ?state=pending_review&flagged=1（只看需要人工判斷的）。
  const [searchParams] = useSearchParams();
  // selected 為 null 時顯示清單；有值時顯示該筆的審核對話面板。
  // mode="start"：從「開始審核」進入，會嘗試 start；
  // mode="view"：從已鎖定狀態的「查看審核歷史」進入，純唯讀。
  const [selected, setSelected] = useState(null); // { classificationId, mode } | null
  // ReviewConversation 完成 confirm-original / confirm-candidate /
  // exclude 之後遞增這個值，讓 ClassificationList 自動重新載入，
  // 不需要使用者手動整理頁面。
  const [refreshSignal, setRefreshSignal] = useState(0);

  // 開啟對話時清單不卸載（只隱藏），分頁、篩選、勾選都保留；關閉後回到原本的捲動位置。
  // 原本會整個換掉清單，每審完一筆就回到第一頁。
  const savedScroll = useRef(0);
  const open = (classificationId, mode) => {
    savedScroll.current = window.scrollY;
    setSelected({ classificationId, mode });
    window.scrollTo(0, 0);
  };
  const restoreScroll = useRef(false);
  const close = () => {
    restoreScroll.current = true;
    setSelected(null);
  };
  useEffect(() => {
    if (!selected && restoreScroll.current) {
      restoreScroll.current = false;
      requestAnimationFrame(() => window.scrollTo(0, savedScroll.current));
    }
  }, [selected]);

  return <>
    {selected && (
      <ReviewConversation
        classificationId={selected.classificationId}
        mode={selected.mode}
        onClose={close}
        onChanged={() => setRefreshSignal((n) => n + 1)}
      />
    )}
    <div hidden={Boolean(selected)}>
    <ClassificationList
      topicParam={topicKey}
      refreshSignal={refreshSignal}
      initialTab={searchParams.get("state") || undefined}
      initialConfirmedSource={searchParams.get("source") || undefined}
      initialNeedsReviewOnly={searchParams.get("flagged") === "1"}
      onOpenReview={open}
    />
    </div>
  </>;
}
