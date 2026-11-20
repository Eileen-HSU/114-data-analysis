import { apiUrl } from "./api";

// Google Identity Services（Google 登入按鈕）。Client ID 由後端 /api/auth/google/config 提供，只設定一處。
const GSI_SRC = "https://accounts.google.com/gsi/client";
let scriptPromise = null;
let configPromise = null;

export function loadGoogleConfig() {
  if (!configPromise) {
    configPromise = fetch(apiUrl("/api/auth/google/config"))
      .then((res) => (res.ok ? res.json() : { enabled: false }))
      .catch(() => ({ enabled: false }));
  }
  return configPromise;
}

export function loadGoogleScript() {
  if (typeof window === "undefined") return Promise.reject(new Error("no window"));
  if (window.google?.accounts?.id) return Promise.resolve(window.google);
  if (!scriptPromise) {
    scriptPromise = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = GSI_SRC;
      script.async = true;
      script.defer = true;
      script.onload = () => resolve(window.google);
      script.onerror = () => { scriptPromise = null; reject(new Error("Google 登入元件載入失敗")); };
      document.head.appendChild(script);
    });
  }
  return scriptPromise;
}
