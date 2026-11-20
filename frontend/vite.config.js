import { fileURLToPath, URL } from "node:url";
import { defineConfig, loadEnv } from "vite";

const GOOGLE = "https://accounts.google.com";

function securityHeaders(env) {
  const api = (env.VITE_API_BASE_URL || "https://site--data-analysisntub--d6tvmpswrhlp.code.run").replace(/\/+$/, "");
  const csp = [
    "default-src 'self'",
    `script-src 'self' https://cdn.jsdelivr.net ${GOOGLE}/gsi/client`,
    `style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com ${GOOGLE}/gsi/style`,
    "font-src 'self' data: https://cdn.jsdelivr.net https://fonts.gstatic.com",
    "img-src 'self' data: blob: https://static.readdy.ai https://*.googleusercontent.com",
    `connect-src 'self' ${api} ${GOOGLE}/gsi/`,
    `frame-src ${GOOGLE}/gsi/`,
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'self'",
    `report-uri ${api}/api/csp-report`,
  ].join("; ");
  const enforce = env.VITE_CSP_ENFORCE === "1";
  return {
    [enforce ? "Content-Security-Policy" : "Content-Security-Policy-Report-Only"]: csp,
    "X-Content-Type-Options": "nosniff",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    // Google 登入彈窗需要 same-origin-allow-popups
    "Cross-Origin-Opener-Policy": "same-origin-allow-popups",
  };
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const apiBaseUrl = env.VITE_API_BASE_URL || "http://localhost:5001";

  return {
    preview: {
      allowedHosts: true,
      // 正式環境由 vite preview 提供網頁，安全標頭設在這裡（_headers 檔不會被 vite preview 讀取）。
      // CSP 先用 Report-Only：只回報、不阻擋。確認 Admin「系統管理 → 系統狀態」沒有誤報後，
      // 把 VITE_CSP_ENFORCE 設為 1（並把後端 CSP_MODE 設為 enforce）即改為正式阻擋。
      headers: securityHeaders(env),
    },
    resolve: {
      alias: {
        "@": fileURLToPath(new URL("./src", import.meta.url)),
      },
    },
    server: {
      proxy: {
        "/api": {
          target: apiBaseUrl,
          changeOrigin: true,
          secure: false,
        },
      },
    },
  };
});
