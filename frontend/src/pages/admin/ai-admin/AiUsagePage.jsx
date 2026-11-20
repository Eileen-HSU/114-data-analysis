import { useEffect, useMemo, useState } from "react";
import { useAuth } from "../../../hooks/AuthContext";
import { api, peekCache } from "./shared/apiClient";
import { t } from "./shared/taxStatus";
import { SkeletonCards } from "./shared/StatusWidgets";
import { AdminPageHeader } from "./shared/AdminLayout";
import { estimate, formatMoney } from "./shared/usageMath";
import "../ai-admin.css";

// AI 用量與成本（後端：GET /api/admin/ai/usage/summary、GET/PUT /api/admin/ai/usage/settings，
// 見 backend/services/ai_usage_report_service.py）。
// 金額一律是「依後台設定單價估算的參考成本」，不是實際帳單。數字全部取自後端，
// 前端只做試算器的乘法（不呼叫 AI、不寫資料庫）。
const SUMMARY_URL = "/api/admin/ai/usage/summary";
const SETTINGS_URL = "/api/admin/ai/usage/settings";

// 試算器輸入上限（避免輸入過大的數字）
const CALC_LIMITS = { surveys: 100000, responses: 1000000, chars: 100000 };

const FEATURES = {
  classification: ["回答分類", "Classification"],
  segmentation: ["回答拆段", "Segmentation"],
  routing: ["題目主題判斷", "Topic routing"],
  summary: ["群組摘要", "Group summaries"],
  second_opinion: ["AI 第二意見", "AI second opinion"],
  review_chat: ["審核對話", "Review chat"],
  taxonomy_generation: ["分類架構歸納", "Taxonomy generation"],
  translation: ["類別名稱翻譯", "Category translation"],
  chat_ask: ["分析結果追問", "Ask about results"],
  survey_generation: ["問卷生成", "Survey generation"],
  survey_revision: ["問卷 AI 修改", "Survey revision"],
  other: ["其他", "Other"],
};
const featureLabel = (key) => (FEATURES[key] ? t(...FEATURES[key]) : key);

const fmtInt = (n) => (n == null ? "—" : Math.round(n).toLocaleString());
const fmtPct = (r) => `${(r * 100).toFixed(1)}%`;

function MetricCard({ title, unit, metric, fx, reliableUnits = 3 }) {
  if (!metric) {
    return (
      <div className="ov-card usage-card">
        <span className="ov-card-title">{title}</span>
        <b className="ov-card-value">—</b>
        <span className="ov-card-text">
          {t("尚無資料：執行一次後就會顯示。", "No data yet: run it once to see numbers.")}
        </span>
      </div>
    );
  }
  const { tokens, cost_usd: cost } = metric;
  return (
    <div className="ov-card ov-card--active usage-card">
      <span className="ov-card-title">{title}</span>
      <b className="ov-card-value">{fmtInt(tokens.avg)} <small>tokens</small></b>
      <span className="usage-card-money">{cost ? formatMoney(cost.avg, fx) : t("未設定單價，無法估算金額", "No price set")}</span>
      <span className="ov-card-text">
        {t(`偏高情況（P90）：${fmtInt(tokens.p90)} tokens`, `High case (P90): ${fmtInt(tokens.p90)} tokens`)}
        {cost && <>｜{formatMoney(cost.p90, fx)}</>}
        <br />
        {t(`依過去 ${tokens.n} ${unit}實際資料估算`, `Based on the last ${tokens.n} real ${unit}`)}
        {tokens.n < reliableUnits && (
          <><br /><span style={{ color: "#b45309" }}>{t(`樣本少，僅供參考（建議累積 ${reliableUnits} 次以上）`, `Small sample; indicative only (${reliableUnits}+ recommended)`)}</span></>
        )}
      </span>
    </div>
  );
}

function parseCalcInput(raw, max, optional) {
  if (raw === "" || raw == null) return optional ? { value: null } : { error: t("請輸入數字", "Enter a number") };
  if (!/^\d+$/.test(String(raw).trim())) return { error: t("請輸入正整數", "Enter a whole number") };
  const value = Number(raw);
  if (value < 1) return { error: t("至少為 1", "Must be at least 1") };
  if (value > max) return { error: t(`最多 ${max.toLocaleString()}`, `At most ${max.toLocaleString()}`) };
  return { value };
}

function Calculator({ metrics, fx }) {
  const [form, setForm] = useState({ surveys: "10", responses: "100", chars: "" });
  const parsed = {
    surveys: parseCalcInput(form.surveys, CALC_LIMITS.surveys, false),
    responses: parseCalcInput(form.responses, CALC_LIMITS.responses, false),
    chars: parseCalcInput(form.chars, CALC_LIMITS.chars, true),
  };
  const invalid = Object.values(parsed).some((p) => p.error);
  const result = invalid ? null : estimate(metrics, {
    surveys: parsed.surveys.value, responses: parsed.responses.value, chars: parsed.chars.value,
  });
  const reliable = metrics?.reliable_units || 3;
  const smallSample = [metrics?.per_survey_generation, metrics?.per_100_responses, metrics?.per_1000_chars]
    .some((m) => m && m.tokens.n < reliable);
  const field = (key, label, hint) => (
    <label className="usage-calc-field">
      <span>{label}</span>
      <input inputMode="numeric" value={form[key]} placeholder={hint}
        onChange={(e) => setForm({ ...form, [key]: e.target.value })} aria-invalid={Boolean(parsed[key].error)} />
      {parsed[key].error && <small className="usage-error">{parsed[key].error}</small>}
    </label>
  );
  return (
    <section className="admin-summary-section">
      <h2 className="admin-summary-section-title">{t("成本試算器", "Cost estimator")}</h2>
      <div className="usage-calc">
        <div className="usage-calc-inputs">
          {field("surveys", t("問卷份數", "Surveys"))}
          {field("responses", t("每份平均回覆筆數", "Responses per survey"))}
          {field("chars", t("平均每筆字數（選填）", "Avg characters per response (optional)"), t("例如 80", "e.g. 80"))}
        </div>
        {result && (
          <div className="usage-calc-result">
            <div>
              <span>{t("平均情況", "Typical")}</span>
              <b>{fmtInt(result.avg.tokens)} tokens</b>
              <span className="usage-card-money">{formatMoney(result.avg.costUsd, fx)}</span>
            </div>
            <div>
              <span>{t("偏高情況（P90）", "High case (P90)")}</span>
              <b>{fmtInt(result.high.tokens)} tokens</b>
              <span className="usage-card-money">{formatMoney(result.high.costUsd, fx)}</span>
            </div>
          </div>
        )}
      </div>
      {result && (
        <p className="usage-note">
          {result.basis === "chars"
            ? t("分析成本依「每 1,000 字」實測平均計算。", "Analysis cost uses the measured per-1,000-character average.")
            : t("分析成本依「每 100 筆回覆」實測平均計算；填入平均字數可改用每 1,000 字估算（長回答較準）。",
              "Analysis cost uses the per-100-responses average; enter average characters to use the per-1,000-character average.")}
          {result.missingGeneration && t(" 尚無問卷生成紀錄，未計入。", " No survey-generation records yet; not included.")}
          {result.missingAnalysis && t(" 尚無回覆分析紀錄，未計入。", " No response-analysis records yet; not included.")}
          {smallSample && t(` 樣本少於 ${metrics?.reliable_units || 3} 次，結果僅供參考。`, " Small sample; indicative only.")}
          {t(" 試算只在畫面上計算，不會呼叫 AI。", " Calculated on this page only; no AI calls.")}
        </p>
      )}
    </section>
  );
}

function UsageTable({ title, rows, keyName, labelFn, fx }) {
  return (
    <section className="admin-summary-section">
      <h2 className="admin-summary-section-title">{title}</h2>
      {!rows.length ? <p className="usage-note">{t("本月還沒有用量。", "No usage this month yet.")}</p> : (
        <table className="usage-table">
          <thead><tr>
            <th>{t("名稱", "Name")}</th><th>{t("呼叫次數", "Calls")}</th><th>{t("失敗", "Failed")}</th>
            <th>Input</th><th>Output</th><th>{t("占比", "Share")}</th><th>{t("參考成本", "Reference cost")}</th>
          </tr></thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row[keyName]}>
                <td>{labelFn(row[keyName])}</td>
                <td>{fmtInt(row.calls)}</td>
                <td>{fmtInt(row.failed)}</td>
                <td>{fmtInt(row.input_tokens)}</td>
                <td>{fmtInt(row.output_tokens + row.thinking_tokens)}</td>
                <td><span className="usage-share"><span style={{ width: fmtPct(row.share) }} /></span>{fmtPct(row.share)}</td>
                <td>{row.total_tokens ? formatMoney(row.cost_usd, fx) : "—"}{row.cost_usd_partial ? " *" : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

const fmtTime = (iso) => {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

// 單份明細：最近每一次問卷生成／回覆分析各自用了多少
function RecentUnitsTable({ rows, fx }) {
  return (
    <section className="admin-summary-section">
      <h2 className="admin-summary-section-title">{t("每次分析明細（最近 30 筆）", "Each run (latest 30)")}</h2>
      {!rows?.length ? (
        <p className="usage-note">{t("還沒有紀錄。上傳一份檔案分析或生成一份問卷後，這裡會列出那一次用了多少。",
          "No records yet. Analyze a file or generate a survey and it will show up here.")}</p>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table className="usage-table">
            <thead><tr>
              <th>{t("時間", "Time")}</th><th>{t("類型", "Type")}</th><th>{t("檔案／問卷", "File / survey")}</th>
              <th>{t("使用者", "User")}</th><th>{t("回覆筆數", "Responses")}</th>
              <th>Input</th><th>Output</th><th>{t("合計 tokens", "Total tokens")}</th><th>{t("參考成本", "Reference cost")}</th>
            </tr></thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={`${row.created_at}-${i}`}>
                  <td style={{ whiteSpace: "nowrap" }}>{fmtTime(row.created_at)}</td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    {row.unit_type === "survey_generation" ? t("問卷生成", "Survey generation") : t("回覆分析", "Response analysis")}
                    {row.status === "failed" && <span style={{ color: "#c0392b" }}>{t("（失敗）", " (failed)")}</span>}
                  </td>
                  <td style={{ maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={row.label}>{row.label || "—"}</td>
                  <td>{row.user_name || "—"}</td>
                  <td>{row.unit_type === "survey_generation" ? "—" : fmtInt(row.response_total ?? row.item_count)}</td>
                  <td>{fmtInt(row.input_tokens)}</td>
                  <td>{fmtInt(row.output_tokens + row.thinking_tokens)}</td>
                  <td><b>{fmtInt(row.total_tokens)}</b>{row.failed_calls > 0 && <small style={{ color: "#888" }}>{t(`（另有 ${row.failed_calls} 次失敗）`, ` (+${row.failed_calls} failed)`)}</small>}</td>
                  <td style={{ whiteSpace: "nowrap" }}>{row.cost_usd == null ? t("未設定單價", "No price") : formatMoney(row.cost_usd, fx)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

const WARNING_TEXT = {
  quota_errors: ["今天已出現 429（額度用完）", "429 (quota) errors today"],
  near_rpd: ["今日請求數接近每日上限（RPD）", "Close to daily request limit (RPD)"],
  near_rpm: ["每分鐘尖峰接近上限（RPM）", "Per-minute peak close to RPM"],
  near_tpm: ["每分鐘 token 尖峰接近上限（TPM）", "Per-minute tokens close to TPM"],
};

function QuotaTable({ rows }) {
  const usedOf = (used, limit) => (limit ? `${fmtInt(used)} / ${fmtInt(limit)}` : fmtInt(used));
  return (
    <section className="admin-summary-section">
      <h2 className="admin-summary-section-title">{t("用量／配額監控（今日）", "Usage vs. quota (today)")}</h2>
      <p className="usage-note">
        {t("上限由管理者依 Google 官方公告填入（下方「單價與配額設定」）；沒填的模型只顯示用量。Google 的配額依模型、帳號分別計算，實際限制以官方為準。",
          "Limits are entered from Google's published quotas (settings below); models without limits show usage only. Google's own limits always win.")}
      </p>
      {!rows.length ? <p className="usage-note">{t("今天還沒有 AI 呼叫。", "No AI calls today.")}</p> : (
        <table className="usage-table">
          <thead><tr>
            <th>{t("模型", "Model")}</th><th>{t("今日請求（RPD）", "Requests today (RPD)")}</th>
            <th>{t("每分鐘尖峰請求（RPM）", "Peak requests/min (RPM)")}</th><th>{t("每分鐘尖峰 token（TPM）", "Peak tokens/min (TPM)")}</th>
            <th>{t("最近一分鐘", "Last minute")}</th><th>{t("今日 429", "429 today")}</th><th>{t("提醒", "Alerts")}</th>
          </tr></thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.model} className={row.warnings.length ? "usage-row--warn" : ""}>
                <td>{row.model}{row.reference_date && <small className="usage-muted"><br />{t(`依 ${row.reference_date} 公告`, `Per ${row.reference_date}`)}</small>}</td>
                <td>{usedOf(row.requests_today, row.rpd_limit)}</td>
                <td>{usedOf(row.peak_rpm_today, row.rpm_limit)}</td>
                <td>{usedOf(row.peak_tpm_today, row.tpm_limit)}</td>
                <td>{t(`${row.last_minute_requests} 次／${fmtInt(row.last_minute_tokens)} tokens`, `${row.last_minute_requests} calls / ${fmtInt(row.last_minute_tokens)} tokens`)}</td>
                <td>{row.quota_errors_today}</td>
                <td>{row.warnings.length ? row.warnings.map((w) => <div key={w}>{WARNING_TEXT[w] ? t(...WARNING_TEXT[w]) : w}</div>) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

const PRICE_FIELDS = [
  ["input_usd_per_mtok", "Input US$／1M"], ["output_usd_per_mtok", "Output US$／1M"],
  ["rpm_limit", "RPM"], ["tpm_limit", "TPM"], ["rpd_limit", "RPD"],
];

function SettingsPanel({ token, onSaved }) {
  const [settings, setSettings] = useState(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState(null);

  const toForm = (data) => ({
    models: data.models.map((m) => Object.fromEntries(Object.entries(m).map(([k, v]) => [k, v ?? ""]))),
    fx: { usd_twd: data.fx.usd_twd ?? "", reference_date: data.fx.reference_date ?? "" },
  });

  useEffect(() => {
    api(SETTINGS_URL, token).then((data) => setSettings(toForm(data))).catch((e) => setMessage({ error: e.message }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const update = (index, key, value) => {
    const models = settings.models.map((m, i) => (i === index ? { ...m, [key]: value } : m));
    setSettings({ ...settings, models });
  };

  const save = async () => {
    setSaving(true);
    setMessage(null);
    try {
      const body = {
        models: settings.models.map(({ model_name, input_usd_per_mtok, output_usd_per_mtok, rpm_limit, tpm_limit, rpd_limit, reference_date }) => (
          { model_name, input_usd_per_mtok, output_usd_per_mtok, rpm_limit, tpm_limit, rpd_limit, reference_date })),
      };
      const data = await api(SETTINGS_URL, token, { method: "PUT", body: JSON.stringify(body) });
      setSettings(toForm(data));
      setMessage({ ok: data.changed ? t(`已儲存 ${data.changed} 項變更（已寫入操作紀錄）。`, `Saved ${data.changed} change(s).`) : t("沒有變更。", "No changes.") });
      onSaved();
    } catch (e) {
      setMessage({ error: e.message });
    } finally {
      setSaving(false);
    }
  };

  return (
    <details className="usage-settings">
      <summary>{t("單價與配額設定", "Prices and quotas")}</summary>
      <p className="usage-note">
        {t("請依 Google 官方定價與配額頁填入，並寫上參考日期。單價為「美金／每百萬 token」；思考 token 依輸出單價計算。沒填單價的模型不估算金額。",
          "Fill these in from Google's official pricing and quota pages, with the reference date. Prices are US$ per 1M tokens; thinking tokens use the output price.")}
      </p>
      {!settings ? <p className="usage-note">{message?.error || t("載入中…", "Loading…")}</p> : (
        <>
          <div className="usage-table-wrap">
            <table className="usage-table usage-table--form">
              <thead><tr>
                <th>{t("模型", "Model")}</th>
                {PRICE_FIELDS.map(([key, label]) => <th key={key}>{label}</th>)}
                <th>{t("參考日期", "Reference date")}</th>
              </tr></thead>
              <tbody>
                {settings.models.map((row, i) => (
                  <tr key={row.model_name}>
                    <td>{row.model_name}</td>
                    {PRICE_FIELDS.map(([key]) => (
                      <td key={key}><input inputMode="decimal" value={row[key]} onChange={(e) => update(i, key, e.target.value)} /></td>
                    ))}
                    <td><input type="date" value={row.reference_date} onChange={(e) => update(i, "reference_date", e.target.value)} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="usage-fx" style={{ justifyContent: "flex-end" }}>
            <button className="primary" disabled={saving} onClick={save}>{saving ? t("儲存中…", "Saving…") : t("儲存", "Save")}</button>
          </div>
          {message?.ok && <p className="review-batch-message review-batch-message--ok" role="status">{message.ok}</p>}
          {message?.error && <p className="ai-admin-error" role="alert">{message.error}</p>}
        </>
      )}
    </details>
  );
}

export default function AiUsagePage() {
  const { user } = useAuth();
  const token = user?.token;
  const [summary, setSummary] = useState(() => peekCache(SUMMARY_URL) || null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      setSummary(await api(SUMMARY_URL, token));
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const fx = summary?.currency?.usd_twd || null;
  const metrics = summary?.unit_metrics;
  const breakdown = useMemo(() => metrics?.per_100_responses?.by_feature || [], [metrics]);

  return <>
    <AdminPageHeader title={t("AI 用量與成本", "AI usage & cost")}
      description={t("金額為依後台設定單價估算的參考成本，不是實際帳單；目前使用免費額度時，實際花費為 0。",
        "Amounts are reference costs from the prices set below, not a bill. On the free tier the actual spend is zero.")}
      actions={<button disabled={loading} onClick={load}>{loading ? t("更新中…", "Refreshing…") : t("重新整理", "Refresh")}</button>} />
    {error && <p className="ai-admin-error" role="alert">{error}<button onClick={() => setError("")}>×</button></p>}
    {!summary ? <SkeletonCards count={3} /> : (
      <>
        {summary.missing_price_models.length > 0 && <p className="review-batch-message review-batch-message--warn" role="status">
          {t(`以下模型尚未設定單價，金額不含這些模型（標 *）：${summary.missing_price_models.join("、")}`,
            `No price set for: ${summary.missing_price_models.join(", ")} (amounts marked * exclude them)`)}</p>}

        <div className="ov-cards usage-cards">
          <MetricCard title={t("每份問卷生成", "Per survey generated")} unit={t("份", "surveys")} metric={metrics.per_survey_generation} fx={fx} reliableUnits={metrics.reliable_units} />
          <MetricCard title={t("每 100 筆回覆分析", "Per 100 responses analyzed")} unit={t("個批次", "batches")} metric={metrics.per_100_responses} fx={fx} reliableUnits={metrics.reliable_units} />
          <MetricCard title={t("每 1,000 字回覆", "Per 1,000 characters")} unit={t("個批次", "batches")} metric={metrics.per_1000_chars} fx={fx} reliableUnits={metrics.reliable_units} />
        </div>
        <p className="usage-note">
          {t(`平均值取最近 ${metrics.window_days} 天的實際紀錄；只計算成功的呼叫。金額單位：美金；單價參考日期：${summary.price_reference_dates.join("、") || "未填"}。`,
            `Averages use real records from the last ${metrics.window_days} days (successful calls only). Amounts in USD; price dates: ${summary.price_reference_dates.join(", ") || "not set"}.`)}
        </p>

        <RecentUnitsTable rows={summary.recent_units} fx={fx} />

        <Calculator metrics={metrics} fx={fx} />

        {breakdown.length > 0 && (
          <section className="admin-summary-section">
            <h2 className="admin-summary-section-title">{t("每 100 筆回覆：各步驟用量", "Per 100 responses: by step")}</h2>
            <ul className="admin-list usage-breakdown">
              {breakdown.map((row) => (
                <li key={row.feature}><span>{featureLabel(row.feature)}</span><b>{fmtInt(row.tokens_per_100)} tokens</b></li>
              ))}
            </ul>
          </section>
        )}

        <section className="admin-summary-section">
          <h2 className="admin-summary-section-title">{t("用量總覽", "Usage")}</h2>
          <div className="ov-auto">
            {[["today", t("今日", "Today")], ["month", t(`本月（${summary.month.month}）`, `This month (${summary.month.month})`)]].map(([key, label]) => {
              const p = summary[key];
              return (
                <div className="ov-auto-item" key={key}>
                  <span>{label}</span>
                  <b>{fmtInt(p.total_tokens)} tokens</b>
                  <small>
                    Input {fmtInt(p.input_tokens)}｜Output {fmtInt(p.output_tokens + p.thinking_tokens)}
                    {p.thinking_tokens > 0 && t(`（含思考 ${fmtInt(p.thinking_tokens)}）`, ` (incl. thinking ${fmtInt(p.thinking_tokens)})`)}
                    <br />{t(`呼叫 ${fmtInt(p.calls)} 次，失敗 ${fmtInt(p.failed)} 次`, `${fmtInt(p.calls)} calls, ${fmtInt(p.failed)} failed`)}
                    <br />{t("參考成本：", "Reference cost: ")}{formatMoney(p.cost_usd, fx)}{p.cost_usd_partial ? " *" : ""}
                  </small>
                </div>
              );
            })}
          </div>
        </section>

        <UsageTable title={t("各功能用量（本月）", "By feature (this month)")} rows={summary.by_feature} keyName="feature" labelFn={featureLabel} fx={fx} />
        <UsageTable title={t("各模型用量（本月）", "By model (this month)")} rows={summary.by_model} keyName="model" labelFn={(x) => x} fx={fx} />
        <QuotaTable rows={summary.quota} />
        <SettingsPanel token={token} onSaved={load} />
        <p className="usage-note">
          {t(`用量紀錄只保存數字（時間、功能、模型、token 數）與檔名／問卷標題，不保存問卷內容、回答或 prompt。明細保留 ${summary.retention_days} 天，之後彙總為每日統計。`,
            `Usage records keep numbers (time, feature, model, tokens) and file names / survey titles — never survey content, answers or prompts. Details are kept ${summary.retention_days} days, then rolled up daily.`)}
        </p>
      </>
    )}
  </>;
}
