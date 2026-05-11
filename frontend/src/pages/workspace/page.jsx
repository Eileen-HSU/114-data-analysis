import { useState, useRef, useEffect, useCallback } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import Navbar from "../../components/feature/Navbar";
import LoginRequiredModal from "../../components/feature/LoginRequiredModal";
import { useAuth } from "../../hooks/AuthContext";
import { useCollection } from "../../hooks/CollectionContext";
import "./workspace.css";

const WELCOME_MSG = {
  id: "welcome",
  role: "assistant",
  content:
    "您好！我是 DataAnalysis AI 助手。請上傳您的資料檔案（CSV、Excel、JSON 或 TXT），或直接輸入您的分析問題，我將為您提供深度洞察。",
};
const ACTIVE_WORKSPACE_KEY = "dataanalysis_active_workspace";

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
  return text
    .replace(/\*\*/g, "")
    .replace(/^[\s\-•]+/, "")
    .trim();
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

function AssistantTableContent({ content }) {
  const rows = parseAssistantTableRows(content);

  if (rows.length < 2) {
    return <PlainMessageContent content={content} />;
  }

  return (
    <div className="assistant-output-table-wrap">
      <table className="assistant-output-table">
        <thead>
          <tr>
            <th>項目</th>
            <th>說明</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={`${row.item}-${index}`}>
              <td>{row.item}</td>
              <td>{row.description}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MessageContent({ message }) {
  if (message.role === "assistant") {
    return <AssistantTableContent content={message.content} />;
  }

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

export default function WorkspacePage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { isLoggedIn, user } = useAuth();


  const { addChatToCollection, addFileToCollection, syncChatTitle, workspaceSessions: sessions, setWorkspaceSessions: setSessions } = useCollection();
  const [showLoginModal] = useState(!isLoggedIn);
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
  const surveyImportHandled = useRef(false);
  const surveyPickerRef = useRef(null);

  const showToast = (msg) => {
    setToastMsg(msg);
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    toastTimerRef.current = setTimeout(() => setToastMsg(null), 3000);
  };

  const activeSession = sessions.find((s) => s.id === activeSessionId) ?? null;
  const messages = activeSession?.messages ?? [];

  useEffect(() => {
    if (activeSessionId || sessions.length === 0) return;
    const savedId = localStorage.getItem(ACTIVE_WORKSPACE_KEY);
    const restored = sessions.find((s) => s.id === savedId);
    setActiveSessionId(restored?.id || sessions[0].id);
  }, [activeSessionId, sessions]);

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

  // Handle survey import from profile page
  useEffect(() => {
    const state = location.state;
    if (!state?.surveyImport || surveyImportHandled.current) return;
    surveyImportHandled.current = true;
    const { sessionTitle, message } = state.surveyImport;
    const newId = `survey-${Date.now()}`;
    const userMsg = { id: `u-${Date.now()}`, role: "user", content: message };
    const newSession = {
      id: newId,
      title: sessionTitle,
      date: "2026/4/25",
      messages: [WELCOME_MSG, userMsg],
    };
    setSessions((prev) => [newSession, ...prev]);
    setActiveSessionId(newId);
    setIsTyping(true);
    setTimeout(() => {
      const aiReply = {
        id: `a-${Date.now()}`,
        role: "assistant",
        content:
          "我已收到您的問卷資料，以下是初步分析結果：\n\n" +
          "**📊 評分題洞察**\n整體平均分表現良好，可進一步比較不同分組的差異。\n\n" +
          "**💬 問答題主題分析**\n回覆內容集中在幾個核心議題，建議進行情感分析以量化正負回饋比例。\n\n" +
          "**💡 建議**\n可進一步詢問：想針對哪道題目深入分析？或需要我生成完整分析報告？",
      };
      setSessions((prev) =>
        prev.map((s) => s.id === newId ? { ...s, messages: [...s.messages, aiReply] } : s)
      );
      setIsTyping(false);
    }, 1800);
    window.history.replaceState({}, "");
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const appendMessage = useCallback((sessionId, msg) => {
    setSessions((prev) =>
      prev.map((s) => s.id === sessionId ? { ...s, messages: [...s.messages, msg] } : s)
    );
  }, []);

  const handleSelectSurvey = (record) => {
    const detail = record.detail;
    if (!detail) return;
    const content = buildSurveyChatContent(detail);
    const newId = `survey-${Date.now()}`;
    const userMsg = { id: `u-${Date.now()}`, role: "user", content };
    const newSession = {
      id: newId,
      title: `問卷分析：${record.title}`,
      date: "2026/4/25",
      messages: [WELCOME_MSG, userMsg],
    };
    setSessions((prev) => [newSession, ...prev]);
    setActiveSessionId(newId);
    setShowSurveyPicker(false);
    setSurveyPickerSearch("");
    addChatToCollection(`問卷分析：${record.title}`, newId);
    setIsTyping(true);
    setTimeout(() => {
      const aiReply = {
        id: `a-${Date.now()}`,
        role: "assistant",
        content:
          `我已收到「${record.title}」的問卷資料，以下是初步分析結果：\n\n` +
          "📊 **評分題洞察**\n整體平均分表現良好，可進一步比較不同分組的差異。\n\n" +
          "💬 **問答題主題分析**\n回覆內容集中在幾個核心議題，建議進行情感分析以量化正負回饋比例。\n\n" +
          "💡 **建議**\n可進一步詢問：想針對哪道題目深入分析？或需要我生成完整分析報告？",
      };
      setSessions((prev) =>
        prev.map((s) => s.id === newId ? { ...s, messages: [...s.messages, aiReply] } : s)
      );
      setIsTyping(false);
    }, 1800);
  };

  const filteredSurveyPicker = getStoredSurveyRecords(user).filter(
    (s) =>
      s.title.toLowerCase().includes(surveyPickerSearch.toLowerCase()) ||
      s.code.toLowerCase().includes(surveyPickerSearch.toLowerCase())
  );

  const sendMessage = () => {
    if (!input.trim() && !attachedFile) return;
    if (!activeSessionId) return;
    const content = attachedFile ? `[檔案：${attachedFile.name}] ${input}` : input;
    const autoTitle = buildAutoSessionTitle(input, attachedFile);
    const userMsg = { id: Date.now().toString(), role: "user", content };
    setSessions((prev) =>
      prev.map((s) => {
        if (s.id !== activeSessionId) return s;
        const shouldAutoTitle = s.title === "新工作區";
        return {
          ...s,
          title: shouldAutoTitle ? autoTitle : s.title,
          messages: [...s.messages, userMsg],
        };
      })
    );
    const session = sessions.find((s) => s.id === activeSessionId);
    if (session?.title === "新工作區") {
      syncChatTitle(activeSessionId, autoTitle);
    }
    setInput("");
    setAttachedFile(null);
    setIsTyping(true);
    const sid = activeSessionId;
    setTimeout(() => {
      const aiResponses = [
        "根據您上傳的資料，我發現以下幾個關鍵趨勢：\n\n1. **銷售成長**：Q3 相比 Q2 成長了 23.5%，主要由電子產品類別驅動。\n2. **客戶留存率**：整體留存率為 78%，高於行業平均的 65%。\n3. **異常值**：第 47 行數據存在異常，建議進一步核查。\n\n需要我針對某個特定面向進行更深入的分析嗎？",
        "我已分析您的問題。根據資料顯示，主要發現如下：\n\n- 數據集包含 1,247 筆記錄，涵蓋 12 個維度\n- 缺失值比例為 2.3%，建議使用均值填補\n- 相關性分析顯示「收入」與「廣告支出」呈強正相關（r=0.87）\n\n是否需要我生成視覺化報告？",
        "這是個很好的問題！根據統計分析：\n\n**描述性統計**\n- 平均值：4,523\n- 中位數：4,102\n- 標準差：892\n\n**建議**：數據分佈略呈右偏，建議考慮對數轉換以改善模型效果。",
      ];
      const reply = aiResponses[Math.floor(Math.random() * aiResponses.length)];
      appendMessage(sid, { id: Date.now().toString(), role: "assistant", content: reply });
      setIsTyping(false);
    }, 1500);
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

  const saveRename = (id) => {
    const trimmed = renameValue.trim();
    if (trimmed) {
      setSessions((prev) => prev.map((s) => (s.id === id ? { ...s, title: trimmed } : s)));
      // sync title to collection chat file
      syncChatTitle(id, trimmed);
    }
    setRenamingId(null);
  };

  const createNewSession = () => {
    const newId = Date.now().toString();
    const title = "新工作區";
    const newSession = {
      id: newId,
      title,
      date: "2026/4/25",
      messages: [WELCOME_MSG],
    };
    setSessions((prev) => [newSession, ...prev]);
    setActiveSessionId(newId);
    addChatToCollection(title, newId);
  };

  if (showLoginModal) {
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
      {/* Toast */}
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
          {/* Sidebar */}
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
                  </div>
                ))
              )}
            </div>
          </aside>

          {/* Main Chat */}
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

                {/* Input Area */}
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
                    {/* Survey Picker Button */}
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

                    {/* File Attach Button */}
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
                        addFileToCollection(f);
                        showToast(`「${f.name}」已加入作品集`);
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
