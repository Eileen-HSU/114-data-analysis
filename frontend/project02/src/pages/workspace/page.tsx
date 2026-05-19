// Workspace 工作區頁面
import { useState, useRef, useCallback, memo } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";
import { mockSessions, mockCurrentMessages } from "@/mocks/workspace";
import Navbar from "@/components/feature/Navbar";
import LoginRequiredModal from "@/components/base/LoginRequiredModal";

interface Message {
  id: string;
  role: string;
  content: string;
  timestamp: string;
}

interface Session {
  id: string;
  title: string;
  createdAt: string;
  messages: Message[];
}

// 根據訊息內容自動生成標題
function generateTitle(content: string): string {
  const cleaned = content.replace(/\[檔案：.*?\]\s*/g, "").trim();
  if (!cleaned) return "新分析工作區";
  const words = cleaned.slice(0, 20);
  return words.length < cleaned.length ? `${words}…` : words;
}

// ── 側邊欄標題項目（可編輯）──
interface SessionItemProps {
  session: Session;
  isActive: boolean;
  onSelect: (id: string) => void;
  onRename: (id: string, newTitle: string) => void;
}

const SessionItem = memo(({ session, isActive, onSelect, onRename }: SessionItemProps) => {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(session.title);
  const inputRef = useRef<HTMLInputElement>(null);

  const startEdit = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    setDraft(session.title);
    setEditing(true);
    setTimeout(() => inputRef.current?.select(), 0);
  }, [session.title]);

  const commitEdit = useCallback(() => {
    const trimmed = draft.trim();
    if (trimmed) onRename(session.id, trimmed);
    setEditing(false);
  }, [draft, session.id, onRename]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === "Enter") commitEdit();
    if (e.key === "Escape") setEditing(false);
  }, [commitEdit]);

  return (
    <div
      className={`group relative flex items-center px-4 py-3.5 hover:bg-rose-50 transition-colors cursor-pointer ${
        isActive ? "bg-rose-50 border-r-2 border-rose-400" : ""
      }`}
      onClick={() => !editing && onSelect(session.id)}
    >
      {editing ? (
        <input
          ref={inputRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commitEdit}
          onKeyDown={handleKeyDown}
          onClick={(e) => e.stopPropagation()}
          className="flex-1 text-sm font-semibold text-slate-700 bg-white border border-rose-300 rounded-md px-2 py-0.5 focus:outline-none focus:ring-1 focus:ring-rose-300"
          autoFocus
        />
      ) : (
        <>
          <div className="flex-1 min-w-0">
            <p className={`text-sm font-semibold truncate ${isActive ? "text-rose-500" : "text-slate-700"}`}>
              {session.title}
            </p>
            <p className="text-xs text-slate-400 mt-0.5">{session.createdAt}</p>
          </div>
          <button
            onClick={startEdit}
            className="opacity-0 group-hover:opacity-100 w-6 h-6 flex items-center justify-center text-slate-400 hover:text-rose-500 transition-all flex-shrink-0 ml-1 cursor-pointer"
            title="重新命名"
          >
            <i className="ri-pencil-line text-xs"></i>
          </button>
        </>
      )}
    </div>
  );
});

// ── 主頁面 ──
const WorkspacePage: React.FC = () => {
  const { isLoggedIn } = useAuth();
  const navigate = useNavigate();
  const [showModal, setShowModal] = useState(!isLoggedIn);
  const [sessions, setSessions] = useState<Session[]>(mockSessions as Session[]);
  const [activeSession, setActiveSession] = useState(mockSessions[0]?.id || "");
  const [messages, setMessages] = useState<Message[]>(mockCurrentMessages);
  const [input, setInput] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [sending, setSending] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [autoTitled, setAutoTitled] = useState<Set<string>>(new Set());
  const fileRef = useRef<HTMLInputElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const filteredSessions = sessions.filter((s) =>
    s.title.toLowerCase().includes(searchQuery.toLowerCase())
  );

  // 新增工作階段
  const handleNewSession = useCallback(() => {
    const id = `session-${Date.now()}`;
    const newSession: Session = {
      id,
      title: "新分析工作區",
      createdAt: new Date().toISOString().split("T")[0],
      messages: [],
    };
    setSessions((prev) => [newSession, ...prev]);
    setActiveSession(id);
    setMessages([
      {
        id: "init",
        role: "assistant",
        content: "您好！我是您的資料分析助理。請上傳檔案或輸入您的問題，開始分析吧！",
        timestamp: new Date().toISOString(),
      },
    ]);
    setFile(null);
    setInput("");
  }, []);

  // 重新命名
  const handleRename = useCallback((id: string, newTitle: string) => {
    setSessions((prev) =>
      prev.map((s) => (s.id === id ? { ...s, title: newTitle } : s))
    );
    // 手動改名後，不再自動覆蓋標題
    setAutoTitled((prev) => new Set([...prev, id]));
  }, []);

  // 切換 session
  const handleSelectSession = useCallback((id: string) => {
    setActiveSession(id);
    const s = sessions.find((x) => x.id === id);
    setMessages(s && s.messages.length ? s.messages : (mockCurrentMessages as Message[]));
  }, [sessions]);

  // 發送訊息
  const handleSend = async () => {
    if (!input.trim() && !file) return;
    const content = file ? `[檔案：${file.name}] ${input}` : input;
    const userMsg: Message = {
      id: `msg-${Date.now()}`,
      role: "user",
      content,
      timestamp: new Date().toISOString(),
    };

    // 自動命名：第一次發送且尚未自動命名過
    setSessions((prev) =>
      prev.map((s) => {
        if (s.id === activeSession && !autoTitled.has(s.id) && s.title === "新分析工作區") {
          setAutoTitled((t) => new Set([...t, s.id]));
          return { ...s, title: generateTitle(content) };
        }
        return s;
      })
    );

    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setFile(null);
    setSending(true);
    await new Promise((r) => setTimeout(r, 1200));
    const reply: Message = {
      id: `msg-${Date.now()}-r`,
      role: "assistant",
      content: "感謝您的輸入！我已收到您的資料。在完整版本中，我將對其進行分析並提供詳細的洞察報告。請連接後端 API 以啟用真實分析功能。",
      timestamp: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, reply]);
    setSending(false);
    setTimeout(() => messagesEndRef.current?.scrollIntoView({ behavior: "smooth" }), 50);
  };

  return (
    <div className="h-screen flex flex-col bg-gradient-to-br from-rose-50 via-pink-50 to-amber-50 overflow-hidden">
      <Navbar onLoginRequired={() => setShowModal(true)} />

      <div className="flex overflow-hidden" style={{ height: "calc(100vh - 72px)", marginTop: "72px" }}>
        {/* 左側歷史紀錄 */}
        <aside className="w-68 bg-white/80 border-r border-rose-100 flex flex-col flex-shrink-0 min-h-0" style={{ width: "272px" }}>
          <div className="p-4 border-b border-rose-100 flex-shrink-0">
            <div className="flex items-center justify-between mb-3">
              <span className="text-sm font-bold text-rose-400 uppercase tracking-wider">歷史紀錄</span>
              <button
                onClick={handleNewSession}
                className="w-8 h-8 flex items-center justify-center bg-gradient-to-br from-rose-400 to-pink-500 text-white rounded-lg hover:from-rose-300 hover:to-pink-400 cursor-pointer transition-all"
                title="新增工作區"
              >
                <i className="ri-add-line text-base"></i>
              </button>
            </div>
            <div className="flex items-center gap-2 bg-rose-50 border border-rose-100 rounded-lg px-3 py-2">
              <div className="w-4 h-4 flex items-center justify-center flex-shrink-0">
                <i className="ri-search-line text-sm text-rose-300"></i>
              </div>
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="搜尋歷史紀錄..."
                className="flex-1 bg-transparent text-sm text-slate-600 placeholder-rose-300 focus:outline-none"
              />
              {searchQuery && (
                <button
                  onClick={() => setSearchQuery("")}
                  className="w-4 h-4 flex items-center justify-center text-rose-300 hover:text-rose-500 cursor-pointer flex-shrink-0"
                >
                  <i className="ri-close-line text-sm"></i>
                </button>
              )}
            </div>
          </div>
          <div className="flex-1 overflow-y-auto py-2 min-h-0">
            {filteredSessions.length === 0 && (
              <div className="px-4 py-8 text-center">
                <div className="w-10 h-10 flex items-center justify-center mx-auto mb-2 text-rose-200">
                  <i className="ri-search-line text-2xl"></i>
                </div>
                <p className="text-sm text-rose-300">找不到符合的紀錄</p>
              </div>
            )}
            {filteredSessions.map((s) => (
              <SessionItem
                key={s.id}
                session={s}
                isActive={activeSession === s.id}
                onSelect={handleSelectSession}
                onRename={handleRename}
              />
            ))}
          </div>
        </aside>

        {/* 主要對話區 - 白色背景 */}
        <main className="flex-1 flex flex-col overflow-hidden bg-white">
          {/* 訊息列表 */}
          <div className="flex-1 overflow-y-auto px-10 py-8 space-y-6">
            {messages.map((msg) => (
              <div key={msg.id} className={`flex gap-4 ${msg.role === "user" ? "flex-row-reverse" : ""}`}>
                <div
                  className={`w-10 h-10 flex items-center justify-center rounded-full flex-shrink-0 ${
                    msg.role === "user"
                      ? "bg-gradient-to-br from-rose-400 to-pink-500"
                      : "bg-rose-50 border border-rose-100"
                  }`}
                >
                  {msg.role === "user" ? (
                    <i className="ri-user-line text-white text-lg"></i>
                  ) : (
                    <i className="ri-robot-line text-rose-400 text-lg"></i>
                  )}
                </div>
                <div
                  className={`max-w-2xl px-6 py-4 rounded-2xl text-[17px] leading-relaxed ${
                    msg.role === "user"
                      ? "bg-gradient-to-br from-rose-400 to-pink-500 text-white"
                      : "bg-rose-50/60 border border-rose-100 text-slate-700"
                  }`}
                >
                  {msg.content}
                </div>
              </div>
            ))}
            {sending && (
              <div className="flex gap-4">
                <div className="w-10 h-10 flex items-center justify-center rounded-full bg-rose-50 border border-rose-100 flex-shrink-0">
                  <i className="ri-robot-line text-rose-400 text-lg"></i>
                </div>
                <div className="px-6 py-4 bg-rose-50/60 border border-rose-100 rounded-2xl">
                  <div className="flex gap-1.5 items-center">
                    <span className="w-2.5 h-2.5 bg-rose-300 rounded-full animate-bounce" style={{ animationDelay: "0ms" }}></span>
                    <span className="w-2.5 h-2.5 bg-pink-300 rounded-full animate-bounce" style={{ animationDelay: "150ms" }}></span>
                    <span className="w-2.5 h-2.5 bg-amber-300 rounded-full animate-bounce" style={{ animationDelay: "300ms" }}></span>
                  </div>
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* 底部輸入區 */}
          <div className="px-10 py-5 bg-white border-t border-rose-100 flex-shrink-0">
            {file && (
              <div className="flex items-center gap-2 mb-3 px-4 py-2.5 bg-rose-50 border border-rose-100 rounded-xl w-fit">
                <i className="ri-attachment-line text-rose-400 text-base"></i>
                <span className="text-base text-rose-600 font-semibold">{file.name}</span>
                <button onClick={() => setFile(null)} className="text-rose-300 hover:text-rose-500 cursor-pointer ml-1">
                  <i className="ri-close-line text-base"></i>
                </button>
              </div>
            )}
            <div className="flex items-end gap-3 bg-slate-50 rounded-2xl border border-slate-200 px-5 py-4">
              <button
                onClick={() => fileRef.current?.click()}
                className="w-10 h-10 flex items-center justify-center text-slate-400 hover:text-slate-600 cursor-pointer flex-shrink-0 transition-colors"
                title="附加檔案"
              >
                <i className="ri-attachment-line text-xl"></i>
              </button>
              <input
                ref={fileRef}
                type="file"
                accept=".csv,.xlsx,.json,.txt"
                className="hidden"
                onChange={(e) => setFile(e.target.files?.[0] || null)}
              />
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    handleSend();
                  }
                }}
                placeholder="輸入您的問題或上傳檔案進行分析..."
                rows={1}
                className="flex-1 bg-transparent text-[17px] text-slate-700 placeholder-slate-400 resize-none focus:outline-none min-h-[28px] max-h-36"
              />
              <button
                onClick={handleSend}
                disabled={sending || (!input.trim() && !file)}
                className="w-10 h-10 flex items-center justify-center bg-gradient-to-br from-rose-400 to-pink-500 text-white rounded-xl hover:from-rose-300 hover:to-pink-400 disabled:opacity-40 cursor-pointer flex-shrink-0 transition-all"
              >
                <i className="ri-send-plane-line text-lg"></i>
              </button>
            </div>
            <p className="text-sm text-slate-400 mt-2.5 text-center">
              支援 CSV、Excel、JSON、TXT · 按 Enter 發送，Shift+Enter 換行
            </p>
          </div>
        </main>
      </div>

      <LoginRequiredModal
        isOpen={showModal}
        onClose={() => { setShowModal(false); navigate("/login"); }}
      />
    </div>
  );
};

export default WorkspacePage;
