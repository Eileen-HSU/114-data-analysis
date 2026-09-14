// Fill this with the new backend origin if the deployment platform cannot set
// VITE_API_BASE_URL. Example: "https://your-new-backend.example.com"
const NEW_BACKEND_URL = "";
const LANGUAGE_STORAGE_KEY = "dataanalysis_language";

function currentLanguage() {
  if (typeof window === "undefined") return "zh-TW";
  return localStorage.getItem(LANGUAGE_STORAGE_KEY) || "zh-TW";
}

// Keep the API language independent from rendered text.  This only adds a
// request header; it never inspects or transforms request bodies.
export function installLanguageAwareFetch() {
  if (typeof window === "undefined" || window.__dataAnalysisLanguageFetch) return;
  const nativeFetch = window.fetch.bind(window);
  window.fetch = (input, init = {}) => {
    const headers = new Headers(init.headers || (input instanceof Request ? input.headers : undefined));
    if (!headers.has("Accept-Language")) headers.set("Accept-Language", currentLanguage());
    return nativeFetch(input, { ...init, headers });
  };
  window.__dataAnalysisLanguageFetch = true;
}

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
