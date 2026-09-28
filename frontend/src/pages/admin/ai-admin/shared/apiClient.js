import { apiUrl } from "../../../../lib/api";

export const api = async (path, token, options = {}) => {
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
