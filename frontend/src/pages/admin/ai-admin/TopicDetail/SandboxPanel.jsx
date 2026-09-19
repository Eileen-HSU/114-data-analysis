import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../shared/apiClient";
import { t, taxStatusText } from "../shared/taxStatus";
import { useAuth } from "../../../../hooks/AuthContext";

const NORMAL_STATUSES = ["published", "draft", "in_review"];

export default function SandboxPanel() {
  const { topicKey } = useParams();
  const { user } = useAuth();
  const token = user?.token;

  const [topicTitle, setTopicTitle] = useState(topicKey);
  const [versions, setVersions] = useState([]);
  const [showArchived, setShowArchived] = useState(false);
  const [selectedVersionId, setSelectedVersionId] = useState(null);
  const [answerTexts, setAnswerTexts] = useState("");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const [topicsData, versionsData] = await Promise.all([
          api("/api/admin/ai/taxonomy-topics", token),
          api(`/api/admin/ai/topics/${topicKey}/taxonomy`, token),
        ]);
        if (cancelled) return;
        const mine = (topicsData.topics || []).find((x) => x.topic_key === topicKey);
        setTopicTitle(mine?.title || topicKey);
        const list = versionsData.versions || [];
        setVersions(list);
        const defaultVersion = list.find((v) => NORMAL_STATUSES.includes(v.status));
        setSelectedVersionId(defaultVersion?.version_id ?? null);
      } catch (e) {
        if (!cancelled) setError(e.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [topicKey]);

  const normalVersions = versions.filter((v) => NORMAL_STATUSES.includes(v.status));
  const archivedVersions = versions.filter((v) => v.status === "archived");

  const runTest = async () => {
    const texts = answerTexts.split("\n").map((s) => s.trim()).filter(Boolean);
    if (!texts.length) { setError(t("請至少輸入一則測試文字", "Please enter at least one test answer")); return; }
    if (!selectedVersionId) { setError(t("請先選擇要測試的版本", "Please select a version to test")); return; }
    setRunning(true);
    setError("");
    try {
      const data = await api(`/api/admin/ai/topics/${topicKey}/taxonomy/${selectedVersionId}/sandbox`, token, {
        method: "POST",
        body: JSON.stringify({ answer_texts: texts }),
      });
      setResult(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setRunning(false);
    }
  };

  if (loading) return <div className="admin-card"><p>{t("載入中...", "Loading...")}</p></div>;

  return <>
    {error && <p className="ai-admin-error">{error}<button onClick={() => setError("")}>×</button></p>}
    <h2>{topicTitle}</h2>

    <div className="admin-card">
      <p className="sandbox-notice">
        <b>{t("這個沙盒不會寫入任何正式分析資料", "This sandbox does not write to any production data")}</b>
        {t("——測試結果不會建立分類紀錄、不會影響已上傳的問卷回答，也不會發布或修改任何 Taxonomy 版本。", " — no classification record is created, no uploaded answers are affected, and no taxonomy version is modified or published.")}
      </p>
      <p className="sandbox-notice sandbox-notice-cost">
        {t("每次執行都會實際呼叫 Gemini AI（非免費），請避免不必要的重複測試。", "Each run makes a real call to the Gemini AI (not free) — avoid unnecessary repeated tests.")}
      </p>

      <label>{t("選擇要測試的版本", "Select a version to test")}
        <select value={selectedVersionId || ""} onChange={(e) => setSelectedVersionId(Number(e.target.value))}>
          {normalVersions.length === 0 && <option value="">{t("（沒有可測試的版本）", "(no testable version)")}</option>}
          {normalVersions.map((v) => (
            <option key={v.version_id} value={v.version_id}>
              v{v.version_number} · {taxStatusText(v.status)}
            </option>
          ))}
          {showArchived && archivedVersions.map((v) => (
            <option key={v.version_id} value={v.version_id}>
              v{v.version_number} · {t("封存版本", "Archived")}
            </option>
          ))}
        </select>
      </label>

      {archivedVersions.length > 0 && (
        <label className="sandbox-archived-toggle">
          <input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} />
          {t("顯示封存版本（供歷史比較 / 問題重現，不是目前有效的候選版本）", "Show archived versions (for historical comparison / debugging — not a current candidate)")}
        </label>
      )}

      <label>{t("測試回答（每行一則）", "Test answers (one per line)")}
        <textarea rows="6" value={answerTexts} onChange={(e) => setAnswerTexts(e.target.value)} placeholder={t("貼上或輸入要測試的回答文字，一行一則", "Paste or type the answers to test, one per line")} />
      </label>

      <button className="primary" onClick={runTest} disabled={running || !selectedVersionId}>
        {running ? t("執行中...", "Running...") : t("執行測試", "Run test")}
      </button>
    </div>

    {result && (
      <div className="admin-card">
        <p><small>{t("使用版本：", "Version used:")} v{result.taxonomy_version.version_number} · {taxStatusText(result.taxonomy_version.status)}</small></p>
        {result.results.map((r, i) => (
          <article className="sandbox-result-row" key={i}>
            <p><b>{t("輸入", "Input")}:</b> {r.input}</p>
            <p><small>{t("拆分狀態", "Segmentation status")}: {r.segmentation_status}{r.segmentation_error_detail ? ` · ${r.segmentation_error_detail}` : ""}</small></p>
            {r.segments.length === 0 && <p className="tax-legacy-note">{t("沒有產生任何分類結果（拆分失敗或未偵測到有效意義單元）。", "No classification produced (segmentation failed or no valid segment detected).")}</p>}
            {r.segments.map((seg, j) => (
              <div className="sandbox-segment" key={j}>
                <p>
                  <b className={seg.status === "completed" ? "pass" : "fail"}>{seg.status}</b>
                  {" — "}{seg.main_category} / {seg.sub_category}
                  {seg.secondary_sub_category ? ` (+ ${seg.secondary_sub_category})` : ""}
                </p>
                <p>{t("推理", "Reasoning")}: {seg.reasoning}</p>
                <p>{t("摘要", "Summary")}: {seg.summary} · {t("信心", "Confidence")}: {seg.confidence}</p>
                <p>{t("方法論", "Methodology")}: {seg.methodology || "—"} · {t("引用", "Citation")}: {seg.citation || "—"}</p>
                {seg.error_detail && <p className="fail">{seg.error_detail}</p>}
              </div>
            ))}
          </article>
        ))}
      </div>
    )}
  </>;
}
