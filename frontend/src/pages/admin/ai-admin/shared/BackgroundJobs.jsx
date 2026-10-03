import { useEffect, useState } from "react";
import { api } from "./apiClient";
import { t } from "./taxStatus";

// 背景工作（全部重試、AI 再確認）共用：開始、停止、執行中每 5 秒更新進度，結束時通知首頁重新整理。
export function useBackgroundJob(path, token, setError, onFinished) {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const running = data?.job?.status === "running" && !data.job.interrupted;

  const reload = async () => {
    try {
      setData(await api(path, token));
    } catch {
      setData(null);
    }
  };

  useEffect(() => {
    if (!running) return undefined;
    const timer = setInterval(async () => {
      const next = await api(path, token).catch(() => null);
      if (!next) return;
      setData(next);
      if (next.job?.status !== "running") onFinished();
    }, 5000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running]);

  const call = async (suffix) => {
    setBusy(true);
    try {
      await api(`${path}${suffix}`, token, { method: "POST" });
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
      reload();
    }
  };

  return {
    data, busy, running, reload,
    start: (confirmText) => { if (window.confirm(confirmText)) call(""); },
    cancel: () => call("/cancel"),
  };
}

export const RETRY_LABELS = {
  running: (j) => t(`正在重試… ${j.processed} / ${j.total_at_start}`, `Retrying… ${j.processed} / ${j.total_at_start}`),
  counts: (j) => t(`成功 ${j.succeeded}、仍失敗 ${j.still_failed}${j.skipped ? `、跳過 ${j.skipped}` : ""}`,
    `${j.succeeded} fixed, ${j.still_failed} still failing${j.skipped ? `, ${j.skipped} skipped` : ""}`),
  name: () => t("全部重試", "retry"),
};
export const RECHECK_LABELS = {
  running: (j) => t(`AI 正在再確認… ${j.processed} / ${j.total_at_start}`, `AI re-checking… ${j.processed} / ${j.total_at_start}`),
  counts: (j) => t(`一致並自動通過 ${j.succeeded}、不一致 ${j.still_failed}`,
    `${j.succeeded} agreed and approved, ${j.still_failed} disagreed`),
  name: () => t("AI 再確認", "AI re-check"),
};

// 背景工作的進度／上一次的結果。沒有任何紀錄時不顯示。
export function JobStatus({ data, labels }) {
  const job = data?.job;
  if (!job) return null;
  const counts = labels.counts(job);
  if (job.status === "running" && !job.interrupted) {
    const percent = job.total_at_start ? Math.min(100, Math.round((job.processed / job.total_at_start) * 100)) : 0;
    return (
      <div className="admin-bulk-status" role="status" aria-live="polite">
        <p><b>{labels.running(job)}</b></p>
        <div className="admin-bulk-bar"><span style={{ width: `${percent}%` }} /></div>
        <p><small>{counts}{job.quota_waits > 0 && t("。AI 額度不足，已自動放慢速度。", ". AI quota is tight, so it slowed down.")}</small></p>
      </div>
    );
  }
  const name = labels.name();
  const summary = {
    completed: t(`上次${name}已完成：${counts}。`, `Last ${name} finished: ${counts}.`),
    paused_quota: t(`上次${name}因 AI 額度用完自動暫停（${counts}）。額度恢復後再按一次即可接續。`,
      `Last ${name} paused because the AI quota ran out (${counts}). Run it again once quota is back.`),
    cancelled: t(`上次${name}已停止（${counts}）。`, `Last ${name} was stopped (${counts}).`),
    failed: t(`上次${name}發生錯誤（${counts}）。可以再按一次。`, `Last ${name} hit an error (${counts}). Try again.`),
  }[job.status];
  const text = job.interrupted
    ? t(`上次${name}中斷了（${counts}），可以再按一次接續，已處理好的不會重做。`,
      `The last ${name} was interrupted (${counts}). Run it again to continue; finished items won't be redone.`)
    : summary;
  return text ? <p className="admin-bulk-status"><small>{text}</small></p> : null;
}



// 系統管理 › 背景工作：全部重試（無法分類）與 AI 再確認（低信心）
export function BackgroundJobsPanel({ token, onError }) {
  const bulk = useBackgroundJob("/api/admin/ai/unassigned/retry-all", token, onError, () => bulk.reload());
  const recheck = useBackgroundJob("/api/admin/ai/second-opinion", token, onError, () => recheck.reload());
  useEffect(() => { bulk.reload(); recheck.reload(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);
  const remainingRetry = bulk.data?.remaining?.total ?? 0;
  const remainingRecheck = recheck.data?.remaining?.total ?? 0;

  const card = (title, description, job, labels, remaining, startLabel, confirmText) => (
    <section className="admin-panel">
      <h3>{title}</h3>
      <p className="admin-muted">{description}</p>
      <p>{t(`目前可處理：${remaining} 筆`, `Ready to process: ${remaining}`)}</p>
      <JobStatus data={job.data} labels={labels} />
      <div className="admin-actions">
        {job.running ? (
          <button disabled={job.busy || job.data.job.cancel_requested} onClick={job.cancel}>
            {job.data.job.cancel_requested ? t("停止中…", "Stopping…") : t("停止", "Stop")}
          </button>
        ) : (
          <button className="primary" disabled={job.busy || remaining === 0} onClick={() => job.start(confirmText)}>
            {job.busy ? t("處理中…", "Working…") : startLabel}
          </button>
        )}
      </div>
    </section>
  );

  return (
    <div className="admin-stack">
      {card(t("全部重試", "Retry all"),
        t("在背景重跑分類失敗、判斷不出主題的資料，會自動配合 AI 額度調整速度。",
          "Re-runs failed and unrouted items in the background, pacing itself to the AI quota."),
        bulk, RETRY_LABELS, remainingRetry, t("全部重試", "Retry all"),
        t(`要在背景重新分析 ${remainingRetry} 筆嗎？會使用 Gemini 額度，可以離開這個頁面。`,
          `Re-analyse ${remainingRetry} items in the background? This uses Gemini quota; you can leave this page.`))}
      {card(t("AI 再確認", "AI re-check"),
        t("低信心的結果交給較強的模型再判斷一次，一致就自動通過。排程每 10 分鐘也會自動執行。",
          "Low-confidence results are re-checked by a stronger model; agreements are approved. Also runs every 10 minutes."),
        recheck, RECHECK_LABELS, remainingRecheck, t("立刻再確認", "Re-check now"),
        t(`要立刻讓 AI 再確認 ${remainingRecheck} 筆低信心的結果嗎？`, `Re-check ${remainingRecheck} low-confidence results now?`))}
    </div>
  );
}
