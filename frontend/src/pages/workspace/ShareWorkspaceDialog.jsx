import { useEffect, useRef, useState } from "react";
import "./sharing.css";

export default function ShareWorkspaceDialog({ invite, onClose }) {
  const dialogRef = useRef(null);
  const [copyStatus, setCopyStatus] = useState("");
  useEffect(() => {
    const dialog = dialogRef.current;
    dialog.showModal();
    return () => dialog.close();
  }, []);
  async function copyLink() {
    try {
      await navigator.clipboard.writeText(invite.link);
      setCopyStatus("已複製連結");
    } catch {
      setCopyStatus("無法自動複製，請選取上方連結手動複製。");
    }
  }
  return (
    <dialog ref={dialogRef} className="workspace-share-dialog" onClose={onClose}
      onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}
      aria-labelledby="share-title">
      <div className="workspace-share-card">
        <div className="share-success-icon"><i className="ri-checkbox-circle-line" /></div>
        <h2 id="share-title">邀請檢視</h2>
        <p>分享「{invite.title}」的對話紀錄</p>
        <p>任何取得連結的人都可免登入瀏覽，只能檢視，無法傳送指令或修改內容。</p>
        <label htmlFor="workspace-share-link">檢視連結</label>
        <input id="workspace-share-link" value={invite.link} readOnly onFocus={(event) => event.target.select()} />
        <button type="button" className="share-primary" onClick={copyLink}>複製檢視連結</button>
        <p role="status">{copyStatus}</p>
        <div className="share-dialog-actions">
          <a href={invite.link} target="_blank" rel="noopener noreferrer">開啟檢視</a>
          <button type="button" onClick={onClose}>完成</button>
        </div>
      </div>
    </dialog>
  );
}