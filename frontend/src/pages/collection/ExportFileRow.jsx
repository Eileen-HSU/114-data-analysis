import { useState } from "react";

export default function ExportFileRow({ item, onDownload, onRename }) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const extension = /\.[^.]+$/.exec(item.export_name || "")?.[0] || (item.export_type ? `.${item.export_type}` : "");

  function startRename() {
    setName(extension && item.export_name?.endsWith(extension)
      ? item.export_name.slice(0, -extension.length) : item.export_name || "");
    setError("");
    setEditing(true);
  }

  async function save(event) {
    event.preventDefault();
    if (saving) return;
    const trimmed = name.trim();
    if (!trimmed) { setError("請輸入檔案名稱。"); return; }
    if (/[\\/:*?"<>|\u0000-\u001f]/.test(trimmed)) { setError("檔案名稱不能包含斜線或特殊符號。"); return; }
    if (trimmed.length + extension.length > 255) { setError("檔案名稱過長，請縮短後再試。"); return; }
    setSaving(true);
    setError("");
    try {
      await onRename(item, trimmed + extension);
      setEditing(false);
    } catch (err) {
      setError(err.message || "重新命名失敗，請稍後再試。");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className={`export-list-item${editing ? " is-renaming" : ""}`}>
      {editing ? (
        <form className="export-rename-form" onSubmit={save}>
          <label htmlFor={`export-name-${item.export_id}`}>修改檔案名稱</label>
          <div className="export-rename-controls">
            <div className="export-name-field">
              <input id={`export-name-${item.export_id}`} value={name}
                onChange={(event) => setName(event.target.value)} autoFocus disabled={saving}
                maxLength={255 - extension.length} aria-invalid={!!error}
                aria-describedby={error ? `export-error-${item.export_id}` : undefined}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && event.nativeEvent.isComposing) event.preventDefault();
                  if (event.key === "Escape" && !saving) setEditing(false);
                }} />
              <span>{extension}</span>
            </div>
            <div className="export-rename-actions">
              <button className="export-save-btn" type="submit" disabled={saving}>{saving ? "儲存中..." : "儲存"}</button>
              <button className="export-cancel-btn" type="button" disabled={saving} onClick={() => setEditing(false)}>取消</button>
            </div>
          </div>
          {error && <p className="export-rename-error" role="alert" id={`export-error-${item.export_id}`}>{error}</p>}
        </form>
      ) : (
        <>
          <button type="button" className="export-download-target" onClick={() => onDownload(item)} title="點擊下載">
            <i className="ri-file-text-line export-list-item-icon" />
            <div className="export-list-item-info">
              <div className="export-list-item-name">{item.export_name}</div>
              {item.source_path && <div className="export-list-item-source"><i className="ri-folder-3-line" /> {item.source_path}</div>}
              <div className="export-list-item-meta">
                {item.row_count != null ? `${item.row_count} 筆` : ""}
                {item.created_at ? `　${new Date(item.created_at).toLocaleString("zh-TW")}` : ""}
              </div>
            </div>
            <i className="ri-download-2-line export-list-item-download" />
          </button>
          <button type="button" className="export-rename-btn" onClick={startRename} aria-label={`重新命名 ${item.export_name}`}>
            <i className="ri-edit-line" /> <span>重新命名</span>
          </button>
        </>
      )}
    </div>
  );
}
