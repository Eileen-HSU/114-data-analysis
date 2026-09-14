import { apiUrl } from "./api";

const PPT_SURVEY_TIMEOUT_MS = 90000;
const CHAT_TIMEOUT_MS = 60000;
const ALLOWED_TYPES = new Set(["short", "rating"]);

function withTimeout(timeoutMs) {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
  return { controller, timeoutId };
}

function parseApiError(status, data) {
  if (data?.error) return data.error;
  if (status === 401) return "Please log in to generate surveys with AI.";
  if (status === 413) return "The file is too large. Upload a PPT or PDF no larger than 25 MB.";
  if (status === 429) return "The AI usage or rate limit has been reached. Please try again later.";
  if (status === 503) return "The AI service is not configured. Please contact the administrator.";
  if (status >= 500) return "The AI service is temporarily unavailable. Please try again later.";
  return "Request failed. Check the file and settings, then try again.";
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
    title: String(question?.title || question?.question || `Question ${index + 1}`).trim(),
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
  if (!file) throw new Error("Please upload a PPT or PDF file first.");
  if (!token) throw new Error("Please log in to generate surveys with AI.");

  const formData = new FormData();
  formData.append("file", file);
  formData.append("config", JSON.stringify({
    direction: config?.direction || "",
    focus: config?.focus || "",
    questionCount: config?.questionCount || 5,
    typeLimits: {
      short: config?.typeLimits?.short !== false,
      rating: config?.typeLimits?.rating !== false,
    },
  }));

  const { controller, timeoutId } = withTimeout(PPT_SURVEY_TIMEOUT_MS);
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
      throw new Error("AI analysis timed out. Try again later or use a smaller file.");
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

export async function reviseSurveyWithAi({ draft, message, token }) {
  if (!token) throw new Error("Please log in to edit surveys with AI.");
  if (!message?.trim()) throw new Error("Please enter editing instructions.");

  const { controller, timeoutId } = withTimeout(CHAT_TIMEOUT_MS);
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
      throw new Error("AI editing timed out. Please try again later.");
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }
}
