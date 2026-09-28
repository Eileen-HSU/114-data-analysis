import { t } from "./taxStatus";

// 切換分頁 / 篩選 / 頁數時立刻顯示「搜尋中」，不讓使用者以為畫面卡住或
// 看到上一個分頁的舊資料。
export function LoadingNotice({ text }) {
  return (
    <p className="ai-admin-loading" role="status" aria-live="polite">
      <i className="ri-loader-4-line ri-spin" aria-hidden="true" /> {text || t("正在搜尋中…", "Searching…")}
    </p>
  );
}

// 後端 services/failure_explainer.py 產生的 failure（code / message /
// message_en / raw）：先顯示看得懂的說明，原始錯誤收在「技術細節」裡。
export function FailureNotice({ failure, fallback }) {
  if (!failure && !fallback) return null;
  const message = failure ? t(failure.message, failure.message_en || failure.message) : fallback;
  return (
    <div className="ai-admin-error ai-admin-failure">
      <div>{message}</div>
      {failure?.raw && (
        <details>
          <summary>{t("技術細節", "Technical details")}</summary>
          <code>{failure.raw}</code>
        </details>
      )}
    </div>
  );
}
