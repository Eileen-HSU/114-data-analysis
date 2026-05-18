import { useState, useRef, useEffect, useCallback } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import Navbar from "../../components/feature/Navbar";
import LoginRequiredModal from "../../components/feature/LoginRequiredModal";
import { useAuth } from "../../hooks/AuthContext";
import { useCollection } from "../../hooks/CollectionContext";
import { useActivity } from "../../hooks/ActivityContext";
import "./workspace.css";

const WELCOME_MSG = {
  id: "welcome",
  role: "assistant",
  content:
    "您好！我是 DataAnalysis 助手。系統目前已與雲端資料庫連線，請上傳您的資料檔案，或匯入您的問卷，我將在後續為您記錄所有對話脈絡。",
};
const ACTIVE_WORKSPACE_KEY = "dataanalysis_active_workspace";

// ── 輔助函式 ────────────────────────────────────────────────

function getStoredSurveyRecords(user) {
  let surveys = [];
  try {
    const stored = JSON.parse(localStorage.getItem("surveys") || "{}");
    surveys = Object.values(stored || {});
  } catch {
    surveys = [];
  }

  return surveys
    .filter((survey) => {
      if (!user) return false;
      if (!survey.ownerId && !survey.ownerEmail) return false;
      return survey.ownerId === user?.user_id || survey.ownerEmail === user?.email;
    })
    .map((survey) => ({
      id: survey.id || survey.code,
      title: survey.title,
      code: survey.code,
      createdAt: survey.createdAt,
      responseCount: survey.responses?.length || 0,
      detail: survey,
    }));
}

function buildSurveyChatContent(survey) {
  const ratingQuestions = survey.questions.filter((q) => q.type === "rating");
  const textQuestions = survey.questions.filter((q) => q.type !== "rating");
  const lines = [];
  lines.push(`📋 問卷名稱：${survey.title}`);
  lines.push(`🔑 問卷代碼：${survey.code}`);
  lines.push(`📅 建立日期：${survey.createdAt}`);
  lines.push(`👥 回覆人數：${survey.responses.length} 人`);
  lines.push(`❓ 題目數量：${survey.questions.length} 道`);
  lines.push("");
  if (ratingQuestions.length > 0) {
    lines.push("── 評分題統計 ──");
    ratingQuestions.forEach((q) => {
      let total = 0;
      let cnt = 0;
      survey.responses.forEach((r) => {
        const v = Number(r.answers[q.id]);
        if (!isNaN(v) && r.answers[q.id] !== "") { total += v; cnt++; }
      });
      const avg = cnt > 0 ? (total / cnt).toFixed(1) : "無資料";
      lines.push(`Q${survey.questions.indexOf(q) + 1}. ${q.title}`);
      lines.push(`   平均分：${avg} / 5（${cnt} 人作答）`);
    });
    lines.push("");
  }
  if (textQuestions.length > 0) {
    lines.push("── 問答題回覆 ──");
    textQuestions.forEach((q) => {
      const answers = survey.responses
        .map((r) => r.answers[q.id])
        .filter((a) => a && (Array.isArray(a) ? a.length > 0 : a !== ""));
      lines.push(`Q${survey.questions.indexOf(q) + 1}. ${q.title}（${answers.length} 人回答）`);
      answers.forEach((ans, i) => {
        const text = Array.isArray(ans) ? ans.join("、") : String(ans);
        lines.push(`   ${i + 1}. ${text}`);
      });
      lines.push("");
    });
  }
  lines.push("請根據以上問卷資料，幫我進行深度分析，包含：關鍵發現、趨勢洞察、以及改善建議。");
  return lines.join("\n");
}

function cleanMessageText(text) {
  return text.replace(/\*\*/g, "").replace(/^[\s\-•]+/, "").trim();
}

function parseAssistantTableRows(content) {
  const rows = [];
  let currentSection = "";

  content.split("\n").forEach((rawLine) => {
    const line = cleanMessageText(rawLine);
    if (!line) return;

    const numbered = line.match(/^(\d+)\.\s*(.+)$/);
    const bullet = line.match(/^[-]\s*(.+)$/);
    const colonIndex = line.indexOf("：");

    if (colonIndex > 0) {
      const label = line.slice(0, colonIndex).trim();
      const value = line.slice(colonIndex + 1).trim();
      rows.push({
        item: numbered ? numbered[2].split("：")[0].trim() : label,
        description: numbered ? numbered[2].slice(numbered[2].indexOf("：") + 1).trim() : value,
      });
      return;
    }

    if (numbered || bullet) {
      rows.push({
        item: numbered ? `項目 ${numbered[1]}` : currentSection || "重點",
        description: numbered ? numbered[2] : bullet[1],
      });
      return;
    }

    if (line.length <= 18) {
      currentSection = line;
      rows.push({ item: "分類", description: line });
      return;
    }

    rows.push({ item: currentSection || "摘要", description: line });
  });

  return rows;
}

function PlainMessageContent({ content }) {
  const lines = content.split("\n");
  return lines.map((line, i) => (
    <span key={i}>{line}{i < lines.length - 1 && <br />}</span>
  ));
}

// 這裡只保留文字輸出，方便除錯，拿掉原本的假 Table 邏輯
function MessageContent({ message }) {
  return <PlainMessageContent content={message.content} />;
}

function buildAutoSessionTitle(text, file) {
  if (file?.name) {
    const baseName = file.name.replace(/\.[^/.]+$/, "");
    return `分析：${baseName}`.slice(0, 28);
  }

  const cleaned = text
    .replace(/\s+/g, " ")
    .replace(/[，。！？、,.!?]/g, " ")
    .trim();

  if (!cleaned) return "新工作區";
  return cleaned.length > 18 ? `${cleaned.slice(0, 18)}...` : cleaned;
}

// ── 主元件 ──────────────────────────────────────────────────

export default function WorkspacePage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { isLoggedIn, user } = useAuth();
  const { recordActivity } = useActivity();

  const { addChatToCollection, syncChatTitle, deleteChatSession, workspaceSessions: sessions, setWorkspaceSessions: setSessions } = useCollection();
  const [activeSessionId, setActiveSessionId] = useState(null);
  const [input, setInput] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const [attachedFile, setAttachedFile] = useState(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [renamingId, setRenamingId] = useState(null);
  const [renameValue, setRenameValue] = useState("");
  const [showSurveyPicker, setShowSurveyPicker] = useState(false);
  const [surveyPickerSearch, setSurveyPickerSearch] = useState("");
  const [toastMsg, setToastMsg] = useState(null);
  const toastTimerRef = useRef(null);

  const messagesEndRef = useRef(null);
  const fileInputRef = useRef(null);
  const textareaRef = useRef(null);
  const surveyPickerRef = useRef(null);

  const showToast = (msg) => {
    setToastMsg(msg);
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    toastTimerRef.current = setTimeout(() => setToastMsg(null), 3000);
  };

  const activeSession = sessions.find((s) => s.id === activeSessionId) ?? null;
  const messages = activeSession?.messages ?? [];

  // 從後端真實撈取使用者的雲端 Workspace 專案清單
  useEffect(() => {
    if (!isLoggedIn || !user?.user_id) return;
    
    const fetchUserWorkspaces = async () => {
      try {
        const res = await fetch(`/api/workspace/user/${user.user_id}`);
        if (!res.ok) throw new Error("無法載入雲端專案紀錄");
        const data = await res.json();
        
        // 轉化為前端可讀的歷史紀錄陣列
        const formattedSessions = data.map(w => ({
          id: w.project_id.toString(),
          title: w.project_name,
          messages: [WELCOME_MSG] 
        }));
        
        setSessions(formattedSessions);
        
        if (formattedSessions.length > 0) {
          const savedId = localStorage.getItem(ACTIVE_WORKSPACE_KEY);
          const restored = formattedSessions.find((s) => s.id === savedId);
          setActiveSessionId(restored?.id || formattedSessions[0].id);
        }
      } catch (err) {
        showToast(err.message);
      }
    };
    
    fetchUserWorkspaces();
  }, [isLoggedIn, user?.user_id]);

  useEffect(() => {
    if (!activeSessionId) return;
    localStorage.setItem(ACTIVE_WORKSPACE_KEY, activeSessionId);
  }, [activeSessionId]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isTyping]);

  useEffect(() => {
    const handleClickOutside = (e) => {
      if (surveyPickerRef.current && !surveyPickerRef.current.contains(e.target)) {
        setShowSurveyPicker(false);
      }
    };
    if (showSurveyPicker) document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [showSurveyPicker]);

  // Handle open session from collection
  useEffect(() => {
    const state = location.state;
    if (!state?.openSession) return;
    const { sessionId } = state.openSession;
    setActiveSessionId(sessionId);
    window.history.replaceState({}, "");
  }, [location.state]);

  const appendMessage = useCallback((sessionId, msg) => {
    setSessions((prev) =>
      prev.map((s) => s.id === sessionId ? { ...s, messages: [...s.messages, msg] } : s)
    );
  }, []);

  // 問卷匯入對接：建立 Workspace 專案，並將資料以「使用者訊息」寫入後端 Chat_History 表
  const handleSelectSurvey = async (record) => {
    const detail = record.detail;
    if (!detail) return;
    
    const content = buildSurveyChatContent(detail);
    const sessionTitle = `問卷分析：${record.title}`;
    
    try {
      setIsTyping(true);
      setShowSurveyPicker(false);
      setSurveyPickerSearch("");

      // 呼叫 /api/workspace 路由，寫入一筆專案資料到資料庫
      const workspaceRes = await fetch("/api/workspace", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: user.user_id,
          project_name: sessionTitle,
          status: "Imported" // 標記為問卷已匯入
        })
      });

      if (!workspaceRes.ok) throw new Error("資料庫專案建立失敗");
      const serverWorkspace = await workspaceRes.json();
      const realProjectId = serverWorkspace.project_id.toString();

      const userMsg = { id: `u-${Date.now()}`, role: "user", content };
      const newSession = {
        id: realProjectId,
        title: sessionTitle,
        date: new Date().toLocaleDateString(),
        messages: [WELCOME_MSG, userMsg],
      };
      setSessions((prev) => [newSession, ...prev]);
      setActiveSessionId(realProjectId);
      addChatToCollection(sessionTitle, realProjectId);

      // 把問卷大文字當作第一筆 Chat_History 寫入 MySQL
      const saveChatRes = await fetch("/api/chat/history", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: serverWorkspace.project_id,
          sender_type: "user",
          message_content: content
        })
      });

      if (!saveChatRes.ok) throw new Error("Chat_History 寫入失敗");

      // 還沒串 AI，在前端手動補一筆純文字提醒，代表資料庫已記錄
      const localAiReply = {
        id: `a-${Date.now()}`,
        role: "assistant",
        content: `【系統提示】問卷「${record.title}」的結構化統計大文字已成功寫入資料庫的 Chat_History 表中。目前尚未接通大模型 (Gemini) 運算服務。`
      };
      appendMessage(realProjectId, localAiReply);

    } catch (err) {
      showToast(`匯入錯誤: ${err.message}`);
    } finally {
      setIsTyping(false);
    }
  };

  const filteredSurveyPicker = getStoredSurveyRecords(user).filter(
    (s) =>
      s.title.toLowerCase().includes(surveyPickerSearch.toLowerCase()) ||
      s.code.toLowerCase().includes(surveyPickerSearch.toLowerCase())
  );

  // 3. 🚀 一般訊息對接：傳送訊息給後端，並將對話內容儲存至 Chat_History
  const sendMessage = async () => {
    if (!input.trim() && !attachedFile) return;
    if (!activeSessionId) return;

    const content = attachedFile ? `[檔案：${attachedFile.name}] ${input}` : input;
    const autoTitle = buildAutoSessionTitle(input, attachedFile);
    const userMsg = { id: Date.now().toString(), role: "user", content };
    
    let isNewWorkspace = false;
    let targetProjectId = activeSessionId;

    // 前端同步亮出使用者打的字
    setSessions((prev) =>
      prev.map((s) => {
        if (s.id !== activeSessionId) return s;
        if (s.title === "新工作區") isNewWorkspace = true;
        return {
          ...s,
          title: s.title === "新工作區" ? autoTitle : s.title,
          messages: [...s.messages, userMsg],
        };
      })
    );

    setInput("");
    setAttachedFile(null);
    setIsTyping(true);

    try {
      // 如果原本是新工作區，在發出第一條訊息時，同步去更新後端的專案名稱
      if (isNewWorkspace) {
        await fetch(`/api/workspace/${activeSessionId}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ project_name: autoTitle })
        });
        syncChatTitle(activeSessionId, autoTitle);
      }

      recordActivity({
        text: `在工作區送出訊息「${autoTitle}」`,
        icon: "ri-message-3-line",
        iconBg: "bg-stat-mauve",
        iconColor: "text-stat-mauve",
      });

      // 🚀 【純資料庫寫入】呼叫後端 API，將這段聊天訊息存入 MySQL 裡的 Chat_History
      const res = await fetch("/api/chat/history", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: parseInt(targetProjectId),
          sender_type: "user",
          message_content: content
        })
      });

      if (!res.ok) throw new Error("Chat_History 寫入失敗");

      // 💡 前端直接返回一個接收成功的提示訊息（因為還沒串 AI）
      appendMessage(targetProjectId, {
        id: Date.now().toString(),
        role: "assistant",
        content: `【系統接收成功】您的訊息已被安全寫入資料庫。目前未串接 AI 模組，以下為您輸入的內文複誦：\n\n"${content}"`
      });

    } catch (err) {
      showToast(`通訊失敗: ${err.message}`);
    } finally {
      setIsTyping(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const handleTextareaInput = () => {
    const ta = textareaRef.current;
    if (ta) {
      ta.style.height = "auto";
      ta.style.height = Math.min(ta.scrollHeight, 144) + "px";
    }
  };

  const filteredSessions = sessions.filter((s) =>
    s.title.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const startRename = (s) => {
    setRenamingId(s.id);
    setRenameValue(s.title);
  };

  // 4. 🚀 重新命名對接：同步修改資料庫中的專案名稱
  const saveRename = async (id) => {
    const trimmed = renameValue.trim();
    if (!trimmed) {
      setRenamingId(null);
      return;
    }

    try {
      const res = await fetch(`/api/workspace/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_name: trimmed })
      });

      if (!res.ok) throw new Error("無法同步雲端專案名稱");
      
      setSessions((prev) => prev.map((s) => (s.id === id ? { ...s, title: trimmed } : s)));
      syncChatTitle(id, trimmed);
    } catch (err) {
      showToast(err.message);
    } finally {
      setRenamingId(null);
    }
  };

  // 5. 🚀 刪除專案對接：呼叫後端 DELETE 進行軟刪除
  const deleteSession = async (sessionId) => {
    const session = sessions.find((s) => s.id === sessionId);
    if (!session) return;
    const ok = window.confirm(`確定要刪除「${session.title}」嗎？刪除後可在作品集的最近刪除中還原。`);
    if (!ok) return;

    try {
      const res = await fetch(`/api/workspace/${sessionId}`, {
        method: "DELETE"
      });

      if (!res.ok) throw new Error("刪除雲端專案失敗");

      deleteChatSession(sessionId);
      setSessions((prev) => prev.filter(s => s.id !== sessionId));
      setRenamingId(null);
      setSearchQuery("");
      
      if (activeSessionId === sessionId) {
        const remaining = sessions.filter((s) => s.id !== sessionId);
        const nextSession = remaining[0] || null;
        setActiveSessionId(nextSession?.id || null);
        if (nextSession?.id) {
          localStorage.setItem(ACTIVE_WORKSPACE_KEY, nextSession.id);
        } else {
          localStorage.removeItem(ACTIVE_WORKSPACE_KEY);
        }
      }
      showToast("已刪除工作區，並移至最近刪除");
    } catch (err) {
      showToast(err.message);
    }
  };

  // 6. 🚀 新增工作區對接：呼叫後端 POST 先建立一筆 project_id
  const createNewSession = async () => {
    try {
      const title = "新工作區";
      const res = await fetch("/api/workspace", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: user.user_id,
          project_name: title,
          status: "Pending"
        })
      });

      if (!res.ok) throw new Error("無法在雲端建立新工作區");
      const serverWorkspace = await res.json();
      const realProjectId = serverWorkspace.project_id.toString();

      const newSession = {
        id: realProjectId,
        title,
        date: new Date().toLocaleDateString(),
        messages: [WELCOME_MSG],
      };
      
      setSessions((prev) => [newSession, ...prev]);
      setActiveSessionId(realProjectId);
      addChatToCollection(title, realProjectId);
    } catch (err) {
      showToast(err.message);
    }
  };

  // ── 以下為 UI 渲染，無縫完整保留 ──────────────────────────────

  if (!isLoggedIn) {
    return (
      <>
        <Navbar />
        <div className="workspace-page" style={{ display: "flex", alignItems: "center", justifyContent: "center" }}>
          <LoginRequiredModal
            message="新增工作區需要登入帳號才能使用，登入後即可開始分析資料。"
            onLogin={() => navigate("/login")}
            onCancel={() => navigate("/")}
          />
        </div>
      </>
    );
  }

  return (
    <>
      <Navbar />
      {toastMsg && (
        <div style={{
          position: "fixed", bottom: 32, left: "50%", transform: "translateX(-50%)",
          background: "#3d2b2b", color: "#fff", borderRadius: 10,
          padding: "10px 22px", fontSize: 14, fontWeight: 600,
          zIndex: 9999, display: "flex", alignItems: "center", gap: 8,
          boxShadow: "0 4px 16px rgba(0,0,0,0.18)", whiteSpace: "nowrap",
        }}>
          <i className="ri-checkbox-circle-line" style={{ color: "#a8e6a3", fontSize: 16 }}></i>
          {toastMsg}
        </div>
      )}
      <div className="workspace-page">
        <div className="workspace-body">
          <aside className="workspace-sidebar">
            <div className="sidebar-header">
              <div className="d-flex align-items-center justify-content-between mb-3">
                <span className="sidebar-title">歷史紀錄</span>
                <button className="btn-new-session" onClick={createNewSession} title="新增工作區">
                  <i className="ri-add-line"></i>
                </button>
              </div>
              <div className="sidebar-search">
                <i className="ri-search-line"></i>
                <input
                  type="text"
                  placeholder="搜尋歷史紀錄..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                />
                {searchQuery && (
                  <button className="search-clear" onClick={() => setSearchQuery("")}>
                    <i className="ri-close-line"></i>
                  </button>
                )}
              </div>
            </div>
            <div className="sidebar-list">
              {sessions.length === 0 ? (
                <div className="sidebar-empty">
                  <i className="ri-chat-ai-line"></i>
                  <p>尚無工作區紀錄</p>
                  <button
                    onClick={createNewSession}
                    style={{
                      marginTop: 8, background: "#c9a0a0", color: "white",
                      border: "none", borderRadius: 8, padding: "6px 14px",
                      fontSize: 12, fontWeight: 700, cursor: "pointer",
                    }}
                  >
                    新增工作區
                  </button>
                </div>
              ) : filteredSessions.length === 0 ? (
                <div className="sidebar-empty">
                  <i className="ri-search-line"></i>
                  <p>找不到相關紀錄</p>
                </div>
              ) : (
                filteredSessions.map((s) => (
                  <div
                    key={s.id}
                    className={`session-item ${activeSessionId === s.id ? "active" : ""}`}
                    onClick={() => setActiveSessionId(s.id)}
                  >
                    <div className="session-info flex-grow-1">
                      {renamingId === s.id ? (
                        <input
                          className="form-control form-control-sm"
                          value={renameValue}
                          autoFocus
                          onChange={(e) => setRenameValue(e.target.value)}
                          onBlur={() => saveRename(s.id)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") saveRename(s.id);
                            if (e.key === "Escape") setRenamingId(null);
                          }}
                          onClick={(e) => e.stopPropagation()}
                          style={{ fontSize: 14, fontWeight: 600 }}
                        />
                      ) : (
                        <p className="session-title" onDoubleClick={() => startRename(s)}>
                          {s.title}
                        </p>
                      )}
                      <p className="session-date">{s.date}</p>
                    </div>
                    <button
                      className="session-edit"
                      onClick={(e) => { e.stopPropagation(); startRename(s); }}
                      title="重新命名"
                    >
                      <i className="ri-pencil-line"></i>
                    </button>
                    <button
                      className="session-delete"
                      onClick={(e) => { e.stopPropagation(); deleteSession(s.id); }}
                      title="刪除工作區"
                    >
                      <i className="ri-delete-bin-line"></i>
                    </button>
                  </div>
                ))
              )}
            </div>
          </aside>

          <main className="workspace-main">
            {activeSession === null ? (
              <div style={{
                flex: 1, display: "flex", flexDirection: "column",
                alignItems: "center", justifyContent: "center",
                color: "#b08080", gap: 16,
              }}>
                <div style={{
                  width: 64, height: 64, background: "#f5e8e6",
                  borderRadius: "50%", display: "flex", alignItems: "center",
                  justifyContent: "center", fontSize: 28,
                }}>
                  <i className="ri-chat-ai-line"></i>
                </div>
                <p style={{ fontSize: 15, fontWeight: 600, margin: 0 }}>選擇或新增一個工作區開始分析</p>
                <button
                  onClick={createNewSession}
                  style={{
                    background: "#c9a0a0", color: "white", border: "none",
                    borderRadius: 10, padding: "10px 24px", fontSize: 14,
                    fontWeight: 700, cursor: "pointer",
                  }}
                >
                  <i className="ri-add-line" style={{ marginRight: 6 }}></i>新增工作區
                </button>
              </div>
            ) : (
              <>
                <div className="messages-area">
                  {messages.map((msg) => (
                    <div key={msg.id} className={`message-row ${msg.role === "user" ? "user" : ""}`}>
                      <div className={`message-avatar ${msg.role === "user" ? "user-avatar" : "assistant-avatar"}`}>
                        <i className={msg.role === "user" ? "ri-user-line" : "ri-robot-line"}></i>
                      </div>
                      <div className={`message-bubble ${msg.role === "user" ? "user-bubble" : "assistant-bubble"}`}>
                        <MessageContent message={msg} />
                      </div>
                    </div>
                  ))}
                  {isTyping && (
                    <div className="message-row">
                      <div className="message-avatar assistant-avatar">
                        <i className="ri-robot-line"></i>
                      </div>
                      <div className="message-bubble assistant-bubble typing-bubble">
                        <div className="typing-dots">
                          <span></span><span></span><span></span>
                        </div>
                      </div>
                    </div>
                  )}
                  <div ref={messagesEndRef}></div>
                </div>

                <div className="input-area">
                  {attachedFile && (
                    <div className="file-attachment">
                      <i className="ri-attachment-line"></i>
                      <span>{attachedFile.name}</span>
                      <button onClick={() => setAttachedFile(null)}>
                        <i className="ri-close-line"></i>
                      </button>
                    </div>
                  )}
                  <div className="input-wrapper">
                    <div className="survey-picker-wrapper" ref={surveyPickerRef}>
                      <button
                        className={`attach-btn survey-pick-btn${showSurveyPicker ? " active" : ""}`}
                        onClick={() => setShowSurveyPicker((v) => !v)}
                        title="選擇問卷分析"
                      >
                        <i className="ri-survey-line"></i>
                      </button>
                      {showSurveyPicker && (
                        <div className="survey-picker-panel">
                          <div className="survey-picker-header">
                            <span className="survey-picker-title">
                              <i className="ri-survey-line"></i>
                              選擇問卷進行分析
                            </span>
                            <button className="survey-picker-close" onClick={() => setShowSurveyPicker(false)}>
                              <i className="ri-close-line"></i>
                            </button>
                          </div>
                          <div className="survey-picker-search">
                            <i className="ri-search-line"></i>
                            <input
                              type="text"
                              placeholder="搜尋問卷名稱或代碼..."
                              value={surveyPickerSearch}
                              onChange={(e) => setSurveyPickerSearch(e.target.value)}
                              autoFocus
                            />
                            {surveyPickerSearch && (
                              <button onClick={() => setSurveyPickerSearch("")}>
                                <i className="ri-close-circle-line"></i>
                              </button>
                            )}
                          </div>
                          <div className="survey-picker-list">
                            {filteredSurveyPicker.length === 0 ? (
                              <div className="survey-picker-empty">
                                <i className="ri-search-line"></i>
                                <p>找不到相關問卷</p>
                              </div>
                            ) : (
                              filteredSurveyPicker.map((s) => (
                                <button
                                  key={s.id}
                                  className="survey-picker-item"
                                  onClick={() => handleSelectSurvey(s)}
                                >
                                  <div className={`survey-picker-icon${s.status === "active" ? " active" : ""}`}>
                                    <i className="ri-survey-line"></i>
                                  </div>
                                  <div className="survey-picker-info">
                                    <span className="survey-picker-name">{s.title}</span>
                                    <div className="survey-picker-meta">
                                      <span><i className="ri-key-2-line"></i>{s.code}</span>
                                      <span><i className="ri-user-line"></i>{s.responseCount} 人回覆</span>
                                      <span><i className="ri-calendar-line"></i>{s.createdAt}</span>
                                    </div>
                                  </div>
                                  <span className={`survey-picker-status${s.status === "active" ? " active" : ""}`}>
                                    {s.status === "active" ? "進行中" : "已結束"}
                                  </span>
                                </button>
                              ))
                            )}
                          </div>
                        </div>
                      )}
                    </div>

                    <button
                      className="attach-btn"
                      onClick={() => fileInputRef.current?.click()}
                      title="附加檔案"
                    >
                      <i className="ri-attachment-line"></i>
                    </button>
                    <input
                      ref={fileInputRef}
                      type="file"
                      className="d-none"
                      accept=".csv,.xlsx,.json,.txt"
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (!f) return;
                        setAttachedFile(f);
                        showToast(`「${f.name}」已準備上傳`);
                        e.target.value = "";
                      }}
                    />
                    <textarea
                      ref={textareaRef}
                      rows={1}
                      placeholder="輸入您的問題或上傳檔案進行分析..."
                      value={input}
                      onChange={(e) => setInput(e.target.value)}
                      onInput={handleTextareaInput}
                      onKeyDown={handleKeyDown}
                    />
                    <button
                      className="send-btn"
                      onClick={sendMessage}
                      disabled={!input.trim() && !attachedFile}
                    >
                      <i className="ri-send-plane-line"></i>
                    </button>
                  </div>
                  <p className="input-hint">
                    <i className="ri-survey-line" style={{ marginRight: 4 }}></i>
                    點擊問卷圖示可直接選擇問卷分析 · 支援 CSV、Excel、JSON、TXT · Enter 發送
                  </p>
                </div>
              </>
            )}
          </main>
        </div>
      </div>
    </>
  );
}