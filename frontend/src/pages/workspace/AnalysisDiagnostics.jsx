import InterfaceText from "../../components/feature/InterfaceText";

// ─────────────────────────────────────────────────────────────
// 上傳 / 分析結果的診斷顯示。
// code 由後端 services/analysis_diagnostics.py 決定（machine-readable、
// 穩定），這裡只依 code 顯示在地化文字，不解析後端訊息字串。
// scripts/check-admin-status-mapping.mjs 會比對 DIAGNOSTIC_CODES /
// ANALYSIS_STATUSES 與後端，兩邊不一致時檢查會失敗。
// 每個 code 都寫成獨立的 <InterfaceText> 字面字串，check-interface-i18n
// 才能確認中英文都有。
// ─────────────────────────────────────────────────────────────

export const ANALYSIS_STATUSES = ["completed", "partial", "failed", "no_data"];
export const DIAGNOSTIC_CODES = [
  "NO_PUBLISHED_TAXONOMY",
  "ROUTING_UNDETERMINED",
  "ROUTING_API_FAILED",
  "SEGMENTATION_FAILED",
  "CLASSIFICATION_FAILED",
  "NO_MEANINGFUL_RESULTS",
  "PARTIAL_CLASSIFICATION",
  "OPEN_CLASSIFICATION_FAILED",
];

export function DiagnosticText({ code }) {
  switch (code) {
    case "NO_PUBLISHED_TAXONOMY":
      return <InterfaceText>{"這個主題目前沒有已發布的分類架構，原始回答已保存，但沒有進行分類。"}</InterfaceText>;
    case "ROUTING_UNDETERMINED":
      return <InterfaceText>{"AI 判斷不出這個欄位屬於哪個主題，原始回答已保存，可以請管理員指派主題。"}</InterfaceText>;
    case "ROUTING_API_FAILED":
      return <InterfaceText>{"判斷主題時 AI 服務呼叫失敗，這個欄位沒有分類，也沒有建立自動主題。原始回答已保存，可以稍後重新處理。"}</InterfaceText>;
    case "SEGMENTATION_FAILED":
      return <InterfaceText>{"AI 拆分回答內容失敗，這些回答沒有分類結果，可以稍後重新處理。"}</InterfaceText>;
    case "CLASSIFICATION_FAILED":
      return <InterfaceText>{"AI 分類呼叫失敗，這些回答沒有分類結果，可以稍後重新處理。"}</InterfaceText>;
    case "NO_MEANINGFUL_RESULTS":
      return <InterfaceText>{"資料已處理，但沒有可以顯示的分類結果（例如沒有文字，或內容都沒有具體建議）。"}</InterfaceText>;
    case "PARTIAL_CLASSIFICATION":
      return <InterfaceText>{"部分回答分類成功，部分失敗；失敗的回答已保存，可以稍後重新處理。"}</InterfaceText>;
    case "OPEN_CLASSIFICATION_FAILED":
      return <InterfaceText>{"開放式分類需要 AI 先歸納分類架構，但這一步失敗了，所以沒有分類。原始回答已保存，可以稍後重新處理。"}</InterfaceText>;
    default:
      return null;
  }
}

// services/failure_explainer.py 的補充原因（AI 額度、忙碌、逾時…）
export function FailureReasonText({ code }) {
  switch (code) {
    case "AI_QUOTA_EXCEEDED":
      return <InterfaceText>{"原因：AI 服務額度不足或請求太頻繁。"}</InterfaceText>;
    case "AI_SERVICE_BUSY":
      return <InterfaceText>{"原因：AI 模型目前使用量過高。"}</InterfaceText>;
    case "AI_TIMEOUT":
      return <InterfaceText>{"原因：AI 服務回應逾時。"}</InterfaceText>;
    case "AI_AUTH_FAILED":
      return <InterfaceText>{"原因：AI 服務金鑰無效或未設定。"}</InterfaceText>;
    case "AI_RESPONSE_INVALID":
      return <InterfaceText>{"原因：AI 回傳的內容格式不正確。"}</InterfaceText>;
    case "PII_MASKING_FAILED":
      return <InterfaceText>{"原因：個資遮罩失敗，內容沒有送出分析。"}</InterfaceText>;
    case "SEGMENTATION_INVALID":
      return <InterfaceText>{"原因：AI 拆分的片段跟原文對不上。"}</InterfaceText>;
    case "CLASSIFICATION_FAILED_UNKNOWN":
      return <InterfaceText>{"原因不明，可以稍後再試一次。"}</InterfaceText>;
    default:
      return null;
  }
}

function StatusLabel({ status }) {
  switch (status) {
    case "completed":
      return <InterfaceText>{"分析完成"}</InterfaceText>;
    case "partial":
      return <InterfaceText>{"部分完成"}</InterfaceText>;
    case "failed":
      return <InterfaceText>{"分析失敗"}</InterfaceText>;
    case "no_data":
      return <InterfaceText>{"沒有資料"}</InterfaceText>;
    default:
      return null;
  }
}

function Counts({ item }) {
  if (item?.saved_answer_count == null) return null;
  return (
    <span className="analysis-diagnostic-counts">
      <InterfaceText>{"已保存"}</InterfaceText>{` ${item.saved_answer_count} · `}
      <InterfaceText>{"分類成功"}</InterfaceText>{` ${item.classified_count ?? 0} · `}
      <InterfaceText>{"失敗"}</InterfaceText>{` ${item.failed_count ?? 0}`}
    </span>
  );
}

/**
 * meta：存在 Chat_History 的分析結果 meta（analysis_status、diagnostic_code、
 * 計數、columns）。整批完成且沒有診斷時不顯示。
 * 多欄上傳：成功的欄位不列出，只列有問題的欄位（成功欄位的結果照常顯示在表格）。
 */
export default function AnalysisDiagnostics({ meta }) {
  if (!meta) return null;
  const columns = Array.isArray(meta.columns) ? meta.columns : [];
  const problemColumns = columns.filter((c) => c.diagnostic_code || (c.analysis_status && c.analysis_status !== "completed"));
  const hasBatchIssue = Boolean(meta.diagnostic_code) || (meta.analysis_status && meta.analysis_status !== "completed");
  if (!hasBatchIssue && problemColumns.length === 0) return null;

  return (
    <div className={`analysis-diagnostic analysis-diagnostic--${meta.analysis_status || "unknown"}`} role="status">
      <p className="analysis-diagnostic-title">
        <b><StatusLabel status={meta.analysis_status} /></b>
        {" "}<Counts item={meta} />
      </p>
      {meta.diagnostic_code && columns.length <= 1 && (
        <p><DiagnosticText code={meta.diagnostic_code} /> <FailureReasonText code={columns[0]?.failure_code} /></p>
      )}
      {columns.length > 1 && problemColumns.length > 0 && (
        <ul className="analysis-diagnostic-columns">
          {problemColumns.map((c) => (
            <li key={c.column}>
              <b>{c.column}</b>{"："}
              <StatusLabel status={c.analysis_status} />{" · "}
              <Counts item={c} />
              <br />
              <DiagnosticText code={c.diagnostic_code} /> <FailureReasonText code={c.failure_code} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** 後端回應 -> 存進 Chat_History meta 的精簡診斷（不含語言相關文字，重新整理後依語言顯示）。 */
export function diagnosticMeta(data) {
  return {
    analysis_status: data?.analysis_status ?? null,
    diagnostic_code: data?.diagnostic_code ?? null,
    saved_answer_count: data?.saved_answer_count ?? null,
    classified_count: data?.classified_count ?? null,
    failed_count: data?.failed_count ?? null,
    columns: (data?.columns || []).map((c) => ({
      column: c.column,
      analysis_status: c.analysis_status ?? null,
      diagnostic_code: c.diagnostic_code ?? null,
      failure_code: c.failure_code ?? null,
      routing_status: c.routing_status ?? null,
      saved_answer_count: c.saved_answer_count ?? null,
      classified_count: c.classified_count ?? null,
      failed_count: c.failed_count ?? null,
    })),
  };
}
