import { useEffect, useState } from "react";
import { api } from "./apiClient";
import { errorMessage, isLegacyTechnicalTopic, topicDisplayName } from "./reviewStates";
import { t } from "./taxStatus";

// 可以當作「移到 / 併入」目標的主題：不是自己、沒有被合併、而且有分類架構可以用。
export const movableTargets = (topics, currentKey) => (topics || []).filter((tp) =>
  tp.topic_key !== currentKey
  && !tp.merged_into
  && !isLegacyTechnicalTopic(tp)
  && (tp.published_version || tp.latest_draft_version));

export const topicLabel = (tp) => {
  const tags = [];
  if (tp.is_auto_topic) tags.push(t("自動主題", "auto"));
  if (!tp.published_version) tags.push(t("暫定分類", "provisional"));
  return `${topicDisplayName(tp)}${tags.length ? `（${tags.join("・")}）` : ""}`;
};

/**
 * 主題分錯了：選一個主題，然後執行 onMove(targetKey)。
 * mode="item"：單筆回答移到其他主題；mode="topic"：整個主題併入其他主題。
 */
export default function TopicMovePicker({ token, currentTopicKey, mode = "item", disabled, onMove }) {
  const [topics, setTopics] = useState(null);
  const [target, setTarget] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(null); // { ok, text }

  useEffect(() => {
    let cancelled = false;
    api("/api/admin/ai/taxonomy-topics", token)
      .then((d) => { if (!cancelled) setTopics(d.topics || []); })
      .catch((e) => { if (!cancelled) { setTopics([]); setMessage({ ok: false, text: errorMessage(e) }); } });
    return () => { cancelled = true; };
  }, [token]);

  const options = movableTargets(topics, currentTopicKey);
  const chosen = options.find((tp) => tp.topic_key === target);

  const submit = async () => {
    if (!chosen) return;
    const question = mode === "topic"
      ? t(`把整個主題併入「${topicDisplayName(chosen)}」？\n這個主題底下的回答會用「${topicDisplayName(chosen)}」的分類架構重新分類，之後同樣的欄位也會直接歸到「${topicDisplayName(chosen)}」。已人工確認的回答不會被動到。`,
        `Merge this whole topic into "${topicDisplayName(chosen)}"? Its answers will be re-classified with that taxonomy, and future uploads of the same column go there too. Reviewed answers are left untouched.`)
      : t(`把這則回答移到「${topicDisplayName(chosen)}」，並用該主題的分類架構重新分類？`,
        `Move this answer to "${topicDisplayName(chosen)}" and re-classify it with that topic's taxonomy?`);
    if (!window.confirm(question)) return;
    setBusy(true);
    setMessage(null);
    try {
      const text = await onMove(chosen);
      setMessage({ ok: true, text });
    } catch (e) {
      setMessage({ ok: false, text: errorMessage(e) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="topic-move-picker">
      {message && <p className={message.ok ? "review-batch-message" : "ai-admin-error"}>{message.text}</p>}
      {topics === null ? (
        <p><small>{t("載入主題中…", "Loading topics…")}</small></p>
      ) : options.length === 0 ? (
        <p className="review-empty-hint">{t("目前沒有其他有分類架構的主題可以選。", "No other topic with a taxonomy is available.")}</p>
      ) : (
        <div className="topic-move-row">
          <select value={target} disabled={disabled || busy} onChange={(e) => setTarget(e.target.value)}>
            <option value="">{mode === "topic" ? t("併入哪個主題…", "Merge into…") : t("移到哪個主題…", "Move to…")}</option>
            {options.map((tp) => <option key={tp.topic_key} value={tp.topic_key}>{topicLabel(tp)}</option>)}
          </select>
          <button disabled={disabled || busy || !chosen} onClick={submit}>
            {busy ? t("處理中…（AI 重新分類）", "Working… (re-classifying)")
              : mode === "topic" ? t("整個主題併入", "Merge topic") : t("移到這個主題", "Move here")}
          </button>
        </div>
      )}
    </div>
  );
}
