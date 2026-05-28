import { createContext, useContext, useEffect, useState } from "react";
import { useActivity } from "./ActivityContext";
import { apiUrl } from "../lib/api";

const INIT_FOLDERS = [];
const INIT_FILES = [];

const CollectionContext = createContext(null);
const WORKSPACE_SESSIONS_KEY = "dataanalysis_workspace_sessions";
const COLLECTION_FOLDERS_KEY = "dataanalysis_collection_folders";
const COLLECTION_FILES_KEY = "dataanalysis_collection_files";
const DELETED_ITEMS_KEY = "dataanalysis_deleted_items";

function loadArray(key, fallback = []) {
  try {
    const raw = localStorage.getItem(key);
    const parsed = raw ? JSON.parse(raw) : fallback;
    return Array.isArray(parsed) ? parsed : fallback;
  } catch {
    return fallback;
  }
}

function loadWorkspaceSessions() {
  return loadArray(WORKSPACE_SESSIONS_KEY);
}

function normalizeCollectionFile(file) {
  if (!file) return file;
  return {
    ...file,
    folder_name: file.folder_name ?? null,
  };
}

// 從 localStorage 取得 token
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
  const [folders, setFolders] = useState(() => loadArray(COLLECTION_FOLDERS_KEY, INIT_FOLDERS));
  const [files, setFiles] = useState(() => loadArray(COLLECTION_FILES_KEY, INIT_FILES).map(normalizeCollectionFile));
  const [deletedItems, setDeletedItems] = useState(() => loadArray(DELETED_ITEMS_KEY));
  const [workspaceSessions, setWorkspaceSessions] = useState(loadWorkspaceSessions);

  const nowString = () => {
    const d = new Date();
    return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  };

  useEffect(() => {
    localStorage.setItem(WORKSPACE_SESSIONS_KEY, JSON.stringify(workspaceSessions));
  }, [workspaceSessions]);

  useEffect(() => {
    localStorage.setItem(COLLECTION_FOLDERS_KEY, JSON.stringify(folders));
  }, [folders]);

  useEffect(() => {
    localStorage.setItem(COLLECTION_FILES_KEY, JSON.stringify(files));
  }, [files]);

  useEffect(() => {
    localStorage.setItem(DELETED_ITEMS_KEY, JSON.stringify(deletedItems));
  }, [deletedItems]);

  useEffect(() => {
    setFiles((prev) => {
      const existingSessionIds = new Set(prev.filter((f) => f.type === "chat").map((f) => String(f.sessionId)));
      const existingTitles = new Set(prev.filter((f) => f.type === "chat").map((f) => f.name));
      const missingChatFiles = workspaceSessions
        .filter((session) => !existingSessionIds.has(String(session.id)) && !existingTitles.has(session.title))
        .map((session) => ({
          id: `chat-${session.id}`,
          name: session.title,
          type: "chat",
          size: "-",
          folder_name: session.folder_name ?? null,
          createdAt: session.date || nowString(),
          sessionId: session.id,
        }));
      return missingChatFiles.length ? [...missingChatFiles, ...prev] : prev;
    });
}, [workspaceSessions]);

  // ── 軟刪除：is_deleted = 1，不從資料庫移除 ──────────────
  const deleteChatSession = async (sessionId) => {
    const session = workspaceSessions.find((s) => s.id === sessionId);
    if (!session) return;

    if (session.project_id) {
      try {
        await fetch(apiUrl(`/api/workspace/${session.project_id}`), {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json",
            ...getAuthHeader(),
          },
          body: JSON.stringify({ is_deleted: 1 }),
        });
      } catch (err) {
        console.error("軟刪除失敗", err);
      }
    }

    const chatFile = files.find((f) => f.type === "chat" && f.sessionId === sessionId);
    setDeletedItems((prev) => [
      {
        id: `del-${Date.now()}`,
        name: chatFile?.name || session.title,
        type: "file",
        deletedAt: nowString(),
        originalData: chatFile || {
          id: `chat-${sessionId}`,
          name: session.title,
          type: "chat",
          size: "-",
          folder_name: null,
          createdAt: session.date || nowString(),
          sessionId,
        },
        workspaceSession: session,
        project_id: session.project_id || null,
      },
      ...prev,
    ]);
    setFiles((prev) => prev.filter((f) => f.sessionId !== sessionId));
    setWorkspaceSessions((prev) => prev.filter((s) => s.id !== sessionId));
    recordActivity({
      text: `刪除工作區 Chat「${chatFile?.name || session.title}」`,
      icon: "ri-chat-delete-line",
      iconBg: "bg-stat-coral",
      iconColor: "text-stat-coral",
    });
  };

  // ── 還原：從垃圾桶還原，同時打後端 API ──────────────────
  const restoreItem = async (item) => {
    if (item.project_id) {
      try {
        const folderName =
          item.workspaceSession?.folder_name ?? item.originalData?.folder_name ?? null;
        await fetch(apiUrl(`/api/workspace/${item.project_id}/restore`), {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...getAuthHeader(),
          },
          body: JSON.stringify({ folder_name: folderName }),
        });
      } catch (err) {
        console.error("還原失敗", err);
      }
    }

    if (item.type === "folder") {
      const folder = item.originalData;
      setFolders((prev) => [...prev, folder]);
      if (item.relatedFiles && item.relatedFiles.length > 0) {
        setFiles((prev) => {
          const existingIds = new Set(prev.map((f) => f.id));
          const toRestore = item.relatedFiles.filter((f) => !existingIds.has(f.id));
          return [...prev, ...toRestore];
        });
      }
    } else {
      const file = item.originalData;
      setFiles((prev) => {
        if (prev.find((f) => f.id === file.id)) return prev;
        return [...prev, file];
      });
      if (file.type === "chat" && item.workspaceSession) {
        setWorkspaceSessions((prev) => {
          if (prev.find((s) => s.id === item.workspaceSession.id)) return prev;
          return [item.workspaceSession, ...prev];
        });
      }
    }

    // 改用 item.id（統一識別碼），避免 project_id 為 undefined 時過濾失效
    setDeletedItems((prev) => prev.filter((d) => d.id !== item.id));
    recordActivity({
      text: `還原「${item.name}」`,
      icon: "ri-arrow-go-back-line",
      iconBg: "bg-stat-teal",
      iconColor: "text-stat-teal",
    });
  };

  // ── 永久刪除：從資料庫完全移除 ──────────────────────────
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

    setDeletedItems((prev) => prev.filter((d) => d.project_id !== id));

    if (target) {
      recordActivity({
        text: `永久刪除「${target.name}」`,
        icon: "ri-delete-bin-2-line",
        iconBg: "bg-stat-coral",
        iconColor: "text-stat-coral",
      });
    }
  };

  const getFileType = (filename) => {
    const ext = filename.split(".").pop()?.toLowerCase() ?? "";
    if (ext === "csv") return "csv";
    if (ext === "xlsx" || ext === "xls") return "xlsx";
    if (ext === "json") return "json";
    if (ext === "txt") return "txt";
    return "txt";
  };

  const formatFileSize = (bytes) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const addFileToCollection = (file) => {
    const type = getFileType(file.name);
    const newFile = {
      id: `file-${Date.now()}`,
      name: file.name,
      type,
      size: formatFileSize(file.size),
      folder_name: null,
      createdAt: nowString(),
    };
    setFiles((prev) => [newFile, ...prev]);
    recordActivity({
      text: `新增檔案「${newFile.name}」到作品集`,
      icon: "ri-file-add-line",
      iconBg: "bg-stat-sky",
      iconColor: "text-stat-sky",
    });
  };

  const addChatToCollection = (title, sessionId) => {
    const createdAt = nowString();
    const newFile = {
      id: `chat-${Date.now()}`,
      name: title,
      type: "chat",
      size: "—",
      folder_name: null,
      createdAt,
      sessionId,
    };
    setFiles((prev) => [newFile, ...prev]);
    recordActivity({
      text: `新增工作區 Chat「${title}」`,
      icon: "ri-chat-new-line",
      iconBg: "bg-stat-mauve",
      iconColor: "text-stat-mauve",
    });
  };

  const syncChatTitle = (sessionId, newTitle) => {
    setFiles((prev) =>
      prev.map((f) => (f.sessionId === sessionId ? { ...f, name: newTitle } : f))
    );
  };

  const updateSessionId = (oldId, newId) => {
  setFiles((prev) =>
    prev.map((f) =>
      f.sessionId === oldId ? { ...f, sessionId: newId, id: `chat-${newId}` } : f
    )
  );
};

  return (
    <CollectionContext.Provider value={{
      folders, files, deletedItems, workspaceSessions,
      setFolders, setFiles, setWorkspaceSessions,
      deleteFolder, deleteFile,
      restoreItem, permanentDelete,
      addChatToCollection, addFileToCollection, syncChatTitle, deleteChatSession,
      updateSessionId,
    }}>
      {children}
    </CollectionContext.Provider>
  );
}

export function useCollection() {
  const ctx = useContext(CollectionContext);
  if (!ctx) throw new Error("useCollection must be used within CollectionProvider");
  return ctx;
}
