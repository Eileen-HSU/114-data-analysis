const RENDER_BACKEND_URL =
  "https://one14-data-analysis-uhkg.onrender.com";

const NORTHFLANK_BACKEND_URL =
  "https://site--data-analysisntub--d6tvmpswrhlp.code.run";

function getDefaultApiBaseUrl() {
  if (typeof window === "undefined") return "";

  const { hostname } = window.location;

  if (hostname === "one14-data-analysis-frontend.onrender.com") {
    return RENDER_BACKEND_URL;
  }

  if (hostname === "site--frontend--d6tvmpswrhlp.code.run") {
    return NORTHFLANK_BACKEND_URL;
  }

  return "";
}

export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || getDefaultApiBaseUrl();

export function apiUrl(path) {
  return `${API_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;
}