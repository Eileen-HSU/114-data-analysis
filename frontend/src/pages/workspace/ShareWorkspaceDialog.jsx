import { useEffect, useRef, useState } from "react";
import "./sharing.css";

export default function ShareWorkspaceDialog({ invite, onClose }) {
  const dialogRef = useRef(null);
  const [copyStatus, setCopyStatus] = useState("");
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    const dialog = dialogRef.current;
    dialog.showModal();
    return () => dialog.close();
  }, []);
  async function copyLink() {
    try {
      await navigator.clipboard.writeText(invite.link);
      setCopied(true);
      setCopyStatus("Link copied. You can now share it with others.");
    } catch {
      setCopied(false);
      setCopyStatus("Unable to copy automatically. Select the link above and copy it manually.");
    }
  }
  return (
    <dialog ref={dialogRef} className="workspace-share-dialog" onClose={(event) => { if (!event.currentTarget.open) onClose(); }}
      onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}
      aria-labelledby="share-title" aria-describedby="share-description">
      <div className="workspace-share-card">
        <header className="share-heading">
          <span className="share-heading-icon"><i className="ri-link" /></span>
          <div><h2 id="share-title">Invite viewers</h2><p id="share-description">Let others view this analysis conversation</p></div>
          <button className="share-close" type="button" onClick={onClose} aria-label="Close invite dialog" autoFocus><i className="ri-close-line" /></button>
        </header>
        <div className="share-conversation">
          <i className="ri-chat-3-line" />
          <div><span>Shared conversation</span><strong>{invite.title}</strong></div>
          <span className="share-permission"><i className="ri-eye-line" /> View only</span>
        </div>
        <label htmlFor="workspace-share-link">View link</label>
        <div className="share-link-field">
          <i className="ri-link" />
          <input id="workspace-share-link" value={invite.link} readOnly onFocus={(event) => event.target.select()} />
        </div>
        <button type="button" className={`share-primary${copied ? " is-copied" : ""}`} onClick={copyLink}>
          <i className={copied ? "ri-check-line" : "ri-file-copy-line"} />{copied ? "Link copied" : "Copy view link"}
        </button>
        <p className="share-copy-status" role="status">{copyStatus}</p>
        <div className="share-access-note"><i className="ri-shield-check-line" /><p>Anyone with the link can view without signing in.<br />Guests cannot send commands or modify this conversation.</p></div>
        <footer className="share-dialog-actions">
          <button type="button" onClick={onClose}>Done</button>
        </footer>
      </div>
    </dialog>
  );
}
