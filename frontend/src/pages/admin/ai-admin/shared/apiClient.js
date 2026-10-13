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

// ── 寫入保護：同一個寫入請求還在跑的時候，再按一次不會重送（回傳同一個結果）；
// 任何寫入進行中，管理畫面的按鈕會變灰、右下角顯示「處理中」（見 ai-admin.css 的 data-api-busy）。
const inflightWrites = new Map();
let pendingWrites = 0;
const BUSY_SAFETY_MS = 120000; // 請求卡住太久就不再讓畫面一直灰著
const syncBusyFlag = () => {
  try {
    if (pendingWrites > 0) document.documentElement.setAttribute("data-api-busy", "");
    else document.documentElement.removeAttribute("data-api-busy");
  } catch { /* 非瀏覽器環境（測試）忽略 */ }
};

export const api = (path, token, options = {}) => {
  const method = (options.method || "GET").toUpperCase();
  if (method === "GET") return request(path, token, options, method);
  const key = `${method} ${path} ${typeof options.body === "string" ? options.body : ""}`;
  if (inflightWrites.has(key)) return inflightWrites.get(key);
  pendingWrites += 1;
  syncBusyFlag();
  let released = false;
  const release = () => {
    if (released) return;
    released = true;
    pendingWrites = Math.max(0, pendingWrites - 1);
    inflightWrites.delete(key);
    syncBusyFlag();
  };
  const safety = setTimeout(release, BUSY_SAFETY_MS);
  const promise = request(path, token, options, method).finally(() => { clearTimeout(safety); release(); });
  inflightWrites.set(key, promise);
  return promise;
};

const request = async (path, token, options, method) => {
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
    // 寫入成功：通知畫面重新讀取上方的數字（例如分類審查頁的待審查）
    try { window.dispatchEvent(new Event("admin-data-changed")); } catch { /* 非瀏覽器環境忽略 */ }
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
