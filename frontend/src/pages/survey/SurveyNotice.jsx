import { useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";

export default function SurveyNotice({ message, language, onClose, onLogin }) {
  const dialog = useRef(null);
  const titleId = useId();
  const descriptionId = useId();
  const en = language === "en";
  const needsLogin = /登入|log\s*in|unauthorized/i.test(message);

  useEffect(() => {
    const element = dialog.current;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    element.showModal();
    return () => {
      element.close();
      document.body.style.overflow = previousOverflow;
    };
  }, []);

  return createPortal(
    <dialog ref={dialog} className="survey-notice" aria-labelledby={titleId}
      aria-describedby={descriptionId} onCancel={onClose} data-localized>
      <button type="button" className="survey-notice-close" onClick={onClose}
        aria-label={en ? "Close" : "關閉"}>×</button>
      <div className="survey-notice-icon" aria-hidden="true">
        <i className={needsLogin ? "ri-lock-line" : "ri-information-line"} />
      </div>
      <h2 id={titleId}>{needsLogin ? (en ? "Log in to continue" : "登入後即可使用") : (en ? "Unable to create your survey" : "暫時無法建立問卷")}</h2>
      <p id={descriptionId}>{needsLogin ? (en ? "Please log in to create your survey with AI." : "請先登入，即可使用 AI 智能問卷功能。") : message}</p>
      <div className="survey-notice-actions">
        <button type="button" className="survey-notice-primary" autoFocus onClick={needsLogin ? onLogin : onClose}>
          {needsLogin ? (en ? "Go to login" : "前往登入") : (en ? "Got it" : "我知道了")}
        </button>
        {needsLogin && <button type="button" className="survey-notice-secondary" onClick={onClose}>{en ? "Maybe later" : "稍後再說"}</button>}
      </div>
    </dialog>, document.body,
  );
}
