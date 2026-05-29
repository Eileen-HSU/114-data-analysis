import { useState } from "react";
import { useNavigate } from "react-router-dom";
import Navbar from "../../components/feature/Navbar";
import { useCollection } from "../../hooks/CollectionContext";

export default function TrashPage() {
  const navigate = useNavigate();
  const { deletedItems, restoreItem, permanentDelete } = useCollection();
  const [permDeleteTarget, setPermDeleteTarget] = useState(null);
  const [restoredIds, setRestoredIds] = useState(new Set());

  const handleRestore = (item) => {
    restoreItem(item);
    setRestoredIds((prev) => new Set(prev).add(item.project_id));
  };

  const handlePermanentDelete = (item) => {
    if (!item) return;
    const isFolder = item.type === "folder";
    console.log("isFolder:", isFolder, "item.type:", item.type); 
    permanentDelete(item, isFolder);
    setPermDeleteTarget(null);
  };

  return (
    <>
      <Navbar />
      <main style={{ minHeight: "100vh", background: "#faf8f8", paddingTop: 80 }}>
        <section style={{ background: "white", borderBottom: "1px solid #f0ebe9", padding: "28px 0" }}>
          <div className="container">
            <div className="d-flex align-items-center gap-3">
              <button
                onClick={() => navigate("/collection")}
                style={{ background: "none", border: "none", cursor: "pointer", color: "#b08080", fontSize: 20, padding: "6px 8px", borderRadius: 8 }}
                title="返回收藏"
              >
                <i className="ri-arrow-left-line"></i>
              </button>
              <div style={{ width: 44, height: 44, background: "#f5e8e6", borderRadius: 12, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 22, color: "#c9a0a0" }}>
                <i className="ri-delete-bin-line"></i>
              </div>
              <div>
                <h1 style={{ fontSize: 22, fontWeight: 800, color: "#3d2c2c", margin: 0 }}>垃圾桶</h1>
                <p style={{ fontSize: 13, color: "#b08080", margin: 0 }}>
                  {deletedItems.length > 0 ? `${deletedItems.length} 個項目可還原或永久刪除` : "目前沒有已刪除的項目"}
                </p>
              </div>
              {deletedItems.length > 0 && (
                <span style={{ marginLeft: 8, background: "#c9a0a0", color: "white", fontSize: 12, fontWeight: 800, padding: "2px 10px", borderRadius: 50 }}>
                  {deletedItems.length}
                </span>
              )}
            </div>
          </div>
        </section>

        <div className="container py-5">
          {deletedItems.length === 0 ? (
            <div style={{ textAlign: "center", padding: "80px 0", color: "#c9a0a0" }}>
              <div style={{ width: 80, height: 80, background: "#f5e8e6", borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 36, margin: "0 auto 20px" }}>
                <i className="ri-delete-bin-line"></i>
              </div>
              <h3 style={{ fontSize: 18, fontWeight: 700, color: "#b08080", marginBottom: 8 }}>垃圾桶是空的</h3>
              <p style={{ fontSize: 14, color: "#c9a0a0", marginBottom: 24 }}>刪除的資料夾或檔案會暫時放在這裡。</p>
              <button onClick={() => navigate("/collection")} style={{ background: "#c9a0a0", color: "white", border: "none", borderRadius: 10, padding: "10px 24px", fontSize: 14, fontWeight: 700, cursor: "pointer" }}>
                <i className="ri-arrow-left-line me-2"></i>返回收藏
              </button>
            </div>
          ) : (
            <>
              <div style={{ background: "#fdf5f3", border: "1px solid #f0e0dc", borderRadius: 12, padding: "12px 18px", marginBottom: 24, display: "flex", alignItems: "center", gap: 10, fontSize: 13, color: "#b08080" }}>
                <i className="ri-information-line" style={{ fontSize: 16 }}></i>
                <span>還原項目會回到收藏；永久刪除後將無法復原。</span>
              </div>

              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                {deletedItems.map((item) => {
                  const isRestored = restoredIds.has(item.project_id);
                  return (
                    <div key={item.project_id} style={{ display: "flex", alignItems: "center", gap: 16, padding: "16px 20px", background: "white", borderRadius: 14, border: "1px solid #f0ebe9", opacity: isRestored ? 0.5 : 1 }}>
                      <div style={{ width: 48, height: 48, flexShrink: 0, background: item.type === "folder" ? "#f5e8e6" : "#edf2f7", borderRadius: 12, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 22, color: item.type === "folder" ? "#c9a0a0" : "#8fa3b8" }}>
                        <i className={item.type === "folder" ? "ri-folder-line" : "ri-file-line"}></i>
                      </div>

                      <div style={{ flex: 1, minWidth: 0 }}>
                        <p style={{ fontSize: 15, fontWeight: 700, color: "#3d2c2c", margin: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {item.name}
                        </p>
                        <p style={{ fontSize: 12, color: "#b08080", margin: "3px 0 0" }}>
                          <span style={{ display: "inline-block", padding: "1px 8px", background: item.type === "folder" ? "#f5e8e6" : "#edf2f7", borderRadius: 6, fontSize: 11, fontWeight: 700, color: item.type === "folder" ? "#c9a0a0" : "#8fa3b8", marginRight: 8 }}>
                            {item.type === "folder" ? "資料夾" : "檔案"}
                          </span>
                          刪除時間：{item.deletedAt}
                          {item.type === "folder" && item.relatedFiles?.length > 0 && <span style={{ marginLeft: 6 }}>包含 {item.relatedFiles.length} 個檔案</span>}
                        </p>
                      </div>

                      {isRestored ? (
                        <span style={{ fontSize: 13, color: "#6aa86a", fontWeight: 700 }}>
                          <i className="ri-check-line me-1"></i>已還原
                        </span>
                      ) : (
                        <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
                          <button onClick={() => handleRestore(item)} style={{ padding: "8px 16px", background: "#f5f0f0", color: "#c9a0a0", border: "1.5px solid #e8d8d8", borderRadius: 9, fontSize: 13, fontWeight: 700, cursor: "pointer", whiteSpace: "nowrap" }}>
                            <i className="ri-arrow-go-back-line me-1"></i>還原
                          </button>
                          <button onClick={() => setPermDeleteTarget(item)} style={{ padding: "8px 16px", background: "none", color: "#c9a0a0", border: "1.5px solid #e2e8f0", borderRadius: 9, fontSize: 13, fontWeight: 600, cursor: "pointer", whiteSpace: "nowrap" }}>
                            <i className="ri-delete-bin-line me-1"></i>永久刪除
                          </button>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </div>
      </main>

      {permDeleteTarget && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.35)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 9999 }} onClick={() => setPermDeleteTarget(null)}>
          <div style={{ background: "white", borderRadius: 18, padding: "36px 32px", maxWidth: 400, width: "90%", textAlign: "center" }} onClick={(event) => event.stopPropagation()}>
            <div style={{ width: 56, height: 56, background: "#fde8e8", borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 26, color: "#e57373", margin: "0 auto 16px" }}>
              <i className="ri-delete-bin-2-line"></i>
            </div>
            <h5 style={{ fontWeight: 800, marginBottom: 8, color: "#3d2c2c" }}>永久刪除</h5>
            <p style={{ color: "#888", marginBottom: 24, fontSize: 14 }}>確定要永久刪除「{permDeleteTarget.name}」嗎？此操作無法復原。</p>
            <div style={{ display: "flex", gap: 10 }}>
              <button style={{ flex: 1, padding: "10px 0", background: "#e57373", color: "white", border: "none", borderRadius: 10, fontWeight: 700, fontSize: 14, cursor: "pointer" }} onClick={() => handlePermanentDelete(permDeleteTarget)}>
                永久刪除
              </button>
              <button style={{ flex: 1, padding: "10px 0", background: "none", color: "#888", border: "1.5px solid #e2e8f0", borderRadius: 10, fontWeight: 600, fontSize: 14, cursor: "pointer" }} onClick={() => setPermDeleteTarget(null)}>
                取消
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
