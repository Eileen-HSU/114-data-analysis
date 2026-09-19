import { useState } from "react";
import { api } from "./shared/apiClient";
import { t } from "./shared/taxStatus";

// topic_key 是 immutable internal identifier，不是產品欄位——Admin
// 完全不會看到、也不能修改這個值。前端在建立當下自己生一個 opaque
// random key（"topic_" + 32 碼十六進位亂數，共 38 字元，遠低於
// backend Topic.topic_key 的 VARCHAR(50) 限制），不從 title slugify、
// 不轉拼音、不翻譯成英文。未來 backend 支援自動生成 ID 後，這裡的
// 生成責任要整個移回 backend，這個函式屆時直接刪掉即可。
function generateTopicKey() {
  const random = crypto.randomUUID().replace(/-/g, "");
  return `topic_${random}`;
}

export default function CreateTopicSection({ token, onCreated }) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [questionText, setQuestionText] = useState("");
  const [answerTexts, setAnswerTexts] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const reset = () => {
    setTitle("");
    setQuestionText("");
    setAnswerTexts("");
    setError("");
  };

  const submit = async () => {
    if (!title.trim()) {
      setError(t("請輸入主題名稱", "Please enter a topic name"));
      return;
    }
    const answers = answerTexts.split("\n").map((s) => s.trim()).filter(Boolean);
    if (!answers.length) {
      setError(t("請至少貼上一則回答資料", "Please paste at least one answer"));
      return;
    }

    const topicKey = generateTopicKey();
    setSubmitting(true);
    setError("");
    try {
      const data = await api(`/api/admin/ai/topics/${topicKey}/taxonomy/generate`, token, {
        method: "POST",
        body: JSON.stringify({
          topic_title: title.trim(),
          question_text: questionText.trim() || undefined,
          answer_texts: answers,
        }),
      });
      reset();
      setOpen(false);
      onCreated(topicKey, data.taxonomy_version);
    } catch (e) {
      setError(e.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="admin-card">
      <button onClick={() => setOpen((v) => !v)}>
        {open ? t("收合", "Collapse") : t("＋ 建立新的分析主題", "＋ Create a new analysis topic")}
      </button>
      {open && (
        <div style={{ marginTop: 14 }}>
          {error && <p className="ai-admin-error">{error}<button onClick={() => setError("")}>×</button></p>}
          <label>
            {t("主題名稱", "Topic name")}
            <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder={t("例如：工作彈性與遠距安排", "e.g. Work flexibility and remote arrangements")} />
          </label>
          <label>
            {t("問卷題目內容（選填）", "Survey question text (optional)")}
            <input value={questionText} onChange={(e) => setQuestionText(e.target.value)} />
          </label>
          <label>
            {t("初始回答資料（每行一則）", "Initial answers (one per line)")}
            <textarea rows="8" value={answerTexts} onChange={(e) => setAnswerTexts(e.target.value)} placeholder={t("貼上這批開放式回答，一行一則", "Paste the open-ended answers, one per line")} />
          </label>
          <p className="sandbox-notice">
            {t("送出後系統會由 AI 依這批回答歸納出一份分類架構草稿，需要你審核、修改後才能發布，不會立即成為正式分類依據。", "After submitting, AI will draft a taxonomy from these answers. You'll review and edit it before it can be published — it won't affect production classification immediately.")}
          </p>
          <button className="primary" onClick={submit} disabled={submitting}>
            {submitting ? t("建立中...", "Creating...") : t("建立主題並產生草稿", "Create topic and generate draft")}
          </button>
        </div>
      )}
    </div>
  );
}
