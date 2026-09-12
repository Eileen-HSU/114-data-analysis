import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { apiUrl } from "../../lib/api";
import { MessageContent, WELCOME_MSG } from "./page";
import Navbar from "../../components/feature/Navbar";
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
  const messages = result?.data?.messages?.length
    ? result.data.messages.map((item) => ({
        id: item.chat_id, content: item.content || "",
        role: item.sender_type === "user" ? "user" : "assistant",
      }))
    : [WELCOME_MSG];

  return (
    <>
      <Navbar readOnly />
      <div className="workspace-page shared-workspace">
        <div className="workspace-body">
          <aside className="workspace-sidebar" aria-label="分享的對話">
            <div className="sidebar-header">
              <div className="d-flex align-items-center mb-3"><span className="sidebar-title">歷史對話紀錄</span></div>
              <div className="sidebar-search">
                <i className="ri-search-line" />
                <input placeholder="搜尋歷史對話紀錄..." aria-label="搜尋歷史對話紀錄（唯讀）" disabled />
              </div>
            </div>
            <div className="sidebar-list">
              {result?.data && <div className="session-item active" aria-current="true">
                <div className="session-info">
                  <h1 className="session-title">{result.data.project_name}</h1>
                  <p className="session-date">分享的對話 · 唯讀</p>
                </div>
              </div>}
            </div>
            <div className="sidebar-footer">
              <button className="btn-new-session sidebar-bottom-add" type="button" disabled aria-label="新增對話（唯讀模式無法使用）"><i className="ri-add-line" /></button>
            </div>
          </aside>
          <main className="workspace-main" aria-label={result?.data?.project_name || "分享對話"}>
            <div className="workspace-share-float">
              <span className="workspace-share-btn shared-view-label"><i className="ri-eye-line" /> 唯讀檢視</span>
            </div>
            <section className="messages-area" aria-label="分享的對話紀錄">
              {!result ? <p className="shared-status" role="status">對話載入中...</p>
                : result.error ? <p className="shared-status" role="alert">{result.error}</p>
                : messages.map((message) => (
                  <div key={message.id} className={`message-row ${message.role === "user" ? "user" : ""}`}>
                    <div className={`message-avatar ${message.role === "user" ? "user-avatar" : "assistant-avatar"}`}>
                      <i className={message.role === "user" ? "ri-user-line" : "ri-robot-line"} />
                    </div>
                    <div className={`message-bubble ${message.role === "user" ? "user-bubble" : "assistant-bubble"}`}>
                      <MessageContent message={message} readOnly />
                    </div>
                  </div>
                ))}
            </section>
            <div className="input-area">
              <div className="input-wrapper">
                <button className="attach-btn survey-pick-btn" type="button" disabled aria-label="選擇問卷（唯讀模式無法使用）"><i className="ri-survey-line" /></button>
                <button className="attach-btn" type="button" disabled aria-label="上傳檔案（唯讀模式無法使用）"><i className="ri-attachment-line" /></button>
                <textarea placeholder="此對話僅供檢視，無法輸入指令..." aria-label="對話輸入（唯讀）" rows={1} disabled />
                <button className="send-btn" type="button" disabled aria-label="傳送訊息（唯讀模式無法使用）"><i className="ri-send-plane-line" /></button>
              </div>
              <p className="input-hint">免登入瀏覽 · 僅能檢視此對話，無法傳送指令或修改內容</p>
            </div>
          </main>
        </div>
      </div>
    </>
  );
}
