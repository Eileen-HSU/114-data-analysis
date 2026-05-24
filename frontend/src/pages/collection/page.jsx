import { useState } from "react";
import { useNavigate } from "react-router-dom";
import Navbar from "../../components/feature/Navbar";
import LoginRequiredModal from "../../components/feature/LoginRequiredModal";
import { useAuth } from "../../hooks/AuthContext";
import { useCollection } from "../../hooks/CollectionContext";
import { useActivity } from "../../hooks/ActivityContext";
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
  const { recordActivity } = useActivity();
  const {
    folders,
    files,
    deletedItems,
    setFolders,
    setFiles,
    deleteFolder,
    deleteFile,
    restoreItem,
    permanentDelete,
    workspaceSessions,
  } = useCollection();

  const [activeView, setActiveView] = useState("folders");
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
  const [fileMenuId, setFileMenuId] = useState(null);

  if (!isLoggedIn) {
    return (
      <>
        <Navbar />
        <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "#f9f7f7" }}>
          <LoginRequiredModal
            message="請先登入後再查看作品集。"
            onLogin={() => navigate("/login")}
            onCancel={() => navigate("/")}
          />
        </div>
      </>
    );
  }

  const looseFiles = files.filter((file) => file.folder_name === null);
  const stats = {
    folders: folders.length,
    exports: 0,
    deleted: deletedItems.length,
  };

  const toggleFolder = (id) => {
    setOpenFolders((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;

    if (deleteTarget.type === "folder") {
      const folderFiles = files.filter((file) => file.folder_name === deleteTarget.name);

      await Promise.all(
        folderFiles.map(async (file) => {
          if (file.type === "chat" && file.sessionId) {
            const session = workspaceSessions.find((s) => s.project_id === Number(file.sessionId));
            if (session?.project_id) {
              try {
                const authUser = JSON.parse(localStorage.getItem("dataanalysis_auth"));
                const token = authUser?.token;
                await fetch(`${import.meta.env.VITE_API_BASE_URL || ""}/api/workspace/${session.project_id}`, {
                  method: "PUT",
                  headers: {
                    "Content-Type": "application/json",
                    ...(token ? { Authorization: `Bearer ${token}` } : {}),
                  },
                  body: JSON.stringify({ folder_name: null }),
                });
              } catch (err) {
                console.error(`更新檔案 ${file.name} 資料庫失敗:`, err);
              }
            }
          }
        })
      );

      deleteFolder(deleteTarget.id, deleteTarget.name);
    }

    if (deleteTarget.type === "file") deleteFile(deleteTarget.id, deleteTarget.name);

    setDeleteTarget(null);
  };

  const createFolder = () => {
    if (!newFolderName.trim()) return;
    setFolders((prev) => [...prev, { id: `folder-${Date.now()}`, name: newFolderName.trim() }]);
    recordActivity({
      text: `建立資料夾「${newFolderName.trim()}」`,
      icon: "ri-folder-add-line",
      iconBg: "bg-stat-sky",
      iconColor: "text-stat-sky",
    });
    setNewFolderName("");
    setShowNewFolderModal(false);
  };

  const openFile = (file) => {
    if (file.type === "chat" && file.sessionId) {
      navigate("/workspace", { state: { openSession: { sessionId: file.sessionId } } });
      return;
    }
    navigate("/workspace");
  };

  const saveFolderRename = (folderId) => {
    if (renameFolderValue.trim()) {
      setFolders((prev) => prev.map((folder) => (folder.id === folderId ? { ...folder, name: renameFolderValue.trim() } : folder)));
      recordActivity({
        text: `重新命名資料夾為「${renameFolderValue.trim()}」`,
        icon: "ri-edit-line",
        iconBg: "bg-violet-50",
        iconColor: "text-violet",
      });
    }
    setRenamingFolderId(null);
  };

  const saveFileRename = (fileId) => {
    if (renameFileValue.trim()) {
      setFiles((prev) => prev.map((file) => (file.id === fileId ? { ...file, name: renameFileValue.trim() } : file)));
      recordActivity({
        text: `重新命名檔案為「${renameFileValue.trim()}」`,
        icon: "ri-edit-line",
        iconBg: "bg-violet-50",
        iconColor: "text-violet",
      });
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
                <p className="collection-banner-label">My Portfolio</p>
                <h1 className="collection-banner-title">我的作品集</h1>
                <p className="collection-banner-stats">{files.length} 個檔案 · {folders.length} 個資料夾</p>
              </div>
              <div className="d-flex gap-2 align-items-center">
                <button className="btn btn-banner" onClick={() => navigate("/workspace")}>
                  <i className="ri-add-line me-1"></i>新增分析
                </button>
              </div>
            </div>
            <div className="row g-3 mt-4">
              {[
                { key: "folders", icon: "ri-folder-line", cls: "stat-folder", val: stats.folders, label: "資料夾", unit: "個資料夾" },
                { key: "exports", icon: "ri-download-cloud-2-line", cls: "stat-export", val: stats.exports, label: "輸出檔案", unit: "個檔案" },
                { key: "deleted", icon: "ri-delete-bin-line", cls: "stat-deleted", val: stats.deleted, label: "最近刪除", unit: "個項目" },
              ].map((item) => (
                <div className="col-12 col-md-4" key={item.label}>
                  <button
                    type="button"
                    className={`stat-card stat-card-button ${activeView === item.key ? "active" : ""}`}
                    onClick={() => setActiveView(item.key)}
                  >
                    <div className={`stat-icon ${item.cls}`}><i className={item.icon}></i></div>
                    <div className="stat-value">{item.val}</div>
                    <div className="stat-label">{item.label}</div>
                    <div className="stat-hint">{item.val} {item.unit}</div>
                  </button>
                </div>
              ))}
            </div>
          </div>
        </section>

        <div className="container py-5">
          {activeView === "folders" && (
          <>
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
                const folderFiles = files.filter((file) => file.folder_name === folder.name);
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
                                  menuOpen={fileMenuId === file.id}
                                  onMenuToggle={() => setFileMenuId((prev) => (prev === file.id ? null : file.id))}
                                  onMenuClose={() => setFileMenuId(null)}
                                  onDelete={() => setDeleteTarget({ type: "file", id: file.id, name: file.name })}
                                  onOpen={() => openFile(file)}
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
                        menuOpen={fileMenuId === file.id}
                        onMenuToggle={() => setFileMenuId((prev) => (prev === file.id ? null : file.id))}
                        onMenuClose={() => setFileMenuId(null)}
                        onDelete={() => setDeleteTarget({ type: "file", id: file.id, name: file.name })}
                        onOpen={() => openFile(file)}
                      />
                    </div>
                  ))}
                </div>
              )}
            </div>
          </section>
          </>
          )}

          {activeView === "exports" && (
            <section>
              <h2 className="section-heading">
                <span className="section-icon export-icon"><i className="ri-download-cloud-2-line"></i></span>
                輸出檔案
                <span className="loose-count">{stats.exports} 個</span>
              </h2>
              <div className="empty-loose">
                <i className="ri-download-cloud-2-line"></i>
                <p>目前沒有輸出檔案。</p>
              </div>
            </section>
          )}

          {activeView === "deleted" && (
            <section>
              <h2 className="section-heading">
                <span className="section-icon deleted-icon"><i className="ri-delete-bin-line"></i></span>
                最近刪除
                <span className="loose-count">{deletedItems.length} 個</span>
              </h2>
              {deletedItems.length === 0 ? (
                <div className="empty-loose">
                  <i className="ri-delete-bin-line"></i>
                  <p>目前沒有最近刪除的項目。</p>
                </div>
              ) : (
                <div className="deleted-list">
                  {deletedItems.map((item) => (
                    <div className="deleted-item" key={item.id}>
                      <div className="deleted-icon-box">
                        <i className={item.type === "folder" ? "ri-folder-line" : "ri-file-list-3-line"}></i>
                      </div>
                      <div className="deleted-info">
                        <div className="deleted-name">{item.name}</div>
                        <div className="deleted-meta">
                          {item.type === "folder" ? "資料夾" : "檔案"} · 刪除時間 {item.deletedAt || "-"}
                        </div>
                      </div>
                      <div className="deleted-actions">
                        <button className="btn-deleted-restore" onClick={() => restoreItem(item)}>
                          <i className="ri-arrow-go-back-line"></i>
                          還原
                        </button>
                        <button className="btn-deleted-remove" onClick={() => permanentDelete(item.id)}>
                          <i className="ri-delete-bin-2-line"></i>
                          永久刪除
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>
          )}
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

function FileRow({ file, compact = false, renamingId, renameValue, menuOpen, onMenuToggle, onMenuClose, onRenameStart, onRenameChange, onRenameSave, onRenameCancel, onDragStart, onDragEnd, onDelete, onOpen }) {
  const isRenaming = renamingId === file.id;
  return (
    <div
      className={`file-item ${compact ? "compact" : ""}`}
      onClick={onOpen}
      onContextMenu={(event) => {
        event.preventDefault();
        onMenuToggle();
      }}
    >
      <i
        className="ri-draggable drag-handle"
        draggable
        onClick={(event) => event.stopPropagation()}
        onDragStart={(event) => {
          event.stopPropagation();
          onDragStart();
        }}
        onDragEnd={(event) => {
          event.stopPropagation();
          onDragEnd();
        }}
      ></i>
      <div className={`file-icon file-icon-${file.type}`}>
        <i className={FILE_ICONS[file.type] || "ri-file-line"}></i>
      </div>
      <div className="file-info flex-grow-1">
        {isRenaming ? (
          <input
            className="form-control form-control-sm"
            value={renameValue}
            autoFocus
            onClick={(event) => event.stopPropagation()}
            onChange={(event) => onRenameChange(event.target.value)}
            onBlur={onRenameSave}
            onKeyDown={(event) => {
              if (event.key === "Enter") onRenameSave();
              if (event.key === "Escape") onRenameCancel();
            }}
          />
        ) : (
          <span
            className="file-name"
            onDoubleClick={(event) => {
              event.stopPropagation();
              onRenameStart();
            }}
          >
            {file.name}
          </span>
        )}
        <div className="file-meta">
          <span className={`file-badge badge-${file.type}`}>{file.type === "chat" ? "Chat" : file.type.toUpperCase()}</span>
          <span className="file-size">{file.size}</span>
          {file.createdAt && <span className="file-size">{file.createdAt}</span>}
        </div>
      </div>
      <div className="file-actions">
        <button
          className="action-btn-sm"
          onClick={(event) => {
            event.stopPropagation();
            onMenuToggle();
          }}
          title="更多"
        >
          <i className="ri-more-2-fill"></i>
        </button>
        {menuOpen && (
          <div className="file-menu" onClick={(event) => event.stopPropagation()}>
            <button
              className="file-menu-item"
              onClick={() => {
                onMenuClose();
                onRenameStart();
              }}
            >
              <i className="ri-edit-line"></i>
              重新命名
            </button>
            <button
              className="file-menu-item danger"
              onClick={() => {
                onMenuClose();
                onDelete();
              }}
            >
              <i className="ri-delete-bin-line"></i>
              刪除
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
