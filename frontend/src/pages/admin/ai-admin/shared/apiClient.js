import { apiUrl } from "../../../../lib/api";

// ── 讀取快取：抓過的資料先拿來立刻顯示，同時在背景重新抓（畫面不用每次都等）。
// 只快取 GET，任何寫入（POST/PUT/DELETE）成功後清空，避免顯示到改之前的資料。
const responseCache = new Map();
const MAX_CACHE_ENTRIES = 100;

export const peekCache = (path) => responseCache.get(path);

// 預先載入（例如滑鼠移到主題卡片上），失敗就算了
export const prefetch = (path, token) => {
  if (responseCache.has(path)) return;
  api(path, token).catch(() => {});
};

export const api = async (path, token, options = {}) => {
  const method = (options.method || "GET").toUpperCase();
  const response = await fetch(apiUrl(path), { ...options, headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}`, ...(options.headers || {}) } });
  // 非 JSON 回應（例如 proxy 回的 HTML 錯誤頁）也要給出具體錯誤，不讓
  // response.json() 直接丟出難懂的 SyntaxError。
  const body = await response.json().catch(() => ({ message: `HTTP ${response.status}` }));
  if (!response.ok) {
    // 把 status 跟完整 body 一起掛在丟出的 Error 上（body.code 是後端的
    // machine-readable 錯誤碼，body.message 是使用者可讀訊息）；既有呼叫端
    // 只讀 e.message 的行為不變。
    const error = new Error(body.message || body.error || "Request failed");
    error.status = response.status;
    error.body = body;
    throw error;
  }
  if (method === "GET") {
    if (responseCache.size >= MAX_CACHE_ENTRIES) responseCache.delete(responseCache.keys().next().value);
    responseCache.set(path, body);
  } else {
    responseCache.clear();
  }
  return body;
};

// 下載二進位檔（報告匯出）。錯誤時後端回 JSON（code / message）。
export const apiDownload = async (path, token, filename) => {
  const response = await fetch(apiUrl(path), { headers: { Authorization: `Bearer ${token}` } });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ message: `HTTP ${response.status}` }));
    const error = new Error(body.message || body.error || "Download failed");
    error.status = response.status;
    error.body = body;
    throw error;
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
};
