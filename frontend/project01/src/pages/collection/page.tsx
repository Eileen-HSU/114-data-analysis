import { useState, useRef, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import Navbar from "@/components/feature/Navbar";
import LoginRequiredModal from "@/components/base/LoginRequiredModal";
import { mockFiles, mockFolders } from "@/mocks/collection";

const fileIcon: Record<string, string> = {
  csv: "ri-file-chart-line",
  xlsx: "ri-file-excel-line",
  json: "ri-file-code-line",
  txt: "ri-file-text-line",
};

const fileColor: Record<string, { bg: string; text: string; badge: string; badgeText: string; badgeBorder: string }> = {
  csv:  { bg: "bg-[#f5e8e6]", text: "text-[#c97b72]", badge: "bg-violet-50", badgeText: "text-violet-600", badgeBorder: "border-violet-200" },
  xlsx: { bg: "bg-[#e6ecf4]", text: "text-[#7a96b8]", badge: "bg-sky-50",    badgeText: "text-sky-600",    badgeBorder: "border-sky-200"    },
  json: { bg: "bg-[#eee8f0]", text: "text-[#9e82b0]", badge: "bg-cyan-50",   badgeText: "text-cyan-600",   badgeBorder: "border-cyan-200"   },
  txt:  { bg: "bg-[#eeeeee]", text: "text-[#888888]", badge: "bg-slate-50",  badgeText: "text-slate-500",  badgeBorder: "border-slate-200"  },
};

/* ── Inline 編輯輸入框 ── */
interface InlineEditProps {
  value: string;
  onSave: (v: string) => void;
  className?: string;
}
const InlineEdit: React.FC<InlineEditProps> = ({ value, onSave, className = "" }) => {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { if (editing) inputRef.current?.select(); }, [editing]);

  const commit = () => {
    const trimmed = draft.trim();
    if (trimmed) onSave(trimmed);
    else setDraft(value);
    setEditing(false);
  };

  if (editing) {
    return (
      <input
        ref={inputRef}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => { if (e.key === "Enter") commit(); if (e.key === "Escape") { setDraft(value); setEditing(false); } }}
        className={`bg-white border border-[#e8b4a8] rounded px-1.5 py-0.5 text-sm outline-none focus:ring-1 focus:ring-[#c97b72] ${className}`}
        style={{ minWidth: 80, maxWidth: 200 }}
        onClick={(e) => e.stopPropagation()}
      />
    );
  }

  return (
    <span
      className={`group/edit cursor-text ${className}`}
      onDoubleClick={(e) => { e.stopPropagation(); setEditing(true); }}
      title="雙擊編輯名稱"
    >
      {value}
      <i className="ri-pencil-line ml-1 text-xs text-slate-300 opacity-0 group-hover/edit:opacity-100 transition-opacity"></i>
    </span>
  );
};

/* ── 主頁面 ── */
const CollectionPage: React.FC = () => {
  const [showModal, setShowModal] = useState(false);
  const [openFolders, setOpenFolders] = useState<string[]>([]);
  const [files, setFiles] = useState(mockFiles);
  const [folders, setFolders] = useState(mockFolders);
  const navigate = useNavigate();

  const toggleFolder = (id: string) =>
    setOpenFolders((prev) =>
      prev.includes(id) ? prev.filter((f) => f !== id) : [...prev, id]
    );

  const renameFile = (id: string, name: string) =>
    setFiles((prev) => prev.map((f) => (f.id === id ? { ...f, name } : f)));

  const renameFolder = (id: string, name: string) =>
    setFolders((prev) => prev.map((f) => (f.id === id ? { ...f, name } : f)));

  const deleteFile = (id: string) => setFiles((prev) => prev.filter((f) => f.id !== id));

  const looseFiles = files.filter((f) => !f.folderId);
  const totalSize = files.length;
  const totalFolders = folders.length;

  return (
    <div className="min-h-screen bg-[#f9f7f6]">
      <Navbar onLoginRequired={() => setShowModal(true)} />
      <div className="h-[72px]" />

      {/* 頂部 Banner - 固定 */}
      <div
        className="sticky top-0 z-40 overflow-hidden py-10 px-6"
        style={{
          backgroundImage: "url('https://static.readdy.ai/image/9080131fd243e879b7aeaa20dae1f896/642102939a4035b219ee0f2200300117.png')",
          backgroundSize: "cover",
          backgroundPosition: "center",
        }}
      >
        <div className="absolute inset-0 bg-black/35" />
        <div className="max-w-7xl mx-auto relative z-10">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-white/70 text-sm font-medium tracking-wider uppercase mb-1">My Collection</p>
              <h1 className="text-3xl font-black text-white mb-1">我的作品集</h1>
              <p className="text-white/70 text-base">{totalSize} 個檔案 · {totalFolders} 個資料夾</p>
            </div>
            <button
              onClick={() => navigate("/workspace")}
              className="flex items-center gap-2 px-6 py-3 bg-white/20 backdrop-blur-sm text-white text-base font-bold rounded-xl hover:bg-white/30 cursor-pointer whitespace-nowrap transition-all border border-white/30"
            >
              <i className="ri-add-line text-lg"></i>
              新增工作區
            </button>
          </div>

          {/* 統計卡片 */}
          <div className="grid grid-cols-4 gap-4 mt-7">
            {[
              { label: "CSV 檔案", count: files.filter(f => f.type === "csv").length, icon: "ri-file-chart-line", bg: "bg-[#f5e8e6]", iconColor: "text-[#c97b72]" },
              { label: "Excel 檔案", count: files.filter(f => f.type === "xlsx").length, icon: "ri-file-excel-line", bg: "bg-[#e6ecf4]", iconColor: "text-[#7a96b8]" },
              { label: "JSON 檔案", count: files.filter(f => f.type === "json").length, icon: "ri-file-code-line", bg: "bg-[#eee8f0]", iconColor: "text-[#9e82b0]" },
              { label: "資料夾", count: totalFolders, icon: "ri-folder-line", bg: "bg-[#f0ebe8]", iconColor: "text-[#b89080]" },
            ].map((s) => (
              <div key={s.label} className="bg-white/20 backdrop-blur-sm rounded-2xl p-4 border border-white/25">
                <div className={`w-10 h-10 flex items-center justify-center ${s.bg} rounded-xl mb-3`}>
                  <i className={`${s.icon} ${s.iconColor} text-xl`}></i>
                </div>
                <div className="text-3xl font-black text-white">{s.count}</div>
                <div className="text-white/70 text-sm mt-0.5">{s.label}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* 主內容 */}
      <div className="max-w-7xl mx-auto px-8 py-10">

        {/* ── 資料夾區塊 ── */}
        <section className="mb-8">
          <h2 className="text-xl font-bold text-slate-700 mb-5 flex items-center gap-3">
            <span className="w-9 h-9 flex items-center justify-center bg-[#f5e8e6] rounded-xl">
              <i className="ri-folder-2-line text-[#c97b72] text-xl"></i>
            </span>
            資料夾
          </h2>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {folders.map((folder) => {
              const folderFiles = files.filter((f) => f.folderId === folder.id);
              const isOpen = openFolders.includes(folder.id);

              return (
                <div key={folder.id} className="bg-white rounded-xl border border-slate-100 overflow-hidden hover:border-[#e8b4a8] transition-all">
                  {/* 資料夾列頭 */}
                  <div
                    className="flex items-center gap-4 px-6 py-5 cursor-pointer hover:bg-[#fdf6f5]/60 transition-colors"
                    onClick={() => toggleFolder(folder.id)}
                  >
                    <div className="w-12 h-12 flex items-center justify-center bg-[#f5e8e6] rounded-xl flex-shrink-0">
                      <i className={`${isOpen ? "ri-folder-open-line" : "ri-folder-line"} text-[#c97b72] text-2xl`}></i>
                    </div>

                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <InlineEdit
                          value={folder.name}
                          onSave={(v) => renameFolder(folder.id, v)}
                          className="text-lg font-semibold text-slate-800 truncate"
                        />
                        <span className="text-sm text-slate-400 whitespace-nowrap flex-shrink-0">{folderFiles.length} 個</span>
                      </div>
                      {/* 類型標籤 */}
                      <div className="flex gap-1.5 mt-2 flex-wrap">
                        {["csv", "xlsx", "json", "txt"].map((t) => {
                          const cnt = folderFiles.filter(f => f.type === t).length;
                          if (!cnt) return null;
                          const c = fileColor[t];
                          return (
                            <span key={t} className={`px-1.5 py-0.5 text-xs font-semibold rounded-full border ${c.badge} ${c.badgeText} ${c.badgeBorder}`}>
                              {t.toUpperCase()} {cnt}
                            </span>
                          );
                        })}
                      </div>
                    </div>

                    <i className={`${isOpen ? "ri-arrow-up-s-line" : "ri-arrow-down-s-line"} text-slate-400 text-lg flex-shrink-0`}></i>
                  </div>

                  {/* 展開的檔案橫向 grid */}
                  {isOpen && (
                    <div className="border-t border-slate-100 px-5 py-5">
                      {folderFiles.length === 0 ? (
                        <p className="text-base text-slate-400 text-center py-5">此資料夾尚無檔案</p>
                      ) : (
                        <div className="grid grid-cols-2 gap-3">
                          {folderFiles.map((file) => {
                            const c = fileColor[file.type] || fileColor.txt;
                            return (
                              <div
                                key={file.id}
                                className="group flex items-center gap-3 px-4 py-3.5 rounded-xl border border-slate-100 hover:border-[#e8b4a8] bg-[#fdfcfc] hover:bg-[#fdf6f5]/60 transition-all"
                              >
                                <div className={`w-10 h-10 flex items-center justify-center ${c.bg} rounded-xl flex-shrink-0`}>
                                  <i className={`${fileIcon[file.type] || "ri-file-line"} ${c.text} text-lg`}></i>
                                </div>
                                <div className="flex-1 min-w-0">
                                  <InlineEdit
                                    value={file.name}
                                    onSave={(v) => renameFile(file.id, v)}
                                    className="text-sm font-semibold text-slate-700 block truncate w-full"
                                  />
                                  <p className="text-sm text-slate-400 truncate">{file.size}</p>
                                </div>
                                <div className="flex flex-col gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
                                  <button
                                    onClick={() => navigate("/workspace")}
                                    className="w-5 h-5 flex items-center justify-center text-slate-400 hover:text-[#c97b72] cursor-pointer transition-colors"
                                  >
                                    <i className="ri-external-link-line text-xs"></i>
                                  </button>
                                  <button
                                    onClick={() => deleteFile(file.id)}
                                    className="w-5 h-5 flex items-center justify-center text-slate-400 hover:text-red-400 cursor-pointer transition-colors"
                                  >
                                    <i className="ri-delete-bin-line text-xs"></i>
                                  </button>
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </section>

        {/* ── 未分類檔案 ── */}
        {looseFiles.length > 0 && (
          <section>
            <h2 className="text-xl font-bold text-slate-700 mb-5 flex items-center gap-3">
              <span className="w-9 h-9 flex items-center justify-center bg-[#e6ecf4] rounded-xl">
                <i className="ri-file-list-3-line text-[#7a96b8] text-xl"></i>
              </span>
              未分類檔案
            </h2>

            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
              {looseFiles.map((file) => {
                const c = fileColor[file.type] || fileColor.txt;
                return (
                  <div
                    key={file.id}
                    className="group flex items-center gap-4 px-5 py-4 rounded-2xl border border-slate-100 hover:border-[#e8b4a8] bg-white hover:bg-[#fdf6f5]/60 transition-all"
                  >
                    <div className={`w-12 h-12 flex items-center justify-center ${c.bg} rounded-2xl flex-shrink-0`}>
                      <i className={`${fileIcon[file.type] || "ri-file-line"} ${c.text} text-2xl`}></i>
                    </div>
                    <div className="flex-1 min-w-0">
                      <InlineEdit
                        value={file.name}
                        onSave={(v) => renameFile(file.id, v)}
                        className="text-base font-semibold text-slate-700 block truncate w-full"
                      />
                      <div className="flex items-center gap-2 mt-1">
                        <span className={`px-2 py-0.5 text-xs font-bold rounded-full border ${c.badge} ${c.badgeText} ${c.badgeBorder}`}>
                          {file.type.toUpperCase()}
                        </span>
                        <span className="text-sm text-slate-400">{file.size}</span>
                      </div>
                    </div>
                    <div className="flex flex-col gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
                      <button
                        onClick={() => navigate("/workspace")}
                        className="w-5 h-5 flex items-center justify-center text-slate-400 hover:text-[#c97b72] cursor-pointer transition-colors"
                      >
                        <i className="ri-external-link-line text-xs"></i>
                      </button>
                      <button
                        onClick={() => deleteFile(file.id)}
                        className="w-5 h-5 flex items-center justify-center text-slate-400 hover:text-red-400 cursor-pointer transition-colors"
                      >
                        <i className="ri-delete-bin-line text-xs"></i>
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        )}

        {/* 空狀態 */}
        {files.length === 0 && (
          <div className="text-center py-20">
            <div className="w-20 h-20 flex items-center justify-center bg-[#f5e8e6] rounded-2xl mx-auto mb-5">
              <i className="ri-folder-open-line text-[#c97b72] text-4xl"></i>
            </div>
            <h3 className="text-xl font-bold text-slate-700 mb-2">作品集是空的</h3>
            <p className="text-base text-slate-400 mb-6">前往工作區開始分析資料，結果會自動儲存在這裡</p>
            <button
              onClick={() => navigate("/workspace")}
              className="px-6 py-3 bg-[#c97b72] text-white text-base font-bold rounded-xl hover:bg-[#b86d64] cursor-pointer whitespace-nowrap transition-all"
            >
              前往工作區
            </button>
          </div>
        )}
      </div>

      <LoginRequiredModal isOpen={showModal} onClose={() => setShowModal(false)} />
    </div>
  );
};

export default CollectionPage;
