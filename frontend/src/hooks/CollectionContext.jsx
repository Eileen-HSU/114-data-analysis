import { createContext, useContext, useEffect, useState } from "react";
import { useActivity } from "./ActivityContext";
import { apiUrl } from "../lib/api";

const CollectionContext = createContext(null);
const WORKSPACE_SESSIONS_KEY = "dataanalysis_workspace_sessions";
const COLLECTION_FOLDERS_KEY = "dataanalysis_collection_folders";
const DELETED_ITEMS_KEY = "dataanalysis_deleted_items";
const COLLECTION_FILES_KEY = "dataanalysis_collection_files";

function loadArray(key, fallback = []) {
  try {
    const raw = localStorage.getItem(key);
    const parsed = raw ? JSON.parse(raw) : fallback;
    return Array.isArray(parsed) ? parsed : fallback;
  } catch {
    return fallback;
  }
}

function getAuthHeader() {
  try {
    const user = JSON.parse(localStorage.getItem("dataanalysis_auth"));
    const token = user?.token;
    return token ? { Authorization: `Bearer ${token}` } : {};
  } catch {
    return {};
  }
}

export function CollectionProvider({ children }) {
  const { recordActivity } = useActivity();
  const [folders, setFolders] = useState(() => loadArray(COLLECTION_FOLDERS_KEY, []));
  const [files, setFiles] = useState(() => loadArray(COLLECTION_FILES_KEY, []));
  const [deletedItems, setDeletedItems] = useState(() => loadArray(DELETED_ITEMS_KEY, []));
  const [workspaceSessions, setWorkspaceSessions] = useState(() => loadArray(WORKSPACE_SESSIONS_KEY, []));

  const nowString = () => {
    const d = new Date();
    return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  };

  useEffect(() => { localStorage.setItem(WORKSPACE_SESSIONS_KEY, JSON.stringify(workspaceSessions)); }, [workspaceSessions]);
  useEffect(() => { localStorage.setItem(COLLECTION_FOLDERS_KEY, JSON.stringify(folders)); }, [folders]);
  useEffect(() => { localStorage.setItem(DELETED_ITEMS_KEY, JSON.stringify(deletedItems)); }, [deletedItems]);
  useEffect(() => { localStorage.setItem(COLLECTION_FILES_KEY, JSON.stringify(files)); }, [files]);


  // 新增
  const addChatToCollection = (title, sessionId) => {
    setWorkspaceSessions((prev) => {
      if (prev.find((s) => s.id === sessionId)) return prev;
      return [{ id: sessionId, title, folder_name: null, date: nowString() }, ...prev];
    });
    recordActivity({
      text: `新增工作區 Chat「${title}」`,
      icon: "ri-chat-new-line",
      iconBg: "bg-stat-mauve",
      iconColor: "text-stat-mauve",
    });
  };

  const addFileToCollection = (file) => {
    setFiles((prev) => [
      { id: `file-${Date.now()}`, name: file.name, size: file.size, type: file.type, date: nowString() },
      ...prev,
    ]);
  };


  // 軟刪除
  const deleteFolder = (id, name) => {
    const folder = folders.find((f) => f.id === id);
    if (!folder) return;
    setDeletedItems((prev) => [
      { id: `del-${Date.now()}`, name, type: "folder", deletedAt: nowString(), originalData: folder },
      ...prev,
    ]);
    setFolders((prev) => prev.filter((f) => f.id !== id));
    setWorkspaceSessions((prev) =>
      prev.map((s) => (s.folder_name === name ? { ...s, folder_name: null } : s))
    );
    recordActivity({
      text: `刪除資料夾「${name}」`,
      icon: "ri-folder-reduce-line",
      iconBg: "bg-stat-coral",
      iconColor: "text-stat-coral",
    });
  };

  const deleteChatSession = async (sessionId) => {
    const session = workspaceSessions.find((s) => s.id === sessionId);
    if (!session) return;
    if (session.project_id) {
      try {
        await fetch(apiUrl(`/api/workspace/${session.project_id}`), {
          method: "PATCH",
          headers: { "Content-Type": "application/json", ...getAuthHeader() },
          body: JSON.stringify({ is_deleted: 1 }),
        });
      } catch (err) {
        console.error("軟刪除失敗", err);
      }
    }
    setDeletedItems((prev) => [
      {
        id: `del-${Date.now()}`, name: session.title, type: "chat", deletedAt: nowString(),
        originalData: session, workspaceSession: session,
        project_id: session.project_id || null,
      },
      ...prev,
    ]);
    setWorkspaceSessions((prev) => prev.filter((s) => s.id !== sessionId));
    recordActivity({
      text: `刪除工作區 Chat「${session.title}」`,
      icon: "ri-chat-delete-line",
      iconBg: "bg-stat-coral",
      iconColor: "text-stat-coral",
    });
  };


  // 還原
  const restoreItem = async (item) => {
    if (item.project_id) {
      try {
        const folderName = item.workspaceSession?.folder_name ?? item.originalData?.folder_name ?? null;
        await fetch(apiUrl(`/api/workspace/${item.project_id}/restore`), {
          method: "POST",
          headers: { "Content-Type": "application/json", ...getAuthHeader() },
          body: JSON.stringify({ folder_name: folderName }),
        });
      } catch (err) {
        console.error("還原失敗", err);
      }
    }

    if (item.type === "folder") {
      setFolders((prev) => [...prev, item.originalData]);
    } else if (item.workspaceSession) {
      // chat
      setWorkspaceSessions((prev) => {
        if (prev.find((s) => s.id === item.workspaceSession.id)) return prev;
        return [item.workspaceSession, ...prev];
      });
    }

    setDeletedItems((prev) => prev.filter((d) => d.id !== item.id));
    recordActivity({
      text: `還原「${item.name}」`,
      icon: "ri-arrow-go-back-line",
      iconBg: "bg-stat-teal",
      iconColor: "text-stat-teal",
    });
  };


  // 永久刪除
  const permanentDelete = async (id) => {
    const target = deletedItems.find((item) => item.project_id === id);
    if (target?.project_id) {
      try {
        await fetch(apiUrl(`/api/workspace/${target.project_id}/permanent`), {
          method: "DELETE",
          headers: getAuthHeader(),
        });
      } catch (err) {
        console.error("永久刪除失敗", err);
      }
    }
    setDeletedItems((prev) => {
      if (!Array.isArray(prev)) return [];
      return prev.filter((d) => d.project_id !== id);
    });
    if (target) {
      recordActivity({
        text: `永久刪除「${target.name}」`,
        icon: "ri-delete-bin-2-line",
        iconBg: "bg-stat-coral",
        iconColor: "text-stat-coral",
      });
    }
  };


  // 同步工具
  const syncChatTitle = (sessionId, newTitle) => {
    setWorkspaceSessions((prev) => prev.map((s) => (s.id === sessionId ? { ...s, title: newTitle } : s)));
  };

  const updateSessionId = (oldId, newId) => {
    setWorkspaceSessions((prev) => prev.map((s) => (s.id === oldId ? { ...s, id: newId } : s)));
  };

  return (
    <CollectionContext.Provider
      value={{
        folders, files, deletedItems, workspaceSessions,
        setFolders, setFiles, setWorkspaceSessions,
        addChatToCollection, addFileToCollection,
        deleteFolder, deleteChatSession,
        restoreItem,
        permanentDelete,
        syncChatTitle, updateSessionId,
      }}
    >
      {children}
    </CollectionContext.Provider>
  );
}

export function useCollection() {
  const ctx = useContext(CollectionContext);
  if (!ctx) throw new Error("useCollection must be used within CollectionProvider");
  return ctx;
}