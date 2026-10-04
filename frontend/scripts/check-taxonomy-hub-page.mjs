// 分類架構頁（TaxonomyHubPage）主題分組測試：
//   node scripts/check-taxonomy-hub-page.mjs
// auto_ 開頭的主題一旦有 published 版本，就已經是正式主題：
//   - 列在「正式主題」，不在「AI 自動主題」
//   - 按鈕是「管理分類架構」，不是「決定去向」
// 還沒發布的 AI 主題仍列在「AI 自動主題」、按鈕「決定去向」；已併入的主題不在這兩組。
import { JSDOM } from "jsdom";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(path.join(root, "package.json"));

const dom = new JSDOM("<!doctype html><div id=root></div>", { url: "http://localhost/admin/ai/taxonomy", pretendToBeVisual: true });
for (const key of ["window", "document", "navigator", "localStorage", "HTMLElement", "Node", "Event", "MouseEvent"]) {
  Object.defineProperty(globalThis, key, { value: dom.window[key], configurable: true, writable: true });
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
globalThis.getComputedStyle = dom.window.getComputedStyle.bind(dom.window);

const published = (n) => ({ version_id: n, version_number: 1, status: "published" });
const topic = (key, extra = {}) => ({
  topic_key: key, title: `Title ${key}`, is_auto_topic: key.startsWith("auto_"), merged_into: null,
  published_version: null, latest_draft_version: null, status: "no_taxonomy", ...extra,
});
const TOPICS = [
  topic("career", { published_version: published(1) }),                       // 一般正式主題
  topic("auto_pub", { published_version: published(2) }),                     // 已發布的 auto_ 主題 -> 正式主題
  topic("auto_draft", { latest_draft_version: { version_id: 3, version_number: 1 }, status: "draft" }), // 未發布 -> 自動主題
  topic("auto_merged", { merged_into: "career" }),                            // 已併入 -> 都不在
];

globalThis.fetch = async (url) => {
  const { pathname } = new URL(String(url), "http://localhost");
  const json = (body, status = 200) => ({ ok: status < 400, status, json: async () => body });
  if (pathname === "/api/admin/ai/taxonomy-topics") return json({ topics: TOPICS });
  if (pathname === "/api/admin/ai/overview") return json({ topics: {} });
  return json({});
};

const { createServer } = require("vite");
const vite = await createServer({
  root, logLevel: "error", server: { middlewareMode: true }, appType: "custom",
  resolve: { alias: [{ find: /^.*hooks\/AuthContext$/, replacement: path.join(root, "scripts/fixtures/AdminAuthStub.jsx") }] },
});
const { default: TaxonomyHubPage } = await vite.ssrLoadModule("/src/pages/admin/ai-admin/TaxonomyHubPage.jsx");
const React = require("react");
const { createRoot } = require("react-dom/client");
const { MemoryRouter } = require("react-router-dom");
const { act } = React;

const container = document.getElementById("root");
const rootNode = createRoot(container);
await act(async () => { rootNode.render(React.createElement(MemoryRouter, null, React.createElement(TaxonomyHubPage))); });
for (let i = 0; i < 4; i += 1) await act(async () => { await new Promise((r) => setTimeout(r, 25)); });

let failures = 0;
const check = (label, ok) => { console.log(`[${ok ? "PASS" : "FAIL"}] ${label}`); if (!ok) failures += 1; };

const sectionOf = (headingPrefix) => {
  const h2 = [...document.querySelectorAll("h2")].find((el) => el.textContent.startsWith(headingPrefix));
  return h2 ? h2.parentElement : null;
};
const official = sectionOf("正式主題");
const auto = sectionOf("AI 自動主題");
const rowFor = (scope, key) => [...(scope?.querySelectorAll("li.admin-row") || [])].find((li) => li.textContent.includes(`Title ${key}`));
const buttonText = (row) => row?.querySelector("button")?.textContent.trim();

check("「正式主題」標題的數量含已發布的 auto_ 主題（2）", official?.querySelector("h2").textContent.includes("（2）"));
check("已發布的 auto_ 主題列在「正式主題」", !!rowFor(official, "auto_pub") && !!rowFor(official, "career"));
check("已發布的 auto_ 主題按鈕是「管理分類架構」（不是「決定去向」）", buttonText(rowFor(official, "auto_pub")) === "管理分類架構");
check("已發布的 auto_ 主題不在「AI 自動主題」", !rowFor(auto, "auto_pub"));
check("「AI 自動主題」只剩未發布的（1）", auto?.querySelector("h2").textContent.includes("（1）") && !!rowFor(auto, "auto_draft"));
check("未發布的 AI 主題按鈕仍是「決定去向」", buttonText(rowFor(auto, "auto_draft")) === "決定去向");
check("已併入的主題不在正式、也不在自動", !rowFor(official, "auto_merged") && !rowFor(auto, "auto_merged"));
check("一般正式主題按鈕不變（管理分類架構）", buttonText(rowFor(official, "career")) === "管理分類架構");

await act(async () => { rootNode.unmount(); });
await vite.close();
console.log(failures ? `\n${failures} 項失敗` : "\n全部通過");
process.exit(failures ? 1 : 0);
