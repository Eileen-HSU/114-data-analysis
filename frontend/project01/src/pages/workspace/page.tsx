// Workspace 工作區頁面 - 亮色系 + 中文化
import { useState, useRef } from "react";
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

const WorkspacePage: React.FC = () => {
  const { isLoggedIn, user } = useAuth();
  const navigate = useNavigate();
  const [showModal, setShowModal] = useState(!isLoggedIn);
  const [sessions, setSessions] = useState(mockSessions);
  const [activeSession, setActiveSession] = useState(mockSessions[0]?.id || "");
  const [messages, setMessages] = useState<Message[]>(mockCurrentMessages);
  const [input, setInput] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [sending, setSending] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  // 新增工作階段
  const handleNewSession = () => {
    const id = `session-${Date.now()}`;
    const newSession = {
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
  };

  // 發送訊息
  const handleSend = async () => {
    if (!input.trim() && !file) return;
    const userMsg: Message = {
      id: `msg-${Date.now()}`,
      role: "user",
      content: file ? `[檔案：${file.name}] ${input}` : input,
      timestamp: new Date().toISOString(),
    };
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
  };

  return (
    <div className="h-screen flex flex-col bg-gradient-to-br from-violet-50 via-sky-50 to-cyan-50 overflow-hidden">
      {/* 頂部 Navbar */}
      <Navbar onLoginRequired={() => setShowModal(true)} />

      <div className="flex flex-1 overflow-hidden">
        {/* 左側歷史紀錄 */}
        <aside className="w-64 bg-white border-r border-slate-100 flex flex-col flex-shrink-0">
          <div className="p-4 border-b border-slate-100 flex items-center justify-between">
            <span className="text-sm font-bold text-slate-500 uppercase tracking-wider">歷史紀錄</span>
            <button
              onClick={handleNewSession}
              className="w-8 h-8 flex items-center justify-center bg-gradient-to-br from-violet-500 to-sky-500 text-white rounded-lg hover:from-violet-400 hover:to-sky-400 cursor-pointer transition-all"
              title="新增工作區"
            >
              <i className="ri-add-line text-base"></i>
            </button>
          </div>
          <div className="flex-1 overflow-y-auto py-2">
            {sessions.map((s) => (
              <button
                key={s.id}
                onClick={() => {
                  setActiveSession(s.id);
                  setMessages(s.messages.length ? (s.messages as Message[]) : mockCurrentMessages);
                }}
                className={`w-full text-left px-4 py-3.5 hover:bg-violet-50 transition-colors cursor-pointer ${
                  activeSession === s.id ? "bg-violet-50 border-r-2 border-violet-500" : ""
                }`}
              >
                <p className={`text-base font-semibold truncate ${activeSession === s.id ? "text-violet-600" : "text-slate-700"}`}>
                  {s.title}
                </p>
                <p className="text-sm text-slate-400 mt-0.5">{s.createdAt}</p>
              </button>
            ))}
          </div>
        </aside>

        {/* 主要對話區 */}
        <main className="flex-1 flex flex-col overflow-hidden">
          {/* 訊息列表 */}
          <div className="flex-1 overflow-y-auto px-8 py-6 space-y-5">
            {messages.map((msg) => (
              <div key={msg.id} className={`flex gap-3 ${msg.role === "user" ? "flex-row-reverse" : ""}`}>
                <div
                  className={`w-9 h-9 flex items-center justify-center rounded-full flex-shrink-0 ${
                    msg.role === "user"
                      ? "bg-gradient-to-br from-violet-500 to-sky-500"
                      : "bg-slate-100 border border-slate-200"
                  }`}
                >
                  {msg.role === "user" ? (
                    <i className="ri-user-line text-white text-base"></i>
                  ) : (
                    <i className="ri-robot-line text-slate-500 text-base"></i>
                  )}
                </div>
                <div
                  className={`max-w-2xl px-5 py-3.5 rounded-2xl text-base leading-relaxed ${
                    msg.role === "user"
                      ? "bg-gradient-to-br from-violet-500 to-sky-500 text-white"
                      : "bg-white border border-slate-100 text-slate-700"
                  }`}
                >
                  {msg.content}
                </div>
              </div>
            ))}
            {sending && (
              <div className="flex gap-3">
                <div className="w-9 h-9 flex items-center justify-center rounded-full bg-slate-100 border border-slate-200 flex-shrink-0">
                  <i className="ri-robot-line text-slate-500 text-base"></i>
                </div>
                <div className="px-5 py-3.5 bg-white border border-slate-100 rounded-2xl">
                  <div className="flex gap-1.5 items-center">
                    <span className="w-2 h-2 bg-violet-300 rounded-full animate-bounce" style={{ animationDelay: "0ms" }}></span>
                    <span className="w-2 h-2 bg-sky-300 rounded-full animate-bounce" style={{ animationDelay: "150ms" }}></span>
                    <span className="w-2 h-2 bg-cyan-300 rounded-full animate-bounce" style={{ animationDelay: "300ms" }}></span>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* 底部輸入區 */}
          <div className="px-8 py-5 bg-white border-t border-slate-100 flex-shrink-0">
            {file && (
              <div className="flex items-center gap-2 mb-3 px-4 py-2.5 bg-violet-50 border border-violet-100 rounded-xl w-fit">
                <i className="ri-attachment-line text-violet-500 text-base"></i>
                <span className="text-sm text-violet-700 font-semibold">{file.name}</span>
                <button onClick={() => setFile(null)} className="text-violet-400 hover:text-violet-600 cursor-pointer ml-1">
                  <i className="ri-close-line text-base"></i>
                </button>
              </div>
            )}
            <div className="flex items-end gap-3 bg-slate-50 rounded-2xl border border-slate-200 px-5 py-4">
              <button
                onClick={() => fileRef.current?.click()}
                className="w-9 h-9 flex items-center justify-center text-slate-400 hover:text-violet-500 cursor-pointer flex-shrink-0 transition-colors"
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
                className="flex-1 bg-transparent text-base text-slate-700 placeholder-slate-400 resize-none focus:outline-none min-h-[24px] max-h-32"
              />
              <button
                onClick={handleSend}
                disabled={sending || (!input.trim() && !file)}
                className="w-9 h-9 flex items-center justify-center bg-gradient-to-br from-violet-500 to-sky-500 text-white rounded-xl hover:from-violet-400 hover:to-sky-400 disabled:opacity-40 cursor-pointer flex-shrink-0 transition-all"
              >
                <i className="ri-send-plane-line text-base"></i>
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
