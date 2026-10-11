import { useEffect, useState } from "react";
import { api } from "./apiClient";
import { t } from "./taxStatus";
import { errorMessage } from "./reviewStates";

const newBatchId = () => (
  typeof crypto !== "undefined" && crypto.randomUUID
    ? crypto.randomUUID().replace(/-/g, "")
    : `${Date.now()}${Math.random().toString(16).slice(2)}`
);

// 預覽超過這段時間就視為過期，必須重新預覽才能執行（資料在這段期間可能已經變動）。
const PREVIEW_TTL_MS = 5 * 60 * 1000;
const EXPIRED = Symbol("preview-expired");
const previewExpired = (p) => Date.now() - p.at > PREVIEW_TTL_MS;

const ITEMS = {
  backfill: {
    title: () => t("套用自動通過規則到既有資料", "Apply auto-approval to existing data"),
    purpose: () => t("把自動通過上線前就分析好、符合條件的待審結果改成自動通過。", "Auto-approve pending results analysed before auto-approval was enabled that meet the rules."),
  },
  legacy: {
    title: () => t("排除舊版分類結果", "Exclude legacy classifications"),
    purpose: () => t("排除沒有信心分數、沒有 taxonomy 版本、從未人工處理的舊版分類結果。", "Exclude legacy classifications with no confidence score or taxonomy version that were never reviewed."),
    risky: true,
  },
};

// 低頻資料維護：選擇項目 → 預覽影響範圍 → 確認執行 → 查看結果。
// 呼叫的 API 與原本完全相同；預覽只用後端實際回傳的欄位，沒有的資訊不推估。
export default function MaintenancePanel({ token }) {
  const [busy, setBusy] = useState("");          // "" | "preview:<kind>" | "run:<kind>"
  const [preview, setPreview] = useState(null);  // { kind, data, at } — 同一時間只保留一份
  const [result, setResult] = useState(null);    // { kind, tone: ok|warn|none, text, detail }
  const [error, setError] = useState("");
  const [now, setNow] = useState(() => Date.now());

  // 讓「預覽已過期」不必等使用者操作就能顯示。
  useEffect(() => {
    if (!preview) return undefined;
    const timer = setInterval(() => setNow(Date.now()), 15000);
    return () => clearInterval(timer);
  }, [preview]);

  const expired = Boolean(preview) && now - preview.at > PREVIEW_TTL_MS;

  const loadPreview = async (kind) => {
    if (busy) return;
    setBusy(`preview:${kind}`);
    setError("");
    setResult(null);
    setPreview(null); // 切換項目或重新預覽：先丟掉舊的預覽
    try {
      const data = kind === "legacy"
        ? await api("/api/classification/review/exclude-legacy/preview", token)
        : await api("/api/admin/ai/classifications/auto-confirm", token, { method: "POST", body: JSON.stringify({ dry_run: true }) });
      setPreview({ kind, data, at: Date.now() });
      setNow(Date.now());
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy("");
    }
  };

  const closePreview = () => { if (!busy) setPreview(null); };

  const runLegacy = async (p) => {
    const reasons = (p.data.skipped_reasons || []).map((r) => `  • ${r.message}：${r.count}`).join("\n");
    if (!window.confirm(t(
      `將排除 ${p.data.eligible_count} 筆舊版分類資料（沒有信心分數、沒有 taxonomy 版本、從未人工處理）。\n略過 ${p.data.skipped_count} 筆：\n${reasons || "  （無）"}\n\n原始紀錄會保留，但不再納入分析與報告，且不保證能完整還原。是否繼續？`,
      `Exclude ${p.data.eligible_count} legacy classifications.\nSkipped ${p.data.skipped_count}:\n${reasons || "  (none)"}\n\nRecords are kept but no longer analysed or reported, and full restoration is not guaranteed. Continue?`,
    ))) return null;
    if (previewExpired(p)) return EXPIRED; // 確認視窗停留過久：寫入前再驗一次
    const res = await api("/api/classification/review/exclude-legacy", token, {
      method: "POST",
      body: JSON.stringify({ batch_id: newBatchId(), expected_ids: p.data.eligible_ids }),
    });
    const planned = p.data.eligible_count;
    const done = res.affected_count ?? 0;
    const detail = [
      res.skipped_count > 0 && t(`執行時略過 ${res.skipped_count} 筆`, `${res.skipped_count} skipped at run time`),
      res.batch_id && t(`批次 ${String(res.batch_id).slice(0, 8)}`, `batch ${String(res.batch_id).slice(0, 8)}`),
      res.idempotent_replay && t("此批次先前已執行過，這次沒有重複寫入", "This batch already ran; nothing was written again"),
    ].filter(Boolean).join(" · ");
    if (done === 0) return { tone: "none", text: t("沒有資料被排除（執行當下已沒有符合條件的資料）。", "Nothing was excluded (no items were eligible at run time)."), detail };
    if (done < planned) return { tone: "warn", text: t(`部分完成：預覽 ${planned} 筆，實際排除 ${done} 筆。`, `Partly done: ${planned} previewed, ${done} actually excluded.`), detail };
    return { tone: "ok", text: t(`已排除 ${done} 筆舊版資料。`, `Excluded ${done} legacy classification(s).`), detail };
  };

  const runBackfill = async (p) => {
    if (!window.confirm(t(
      `有 ${p.data.eligible_count} 筆待處理的結果符合自動通過條件（信心 ≥ 0.75、類別在已發布的分類架構內、沒有需要人工判斷的問題）。\n\n要把它們改成「自動通過」嗎？之後仍可在「已確認 › 自動通過」重新審核。`,
      `${p.data.eligible_count} pending items meet the auto-approval rules (confidence ≥ 0.75, category in the published taxonomy, nothing flagged).\n\nAuto-approve them? You can still re-review them under Confirmed › Auto-approved.`,
    ))) return null;
    if (previewExpired(p)) return EXPIRED; // 確認視窗停留過久：寫入前再驗一次
    const res = await api("/api/admin/ai/classifications/auto-confirm", token, { method: "POST", body: JSON.stringify({ dry_run: false }) });
    if (!res.eligible_count) return { tone: "none", text: t("沒有資料被處理（執行當下已沒有符合條件的資料）。", "Nothing was processed (no items were eligible at run time).") };
    if (res.limit_reached) return { tone: "warn", text: t(`已自動通過 ${res.eligible_count} 筆。`, `Auto-approved ${res.eligible_count} items.`), detail: t("已達單次處理上限，可能還有更多符合條件的資料；請重新預覽後再執行。", "The per-run limit was reached; more eligible items may remain. Preview again and re-run.") };
    return { tone: "ok", text: t(`已自動通過 ${res.eligible_count} 筆。`, `Auto-approved ${res.eligible_count} items.`) };
  };

  const execute = async () => {
    if (busy || !preview) return;
    const p = preview;
    // 預覽過期、或沒有可處理的資料時不執行；一律要求重新預覽。
    if (previewExpired(p) || !(p.data.eligible_count > 0)) { setNow(Date.now()); return; }
    setBusy(`run:${p.kind}`);
    setError("");
    try {
      const outcome = await (p.kind === "legacy" ? runLegacy(p) : runBackfill(p));
      if (outcome === EXPIRED) {
        setNow(Date.now()); // 保留（已過期的）預覽以顯示提示與「重新預覽」；不送出寫入
      } else if (outcome) {
        setResult({ kind: p.kind, ...outcome });
        setPreview(null); // 執行完成後，舊預覽不能再用
      }
    } catch (e) {
      setError(errorMessage(e));
      setPreview(null); // 失敗時結果不確定，必須重新預覽
    } finally {
      setBusy("");
    }
  };

  const previewPanel = (kind) => {
    if (!preview || preview.kind !== kind) return null;
    const d = preview.data;
    const count = d.eligible_count ?? 0;
    const risky = ITEMS[kind].risky;
    return (
      <div className="mnt-preview" role="region" aria-label={t("預覽結果", "Preview")}>
        <dl className="mnt-facts">
          <div><dt>{t("預計處理", "Will be processed")}</dt><dd><b>{count}</b> {t("筆", "items")}</dd></div>
          {kind === "legacy" && (
            <div><dt>{t("不符合條件／略過", "Not eligible / skipped")}</dt><dd>
              <b>{d.skipped_count ?? 0}</b> {t("筆", "items")}
              {(d.skipped_reasons || []).length > 0 && (
                <ul>{d.skipped_reasons.map((r) => <li key={r.code || r.message}>{r.message}：{r.count}</li>)}</ul>
              )}
            </dd></div>
          )}
          {count === 0 && <div><dt>{t("無需處理", "Nothing to do")}</dt><dd>{t("目前沒有符合條件的資料。", "No items currently meet the conditions.")}</dd></div>}
        </dl>
        {kind === "backfill" && d.limit_reached && (
          <p className="mnt-note mnt-note--warn">{t("已達單次處理上限：可能還有更多符合條件的資料，執行後請再預覽一次。", "The per-run limit was reached: more eligible items may exist. Preview again after running.")}</p>
        )}
        {kind === "legacy" && count > 0 && (
          <p className="mnt-note">{t("執行時只處理這次預覽的項目，且必須在執行當下仍符合條件。", "Only the previewed items are processed, and only if they still qualify when you run it.")}</p>
        )}
        {risky && count > 0 && (
          <p className="mnt-note mnt-note--risk">{t("高風險：被排除的資料不再納入分析與報告，已產生的報告可能因此過期，且不保證能完整還原。", "High risk: excluded items leave analysis and reports, existing reports may become outdated, and full restoration is not guaranteed.")}</p>
        )}
        {expired && <p className="mnt-note mnt-note--warn" role="status">{t("預覽已過期，請重新預覽後再執行。", "This preview has expired. Preview again before running.")}</p>}
        <div className="mnt-actions">
          {count > 0 && (
            <button type="button" className={risky ? "tax-danger mnt-run-risky" : "primary"} disabled={Boolean(busy) || expired} onClick={execute}>
              {busy === `run:${kind}` ? t("處理中…", "Working…") : risky ? t(`確認排除 ${count} 筆`, `Exclude ${count}`) : t(`確認套用 ${count} 筆`, `Apply to ${count}`)}
            </button>
          )}
          {expired && <button type="button" disabled={Boolean(busy)} onClick={() => loadPreview(kind)}>{t("重新預覽", "Preview again")}</button>}
          <button type="button" className="link-button" disabled={Boolean(busy)} onClick={closePreview}>{t("關閉預覽", "Close preview")}</button>
        </div>
      </div>
    );
  };

  return (
    <section className="admin-section mnt">
      {error && <p className="ai-admin-error" role="alert">{error}<button onClick={() => setError("")}>×</button></p>}
      {result && (
        <div className={`review-batch-message${result.tone === "warn" ? " review-batch-message--warn" : result.tone === "ok" ? " review-batch-message--ok" : ""}`} role="status">
          {result.tone === "ok" ? "✓ " : ""}<b>{ITEMS[result.kind].title()}</b>：{result.text}
          {result.detail && <div><small>{result.detail}</small></div>}
        </div>
      )}
      <p className="admin-muted">{t("低頻的資料維護，和錯誤處理分開。流程：預覽影響範圍 → 確認執行 → 查看結果。", "Occasional data maintenance, separate from error handling. Preview the impact, confirm, then review the result.")}</p>
      <ul className="admin-list mnt-list">
        {Object.keys(ITEMS).map((kind) => (
          <li key={kind} className="mnt-item">
            <div className="mnt-item-head">
              <div className="mnt-item-body">
                <b>{ITEMS[kind].title()}</b>
                {ITEMS[kind].risky && <span className="rpt-tag rpt-tag--failed">{t("高風險", "High risk")}</span>}
                <p>{ITEMS[kind].purpose()}</p>
              </div>
              <button type="button" disabled={Boolean(busy)} onClick={() => loadPreview(kind)}>
                {busy === `preview:${kind}` ? t("預覽中…", "Loading preview…") : t("預覽影響範圍", "Preview impact")}
              </button>
            </div>
            {previewPanel(kind)}
          </li>
        ))}
      </ul>
    </section>
  );
}
