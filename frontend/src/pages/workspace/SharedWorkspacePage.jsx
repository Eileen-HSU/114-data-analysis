import InterfaceText from "../../components/feature/InterfaceText";
import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { apiUrl } from "../../lib/api";
import { MessageContent, WELCOME_MSG } from "./page";
import Navbar from "../../components/feature/Navbar";
import LoginRequiredModal from "../../components/feature/LoginRequiredModal";
import { useLanguage } from "../../context/LanguageContext";
import "./workspace.css";
import "./sharing.css";

export default function SharedWorkspacePage() {
  const { shareCode } = useParams();
  const navigate = useNavigate();
  const { language } = useLanguage();
  const [loginFeature, setLoginFeature] = useState("");
  const [isLeaveConfirmOpen, setIsLeaveConfirmOpen] = useState(false);
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
  const isEnglish = language === "en";
  const requestLeaveSharedChat = () => setIsLeaveConfirmOpen(true);
  const confirmLeaveSharedChat = () => navigate("/survey", { replace: true });

  return (
    <>
      <Navbar
        readOnly
        onRequireLogin={setLoginFeature}
        sharedAssistantPath={`/shared/${encodeURIComponent(shareCode)}`}
        onSurveyNavigate={requestLeaveSharedChat}
      />
      {loginFeature && <div className="shared-login-prompt"><LoginRequiredModal
        message={`請先登入才能使用${loginFeature}。`}
        onLogin={() => navigate("/login")}
        onCancel={() => setLoginFeature("")}
      /></div>}
      <div className="workspace-page shared-workspace">
        <div className="workspace-body">
          <aside className="workspace-sidebar" aria-label="分享的對話">
            <div className="sidebar-header">
              <div className="d-flex align-items-center mb-3"><span className="sidebar-title"><InterfaceText>{"歷史對話紀錄"}</InterfaceText></span></div>
              <div className="sidebar-search">
                <i className="ri-search-line" />
                <input placeholder="搜尋歷史對話紀錄..." aria-label="搜尋歷史對話紀錄（唯讀）" disabled />
              </div>
            </div>
            <div className="sidebar-list">
              {result?.data && <div className="session-item active" aria-current="true">
                <div className="session-info">
                  <h1 className="session-title">{result.data.project_name}</h1>
                  <p className="session-date">分享的對話 · 訪客檢視</p>
                </div>
              </div>}
            </div>
            <div className="sidebar-footer">
              <button className="btn-new-session sidebar-bottom-add" type="button" disabled title="此分享連結僅供檢視目前對話" aria-label="無法在分享頁建立新對話"><i className="ri-add-line" /></button>
            </div>
          </aside>
          <main className="workspace-main" aria-label={result?.data?.project_name || "分享對話"}>
            <div className="workspace-share-float">
              <span className="workspace-share-btn shared-view-label"><i className="ri-eye-line" /><InterfaceText>{"訪客檢視"}</InterfaceText></span>
            </div>
            <section className="messages-area" aria-label="分享的對話紀錄">
              {!result ? <p className="shared-status" role="status"><InterfaceText>{"對話載入中..."}</InterfaceText></p>
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
                <button className="attach-btn survey-pick-btn" type="button" onClick={requestLeaveSharedChat} aria-label="問卷調查"><i className="ri-survey-line" /></button>
                <button className="attach-btn" type="button" disabled aria-label="上傳檔案（唯讀模式無法使用）"><i className="ri-attachment-line" /></button>
                <textarea placeholder="此對話僅供檢視，無法輸入指令..." aria-label="對話輸入（唯讀）" rows={1} disabled />
                <button className="send-btn" type="button" disabled aria-label="傳送訊息（唯讀模式無法使用）"><i className="ri-send-plane-line" /></button>
              </div>
              <p className="input-hint"><InterfaceText>{"免登入瀏覽 · 僅能檢視此對話，無法傳送指令或修改內容"}</InterfaceText></p>
            </div>
          </main>
        </div>
      </div>
      {isLeaveConfirmOpen && (
        <div className="workspace-modal-backdrop shared-leave-confirm" onClick={() => setIsLeaveConfirmOpen(false)}>
          <section className="workspace-alert-modal" role="dialog" aria-modal="true" aria-labelledby="shared-leave-title" onClick={(event) => event.stopPropagation()}>
            <div className="workspace-alert-icon"><i className="ri-error-warning-line" /></div>
            <h3 id="shared-leave-title">{isEnglish ? "Leave this shared chat?" : "確定要離開此分享對話嗎？"}</h3>
            <p>{isEnglish
              ? "After leaving, this shared chat will not be kept as a return link. To view it again, paste the original invite link."
              : "離開後不會保留回到此分享對話的入口；若要再次瀏覽，請重新貼上原始邀請連結。"}</p>
            <div className="workspace-alert-actions">
              <button className="workspace-alert-primary" type="button" onClick={confirmLeaveSharedChat}>{isEnglish ? "Leave" : "確定離開"}</button>
              <button className="workspace-alert-secondary" type="button" onClick={() => setIsLeaveConfirmOpen(false)}>{isEnglish ? "Cancel" : "取消"}</button>
            </div>
          </section>
        </div>
      )}
    </>
  );
}
