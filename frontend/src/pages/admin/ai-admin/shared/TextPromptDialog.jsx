import { useEffect, useRef, useState } from "react";
import { t } from "./taxStatus";

/**
 * 取代 window.prompt：可以換行、有說明、按錯不會消失（取消要明確按）。
 *
 *   const [promptDialog, askText] = useTextPrompt();
 *   const value = await askText({ title, message, initial, placeholder, required, confirmLabel });
 *   // value === null 代表取消
 *   return <>{promptDialog} ...</>;
 */
export function useTextPrompt() {
  const [request, setRequest] = useState(null);
  const ask = (options) => new Promise((resolve) => setRequest({ ...options, resolve }));
  const close = (value) => {
    request?.resolve(value);
    setRequest(null);
  };
  const dialog = request ? <TextPromptDialog key={request.title} request={request} onClose={close} /> : null;
  return [dialog, ask];
}

function TextPromptDialog({ request, onClose }) {
  const [value, setValue] = useState(request.initial || "");
  const ref = useRef(null);
  useEffect(() => { ref.current?.focus(); }, []);
  const empty = request.required && !value.trim();
  const submit = () => { if (!empty) onClose(value.trim()); };

  return (
    <div className="text-prompt-backdrop">
      <div className="text-prompt" role="dialog" aria-modal="true" aria-labelledby="text-prompt-title"
        onKeyDown={(e) => {
          if (e.key === "Escape") onClose(null);
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit();
        }}>
        <h3 id="text-prompt-title">{request.title}</h3>
        {request.message && <p>{request.message}</p>}
        <textarea ref={ref} rows={request.rows || 5} value={value} placeholder={request.placeholder || ""}
          onChange={(e) => setValue(e.target.value)} />
        <div className="text-prompt-actions">
          <small>{t("Ctrl／⌘ + Enter 送出，Esc 取消", "Ctrl/⌘ + Enter to submit, Esc to cancel")}</small>
          <button onClick={() => onClose(null)}>{t("取消", "Cancel")}</button>
          <button className="primary" disabled={empty} onClick={submit}>{request.confirmLabel || t("確定", "OK")}</button>
        </div>
      </div>
    </div>
  );
}
