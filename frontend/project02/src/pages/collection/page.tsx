import { useState, useRef, useEffect, useCallback, memo } from "react";
import { useNavigate } from "react-router-dom";
import Navbar from "@/components/feature/Navbar";
import LoginRequiredModal from "@/components/base/LoginRequiredModal";
import { mockFiles, mockFolders } from "@/mocks/collection";

/* ── 型別 ── */
interface FileItem {
  id: string;
  name: string;
  type: string;
  size: string;
  createdAt: string;
  folderId: string | null;
}
interface FolderItem {
  id: string;
  name: string;
  createdAt: string;
  color: string;
}

/* ── 常數 ── */
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

/* ── Inline 編輯 ── */
interface InlineEditProps { value: string; onSave: (v: string) => void; className?: string; }
const InlineEdit: React.FC<InlineEditProps> = memo(({ value, onSave, className = "" }) => {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => { if (editing) inputRef.current?.select(); }, [editing]);
  const commit = () => {
    const t = draft.trim();
    if (t) onSave(t); else setDraft(value);
    setEditing(false);
  };
  if (editing) return (
    <input ref={inputRef} value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => { if (e.key === "Enter") commit(); if (e.key === "Escape") { setDraft(value); setEditing(false); } }}
      className={`bg-white border border-[#e8b4a8] rounded px-1.5 py-0.5 text-sm outline-none focus:ring-1 focus:ring-[#c97b72] ${className}`}
      style={{ minWidth: 80, maxWidth: 200 }}
      onClick={(e) => e.stopPropagation()}
    />
  );
  return (
    <span className={`group/edit cursor-text ${className}`}
      onDoubleClick={(e) => { e.stopPropagation(); setEditing(true); }}
      title="雙擊編輯名稱">
      {value}
      <i className="ri-pencil-line ml-1 text-xs text-slate-300 opacity-0 group-hover/edit:opacity-100 transition-opacity"></i>
    </span>
  );
});

/* ── 刪除確認 Modal ── */
interface ConfirmModalProps { title: string; desc: string; onConfirm: () => void; onCancel: () => void; }
const ConfirmModal: React.FC<ConfirmModalProps> = ({ title, desc, onConfirm, onCancel }) => (
  <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm" onClick={onCancel}>
    <div className="bg-white rounded-2xl p-8 w-full max-w-sm mx-4 border border-slate-100" onClick={(e) => e.stopPropagation()}>
      <div className="w-12 h-12 flex items-center justify-center bg-red-50 rounded-xl mx-auto mb-4">
        <i className="ri-delete-bin-line text-red-400 text-2xl"></i>
      </div>
      <h3 className="text-lg font-bold text-slate-800 text-center mb-2">{title}</h3>
      <p className="text-sm text-slate-500 text-center mb-6">{desc}</p>
      <div className="flex gap-3">
        <button onClick={onConfirm} className="flex-1 py-3 bg-red-400 text-white text-base font-bold rounded-xl hover:bg-red-500 cursor-pointer whitespace-nowrap transition-all">確認刪除</button>
        <button onClick={onCancel} className="flex-1 py-3 border border-slate-200 text-slate-500 text-base font-semibold rounded-xl hover:bg-slate-50 cursor-pointer whitespace-nowrap transition-colors">取消</button>
      </div>
    </div>
  </div>
);

/* ── 檔案卡片（元件外部，避免每次 render 重建） ── */
interface FileCardProps {
  file: FileItem;
  compact?: boolean;
  isDragging: boolean;
  onDragStart: (e: React.DragEvent, id: string) => void;
  onDragEnd: () => void;
  onRename: (id: string, name: string) => void;
  onDelete: (file: FileItem) => void;
  onOpen: () => void;
}
const FileCard: React.FC<FileCardProps> = memo(({ file, compact = false, isDragging, onDragStart, onDragEnd, onRename, onDelete, onOpen }) => {
  const c = fileColor[file.type] || fileColor.txt;
  return (
    <div
      draggable
      onDragStart={(e) => onDragStart(e, file.id)}
      onDragEnd={onDragEnd}
      className={`group flex items-center gap-3 rounded-xl border transition-colors cursor-grab active:cursor-grabbing select-none
        ${compact ? "px-4 py-3 bg-[#fdfcfc]" : "px-5 py-4 bg-white"}
        ${isDragging ? "opacity-40 border-[#e8b4a8]" : "border-slate-100 hover:border-[#e8b4a8] hover:bg-[#fdf6f5]/60"}`}
    >
      <i className="ri-draggable text-slate-300 text-base opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0 -ml-1"></i>
      <div className={`flex items-center justify-center ${c.bg} rounded-xl flex-shrink-0 ${compact ? "w-9 h-9" : "w-11 h-11"}`}>
        <i className={`${fileIcon[file.type] || "ri-file-line"} ${c.text} ${compact ? "text-base" : "text-xl"}`}></i>
      </div>
      <div className="flex-1 min-w-0">
        <InlineEdit value={file.name} onSave={(v) => onRename(file.id, v)}
          className={`font-semibold text-slate-700 block truncate w-full ${compact ? "text-sm" : "text-base"}`} />
        <div className="flex items-center gap-2 mt-0.5">
          <span className={`px-1.5 py-0.5 text-xs font-bold rounded-full border ${c.badge} ${c.badgeText} ${c.badgeBorder}`}>
            {file.type.toUpperCase()}
          </span>
          <span className="text-xs text-slate-400">{file.size}</span>
        </div>
      </div>
      <div className="flex flex-col gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
        <button onClick={onOpen} className="w-5 h-5 flex items-center justify-center text-slate-400 hover:text-[#c97b72] cursor-pointer transition-colors" title="開啟">
          <i className="ri-external-link-line text-xs"></i>
        </button>
        <button onClick={() => onDelete(file)} className="w-5 h-5 flex items-center justify-center text-slate-400 hover:text-red-400 cursor-pointer transition-colors" title="刪除">
          <i className="ri-delete-bin-line text-xs"></i>
        </button>
      </div>
    </div>
  );
});

/* ── 主頁面 ── */
const CollectionPage: React.FC = () => {
  const [showModal, setShowModal] = useState(false);
  const [openFolders, setOpenFolders] = useState<string[]>([]);
  const [files, setFiles] = useState<FileItem[]>(mockFiles);
  const [folders, setFolders] = useState<FolderItem[]>(mockFolders);
  const [showNewFolderModal, setShowNewFolderModal] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");
  const [newFolderError, setNewFolderError] = useState("");
  const newFolderInputRef = useRef<HTMLInputElement>(null);
  const [confirmDelete, setConfirmDelete] = useState<{ type: "file" | "folder"; id: string; name: string } | null>(null);

  // 拖曳狀態 — 用 ref 追蹤 dragOver 避免頻繁 setState
  const [draggingFileId, setDraggingFileId] = useState<string | null>(null);
  const [dragOverTarget, setDragOverTarget] = useState<string | null>(null);
  const dragOverRef = useRef<string | null>(null);
  const dragTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const navigate = useNavigate();

  useEffect(() => {
    if (showNewFolderModal) setTimeout(() => newFolderInputRef.current?.focus(), 50);
  }, [showNewFolderModal]);

  // 清理 timer
  useEffect(() => () => { if (dragTimerRef.current) clearTimeout(dragTimerRef.current); }, []);

  /* ── 資料夾操作 ── */
  const toggleFolder = useCallback((id: string) =>
    setOpenFolders((prev) => prev.includes(id) ? prev.filter((f) => f !== id) : [...prev, id]), []);

  const renameFile = useCallback((id: string, name: string) =>
    setFiles((prev) => prev.map((f) => f.id === id ? { ...f, name } : f)), []);

  const renameFolder = useCallback((id: string, name: string) =>
    setFolders((prev) => prev.map((f) => f.id === id ? { ...f, name } : f)), []);

  const doDeleteFile = useCallback((id: string) =>
    setFiles((prev) => prev.filter((f) => f.id !== id)), []);

  const doDeleteFolder = useCallback((id: string) => {
    setFolders((prev) => prev.filter((f) => f.id !== id));
    setFiles((prev) => prev.map((f) => f.folderId === id ? { ...f, folderId: null } : f));
    setOpenFolders((prev) => prev.filter((f) => f !== id));
  }, []);

  const handleCreateFolder = useCallback(() => {
    const name = newFolderName.trim();
    if (!name) { setNewFolderError("請輸入資料夾名稱"); return; }
    if (folders.some((f) => f.name === name)) { setNewFolderError("已有相同名稱的資料夾"); return; }
    setFolders((prev) => [...prev, { id: `folder-${Date.now()}`, name, createdAt: new Date().toISOString().slice(0, 10), color: "#c97b72" }]);
    setNewFolderName(""); setNewFolderError(""); setShowNewFolderModal(false);
  }, [newFolderName, folders]);

  /* ── 拖曳處理（節流 dragOver，避免卡頓） ── */
  const handleDragStart = useCallback((e: React.DragEvent, fileId: string) => {
    setDraggingFileId(fileId);
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("fileId", fileId);
  }, []);

  const handleDragEnd = useCallback(() => {
    setDraggingFileId(null);
    setDragOverTarget(null);
    dragOverRef.current = null;
  }, []);

  // dragOver 節流：同一個 target 不重複 setState
  const handleDragOver = useCallback((e: React.DragEvent, targetId: string) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    if (dragOverRef.current === targetId) return; // 同 target 不重複更新
    dragOverRef.current = targetId;
    setDragOverTarget(targetId);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    // 只有真正離開容器才清除（避免子元素觸發 leave）
    const related = e.relatedTarget as Node | null;
    if (related && (e.currentTarget as HTMLElement).contains(related)) return;
    dragOverRef.current = null;
    setDragOverTarget(null);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent, targetFolderId: string | null) => {
    e.preventDefault();
    const fileId = e.dataTransfer.getData("fileId");
    if (!fileId) return;
    setFiles((prev) => prev.map((f) => f.id === fileId ? { ...f, folderId: targetFolderId } : f));
    if (targetFolderId) {
      setOpenFolders((prev) => prev.includes(targetFolderId) ? prev : [...prev, targetFolderId]);
    }
    setDraggingFileId(null);
    setDragOverTarget(null);
    dragOverRef.current = null;
  }, []);

  const openNewFolderModal = useCallback(() => {
    setShowNewFolderModal(true); setNewFolderName(""); setNewFolderError("");
  }, []);

  const looseFiles = files.filter((f) => !f.folderId);

  return (
    <div className="min-h-screen bg-[#f9f7f6]">
      <Navbar onLoginRequired={() => setShowModal(true)} />
      <div className="h-[72px]" />

      {/* 頂部 Banner */}
      <div className="sticky top-0 z-40 overflow-hidden py-10 px-6"
        style={{ backgroundImage: "url('https://static.readdy.ai/image/9080131fd243e879b7aeaa20dae1f896/642102939a4035b219ee0f2200300117.png')", backgroundSize: "cover", backgroundPosition: "center" }}>
        <div className="absolute inset-0 bg-black/35" />
        <div className="max-w-7xl mx-auto relative z-10">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-white/70 text-sm font-medium tracking-wider uppercase mb-1">My Collection</p>
              <h1 className="text-3xl font-black text-white mb-1">我的作品集</h1>
              <p className="text-white/70 text-base">{files.length} 個檔案 · {folders.length} 個資料夾</p>
            </div>
            <button onClick={() => navigate("/workspace")}
              className="flex items-center gap-2 px-6 py-3 bg-white/20 backdrop-blur-sm text-white text-base font-bold rounded-xl hover:bg-white/30 cursor-pointer whitespace-nowrap transition-all border border-white/30">
              <i className="ri-add-line text-lg"></i>新增工作區
            </button>
          </div>
          <div className="grid grid-cols-4 gap-4 mt-7">
            {[
              { label: "CSV 檔案", count: files.filter(f => f.type === "csv").length, icon: "ri-file-chart-line", bg: "bg-[#f5e8e6]", iconColor: "text-[#c97b72]" },
              { label: "Excel 檔案", count: files.filter(f => f.type === "xlsx").length, icon: "ri-file-excel-line", bg: "bg-[#e6ecf4]", iconColor: "text-[#7a96b8]" },
              { label: "JSON 檔案", count: files.filter(f => f.type === "json").length, icon: "ri-file-code-line", bg: "bg-[#eee8f0]", iconColor: "text-[#9e82b0]" },
              { label: "資料夾", count: folders.length, icon: "ri-folder-line", bg: "bg-[#f0ebe8]", iconColor: "text-[#b89080]" },
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

      {/* 拖曳提示條 */}
      {draggingFileId && (
        <div className="sticky top-0 z-30 bg-[#f5e8e6] border-b border-[#e8b4a8] px-8 py-2.5 flex items-center gap-2 text-[#c97b72] text-sm font-semibold">
          <i className="ri-drag-move-line text-base"></i>
          拖曳到資料夾可移入，拖曳到「未分類」區域可移出
        </div>
      )}

      {/* 主內容 */}
      <div className="max-w-7xl mx-auto px-8 py-10">

        {/* ── 資料夾區塊 ── */}
        <section className="mb-10">
          <h2 className="text-xl font-bold text-slate-700 mb-5 flex items-center gap-3">
            <span className="w-9 h-9 flex items-center justify-center bg-[#f5e8e6] rounded-xl">
              <i className="ri-folder-2-line text-[#c97b72] text-xl"></i>
            </span>
            資料夾
            <button onClick={openNewFolderModal}
              className="ml-auto flex items-center gap-2 px-4 py-2 bg-[#c97b72] text-white text-sm font-bold rounded-xl hover:bg-[#b86d64] cursor-pointer whitespace-nowrap transition-all">
              <i className="ri-folder-add-line text-base"></i>新增資料夾
            </button>
          </h2>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {folders.map((folder) => {
              const folderFiles = files.filter((f) => f.folderId === folder.id);
              const isOpen = openFolders.includes(folder.id);
              const isDragOver = dragOverTarget === folder.id;

              return (
                <div key={folder.id}
                  onDragOver={(e) => handleDragOver(e, folder.id)}
                  onDragLeave={handleDragLeave}
                  onDrop={(e) => handleDrop(e, folder.id)}
                  className={`bg-white rounded-xl border overflow-hidden transition-colors
                    ${isDragOver ? "border-[#c97b72] ring-2 ring-[#f5e8e6]" : "border-slate-100 hover:border-[#e8b4a8]"}`}>

                  {isDragOver && (
                    <div className="bg-[#fdf6f5] px-6 py-2 flex items-center gap-2 text-[#c97b72] text-sm font-semibold border-b border-[#e8b4a8]">
                      <i className="ri-folder-received-line text-base"></i>
                      放開以移入「{folder.name}」
                    </div>
                  )}

                  <div className="flex items-center gap-4 px-6 py-5 cursor-pointer hover:bg-[#fdf6f5]/60 transition-colors"
                    onClick={() => toggleFolder(folder.id)}>
                    <div className="w-12 h-12 flex items-center justify-center bg-[#f5e8e6] rounded-xl flex-shrink-0">
                      <i className={`${isOpen ? "ri-folder-open-line" : "ri-folder-line"} text-[#c97b72] text-2xl`}></i>
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <InlineEdit value={folder.name} onSave={(v) => renameFolder(folder.id, v)}
                          className="text-lg font-semibold text-slate-800 truncate" />
                        <span className="text-sm text-slate-400 whitespace-nowrap flex-shrink-0">{folderFiles.length} 個</span>
                      </div>
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
                    <div className="flex items-center gap-1 flex-shrink-0">
                      <button
                        onClick={(e) => { e.stopPropagation(); setConfirmDelete({ type: "folder", id: folder.id, name: folder.name }); }}
                        className="w-7 h-7 flex items-center justify-center text-slate-300 hover:text-red-400 hover:bg-red-50 rounded-lg cursor-pointer transition-all" title="刪除資料夾">
                        <i className="ri-delete-bin-line text-sm"></i>
                      </button>
                      <i className={`${isOpen ? "ri-arrow-up-s-line" : "ri-arrow-down-s-line"} text-slate-400 text-lg`}></i>
                    </div>
                  </div>

                  {isOpen && (
                    <div className="border-t border-slate-100 px-5 py-5">
                      {folderFiles.length === 0 ? (
                        <div className="flex flex-col items-center justify-center py-6 rounded-xl border-2 border-dashed border-slate-200">
                          <i className="ri-drag-move-line text-2xl text-slate-300 mb-1"></i>
                          <p className="text-sm text-slate-400">可拖曳檔案至此</p>
                        </div>
                      ) : (
                        <div className="grid grid-cols-1 gap-2">
                          {folderFiles.map((file) => (
                            <FileCard key={file.id} file={file} compact
                              isDragging={draggingFileId === file.id}
                              onDragStart={handleDragStart}
                              onDragEnd={handleDragEnd}
                              onRename={renameFile}
                              onDelete={(f) => setConfirmDelete({ type: "file", id: f.id, name: f.name })}
                              onOpen={() => navigate("/workspace")}
                            />
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}

            {folders.length === 0 && (
              <div onClick={openNewFolderModal}
                className="flex flex-col items-center justify-center gap-3 p-8 rounded-xl border-2 border-dashed border-slate-200 hover:border-[#e8b4a8] hover:bg-[#fdf6f5]/40 cursor-pointer transition-all text-center">
                <div className="w-12 h-12 flex items-center justify-center bg-[#f5e8e6] rounded-xl">
                  <i className="ri-folder-add-line text-[#c97b72] text-2xl"></i>
                </div>
                <p className="text-base font-semibold text-slate-500">建立第一個資料夾</p>
              </div>
            )}
          </div>
        </section>

        {/* ── 未分類檔案 ── */}
        <section>
          <h2 className="text-xl font-bold text-slate-700 mb-5 flex items-center gap-3">
            <span className="w-9 h-9 flex items-center justify-center bg-[#e6ecf4] rounded-xl">
              <i className="ri-file-list-3-line text-[#7a96b8] text-xl"></i>
            </span>
            未分類檔案
            {looseFiles.length > 0 && <span className="text-sm text-slate-400 font-normal">{looseFiles.length} 個</span>}
          </h2>

          <div
            onDragOver={(e) => handleDragOver(e, "loose")}
            onDragLeave={handleDragLeave}
            onDrop={(e) => handleDrop(e, null)}
            className={`min-h-[120px] rounded-2xl transition-colors p-1
              ${dragOverTarget === "loose" ? "ring-2 ring-[#7a96b8] bg-[#e6ecf4]/30" : ""}`}>

            {dragOverTarget === "loose" && (
              <div className="flex items-center justify-center gap-2 py-3 mb-3 bg-[#e6ecf4] rounded-xl text-[#7a96b8] text-sm font-semibold">
                <i className="ri-file-transfer-line text-base"></i>
                放開以移至未分類
              </div>
            )}

            {looseFiles.length === 0 ? (
              <div className={`flex flex-col items-center justify-center py-12 rounded-2xl border-2 border-dashed transition-colors
                ${draggingFileId ? "border-[#7a96b8] bg-[#e6ecf4]/20" : "border-slate-200"}`}>
                <i className="ri-file-list-3-line text-3xl text-slate-300 mb-2"></i>
                <p className="text-base text-slate-400">
                  {draggingFileId ? "拖曳到這裡移出資料夾" : "所有檔案都已整理到資料夾中"}
                </p>
              </div>
            ) : (
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
                {looseFiles.map((file) => (
                  <FileCard key={file.id} file={file}
                    isDragging={draggingFileId === file.id}
                    onDragStart={handleDragStart}
                    onDragEnd={handleDragEnd}
                    onRename={renameFile}
                    onDelete={(f) => setConfirmDelete({ type: "file", id: f.id, name: f.name })}
                    onOpen={() => navigate("/workspace")}
                  />
                ))}
              </div>
            )}
          </div>
        </section>

        {files.length === 0 && (
          <div className="text-center py-20">
            <div className="w-20 h-20 flex items-center justify-center bg-[#f5e8e6] rounded-2xl mx-auto mb-5">
              <i className="ri-folder-open-line text-[#c97b72] text-4xl"></i>
            </div>
            <h3 className="text-xl font-bold text-slate-700 mb-2">作品集是空的</h3>
            <p className="text-base text-slate-400 mb-6">前往工作區開始分析資料，結果會自動儲存在這裡</p>
            <button onClick={() => navigate("/workspace")}
              className="px-6 py-3 bg-[#c97b72] text-white text-base font-bold rounded-xl hover:bg-[#b86d64] cursor-pointer whitespace-nowrap transition-all">
              前往工作區
            </button>
          </div>
        )}
      </div>

      {/* 新增資料夾 Modal */}
      {showNewFolderModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm"
          onClick={() => setShowNewFolderModal(false)}>
          <div className="bg-white rounded-2xl p-8 w-full max-w-sm mx-4 border border-slate-100"
            onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center gap-3 mb-6">
              <div className="w-11 h-11 flex items-center justify-center bg-[#f5e8e6] rounded-xl">
                <i className="ri-folder-add-line text-[#c97b72] text-xl"></i>
              </div>
              <h3 className="text-xl font-bold text-slate-800">新增資料夾</h3>
            </div>
            <label className="block text-sm font-semibold text-slate-600 mb-2">資料夾名稱</label>
            <input ref={newFolderInputRef} type="text" value={newFolderName}
              onChange={(e) => { setNewFolderName(e.target.value); setNewFolderError(""); }}
              onKeyDown={(e) => { if (e.key === "Enter") handleCreateFolder(); if (e.key === "Escape") setShowNewFolderModal(false); }}
              placeholder="例如：2025 年度報告" maxLength={50}
              className="w-full px-4 py-3 bg-white border border-slate-200 rounded-xl text-base text-slate-800 placeholder-slate-400 focus:outline-none focus:border-[#e8b4a8] focus:ring-2 focus:ring-[#f5e8e6] transition-all" />
            {newFolderError && (
              <p className="mt-2 text-sm text-red-500 flex items-center gap-1.5">
                <i className="ri-error-warning-line"></i>{newFolderError}
              </p>
            )}
            <div className="flex gap-3 mt-6">
              <button onClick={handleCreateFolder}
                className="flex-1 py-3 bg-[#c97b72] text-white text-base font-bold rounded-xl hover:bg-[#b86d64] cursor-pointer whitespace-nowrap transition-all">建立</button>
              <button onClick={() => setShowNewFolderModal(false)}
                className="flex-1 py-3 border border-slate-200 text-slate-500 text-base font-semibold rounded-xl hover:bg-slate-50 cursor-pointer whitespace-nowrap transition-colors">取消</button>
            </div>
          </div>
        </div>
      )}

      {/* 刪除確認 Modal */}
      {confirmDelete && (
        <ConfirmModal
          title={confirmDelete.type === "folder" ? "刪除資料夾" : "刪除檔案"}
          desc={confirmDelete.type === "folder"
            ? `確定要刪除「${confirmDelete.name}」？資料夾內的檔案將移至未分類。`
            : `確定要刪除「${confirmDelete.name}」？此操作無法復原。`}
          onConfirm={() => {
            if (confirmDelete.type === "folder") doDeleteFolder(confirmDelete.id);
            else doDeleteFile(confirmDelete.id);
            setConfirmDelete(null);
          }}
          onCancel={() => setConfirmDelete(null)}
        />
      )}

      <LoginRequiredModal isOpen={showModal} onClose={() => setShowModal(false)} />
    </div>
  );
};

export default CollectionPage;
