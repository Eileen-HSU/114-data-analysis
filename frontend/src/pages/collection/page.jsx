import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import Navbar from "../../components/feature/Navbar";
import LoginRequiredModal from "../../components/feature/LoginRequiredModal";
import { useAuth } from "../../hooks/AuthContext";
import { useCollection } from "../../hooks/CollectionContext";
import { useActivity } from "../../hooks/ActivityContext";
import { apiUrl } from "../../lib/api";
import "./collection.css";
import ExportFileRow from "./ExportFileRow";

const ACTIVE_WORKSPACE_KEY = "dataanalysis_active_workspace";

const FILE_ICONS = {
  csv: "ri-file-chart-line",
  xlsx: "ri-file-excel-line",
  json: "ri-file-code-line",
  txt: "ri-file-text-line",
  chat: "ri-chat-3-line",
};

const getFileFolderName = (file) => file.folder_name ?? null;

function getAuthHeader() {
  try {
    const user = JSON.parse(localStorage.getItem("dataanalysis_auth"));
    const token = user?.token;
    return token ? { Authorization: `Bearer ${token}` } : {};
  } catch {
    return {};
  }
}

export default function CollectionPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { isLoggedIn, user } = useAuth();
  const { recordActivity } = useActivity();
  const {
    folders,
    files,
    deletedItems,
    setFolders,
    setFiles,
    setWorkspaceSessions,
    deleteFolder,
    deleteChatSession,
    restoreItem,
    permanentDelete,
    workspaceSessions,
  } = useCollection();

  const [activeView, setActiveView] = useState(() => location.state?.activeView || "folders");
  // 進入專案管理即載入匯出紀錄，讓統計卡片同步顯示實際數量。
  const [exportsList, setExportsList] = useState([]);
  const [exportSearch, setExportSearch] = useState("");
  const [exportNotice, setExportNotice] = useState("");
  const exportSearchTerm = exportSearch.trim().toLocaleLowerCase();
  const filteredExports = useMemo(() => exportsList.filter((item) =>
    String(item.export_name ?? "").toLocaleLowerCase().includes(exportSearchTerm)
  ), [exportsList, exportSearchTerm]);
  const [exportsLoading, setExportsLoading] = useState(isLoggedIn);
  const [exportsError, setExportsError] = useState(null);
  const [openFolders, setOpenFolders] = useState(new Set(["f1"]));
  const [draggingId, setDraggingId] = useState(null);
  const [dragOverTarget, setDragOverTarget] = useState(null);
  const [showNewFolderModal, setShowNewFolderModal] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [restoringId, setRestoringId] = useState(null);
  const [permanentDeletingId, setPermanentDeletingId] = useState(null);
  const [renamingFileId, setRenamingFileId] = useState(null);
  const [renameFileValue, setRenameFileValue] = useState("");
  const [renamingFolderId, setRenamingFolderId] = useState(null);
  const [renameFolderValue, setRenameFolderValue] = useState("");
  const [fileMenuId, setFileMenuId] = useState(null);
  const [renameTarget, setRenameTarget] = useState(null);
  const [isSavingRename, setIsSavingRename] = useState(false);
  const [isCreatingAnalysis, setIsCreatingAnalysis] = useState(false);

  useEffect(() => {
    if (location.state?.exportCreated) setExportNotice(`「${location.state.exportCreated} is ready. Click the file to download.`);
    if (location.state?.activeView) {
      setActiveView(location.state.activeView);
      window.history.replaceState({}, "");
    }
  }, [location.state]);

  // 登入後立即載入總數及清單，不必先點選匯出檔案。
  useEffect(() => {
    if (!isLoggedIn) { setExportsList([]); setExportsLoading(false); return; }
    let cancelled = false;
    setExportsLoading(true);
    setExportsError(null);
    fetch(apiUrl("/api/exports"), { headers: getAuthHeader() })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data) => {
        if (!cancelled) setExportsList(Array.isArray(data) ? data : []);
      })
      .catch((err) => {
        if (!cancelled) setExportsError(err?.message || "Loading failed");
      })
      .finally(() => {
        if (!cancelled) setExportsLoading(false);
      });
    return () => { cancelled = true; };
  }, [isLoggedIn, user?.token]);

  const handleOpenExportChat = async (item) => {
    if (!item.project_id) throw new Error("The source conversation for this file was not found.");
    const response = await fetch(apiUrl(`/api/workspace/${item.project_id}`), { headers: getAuthHeader() });
    if (!response.ok) throw new Error(response.status === 404
      ? "The source conversation was deleted or is unavailable." : "Unable to open the source conversation. Please try again later.");
    const workspace = await response.json();
    if (!workspace.project_id || String(workspace.project_id) !== String(item.project_id)) {
      throw new Error("Unable to find the source conversation. Refresh and try again.");
    }
    const existing = workspaceSessions.find((session) => String(session.project_id ?? session.id) === String(workspace.project_id));
    const sessionId = existing?.id || String(workspace.project_id);
    const session = {
      ...existing, id: sessionId, project_id: workspace.project_id,
      title: workspace.project_name, name: workspace.project_name,
      folder_name: workspace.folder_name ?? null,
      date: workspace.created_at ? workspace.created_at.slice(0, 10) : "",
    };
    setWorkspaceSessions((current) => [session, ...current.filter((entry) =>
      String(entry.project_id ?? entry.id) !== String(workspace.project_id)
    )]);
    localStorage.setItem(ACTIVE_WORKSPACE_KEY, String(sessionId));
    navigate("/workspace", { state: { openSession: { sessionId, scrollToBottom: true } } });
  };

  const handleRenameExport = async (item, filename) => {
    setExportNotice("");
    const response = await fetch(apiUrl(`/api/exports/${item.export_id}`), {
      method: "PATCH",
      headers: { "Content-Type": "application/json", ...getAuthHeader() },
      body: JSON.stringify({ filename }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || "Rename failed. Please try again later.");
    if (!data.export_name) throw new Error("The server did not return a file name. Please refresh to check.");
    setExportsList((items) => items.map((entry) => entry.export_id === item.export_id ? { ...entry, ...data } : entry));
    setExportNotice(`Renamed the file to: ${data.export_name}」。`);
  };

  const handleDownloadExport = async (exportItem) => {
    try {
      const res = await fetch(apiUrl(`/api/exports/${exportItem.export_id}/download`), {
        headers: getAuthHeader(),
      });
      if (!res.ok) {
        // 【修正】之前失敗只印在 console 裡，使用者完全看不到、
        // 感覺就像「點了沒反應」。這裡照這個頁面既有的 alert() 慣例補上。
        alert(`Download failed (HTTP  ${res.status}). Please try again later.`);
        return;
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = exportItem.export_name || "export.csv";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error("Failed to download exported file: ", err);
      alert("Download failed. Please try again later.");
    }
  };

  if (!isLoggedIn) {
    return (
      <>
        <Navbar />
        <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "#f9f7f7" }}>
          <LoginRequiredModal
            message="Please log in to view Project Management."
            onLogin={() => navigate("/login")}
            onCancel={() => navigate("/")}
          />
        </div>
      </>
    );
  }

  const filesByFolder = useMemo(() => {
    const grouping = {};
    const assignedFileIds = new Set();
    folders.forEach((folder) => {
      const memberIds = new Set(folder.fileIds || []);
      files.forEach((file) => {
        if (getFileFolderName(file) === folder.name) memberIds.add(file.id);
      });
      grouping[folder.name] = files.filter((file) => {
        const belongsToFolder = memberIds.has(file.id);
        if (belongsToFolder) assignedFileIds.add(file.id);
        return belongsToFolder;
      });
    });
    grouping.loose = files.filter((file) => !assignedFileIds.has(file.id));
    return grouping;
  }, [files, folders]);

  const sessionsByFolder = useMemo(() => {
    const grouping = {};
    const assignedSessionIds = new Set();
    folders.forEach((folder) => {
      grouping[folder.name] = workspaceSessions.filter((session) => session.folder_name === folder.name);
      grouping[folder.name].forEach((session) => assignedSessionIds.add(session.id));
    });
    grouping.loose = workspaceSessions.filter((session) => !assignedSessionIds.has(session.id));
    return grouping;
  }, [workspaceSessions, folders]);

  const looseFiles = filesByFolder.loose || [];
  const looseSessions = sessionsByFolder.loose || [];
  const stats = useMemo(() => {
    const chatSessions = new Map();
    workspaceSessions.forEach((session) => {
      const sessionId = session.project_id ?? session.id;
      if (sessionId !== undefined && sessionId !== null && String(sessionId).trim()) {
        chatSessions.set(String(sessionId), session);
      }
    });

    const folderNames = new Set();
    folders.forEach((folder) => {
      const folderName = folder?.name?.trim();
      if (folderName) folderNames.add(folderName);
    });
    chatSessions.forEach((session) => {
      const folderName = session?.folder_name?.trim();
      if (folderName) folderNames.add(folderName);
    });

    return {
      folders: folderNames.size,
      chats: chatSessions.size,
      exports: exportsList.length,
      deleted: deletedItems.length,
    };
  }, [workspaceSessions, folders, deletedItems.length, exportsList.length]);

  const toggleFolder = (id) => {
    setOpenFolders((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  // 刪除
  const confirmDelete = async () => {
    if (!deleteTarget || isDeleting) return;
    setIsDeleting(true);

    try {
    if (deleteTarget.type === "folder") {
      const folderFiles = files.filter((file) => getFileFolderName(file) === deleteTarget.name);

      // 資料夾內的 chat session 同步後端 folder_name = null
      await Promise.all(
        folderFiles.map(async (file) => {
          if (file.type === "chat" && file.sessionId) {
            const session = workspaceSessions.find(
              (s) =>
                String(s.id) === String(file.sessionId) ||
                (s.project_id && String(s.project_id) === String(file.sessionId))
            );
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
                console.error(`Update file  ${file.name}  database update failed:`, err);
              }
            }
          }
        })
      );

      const folderSessionIds = new Set(folderFiles.map((file) => String(file.sessionId)));
      setWorkspaceSessions((prev) =>
        prev.map((session) =>
          folderSessionIds.has(String(session.id))
            ? { ...session, folder_name: null }
            : session
        )
      );

      deleteFolder(deleteTarget.id, deleteTarget.name);
    }

    if (deleteTarget.type === "file") {
      const file = files.find((f) => f.id === deleteTarget.id);
      if (file?.type === "chat" && file?.sessionId) {
        // chat 類型：透過 deleteChatSession 同步 workspace
        await deleteChatSession(String(file.sessionId));
      }
    }

    if (deleteTarget.type === "session") {
      await deleteChatSession(String(deleteTarget.id));
    }

    setDeleteTarget(null);
    } finally {
      setIsDeleting(false);
    }
  };

  // 新增資料夾
  const handlePermanentDelete = async (item) => {
    if (!item || permanentDeletingId || restoringId) return;
    setPermanentDeletingId(item.id);
    try {
      await permanentDelete(item, item.type === "folder");
    } finally {
      setPermanentDeletingId(null);
    }
  };

  const handleRestoreItem = async (item) => {
    if (!item || restoringId || permanentDeletingId) return;
    setRestoringId(item.id);
    try {
      await restoreItem(item);
    } finally {
      setRestoringId(null);
    }
  };

  const createFolder = () => {
    if (!newFolderName.trim()) return;
    setFolders((prev) => [...prev, { id: `folder-${Date.now()}`, name: newFolderName.trim(), fileIds: [] }]);
    recordActivity({
      text: `Created folder: ${newFolderName.trim()}`,
      icon: "ri-folder-add-line",
      iconBg: "bg-stat-sky",
      iconColor: "text-stat-sky",
    });
    setNewFolderName("");
    setShowNewFolderModal(false);
  };

  // 開啟檔案
  const openFile = (file) => {
    if (file.type === "chat" && file.sessionId) {
      navigate("/workspace", { state: { openSession: { sessionId: file.sessionId } } });
      return;
    }
    navigate("/workspace");
  };

  // 重新命名
  const saveFolderRename = (folderId) => {
    if (renameFolderValue.trim()) {
      setFolders((prev) => prev.map((folder) => (folder.id === folderId ? { ...folder, name: renameFolderValue.trim() } : folder)));
      recordActivity({
        text: `Renamed folder to: ${renameFolderValue.trim()}`,
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
        text: `Renamed file to: ${renameFileValue.trim()}`,
        icon: "ri-edit-line",
        iconBg: "bg-violet-50",
        iconColor: "text-violet",
      });
    }
    setRenamingFileId(null);
  };

  const saveSessionRename = async (sessionId) => {
    const newName = renameFileValue.trim();
    if (newName) {
      const session = workspaceSessions.find((item) => String(item.id) === String(sessionId));
      setWorkspaceSessions((prev) =>
        prev.map((item) =>
          String(item.id) === String(sessionId)
            ? { ...item, title: newName, name: newName }
            : item
        )
      );
      recordActivity({
        text: `Renamed file to: ${newName}`,
        icon: "ri-edit-line",
        iconBg: "bg-violet-50",
        iconColor: "text-violet",
      });

      const projectId = session?.project_id ?? session?.id;
      if (projectId) {
        try {
          const authUser = JSON.parse(localStorage.getItem("dataanalysis_auth"));
          const token = authUser?.token;
          await fetch(`${import.meta.env.VITE_API_BASE_URL || ""}/api/workspace/${projectId}`, {
            method: "PUT",
            headers: {
              "Content-Type": "application/json",
              ...(token ? { Authorization: `Bearer ${token}` } : {}),
            },
            body: JSON.stringify({ project_name: newName }),
          });
        } catch (err) {
          console.error("Failed to rename chat", err);
        }
      }
    }
    setRenamingFileId(null);
  };

  const openRenameModal = (target) => {
    setRenameTarget(target);
    setRenameFileValue(target.name || "");
    setRenamingFileId(null);
    setFileMenuId(null);
  };

  const closeRenameModal = () => {
    if (isSavingRename) return;
    setRenameTarget(null);
    setRenameFileValue("");
  };

  const updateWorkspaceProjectName = async (projectId, projectName) => {
    if (!projectId) return;
    const authUser = JSON.parse(localStorage.getItem("dataanalysis_auth"));
    const token = authUser?.token;
    await fetch(`${import.meta.env.VITE_API_BASE_URL || ""}/api/workspace/${projectId}`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ project_name: projectName }),
    });
  };

  const submitRename = async () => {
    const newName = renameFileValue.trim();
    if (!renameTarget || !newName || isSavingRename) return;
    setIsSavingRename(true);

    try {
      if (renameTarget.type === "file") {
        setFiles((prev) =>
          prev.map((file) => (file.id === renameTarget.id ? { ...file, name: newName } : file))
        );
        if (renameTarget.fileType === "chat" && renameTarget.sessionId) {
          setWorkspaceSessions((prev) =>
            prev.map((session) =>
              String(session.id) === String(renameTarget.sessionId)
                ? { ...session, title: newName, name: newName }
                : session
            )
          );
          await updateWorkspaceProjectName(renameTarget.sessionId, newName);
        }
      }

      if (renameTarget.type === "session") {
        setWorkspaceSessions((prev) =>
          prev.map((session) =>
            String(session.id) === String(renameTarget.id)
              ? { ...session, title: newName, name: newName }
              : session
          )
        );
        await updateWorkspaceProjectName(renameTarget.projectId || renameTarget.id, newName);
      }

      if (renameTarget.type === "folder") {
        const oldName = renameTarget.name;
        setFolders((prev) =>
          prev.map((folder) =>
            folder.id === renameTarget.id ? { ...folder, name: newName } : folder
          )
        );
        setFiles((prev) =>
          prev.map((file) =>
            getFileFolderName(file) === oldName ? { ...file, folder_name: newName } : file
          )
        );
        setWorkspaceSessions((prev) =>
          prev.map((session) =>
            session.folder_name === oldName ? { ...session, folder_name: newName } : session
          )
        );

        const folderSessions = workspaceSessions.filter((session) => session.folder_name === oldName);
        await Promise.all(
          folderSessions.map((session) => {
            const projectId = session.project_id || session.id;
            if (!projectId) return Promise.resolve();
            const authUser = JSON.parse(localStorage.getItem("dataanalysis_auth"));
            const token = authUser?.token;
            return fetch(`${import.meta.env.VITE_API_BASE_URL || ""}/api/workspace/${projectId}`, {
              method: "PUT",
              headers: {
                "Content-Type": "application/json",
                ...(token ? { Authorization: `Bearer ${token}` } : {}),
              },
              body: JSON.stringify({ folder_name: newName }),
            });
          })
        );
      }

      recordActivity({
        text: `Rename${renameTarget.type === "folder" ? "Folder" : "File"} to: ${newName}」`,
        icon: "ri-edit-line",
        iconBg: "bg-violet-50",
        iconColor: "text-violet",
      });
      setRenameTarget(null);
      setRenameFileValue("");
    } catch (err) {
      console.error("Rename failed", err);
      alert("Rename failed. Please try again later.");
    } finally {
      setIsSavingRename(false);
    }
  };

  // 拖曳
  const resetDragState = () => {
    setDraggingId(null);
    setDragOverTarget(null);
  };

  const handleFolderDragOver = (targetId, event) => {
    event.preventDefault();
    event.stopPropagation();
    event.dataTransfer.dropEffect = "move";
    if (dragOverTarget !== targetId) setDragOverTarget(targetId);
  };

  const handleFolderDragLeave = (event) => {
    if (event.currentTarget.contains(event.relatedTarget)) return;
    setDragOverTarget(null);
  };

  const handleDrop = async (targetFolderId, event) => {
    event.preventDefault();
    event.stopPropagation();
    setDragOverTarget(null);
    const droppedFileId = event.dataTransfer?.getData("text/plain") || draggingId;
    if (!droppedFileId) return;

    const targetFolderName = targetFolderId
      ? folders.find((f) => f.id === targetFolderId)?.name ?? null
      : null;

    const file = files.find((f) => f.id === droppedFileId);

    if (file) {
      setFiles((prev) =>
        prev.map((f) => (f.id === droppedFileId ? { ...f, folder_name: targetFolderName } : f))
      );
      setFolders((prev) =>
        prev.map((folder) => {
          const currentFileIds = Array.isArray(folder.fileIds) ? folder.fileIds : [];
          const fileIdsWithoutDropped = currentFileIds.filter((id) => id !== droppedFileId);
          if (folder.id !== targetFolderId) return { ...folder, fileIds: fileIdsWithoutDropped };
          return { ...folder, fileIds: [...fileIdsWithoutDropped, droppedFileId] };
        })
      );
      setWorkspaceSessions((prev) =>
        prev.map((session) =>
          String(session.id) === String(file.sessionId)
            ? { ...session, folder_name: targetFolderName }
            : session
        )
      );
      if (file.type === "chat" && file.sessionId) {
        const session = workspaceSessions.find(
          (s) =>
            String(s.id) === String(file.sessionId) ||
            (s.project_id && String(s.project_id) === String(file.sessionId))
        );
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
              body: JSON.stringify({ folder_name: targetFolderName }),
            });
          } catch (err) {
            console.error("Drag-and-drop database update failed:", err);
          }
        }
      }
    } else {
      const session = workspaceSessions.find((s) => String(s.id) === String(droppedFileId));
      if (!session) { setDraggingId(null); return; }

      setWorkspaceSessions((prev) =>
        prev.map((s) =>
          String(s.id) === String(droppedFileId)
            ? { ...s, folder_name: targetFolderName }
            : s
        )
      );
      if (session.project_id) {
        try {
          const authUser = JSON.parse(localStorage.getItem("dataanalysis_auth"));
          const token = authUser?.token;
          await fetch(`${import.meta.env.VITE_API_BASE_URL || ""}/api/workspace/${session.project_id}`, {
            method: "PUT",
            headers: {
              "Content-Type": "application/json",
              ...(token ? { Authorization: `Bearer ${token}` } : {}),
            },
            body: JSON.stringify({ folder_name: targetFolderName }),
          });
        } catch (err) {
          console.error("Session drag-and-drop database update failed:", err);
        }
      }
    }

    setDraggingId(null);
  };

  const createAnalysis = async () => {
    if (isCreatingAnalysis) return;
    setIsCreatingAnalysis(true);

    try {
      const authUser = JSON.parse(localStorage.getItem("dataanalysis_auth"));
      const token = authUser?.token;
      const title = "New analysis";
      const res = await fetch(apiUrl("/api/workspace"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ project_name: title }),
      });

      if (!res.ok) throw new Error(`Failed to create analysis: ${res.status}`);

      const data = await res.json();
      if (!data?.project_id) throw new Error("Failed to create analysis: no chat ID returned");

      const sessionId = String(data.project_id);
      const newSession = {
        id: sessionId,
        project_id: data.project_id,
        title: data.project_name || title,
        name: data.project_name || title,
        folder_name: data.folder_name ?? null,
        date: data.created_at ? data.created_at.slice(0, 10) : "",
        pendingSync: true,
      };

      setWorkspaceSessions((currentSessions) => [
        newSession,
        ...(Array.isArray(currentSessions)
          ? currentSessions.filter((session) => String(session.id) !== sessionId)
          : []),
      ]);
      localStorage.setItem(ACTIVE_WORKSPACE_KEY, sessionId);
      navigate("/workspace", { state: { openSession: { sessionId } } });
    } catch (err) {
      console.error("Failed to create analysis", err);
      alert(err.message || "Failed to create analysis. Please try again later.");
    } finally {
      setIsCreatingAnalysis(false);
    }
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
                <p className="collection-banner-label">Project Management</p>
                <h1 className="collection-banner-title">Project management</h1>
                <p className="collection-banner-stats">{stats.folders} folders ·  {stats.chats} chats</p>
              </div>
              <div className="d-flex gap-2 align-items-center">
                <button
                  className="btn btn-banner"
                  onClick={createAnalysis}
                  disabled={isCreatingAnalysis}
                >
                  <i className={`${isCreatingAnalysis ? "ri-loader-4-line" : "ri-add-line"} me-1`}></i>
                  {isCreatingAnalysis ? "Creating..." : "New analysis"}
                </button>
              </div>
            </div>
            <div className="row g-3 mt-4">
              {[
                { key: "folders", icon: "ri-chat-3-line", cls: "stat-folder", val: stats.chats, label: "Project history", unit: "chats" },
                { key: "exports", icon: "ri-download-cloud-2-line", cls: "stat-export", val: exportsLoading ? "…" : exportsError ? "—" : stats.exports, label: "Exported files", unit: "files" },
                { key: "deleted", icon: "ri-delete-bin-line", cls: "stat-deleted", val: stats.deleted, label: "Recently deleted", unit: "items" },
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
                    <div className="stat-hint">{item.key === "exports" && exportsLoading ? "Loading file count..." : item.key === "exports" && exportsError ? "Failed to load count. Please refresh." : `${item.val} ${item.unit}`}</div>
                  </button>
                </div>
              ))}
            </div>
          </div>
        </section>

        <div className="container py-5">
          {activeView === "folders" && (
            <>
              {/* 資料夾 */}
              <section className="mb-5">
                <h2 className="section-heading">
                  <span className="section-icon folder-icon"><i className="ri-folder-2-line"></i></span>
                  Folder
                  <button className="btn btn-add-folder ms-auto" onClick={() => setShowNewFolderModal(true)}>
                    <i className="ri-folder-add-line me-1"></i>New folder
                  </button>
                </h2>
                <div className="row g-3">
                  {folders.map((folder) => {
                    const folderFiles = filesByFolder[folder.name] || [];
                    const folderSessions = sessionsByFolder[folder.name] || [];
                    const folderItemCount = folderFiles.length + folderSessions.length;
                    const isOpen = openFolders.has(folder.id);
                    const isDragOver = dragOverTarget === folder.id;
                    return (
                      <div className="col-md-6 col-lg-4" key={folder.id}>
                        <div
                          className={`folder-card ${isDragOver ? "drag-over" : ""}`}
                          onDragEnter={(event) => handleFolderDragOver(folder.id, event)}
                          onDragOver={(event) => handleFolderDragOver(folder.id, event)}
                          onDragLeave={handleFolderDragLeave}
                          onDrop={(event) => handleDrop(folder.id, event)}
                        >
                          {isDragOver && <div className="folder-drop-hint"><i className="ri-folder-received-line me-2"></i>Move to: {folder.name}」</div>}
                          <div
                            className="folder-header"
                            onClick={() => { if (!draggingId) toggleFolder(folder.id); }}
                            onDragEnter={(event) => handleFolderDragOver(folder.id, event)}
                            onDragOver={(event) => handleFolderDragOver(folder.id, event)}
                            onDrop={(event) => handleDrop(folder.id, event)}
                          >
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
                                <span className="folder-count">{folderItemCount}  items</span>
                              </div>
                              <div className="folder-tags">
                                {["csv", "xlsx", "json", "txt", "chat"].map((type) => {
                                  const count = folderFiles.filter((file) => file.type === type).length;
                                  return count > 0 ? <span key={type} className={`folder-tag tag-${type}`}>{type === "chat" ? "Chat" : type.toUpperCase()} {count}</span> : null;
                                })}
                              </div>
                            </div>
                            <div className="folder-actions">
                              <button
                                className="action-btn"
                                onClick={(event) => {
                                  event.stopPropagation();
                                  openRenameModal({ type: "folder", id: folder.id, name: folder.name });
                                }}
                                title="Rename"
                              >
                                <i className="ri-edit-line"></i>
                              </button>
                              <button className="action-btn" onClick={(event) => { event.stopPropagation(); setDeleteTarget({ type: "folder", id: folder.id, name: folder.name }); }} title="Delete">
                                <i className="ri-delete-bin-line"></i>
                              </button>
                              <i className="ri-arrow-down-s-line folder-arrow" style={{ transform: isOpen ? "rotate(180deg)" : "rotate(0deg)" }}></i>
                            </div>
                          </div>
                          {isOpen && (
                            <div
                              className="folder-content"
                              onDragEnter={(event) => handleFolderDragOver(folder.id, event)}
                              onDragOver={(event) => handleFolderDragOver(folder.id, event)}
                              onDrop={(event) => handleDrop(folder.id, event)}
                            >
                              {folderItemCount === 0 ? (
                                <div className="empty-folder"><i className="ri-drag-move-line"></i><p>Drag files here</p></div>
                              ) : (
                                <div
                                  className="folder-files"
                                  onDragEnter={(event) => handleFolderDragOver(folder.id, event)}
                                  onDragOver={(event) => handleFolderDragOver(folder.id, event)}
                                  onDrop={(event) => handleDrop(folder.id, event)}
                                >
                                  {folderFiles.map((file) => (
                                    <FileRow
                                      key={file.id}
                                      file={file}
                                      compact
                                      renamingId={renamingFileId}
                                      renameValue={renameFileValue}
                                      onRenameStart={() => openRenameModal({ type: "file", id: file.id, name: file.name, fileType: file.type, sessionId: file.sessionId })}
                                      onRenameChange={setRenameFileValue}
                                      onRenameSave={() => saveFileRename(file.id)}
                                      onRenameCancel={() => setRenamingFileId(null)}
                                      onDragStart={() => { setDraggingId(file.id); setDragOverTarget(null); }}
                                      onDragEnd={resetDragState}
                                      menuOpen={fileMenuId === file.id}
                                      onMenuToggle={() => setFileMenuId((prev) => (prev === file.id ? null : file.id))}
                                      onMenuClose={() => setFileMenuId(null)}
                                      onDelete={() => setDeleteTarget({ type: file.type === "chat" ? "session" : "file", id: file.id, name: file.name })}
                                      onOpen={() => openFile(file)}
                                    />
                                  ))}
                                  {folderSessions.map((session) => (
                                    <FileRow
                                      key={`session-${session.id}`}
                                      file={{ ...session, name: session.title, type: "chat", size: session.date, sessionId: session.id }}
                                      compact
                                      renamingId={renamingFileId}
                                      renameValue={renameFileValue}
                                      onRenameStart={() => openRenameModal({ type: "session", id: session.id, name: session.title, projectId: session.project_id || session.id })}
                                      onRenameChange={setRenameFileValue}
                                      onRenameSave={() => saveSessionRename(session.id)}
                                      onRenameCancel={() => setRenamingFileId(null)}
                                      onDragStart={() => { setDraggingId(session.id); setDragOverTarget(null); }}
                                      onDragEnd={resetDragState}
                                      menuOpen={fileMenuId === session.id}
                                      onMenuToggle={() => setFileMenuId((prev) => (prev === session.id ? null : session.id))}
                                      onMenuClose={() => setFileMenuId(null)}
                                      onDelete={() => setDeleteTarget({ type: "session", id: session.id, name: session.title, sessionId: session.id })}
                                      onOpen={() => navigate("/workspace", { state: { openSession: { sessionId: session.id } } })}
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

              {/* 未分類檔案 */}
              <section className="mb-5">
                <h2 className="section-heading">
                  <span className="section-icon loose-icon"><i className="ri-file-list-3-line"></i></span>
                  Unfiled items
                  {(looseFiles.length + looseSessions.length) > 0 && (
                    <span className="loose-count">{looseFiles.length + looseSessions.length}  items</span>
                  )}
                </h2>
                <div
                  className={`loose-area ${dragOverTarget === "loose" ? "drag-over" : ""}`}
                  onDragOver={(event) => { event.preventDefault(); if (dragOverTarget !== "loose") setDragOverTarget("loose"); }}
                  onDragLeave={() => setDragOverTarget(null)}
                  onDrop={(event) => handleDrop(null, event)}
                >
                  {dragOverTarget === "loose" && (
                    <div className="loose-drop-hint"><i className="ri-file-transfer-line me-2"></i>Move to Unfiled</div>
                  )}
                  {looseFiles.length === 0 && looseSessions.length === 0 ? (
                    <div className="empty-loose"><i className="ri-file-list-3-line"></i><p>No unfiled files.</p></div>
                  ) : (
                    <div className="row g-3">
                      {looseFiles.map((file) => (
                        <div className="col-md-6 col-lg-4 col-xl-3" key={file.id}>
                          <FileRow
                            file={file}
                            renamingId={renamingFileId}
                            renameValue={renameFileValue}
                            onRenameStart={() => openRenameModal({ type: "file", id: file.id, name: file.name, fileType: file.type, sessionId: file.sessionId })}
                            onRenameChange={setRenameFileValue}
                            onRenameSave={() => saveFileRename(file.id)}
                            onRenameCancel={() => setRenamingFileId(null)}
                            onDragStart={() => { setDraggingId(file.id); setDragOverTarget(null); }}
                            onDragEnd={resetDragState}
                            menuOpen={fileMenuId === file.id}
                            onMenuToggle={() => setFileMenuId((prev) => (prev === file.id ? null : file.id))}
                            onMenuClose={() => setFileMenuId(null)}
                            onDelete={() => setDeleteTarget({ type: "file", id: file.id, name: file.name })}
                            onOpen={() => openFile(file)}
                          />
                        </div>
                      ))}
                      {looseSessions.map((session) => (
                        <div className="col-md-6 col-lg-4 col-xl-3" key={session.id}>
                          <FileRow
                            file={{ ...session, name: session.title, type: "chat", size: session.date, sessionId: session.id }}
                            renamingId={renamingFileId}
                            renameValue={renameFileValue}
                            onRenameStart={() => openRenameModal({ type: "session", id: session.id, name: session.title, projectId: session.project_id || session.id })}
                            onRenameChange={setRenameFileValue}
                            onRenameSave={() => saveSessionRename(session.id)}
                            onRenameCancel={() => setRenamingFileId(null)}
                            onDragStart={() => { setDraggingId(session.id); setDragOverTarget(null); }}
                            onDragEnd={resetDragState}
                            menuOpen={fileMenuId === session.id}
                            onMenuToggle={() => setFileMenuId((prev) => (prev === session.id ? null : session.id))}
                            onMenuClose={() => setFileMenuId(null)}
                            onDelete={() => setDeleteTarget({ type: "session", id: session.id, name: session.title, sessionId: session.id })}
                            onOpen={() => navigate("/workspace", { state: { openSession: { sessionId: session.id } } })}
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
              <div className="exports-toolbar">
              <h2 className="section-heading">
                <span className="section-icon export-icon"><i className="ri-download-cloud-2-line"></i></span>
                Exported files
                <span className="loose-count" role="status">{exportSearchTerm ? `${filteredExports.length} / ${stats.exports}  items` : `${stats.exports}  items`}</span>
              </h2>
              <div className="export-search" role="search" aria-label="Search exported files">
                <i className="ri-search-line" aria-hidden="true" />
                <input
                  type="search"
                  aria-label="Search exported file names"
                  placeholder="Search exported file names…"
                  value={exportSearch}
                  onChange={(event) => setExportSearch(event.target.value)}
                />
                {exportSearch && <button type="button" onClick={() => setExportSearch("")} aria-label="Clear search" title="Clear search"><i className="ri-close-line" aria-hidden="true" /></button>}
              </div>
              </div>
              {exportNotice && <p className="export-notice" role="status">{exportNotice}</p>}
              {exportsLoading ? (
                <div className="empty-loose">
                  <i className="ri-loader-4-line"></i>
                  <p>Loading...</p>
                </div>
              ) : exportsError ? (
                <div className="empty-loose">
                  <i className="ri-error-warning-line"></i>
                  <p>Loading failed: {exportsError}</p>
                </div>
              ) : exportsList.length === 0 ? (
                <div className="empty-loose">
                  <i className="ri-download-cloud-2-line"></i>
                  <p>No exported files yet.</p>
                </div>
              ) : filteredExports.length === 0 ? (
                <div className="empty-loose" role="status">
                  <i className="ri-search-line" aria-hidden="true" />
                  <p>No files match {exportSearch.trim()}. Try another keyword.</p>
                </div>
              ) : (
                <div className="exports-list">
                  {filteredExports.map((item) => (
                    <ExportFileRow key={item.export_id} item={item} onDownload={handleDownloadExport} onRename={handleRenameExport} onOpenChat={handleOpenExportChat} />
                  ))}
                </div>
              )}
            </section>
          )}

          {activeView === "deleted" && (
            <section>
              <h2 className="section-heading">
                <span className="section-icon deleted-icon"><i className="ri-delete-bin-line"></i></span>
                Recently deleted
                <span className="loose-count">{deletedItems.length}  items</span>
              </h2>
              {deletedItems.length === 0 ? (
                <div className="empty-loose">
                  <i className="ri-delete-bin-line"></i>
                  <p>There are no recently deleted items.</p>
                </div>
              ) : (
                <div className="deleted-list">
                  {deletedItems.map((item) => (
                    <div className="deleted-item" key={item.id}>
                      {(() => {
                        const isPermanentlyDeleting = permanentDeletingId === item.id;
                        const isRestoring = restoringId === item.id;
                        return (
                          <>
                      <div className="deleted-icon-box">
                        <i className={item.type === "folder" ? "ri-folder-line" : "ri-chat-3-line"}></i>
                      </div>
                      <div className="deleted-info">
                        <div className="deleted-name">{item.name}</div>
                        <div className="deleted-meta">
                          {item.type === "folder" ? "Folder" : "Chat"} · Deleted on  {item.deletedAt || "-"}
                        </div>
                      </div>
                      <div className="deleted-actions">
                        <button className="btn-deleted-restore" onClick={() => handleRestoreItem(item)} disabled={isPermanentlyDeleting || isRestoring}>
                          <i className={isRestoring ? "ri-loader-4-line ri-spin" : "ri-arrow-go-back-line"}></i>
                          {isRestoring ? "Restoring" : "Restore"}
                        </button>
                        <button className="btn-deleted-remove" onClick={() => handlePermanentDelete(item)} disabled={isPermanentlyDeleting || isRestoring}>
                          <i className={isPermanentlyDeleting ? "ri-loader-4-line ri-spin" : "ri-delete-bin-2-line"}></i>
                          {isPermanentlyDeleting ? "Deleting" : "Delete permanently"}
                        </button>
                      </div>
                          </>
                        );
                      })()}
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
              <h5 className="fw-bold m-0">New folder</h5>
            </div>
            <label className="auth-label">Folder name</label>
            <input className="form-control" value={newFolderName} onChange={(event) => setNewFolderName(event.target.value)} onKeyDown={(event) => event.key === "Enter" && createFolder()} autoFocus />
            <div className="d-flex gap-2 mt-4">
              <button className="btn btn-add-folder flex-fill" onClick={createFolder}>Create</button>
              <button className="btn btn-outline-secondary flex-fill" onClick={() => setShowNewFolderModal(false)}>Cancel</button>
            </div>
          </div>
        </div>
      )}

      {renameTarget && (
        <div className="modal-backdrop-custom" onClick={closeRenameModal}>
          <div className="modal-box" onClick={(event) => event.stopPropagation()}>
            <div className="d-flex align-items-center gap-3 mb-4">
              <div className="modal-folder-icon"><i className="ri-edit-line"></i></div>
              <h5 className="fw-bold m-0">Rename</h5>
            </div>
            <label className="auth-label">Name</label>
            <input
              className="form-control"
              value={renameFileValue}
              onChange={(event) => setRenameFileValue(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") submitRename();
                if (event.key === "Escape") closeRenameModal();
              }}
              autoFocus
            />
            <div className="d-flex gap-2 mt-4">
              <button className="btn btn-add-folder flex-fill" onClick={submitRename} disabled={isSavingRename || !renameFileValue.trim()}>
                {isSavingRename ? (
                  <>
                    <i className="ri-loader-4-line ri-spin me-2"></i>
                    Saving
                  </>
                ) : (
                  "Save"
                )}
              </button>
              <button className="btn btn-outline-secondary flex-fill" onClick={closeRenameModal} disabled={isSavingRename}>Cancel</button>
            </div>
          </div>
        </div>
      )}

      {deleteTarget && (
        <div className="modal-backdrop-custom" onClick={() => !isDeleting && setDeleteTarget(null)}>
          <div className="modal-box text-center" onClick={(event) => event.stopPropagation()}>
            <div className={`delete-icon ${isDeleting ? "is-loading" : ""}`}>
              <i className={isDeleting ? "ri-loader-4-line ri-spin" : "ri-delete-bin-line"}></i>
            </div>
            <h5 className="fw-bold mb-2">
              {isDeleting ? "Deleting..." : `Delete${deleteTarget.type === "folder" ? "Folder" : "Chat"}`}
            </h5>
            <p className="text-muted mb-4">
              {isDeleting ? "Moving to trash. Please wait." : `「${deleteTarget.name} will be moved to trash and can be restored later.`}
            </p>
            <div className="d-flex gap-2">
              <button className="btn btn-danger flex-fill" onClick={confirmDelete} disabled={isDeleting}>
                {isDeleting ? (
                  <>
                    <i className="ri-loader-4-line ri-spin me-2"></i>
                    Deleting
                  </>
                ) : (
                  "Delete"
                )}
              </button>
              <button className="btn btn-outline-secondary flex-fill" onClick={() => setDeleteTarget(null)} disabled={isDeleting}>Cancel</button>
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
      draggable={!isRenaming}
      onClick={onOpen}
      onContextMenu={(event) => {
        event.preventDefault();
        onMenuToggle();
      }}
      onDragStart={(event) => {
        if (isRenaming) {
          event.preventDefault();
          return;
        }
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.dropEffect = "move";
        event.dataTransfer.setData("text/plain", file.id);
        onDragStart();
      }}
      onDragEnd={onDragEnd}
    >
      <i className="ri-draggable drag-handle" aria-hidden="true" onClick={(event) => event.stopPropagation()}></i>
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
          <span className="file-name" onDoubleClick={(event) => { event.stopPropagation(); onRenameStart(); }}>
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
        <button className="action-btn-sm" onClick={(event) => { event.stopPropagation(); onMenuToggle(); }} title="More">
          <i className="ri-more-2-fill"></i>
        </button>
        {menuOpen && (
          <div className="file-menu" onClick={(event) => event.stopPropagation()}>
            <button className="file-menu-item" onClick={() => { onMenuClose(); onRenameStart(); }}>
              <i className="ri-edit-line"></i>Rename
            </button>
            <button className="file-menu-item danger" onClick={() => { onMenuClose(); onDelete(); }}>
              <i className="ri-delete-bin-line"></i>Delete
            </button>
          </div>
        )}
      </div>
    </div>
  );
}