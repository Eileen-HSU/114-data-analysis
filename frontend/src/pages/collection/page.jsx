import { useState } from "react";
import { useNavigate } from "react-router-dom";
import Navbar from "../../components/feature/Navbar";
import LoginRequiredModal from "../../components/feature/LoginRequiredModal";
import { useAuth } from "../../hooks/AuthContext";
import { useCollection } from "../../hooks/CollectionContext";
import "./collection.css";

const FILE_ICONS = {
  csv: "ri-file-chart-line",
  xlsx: "ri-file-excel-line",
  json: "ri-file-code-line",
  txt: "ri-file-text-line",
  chat: "ri-chat-ai-line",
};

export default function CollectionPage() {
  const navigate = useNavigate();
  const { isLoggedIn } = useAuth();
  const {
    folders,
    files,
    deletedItems,
    setFolders,
    setFiles,
    deleteFolder,
    deleteFile,
  } = useCollection();

  const [openFolders, setOpenFolders] = useState(new Set(["f1"]));
  const [draggingId, setDraggingId] = useState(null);
  const [dragOverTarget, setDragOverTarget] = useState(null);
  const [showNewFolderModal, setShowNewFolderModal] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [renamingFileId, setRenamingFileId] = useState(null);
  const [renameFileValue, setRenameFileValue] = useState("");
  const [renamingFolderId, setRenamingFolderId] = useState(null);
  const [renameFolderValue, setRenameFolderValue] = useState("");

  if (!isLoggedIn) {
    return (
      <>
        <Navbar />
        <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "#f9f7f7" }}>
          <LoginRequiredModal
            message="請先登入後再查看收藏。"
            onLogin={() => navigate("/login")}
            onCancel={() => navigate("/")}
          />
        </div>
      </>
    );
  }

  const looseFiles = files.filter((file) => file.folderId === null);
  const stats = {
    csv: files.filter((file) => file.type === "csv").length,
    xlsx: files.filter((file) => file.type === "xlsx").length,
    json: files.filter((file) => file.type === "json").length,
    folders: folders.length,
  };

  const toggleFolder = (id) => {
    setOpenFolders((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const handleDrop = (folderId) => {
    if (!draggingId) return;
    setFiles((prev) => prev.map((file) => (file.id === draggingId ? { ...file, folderId } : file)));
    setDraggingId(null);
    setDragOverTarget(null);
  };

  const createFolder = () => {
    if (!newFolderName.trim()) return;
    setFolders((prev) => [...prev, { id: `folder-${Date.now()}`, name: newFolderName.trim() }]);
    setNewFolderName("");
    setShowNewFolderModal(false);
  };

  const confirmDelete = () => {
    if (!deleteTarget) return;
    if (deleteTarget.type === "folder") deleteFolder(deleteTarget.id, deleteTarget.name);
    if (deleteTarget.type === "file") deleteFile(deleteTarget.id, deleteTarget.name);
    setDeleteTarget(null);
  };

  const saveFolderRename = (folderId) => {
    if (renameFolderValue.trim()) {
      setFolders((prev) => prev.map((folder) => (folder.id === folderId ? { ...folder, name: renameFolderValue.trim() } : folder)));
    }
    setRenamingFolderId(null);
  };

  const saveFileRename = (fileId) => {
    if (renameFileValue.trim()) {
      setFiles((prev) => prev.map((file) => (file.id === fileId ? { ...file, name: renameFileValue.trim() } : file)));
    }
    setRenamingFileId(null);
  };

  return (
    <>
      <Navbar />
      <main>
        <section className="collection-banner">
          <div className="collection-banner-overlay"></div>
          <div className="container position-relative">
            <div className="d-flex align-items-center justify-content-between flex-wrap gap-3">
              <div>
                <p className="collection-banner-label">My Collection</p>
                <h1 className="collection-banner-title">我的收藏</h1>
                <p className="collection-banner-stats">{files.length} 個檔案 · {folders.length} 個資料夾</p>
              </div>
              <div className="d-flex gap-2 align-items-center">
                <button className="btn-trash" onClick={() => navigate("/trash")} title="垃圾桶">
                  <i className="ri-delete-bin-line"></i>
                  垃圾桶
                  {deletedItems.length > 0 && <span className="trash-badge">{deletedItems.length}</span>}
                </button>
                <button className="btn btn-banner" onClick={() => navigate("/workspace")}>
                  <i className="ri-add-line me-1"></i>新增分析
                </button>
              </div>
            </div>
            <div className="row g-3 mt-4">
              {[
                { icon: "ri-file-chart-line", cls: "stat-csv", val: stats.csv, label: "CSV 檔案" },
                { icon: "ri-file-excel-line", cls: "stat-xlsx", val: stats.xlsx, label: "Excel 檔案" },
                { icon: "ri-file-code-line", cls: "stat-json", val: stats.json, label: "JSON 檔案" },
                { icon: "ri-folder-line", cls: "stat-folder", val: stats.folders, label: "資料夾" },
              ].map((item) => (
                <div className="col-6 col-md-3" key={item.label}>
                  <div className="stat-card">
                    <div className={`stat-icon ${item.cls}`}><i className={item.icon}></i></div>
                    <div className="stat-value">{item.val}</div>
                    <div className="stat-label">{item.label}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        <div className="container py-5">
          <section className="mb-5">
            <h2 className="section-heading">
              <span className="section-icon folder-icon"><i className="ri-folder-2-line"></i></span>
              資料夾
              <button className="btn btn-add-folder ms-auto" onClick={() => setShowNewFolderModal(true)}>
                <i className="ri-folder-add-line me-1"></i>新增資料夾
              </button>
            </h2>
            <div className="row g-3">
              {folders.map((folder) => {
                const folderFiles = files.filter((file) => file.folderId === folder.id);
                const isOpen = openFolders.has(folder.id);
                const isDragOver = dragOverTarget === folder.id;
                return (
                  <div className="col-md-6 col-lg-4" key={folder.id}>
                    <div
                      className={`folder-card ${isDragOver ? "drag-over" : ""}`}
                      onDragOver={(event) => { event.preventDefault(); setDragOverTarget(folder.id); }}
                      onDragLeave={() => setDragOverTarget(null)}
                      onDrop={() => handleDrop(folder.id)}
                    >
                      {isDragOver && <div className="folder-drop-hint"><i className="ri-folder-received-line me-2"></i>移到「{folder.name}」</div>}
                      <div className="folder-header" onClick={() => toggleFolder(folder.id)}>
                        <div className="folder-icon-box"><i className={isOpen ? "ri-folder-open-line" : "ri-folder-line"}></i></div>
                        <div className="folder-info flex-grow-1">
                          <div className="d-flex align-items-center gap-2">
                            {renamingFolderId === folder.id ? (
                              <input
                                className="form-control form-control-sm"
                                value={renameFolderValue}
                                autoFocus
                                onClick={(event) => event.stopPropagation()}
                                onChange={(event) => setRenameFolderValue(event.target.value)}
                                onBlur={() => saveFolderRename(folder.id)}
                                onKeyDown={(event) => {
                                  if (event.key === "Enter") saveFolderRename(folder.id);
                                  if (event.key === "Escape") setRenamingFolderId(null);
                                }}
                              />
                            ) : (
                              <span className="folder-name" onDoubleClick={(event) => { event.stopPropagation(); setRenamingFolderId(folder.id); setRenameFolderValue(folder.name); }}>
                                {folder.name}
                              </span>
                            )}
                            <span className="folder-count">{folderFiles.length} 個</span>
                          </div>
                          <div className="folder-tags">
                            {["csv", "xlsx", "json", "txt", "chat"].map((type) => {
                              const count = folderFiles.filter((file) => file.type === type).length;
                              return count > 0 ? <span key={type} className={`folder-tag tag-${type}`}>{type === "chat" ? "Chat" : type.toUpperCase()} {count}</span> : null;
                            })}
                          </div>
                        </div>
                        <div className="folder-actions">
                          <button className="action-btn" onClick={(event) => { event.stopPropagation(); setDeleteTarget({ type: "folder", id: folder.id, name: folder.name }); }} title="刪除">
                            <i className="ri-delete-bin-line"></i>
                          </button>
                          <i className="ri-arrow-down-s-line folder-arrow" style={{ transform: isOpen ? "rotate(180deg)" : "rotate(0deg)" }}></i>
                        </div>
                      </div>
                      {isOpen && (
                        <div className="folder-content">
                          {folderFiles.length === 0 ? (
                            <div className="empty-folder"><i className="ri-drag-move-line"></i><p>拖曳檔案到這裡</p></div>
                          ) : (
                            <div className="folder-files">
                              {folderFiles.map((file) => (
                                <FileRow
                                  key={file.id}
                                  file={file}
                                  compact
                                  renamingId={renamingFileId}
                                  renameValue={renameFileValue}
                                  onRenameStart={() => { setRenamingFileId(file.id); setRenameFileValue(file.name); }}
                                  onRenameChange={setRenameFileValue}
                                  onRenameSave={() => saveFileRename(file.id)}
                                  onRenameCancel={() => setRenamingFileId(null)}
                                  onDragStart={() => setDraggingId(file.id)}
                                  onDragEnd={() => setDraggingId(null)}
                                  onDelete={() => setDeleteTarget({ type: "file", id: file.id, name: file.name })}
                                  onOpen={() => file.type === "chat" && file.sessionId ? navigate("/workspace", { state: { openSession: { sessionId: file.sessionId } } }) : navigate("/workspace")}
                                />
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </section>

          <section>
            <h2 className="section-heading">
              <span className="section-icon loose-icon"><i className="ri-file-list-3-line"></i></span>
              未分類檔案
              {looseFiles.length > 0 && <span className="loose-count">{looseFiles.length} 個</span>}
            </h2>
            <div
              className={`loose-area ${dragOverTarget === "loose" ? "drag-over" : ""}`}
              onDragOver={(event) => { event.preventDefault(); setDragOverTarget("loose"); }}
              onDragLeave={() => setDragOverTarget(null)}
              onDrop={() => handleDrop(null)}
            >
              {dragOverTarget === "loose" && <div className="loose-drop-hint"><i className="ri-file-transfer-line me-2"></i>移到未分類</div>}
              {looseFiles.length === 0 ? (
                <div className="empty-loose"><i className="ri-file-list-3-line"></i><p>目前沒有未分類檔案。</p></div>
              ) : (
                <div className="row g-3">
                  {looseFiles.map((file) => (
                    <div className="col-md-6 col-lg-4 col-xl-3" key={file.id}>
                      <FileRow
                        file={file}
                        renamingId={renamingFileId}
                        renameValue={renameFileValue}
                        onRenameStart={() => { setRenamingFileId(file.id); setRenameFileValue(file.name); }}
                        onRenameChange={setRenameFileValue}
                        onRenameSave={() => saveFileRename(file.id)}
                        onRenameCancel={() => setRenamingFileId(null)}
                        onDragStart={() => setDraggingId(file.id)}
                        onDragEnd={() => setDraggingId(null)}
                        onDelete={() => setDeleteTarget({ type: "file", id: file.id, name: file.name })}
                        onOpen={() => file.type === "chat" && file.sessionId ? navigate("/workspace", { state: { openSession: { sessionId: file.sessionId } } }) : navigate("/workspace")}
                      />
                    </div>
                  ))}
                </div>
              )}
            </div>
          </section>
        </div>
      </main>

      {showNewFolderModal && (
        <div className="modal-backdrop-custom" onClick={() => setShowNewFolderModal(false)}>
          <div className="modal-box" onClick={(event) => event.stopPropagation()}>
            <div className="d-flex align-items-center gap-3 mb-4">
              <div className="modal-folder-icon"><i className="ri-folder-add-line"></i></div>
              <h5 className="fw-bold m-0">新增資料夾</h5>
            </div>
            <label className="auth-label">資料夾名稱</label>
            <input className="form-control" value={newFolderName} onChange={(event) => setNewFolderName(event.target.value)} onKeyDown={(event) => event.key === "Enter" && createFolder()} autoFocus />
            <div className="d-flex gap-2 mt-4">
              <button className="btn btn-add-folder flex-fill" onClick={createFolder}>建立</button>
              <button className="btn btn-outline-secondary flex-fill" onClick={() => setShowNewFolderModal(false)}>取消</button>
            </div>
          </div>
        </div>
      )}

      {deleteTarget && (
        <div className="modal-backdrop-custom" onClick={() => setDeleteTarget(null)}>
          <div className="modal-box text-center" onClick={(event) => event.stopPropagation()}>
            <div className="delete-icon"><i className="ri-delete-bin-line"></i></div>
            <h5 className="fw-bold mb-2">刪除{deleteTarget.type === "folder" ? "資料夾" : "檔案"}</h5>
            <p className="text-muted mb-4">「{deleteTarget.name}」會移到垃圾桶，可稍後還原。</p>
            <div className="d-flex gap-2">
              <button className="btn btn-danger flex-fill" onClick={confirmDelete}>確認刪除</button>
              <button className="btn btn-outline-secondary flex-fill" onClick={() => setDeleteTarget(null)}>取消</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function FileRow({ file, compact = false, renamingId, renameValue, onRenameStart, onRenameChange, onRenameSave, onRenameCancel, onDragStart, onDragEnd, onDelete, onOpen }) {
  const isRenaming = renamingId === file.id;
  return (
    <div className={`file-item ${compact ? "compact" : ""}`} draggable onDragStart={onDragStart} onDragEnd={onDragEnd}>
      <i className="ri-draggable drag-handle"></i>
      <div className={`file-icon file-icon-${file.type}`}>
        <i className={FILE_ICONS[file.type] || "ri-file-line"}></i>
      </div>
      <div className="file-info flex-grow-1">
        {isRenaming ? (
          <input
            className="form-control form-control-sm"
            value={renameValue}
            autoFocus
            onChange={(event) => onRenameChange(event.target.value)}
            onBlur={onRenameSave}
            onKeyDown={(event) => {
              if (event.key === "Enter") onRenameSave();
              if (event.key === "Escape") onRenameCancel();
            }}
          />
        ) : (
          <span className="file-name" onDoubleClick={onRenameStart}>{file.name}</span>
        )}
        <div className="file-meta">
          <span className={`file-badge badge-${file.type}`}>{file.type === "chat" ? "Chat" : file.type.toUpperCase()}</span>
          <span className="file-size">{file.size}</span>
          {file.createdAt && <span className="file-size">{file.createdAt}</span>}
        </div>
      </div>
      <div className="file-actions">
        <button className="action-btn-sm" onClick={onOpen} title="開啟"><i className="ri-external-link-line"></i></button>
        <button className="action-btn-sm" onClick={onDelete} title="刪除"><i className="ri-delete-bin-line"></i></button>
      </div>
    </div>
  );
}
