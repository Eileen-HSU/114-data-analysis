import { apiUrl } from "../../../../lib/api";

export const api = async (path, token, options = {}) => {
  const response = await fetch(apiUrl(path), { ...options, headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}`, ...(options.headers || {}) } });
  const body = await response.json();
  if (!response.ok) {
    // 【新增】把 status 跟完整 body 一起掛在丟出的 Error 上，不改變既有
    // 呼叫端只讀 e.message 的行為（error.message 維持原樣）。這是給
    // Human Review 併發衝突（409，body 裡帶 reviewing_admin_id /
    // reviewing_admin_name）這類「錯誤本身帶有額外資訊」的呼叫端用，
    // 不是另外造一套 fetch helper。
    const error = new Error(body.error || "Request failed");
    error.status = response.status;
    error.body = body;
    throw error;
  }
  return body;
};
