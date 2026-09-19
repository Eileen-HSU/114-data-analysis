import { apiUrl } from "../../../../lib/api";

export const api = async (path, token, options = {}) => {
  const response = await fetch(apiUrl(path), { ...options, headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}`, ...(options.headers || {}) } });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || "Request failed");
  return body;
};
