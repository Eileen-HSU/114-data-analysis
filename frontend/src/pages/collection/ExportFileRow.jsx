import { useState } from "react";

export default function ExportFileRow({ item, onDownload, onRename, onOpenChat }) {
  const [opening, setOpening] = useState(false);
  const [sourceError, setSourceError] = useState("");
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const extension = /\.[^.]+$/.exec(item.export_name || "")?.[0] || (item.export_type ? `.${item.export_type}` : "");

  async function openSourceChat() {
    if (opening) return;
    setOpening(true);
    setSourceError("");
    try { await onOpenChat(item); }
    catch (err) { setSourceError(err.message || "Unable to open the source conversation."); }
    finally { setOpening(false); }
  }

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
    if (!trimmed) { setError("Please enter a file name."); return; }
    if (/[\\/:*?"<>|\u0000-\u001f]/.test(trimmed)) { setError("File names cannot contain slashes or special characters."); return; }
    if (trimmed.length + extension.length > 255) { setError("The file name is too long. Shorten it and try again."); return; }
    setSaving(true);
    setError("");
    try {
      await onRename(item, trimmed + extension);
      setEditing(false);
    } catch (err) {
      setError(err.message || "Rename failed. Please try again later.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className={`export-list-item${editing ? " is-renaming" : ""}`}>
      <div className="export-source-column">
        <button type="button" className="export-source-link" onClick={openSourceChat}
          disabled={opening || !item.project_id} title={`Open the latest message in ${item.source_path || "Source conversation"} `}>
          {opening ? <i className="ri-loader-4-line ri-spin" /> : <span className="export-chat-emoji" aria-hidden="true">💬</span>}
          <span>{item.source_path || "Source conversation"}</span>
        </button>
        {sourceError && <p className="export-source-error" role="alert">{sourceError}</p>}
      </div>
      {editing ? (
        <form className="export-rename-form" onSubmit={save}>
          <label htmlFor={`export-name-${item.export_id}`}>Edit file name</label>
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
              <button className="export-save-btn" type="submit" disabled={saving}>{saving ? "Saving…" : "Save"}</button>
              <button className="export-cancel-btn" type="button" disabled={saving} onClick={() => setEditing(false)}>Cancel</button>
            </div>
          </div>
          {error && <p className="export-rename-error" role="alert" id={`export-error-${item.export_id}`}>{error}</p>}
        </form>
      ) : (
        <>
          <button type="button" className="export-download-target" onClick={() => onDownload(item)} title="Click to download">
            <i className="ri-file-text-line export-list-item-icon" />
            <div className="export-list-item-info">
              <span className="export-column-label">Exported files</span>
              <div className="export-list-item-name">{item.export_name}</div>
              <div className="export-list-item-meta">
                {item.row_count != null ? `${item.row_count} responses` : ""}
                {item.created_at ? `　${new Date(item.created_at).toLocaleString("en-US")}` : ""}
              </div>
            </div>
            <i className="ri-download-2-line export-list-item-download" />
          </button>
          <button type="button" className="export-rename-btn" onClick={startRename} aria-label={`Rename ${item.export_name}`}>
            <i className="ri-edit-line" /> <span>Rename</span>
          </button>
        </>
      )}
    </div>
  );
}
