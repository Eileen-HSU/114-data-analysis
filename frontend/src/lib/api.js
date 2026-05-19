export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || "https://one14-data-analysis-uhkg.onrender.com";

export function apiUrl(path) {
  return `${API_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;
}