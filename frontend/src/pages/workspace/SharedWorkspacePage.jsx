import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { apiUrl } from "../../lib/api";
import { MessageContent } from "./page";
import "./workspace.css";
import "./sharing.css";

export default function SharedWorkspacePage() {
  const { shareCode } = useParams();
  const [result, setResult] = useState(null);
  useEffect(() => {
    const controller = new AbortController();
    setResult(null);
    async function load() {
      try {
        const response = await fetch(apiUrl(`/api/public/workspace/${encodeURIComponent(shareCode)}`), {
          signal: controller.signal, credentials: "omit", cache: "no-store",
        });
        const data = await response.json();
        if (!response.ok) throw new Error(response.status === 404 ? "邀請連結無效或已失效" : "無法載入對話，請稍後重新整理。");
        if (!Array.isArray(data.messages)) throw new Error("無法載入對話，請稍後重新整理。");
        setResult({ data });
      } catch (error) {
        if (!controller.signal.aborted) setResult({ error: error.message || "無法載入對話，請稍後重新整理。" });
      }
    }
    load();
    return () => controller.abort();
  }, [shareCode]);
  return (
    <main className="shared-workspace">
      <header className="shared-workspace-header">
        <span className="shared-readonly-badge"><i className="ri-eye-line" /> 唯讀檢視</span>
        <h1>{result?.data?.project_name || "分析助理 · 分享對話"}</h1>
        <p>免登入瀏覽 · 無法傳送指令、上傳檔案或修改對話</p>
      </header>
      {!result ? <p className="shared-status" role="status">對話載入中...</p>
        : result.error ? <p className="shared-status" role="alert">{result.error}</p>
        : <section className="messages-area" aria-label="分享的對話紀錄">
          {result.data.messages.length === 0 && <p className="shared-status">這個對話目前還沒有訊息。</p>}
          {result.data.messages.map((item) => {
            const message = { content: item.content || "", role: item.sender_type === "user" ? "user" : "assistant" };
            return (
              <div key={item.chat_id} className={`message-row ${message.role === "user" ? "user" : ""}`}>
                <div className={`message-avatar ${message.role === "user" ? "user-avatar" : "assistant-avatar"}`}>
                  <i className={message.role === "user" ? "ri-user-line" : "ri-robot-line"} />
                </div>
                <div className={`message-bubble ${message.role === "user" ? "user-bubble" : "assistant-bubble"}`}>
                  <MessageContent message={message} readOnly />
                </div>
              </div>
            );
          })}
        </section>}
    </main>
  );
}