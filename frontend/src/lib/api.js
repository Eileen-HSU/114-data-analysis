// Fill this with the new backend origin if the deployment platform cannot set
// VITE_API_BASE_URL. Example: "https://your-new-backend.example.com"
const NEW_BACKEND_URL = "";

function getDefaultApiBaseUrl() {
  if (typeof window === "undefined") return "";

  const { hostname } = window.location;

  if (hostname === "localhost" || hostname === "127.0.0.1") {
    return "";
  }

  return NEW_BACKEND_URL;
}

export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || getDefaultApiBaseUrl();

export function apiUrl(path) {
  return `${API_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;
}
