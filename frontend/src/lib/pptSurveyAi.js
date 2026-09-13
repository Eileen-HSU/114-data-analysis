import { apiUrl } from "./api";

const PPT_SURVEY_TIMEOUT_MS = 90000;
const ALLOWED_TYPES = new Set(["short", "rating"]);

function withTimeout(timeoutMs = PPT_SURVEY_TIMEOUT_MS) {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
  return { controller, timeoutId };
}

function parseApiError(status, data) {
  if (data?.error) return data.error;
  if (status === 401) return "請先登入後再使用 AI 生成問卷。";
  if (status === 413) return "檔案過大，請改用較小的 PPT/PDF。";
  if (status === 429) return "AI 額度或速率限制不足，請稍後再試。";
  if (status === 503) return "AI 服務尚未完成設定，請確認後端環境變數。";
  if (status >= 500) return "AI 服務暫時無法使用，請稍後再試。";
  return "請求失敗，請確認檔案與參數後再試。";
}

async function readJsonResponse(response) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(parseApiError(response.status, data));
  }
  return data;
}

function normalizeQuestion(question, index) {
  const type = ALLOWED_TYPES.has(question?.type) ? question.type : "short";
  return {
    id: question?.id || crypto.randomUUID(),
    type,
    title: String(question?.title || question?.question || `第 ${index + 1} 題`).trim(),
    required: question?.required !== false,
    options: Array.isArray(question?.options)
      ? question.options.map((option) => String(option || "").trim()).filter(Boolean)
      : [],
  };
}

export function toCompatibleSurveyPayload(draft) {
  const questions = Array.isArray(draft?.questions) ? draft.questions : [];
  return {
    title: String(draft?.title || "").trim(),
    description: String(draft?.description || "").trim(),
    identity_mode: draft?.identity_mode === "identified" ? "identified" : "anonymous",
    deadline_at: draft?.deadline_at || "",
    questions: questions.map(normalizeQuestion),
  };
}

export async function generateSurveyFromPpt({ file, config, token }) {
  if (!file) throw new Error("請先上傳 PPT 或 PDF 檔案。");
  if (!token) throw new Error("請先登入後再使用 AI 生成問卷。");

  const formData = new FormData();
  formData.append("file", file);
  formData.append("config", JSON.stringify(config || {}));

  const { controller, timeoutId } = withTimeout();
  try {
    const response = await fetch(apiUrl("/api/ai/ppt-survey/generate"), {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
      },
      body: formData,
      signal: controller.signal,
    });
    const data = await readJsonResponse(response);
    return toCompatibleSurveyPayload(data.draft);
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error("AI 生成逾時，請稍後再試或上傳較小的檔案。");
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

export async function reviseSurveyWithAi({ draft, message, token }) {
  if (!token) throw new Error("請先登入後再使用 AI 修改問卷。");
  if (!message?.trim()) throw new Error("請輸入修改指令。");

  const { controller, timeoutId } = withTimeout(60000);
  try {
    const response = await fetch(apiUrl("/api/ai/ppt-survey/chat"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        draft: toCompatibleSurveyPayload(draft),
        message: message.trim(),
      }),
      signal: controller.signal,
    });
    const data = await readJsonResponse(response);
    return toCompatibleSurveyPayload(data.draft);
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error("AI 修改逾時，請稍後再試。");
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }
}
