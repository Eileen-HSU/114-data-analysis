import { apiUrl } from "./api";

const START_TASK_TIMEOUT_MS = 20000;
const POLL_TIMEOUT_MS = 60000;
const MAX_POLL_TIME_MS = 10 * 60 * 1000;
const MAX_POLL_ATTEMPTS = 200;
const DEFAULT_POLL_INTERVAL_MS = 3000;
const CHAT_TIMEOUT_MS = 60000;
const ALLOWED_TYPES = new Set(["short", "rating"]);
const ACTIVE_TASK_STATUSES = new Set(["queued", "processing", "pending", "running", "started"]);
const FAILED_TASK_STATUSES = new Set(["failed", "error"]);

function withTimeout(timeoutMs) {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
  return { controller, timeoutId };
}

function parseApiError(status, data) {
  const detail = data?.traceback ? `\n\n${data.traceback}` : "";
  if (data?.error) return `${data.error}${detail}`;
  if (status === 401) return "請先登入後再使用 AI 問卷功能。";
  if (status === 413) return "檔案太大，請上傳 25MB 以下的 PPT/PDF。";
  if (status === 429) return "AI API 額度暫時不足，請稍後再試。";
  if (status === 503) return "AI 服務尚未完成設定，請檢查後端環境變數與套件。";
  if (status >= 500) return "AI 服務發生錯誤，請查看 Server Log。";
  return "請求失敗，請檢查檔案格式後再試。";
}

async function readJsonResponse(response, { allowErrorBody = false } = {}) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok && !allowErrorBody) {
    throw new Error(parseApiError(response.status, data));
  }
  return data;
}

async function fetchWithTimeout(url, options, timeoutMs) {
  const { controller, timeoutId } = withTimeout(timeoutMs);
  try {
    return await fetch(url, {
      ...options,
      signal: controller.signal,
    });
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error("伺服器回應逾時，請稍後再試或查看任務狀態。");
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

function sleep(ms) {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

function normalizeTaskStatus(task) {
  return String(task?.status || "").trim().toLowerCase();
}

function isCompletedTask(task) {
  return normalizeTaskStatus(task) === "completed";
}

function isFailedTask(task) {
  return FAILED_TASK_STATUSES.has(normalizeTaskStatus(task));
}

function isActiveTask(task) {
  const status = normalizeTaskStatus(task);
  return ACTIVE_TASK_STATUSES.has(status) || (Boolean(task?.task_id) && !status);
}

function buildTaskStatusUrl(task) {
  const statusUrl = task?.status_url || task?.statusUrl;
  if (statusUrl) return apiUrl(statusUrl);
  if (task?.task_id) return apiUrl(`/api/ai/ppt-survey/tasks/${encodeURIComponent(task.task_id)}`);
  return "";
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

export async function startSurveyGenerationTask({ file, config, token }) {
  if (!file) throw new Error("請先上傳 PPT 或 PDF 檔案。");
  if (!token) throw new Error("請先登入後再使用 AI 問卷功能。");

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

  const response = await fetchWithTimeout(apiUrl("/api/ai/ppt-survey/generate"), {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
    },
    body: formData,
  }, START_TASK_TIMEOUT_MS);

  const data = await readJsonResponse(response);
  if (data?.draft) {
    return { ...data, status: "completed", draft: toCompatibleSurveyPayload(data.draft) };
  }
  if (!data?.task_id) {
    throw new Error("後端沒有回傳 task_id，請查看 Server Log。");
  }

  return data;
}

export async function getSurveyGenerationTask({ task, taskId, statusUrl, token }) {
  if (!task && !taskId && !statusUrl) throw new Error("缺少 AI 任務 ID。");
  if (!token) throw new Error("請先登入後再使用 AI 問卷功能。");

  const taskUrl = statusUrl ? apiUrl(statusUrl) : buildTaskStatusUrl(task || { task_id: taskId });
  if (!taskUrl) throw new Error("缺少 AI 任務狀態查詢網址。");

  const response = await fetchWithTimeout(taskUrl, {
    method: "GET",
    headers: {
      Authorization: `Bearer ${token}`,
    },
  }, POLL_TIMEOUT_MS);

  const data = await readJsonResponse(response, { allowErrorBody: true });
  if (!response.ok) {
    throw new Error(parseApiError(response.status, data));
  }
  return data;
}

export async function generateSurveyFromPpt({ file, config, token, onProgress }) {
  const firstTask = await startSurveyGenerationTask({ file, config, token });

  if (isCompletedTask(firstTask) && firstTask.draft) {
    return toCompatibleSurveyPayload(firstTask.draft);
  }
  if (!isActiveTask(firstTask)) {
    throw new Error(firstTask.error || `AI 任務狀態異常：${firstTask.status || "unknown"}`);
  }

  const startedAt = Date.now();
  const intervalMs = Math.max(
    DEFAULT_POLL_INTERVAL_MS,
    Number(firstTask.poll_interval_seconds || 0) * 1000 || DEFAULT_POLL_INTERVAL_MS,
  );
  const statusUrl = firstTask.status_url || buildTaskStatusUrl(firstTask);
  let pollAttempts = 0;

  onProgress?.(firstTask);

  while (pollAttempts < MAX_POLL_ATTEMPTS && Date.now() - startedAt < MAX_POLL_TIME_MS) {
    await sleep(intervalMs);
    pollAttempts += 1;

    const latestTask = await getSurveyGenerationTask({
      task: firstTask,
      statusUrl,
      token,
    });
    onProgress?.(latestTask);

    if (isCompletedTask(latestTask)) {
      if (!latestTask.draft) throw new Error("AI 任務已完成，但後端沒有回傳問卷草稿。");
      return toCompatibleSurveyPayload(latestTask.draft);
    }
    if (isFailedTask(latestTask)) {
      throw new Error(latestTask.error || "AI 問卷產生失敗，請查看 Server Log。");
    }
    if (!isActiveTask(latestTask)) {
      throw new Error(latestTask.error || `AI 任務狀態異常：${latestTask.status || "unknown"}`);
    }
  }

  throw new Error("AI 問卷產生超過等待時間。任務可能仍在背景執行，請稍後重試。");
}

export async function reviseSurveyWithAi({ draft, message, token }) {
  if (!token) throw new Error("請先登入後再使用 AI 編修問卷功能。");
  if (!message?.trim()) throw new Error("請輸入要調整的內容。");

  const response = await fetchWithTimeout(apiUrl("/api/ai/ppt-survey/chat"), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      draft: toCompatibleSurveyPayload(draft),
      message: message.trim(),
    }),
  }, CHAT_TIMEOUT_MS);

  const data = await readJsonResponse(response);
  return toCompatibleSurveyPayload(data.draft);
}
