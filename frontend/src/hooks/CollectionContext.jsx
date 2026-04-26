import { createContext, useContext, useState } from "react";

const INIT_FOLDERS = [
  { id: "f1", name: "2025 客戶分析" },
  { id: "f2", name: "產品研究" },
];

const INIT_FILES = [
  { id: "file-1", name: "customer_feedback.csv", type: "csv", size: "84.2 KB", folderId: "f1", createdAt: "2026/4/20 10:15" },
  { id: "file-2", name: "sales_dashboard.xlsx", type: "xlsx", size: "132.8 KB", folderId: "f1", createdAt: "2026/4/21 14:32" },
  { id: "file-3", name: "survey_schema.json", type: "json", size: "12.4 KB", folderId: "f2", createdAt: "2026/4/22 09:48" },
  { id: "file-4", name: "AI 分析對話紀錄", type: "chat", size: "—", folderId: null, createdAt: "2026/4/23 16:05", sessionId: "sample-chat" },
];

const CollectionContext = createContext(null);

export function CollectionProvider({ children }) {
  const [folders, setFolders] = useState(INIT_FOLDERS);
  const [files, setFiles] = useState(INIT_FILES);
  const [deletedItems, setDeletedItems] = useState([]);
  const [workspaceSessions, setWorkspaceSessions] = useState([]);

  const nowString = () => {
    const d = new Date();
    return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  };

  const deleteFolder = (id, name) => {
    const folder = folders.find((f) => f.id === id);
    if (!folder) return;
    const relatedFiles = files.filter((f) => f.folderId === id);
    setDeletedItems((prev) => [
      {
        id: `del-${Date.now()}`,
        name,
        type: "folder",
        deletedAt: nowString(),
        originalData: folder,
        relatedFiles,
      },
      ...prev,
    ]);
    setFolders((prev) => prev.filter((f) => f.id !== id));
    setFiles((prev) => prev.map((f) => (f.folderId === id ? { ...f, folderId: null } : f)));
  };

  const deleteFile = (id, name) => {
    const file = files.find((f) => f.id === id);
    if (!file) return;
    setDeletedItems((prev) => [
      {
        id: `del-${Date.now()}`,
        name,
        type: "file",
        deletedAt: nowString(),
        originalData: file,
      },
      ...prev,
    ]);
    setFiles((prev) => prev.filter((f) => f.id !== id));
  };

  const restoreItem = (item) => {
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
    }
    setDeletedItems((prev) => prev.filter((d) => d.id !== item.id));
  };

  const permanentDelete = (id) => {
    setDeletedItems((prev) => prev.filter((d) => d.id !== id));
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
      folderId: null,
      createdAt: nowString(),
    };
    setFiles((prev) => [newFile, ...prev]);
  };

  const addChatToCollection = (title, sessionId) => {
    const createdAt = nowString();
    const newFile = {
      id: `chat-${Date.now()}`,
      name: title,
      type: "chat",
      size: "—",
      folderId: null,
      createdAt,
      sessionId,
    };
    setFiles((prev) => [newFile, ...prev]);
  };

  const syncChatTitle = (sessionId, newTitle) => {
    setFiles((prev) =>
      prev.map((f) =>
        f.sessionId === sessionId ? { ...f, name: newTitle } : f
      )
    );
  };

  return (
    <CollectionContext.Provider value={{
      folders, files, deletedItems, workspaceSessions,
      setFolders, setFiles, setWorkspaceSessions,
      deleteFolder, deleteFile,
      restoreItem, permanentDelete,
      addChatToCollection, addFileToCollection, syncChatTitle,
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
