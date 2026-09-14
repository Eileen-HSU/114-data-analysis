import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { apiUrl } from "../../lib/api";
import { MessageContent, WELCOME_MSG } from "./page";
import Navbar from "../../components/feature/Navbar";
import LoginRequiredModal from "../../components/feature/LoginRequiredModal";
import { useAuth } from "../../hooks/AuthContext";
import "./workspace.css";
import "./sharing.css";

export default function SharedWorkspacePage() {
  const { shareCode } = useParams();
  const navigate = useNavigate();
  const { isLoggedIn } = useAuth();
  const [loginFeature, setLoginFeature] = useState("");
  const requestNewChat = () => {
    if (!isLoggedIn) setLoginFeature("New conversation");
    else navigate("/workspace");
  };
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
        if (!response.ok) throw new Error(response.status === 404 ? "The invite link is invalid or has expired" : "Unable to load the conversation. Please refresh later.");
        if (!Array.isArray(data.messages)) throw new Error("Unable to load the conversation. Please refresh later.");
        setResult({ data });
      } catch (error) {
        if (!controller.signal.aborted) setResult({ error: error.message || "Unable to load the conversation. Please refresh later." });
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
      <Navbar readOnly onRequireLogin={setLoginFeature} />
      {loginFeature && <div className="shared-login-prompt"><LoginRequiredModal
        message={`Please log in to use this feature${loginFeature}。`}
        onLogin={() => navigate("/login")}
        onCancel={() => setLoginFeature("")}
      /></div>}
      <div className="workspace-page shared-workspace">
        <div className="workspace-body">
          <aside className="workspace-sidebar" aria-label="Shared conversation">
            <div className="sidebar-header">
              <div className="d-flex align-items-center mb-3"><span className="sidebar-title">Conversation history</span></div>
              <div className="sidebar-search">
                <i className="ri-search-line" />
                <input placeholder="Search conversation history…" aria-label="Search conversation history (read only)" disabled />
              </div>
            </div>
            <div className="sidebar-list">
              {result?.data && <div className="session-item active" aria-current="true">
                <div className="session-info">
                  <h1 className="session-title">{result.data.project_name}</h1>
                  <p className="session-date">Shared conversation · Guest view</p>
                </div>
              </div>}
            </div>
            <div className="sidebar-footer">
              <button className="btn-new-session sidebar-bottom-add" type="button" onClick={requestNewChat} aria-label="New conversation"><i className="ri-add-line" /></button>
            </div>
          </aside>
          <main className="workspace-main" aria-label={result?.data?.project_name || "Shared conversation"}>
            <div className="workspace-share-float">
              <span className="workspace-share-btn shared-view-label"><i className="ri-eye-line" /> Guest view</span>
            </div>
            <section className="messages-area" aria-label="Shared conversation history">
              {!result ? <p className="shared-status" role="status">Loading conversation...</p>
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
                <button className="attach-btn survey-pick-btn" type="button" onClick={() => navigate("/survey")} aria-label="Surveys"><i className="ri-survey-line" /></button>
                <button className="attach-btn" type="button" disabled aria-label="Upload file (unavailable in read-only mode)"><i className="ri-attachment-line" /></button>
                <textarea placeholder="This conversation is view only. Sending messages is disabled." aria-label="Message input (read only)" rows={1} disabled />
                <button className="send-btn" type="button" disabled aria-label="Send message (unavailable in read-only mode)"><i className="ri-send-plane-line" /></button>
              </div>
              <p className="input-hint">No login required · View only. Sending messages and editing are disabled.</p>
            </div>
          </main>
        </div>
      </div>
    </>
  );
}
