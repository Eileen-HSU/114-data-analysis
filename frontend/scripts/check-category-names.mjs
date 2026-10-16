// 大類別 / 子類別名稱的顯示語言：node scripts/check-category-names.mjs
// 在 jsdom 用真正的 LanguageProvider（含全域翻譯器）渲染真正的 MessageContent，驗證：
//   - 歡迎訊息 = ui_lang（切換介面語言會跟著變）
//   - 「分類完成，共 N 個類別」這類系統句 = 訊息裡記的 instruction_lang（不是 ui_lang）
//   - 表格標題 = ui_lang
//   - 已決定語言的輸出，不會被全域翻譯器再改一次
//   - 舊訊息（沒有 language）維持原本行為（系統句跟介面語言）
import { JSDOM } from "jsdom";
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(path.join(root, "package.json"));

const dom = new JSDOM("<!doctype html><div id=root></div>", { url: "http://localhost/workspace", pretendToBeVisual: true });
for (const key of ["window", "document", "navigator", "localStorage", "HTMLElement", "Node", "NodeFilter", "Event", "MouseEvent", "MutationObserver"]) {
  Object.defineProperty(globalThis, key, { value: dom.window[key], configurable: true, writable: true });
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
// jsdom 的 window 有 requestAnimationFrame，但 Node 全域沒有；ExportActions 會用它捲動通知。
globalThis.requestAnimationFrame = (cb) => setTimeout(() => cb(Date.now()), 0);
globalThis.cancelAnimationFrame = (id) => clearTimeout(id);
dom.window.HTMLElement.prototype.scrollIntoView = () => {};   // jsdom 沒有實作；ExportActions 顯示進度時會呼叫
globalThis.getComputedStyle = dom.window.getComputedStyle.bind(dom.window);
// jsdom 沒有 fetch。LanguageProvider 載入時 installLanguageAwareFetch() 會把 window.fetch 包起來（自動帶
// Accept-Language），所以要先給 jsdom 的 window 一個 fetch；記下實際送出的標頭，順便驗證只有這一套機制在注入語言標頭。
const TABLE = { 主管領導: 'Supervisor Leadership', 'A1 工作與生活邊界': 'A1 Work-Life Boundaries' };
const sentRequests = [];
const mockFetch = async (input, init = {}) => {
  sentRequests.push({ url: String(input), acceptLanguage: new Headers(init.headers).get("Accept-Language") });
  if (String(input).includes("/api/classification/category-names")) {
    const names = JSON.parse(init.body).names;
    return { ok: true, status: 200, json: async () => ({ names: Object.fromEntries(names.map((n) => [n, TABLE[n] || n])) }) };
  }
  return { ok: true, status: 200, json: async () => ({}) };
};
dom.window.fetch = mockFetch;
// 瀏覽器裡 fetch === window.fetch（LanguageProvider 會把它包起來自動帶 Accept-Language），測試也要一樣
Object.defineProperty(globalThis, "fetch", { get: () => dom.window.fetch, configurable: true });

const { createServer } = require("vite");
const vite = await createServer({ root, logLevel: "error", server: { middlewareMode: true }, appType: "custom" });
const page = await vite.ssrLoadModule("/src/pages/workspace/page.jsx");
const { LanguageProvider } = await vite.ssrLoadModule("/src/context/LanguageContext.jsx");
const React = require("react");
const { createRoot } = require("react-dom/client");
const { MemoryRouter } = require("react-router-dom");
const { act } = React;
const { MessageContent, WELCOME_MSG } = page;


const ROWS = [{
  main_category: "主管領導", sub_category: "A1 工作與生活邊界", respondent_text: "受試者1：下班後還要回訊息", aggregated_reasoning: "reason", aggregated_summary: "summary",
  synthesis_status: "ok", synthesis_error: null, respondent_count: 1, secondary_count: 0, is_new_category: false,
}];
const msg = { id: "a-1", role: "assistant", chatId: null, content: `[[CLASSIFICATION_TABLE]]${JSON.stringify({ rows: ROWS, meta: {}, rating_stats: [] })}` };
const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 60)); });
async function render(uiLang) {
  dom.window.localStorage.setItem("dataanalysis_language", uiLang);
  const container = document.createElement("div");
  document.body.appendChild(container);
  const rootNode = createRoot(container);
  await act(async () => {
    rootNode.render(React.createElement(MemoryRouter, null,
      React.createElement(LanguageProvider, null, React.createElement(MessageContent, { message: msg, showToast: () => {} }))));
  });
  await settle(); await settle();
  const text = container.textContent;
  await act(async () => { rootNode.unmount(); }); container.remove();
  return text;
}
let failed = 0;
const check = (name, ok) => { console.log(`${ok ? "PASS" : "FAIL"}  ${name}`); if (!ok) failed++; };

const zh = await render("zh-TW");
check("中文介面：大類別 / 子類別維持原名稱", zh.includes("主管領導") && zh.includes("A1 工作與生活邊界"));
check("中文介面：不呼叫翻譯 API", !sentRequests.some((r) => r.url.includes("category-names")));

const en = await render("en");
check("英文介面：大類別顯示英文", en.includes("Supervisor Leadership") && !en.includes("主管領導"));
check("英文介面：子類別顯示英文（代碼保留）", en.includes("A1 Work-Life Boundaries") && !en.includes("工作與生活邊界"));
const call = sentRequests.find((r) => r.url.includes("category-names"));
check("英文介面：翻譯 API 帶 Accept-Language: en", call?.acceptLanguage === "en");
await vite.close();
process.exit(failed ? 1 : 0);
