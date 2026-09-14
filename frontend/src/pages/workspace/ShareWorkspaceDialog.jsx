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
      setCopyStatus("連結已複製，可以分享給其他人了。");
    } catch {
      setCopied(false);
      setCopyStatus("無法自動複製，請選取上方連結手動複製。");
    }
  }
  return (
    <dialog ref={dialogRef} className="workspace-share-dialog" onClose={onClose}
      onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}
      aria-labelledby="share-title" aria-describedby="share-description">
      <div className="workspace-share-card">
        <header className="share-heading">
          <span className="share-heading-icon"><i className="ri-link" /></span>
          <div><h2 id="share-title">邀請檢視</h2><p id="share-description">讓其他人一起查看這段分析對話</p></div>
          <button className="share-close" type="button" onClick={onClose} aria-label="關閉邀請視窗" autoFocus><i className="ri-close-line" /></button>
        </header>
        <div className="share-conversation">
          <i className="ri-chat-3-line" />
          <div><span>分享的對話</span><strong>{invite.title}</strong></div>
          <span className="share-permission"><i className="ri-eye-line" /> 僅供瀏覽</span>
        </div>
        <label htmlFor="workspace-share-link">檢視連結</label>
        <div className="share-link-field">
          <i className="ri-link" />
          <input id="workspace-share-link" value={invite.link} readOnly onFocus={(event) => event.target.select()} />
        </div>
        <button type="button" className={`share-primary${copied ? " is-copied" : ""}`} onClick={copyLink}>
          <i className={copied ? "ri-check-line" : "ri-file-copy-line"} />{copied ? "已複製連結" : "複製檢視連結"}
        </button>
        <p className="share-copy-status" role="status">{copyStatus}</p>
        <div className="share-access-note"><i className="ri-shield-check-line" /><p>取得連結即可免登入查看。<br />訪客無法傳送指令或修改這段對話。</p></div>
        <footer className="share-dialog-actions">
          <button type="button" onClick={onClose}>完成</button>
        </footer>
      </div>
    </dialog>
  );
}
