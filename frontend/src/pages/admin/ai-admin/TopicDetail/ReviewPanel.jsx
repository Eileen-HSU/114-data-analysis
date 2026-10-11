import { useEffect, useRef, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import ClassificationList from "../shared/ClassificationList";
import ReviewConversation from "./ReviewConversation";

export default function ReviewPanel({ topic }) {
  // 分類審查頁傳入 topic（篩選條件，空字串代表全部主題）；舊的主題內路由沿用網址參數
  const params = useParams();
  const topicKey = topic !== undefined ? (topic || undefined) : params.topicKey;
  // 從首頁連過來時可以指定初始分頁，例如 ?state=confirmed&source=auto（抽查自動通過）
  // 或 ?queue=ai_disagreement（只看 AI 判斷不一致的）。預設只列需要人工處理的待審；flagged=0 可看全部。
  const [searchParams, setSearchParams] = useSearchParams();
  // 分頁 / 確認方式寫回網址（replace，不堆疊歷史），重新整理或分享連結都能還原；
  // 預設值（待審、全部）不寫入網址。
  const changeFilter = ({ state, source }) => {
    const next = new URLSearchParams(searchParams);
    if (state && state !== "pending_review") next.set("state", state); else next.delete("state");
    if (state === "confirmed" && source && source !== "all") next.set("source", source); else next.delete("source");
    setSearchParams(next, { replace: true });
  };
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
  const open = (classificationId, mode, context) => {
    savedScroll.current = window.scrollY;
    setSelected({ classificationId, mode, queue: context?.queue || [] });
    window.scrollTo(0, 0);
  };
  // 審完直接處理本頁下一筆：不經過列表，返回列表時仍回到最初的捲動位置與頁數。
  const openNext = () => {
    const [nextId, ...rest] = selected?.queue || [];
    if (!nextId) return;
    setSelected({ classificationId: nextId, mode: "start", queue: rest });
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
        key={selected.classificationId}
        classificationId={selected.classificationId}
        mode={selected.mode}
        onClose={close}
        onNext={selected.queue.length > 0 ? openNext : null}
        remaining={selected.queue.length}
        onChanged={() => setRefreshSignal((n) => n + 1)}
      />
    )}
    <div hidden={Boolean(selected)}>
    <ClassificationList
      topicParam={topicKey}
      refreshSignal={refreshSignal}
      tab={searchParams.get("state") || undefined}
      source={searchParams.get("source") || undefined}
      onFilterChange={changeFilter}
      queue={searchParams.get("queue") || "human"}
      onOpenReview={open}
    />
    </div>
  </>;
}
