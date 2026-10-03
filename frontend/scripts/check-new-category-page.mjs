// 新類別候選頁（NewCategoryPage）的主題判定測試：
//   node scripts/check-new-category-page.mjs
// 在 jsdom 裡渲染真正的元件、mock 後端 API，驗證：
//   1. 未發布的 auto_ 主題 -> 顯示主題決策流程、不顯示候選卡片
//   2. 已發布的 auto_ 主題 -> 顯示一般新類別候選卡片、不顯示主題決策流程
//   3. 已發布的 auto_ 主題可以成為「併入既有正式主題」的目標
//   4. topics 載入中不會誤顯示「未決定」流程（也不顯示卡片）
//   5. topics 載入完成但找不到該主題時，才退回前綴判斷
import { JSDOM } from "jsdom";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(path.join(root, "package.json"));

const dom = new JSDOM("<!doctype html><div id=root></div>", { url: "http://localhost/admin/ai/taxonomy?view=candidates", pretendToBeVisual: true });
for (const key of ["window", "document", "navigator", "localStorage", "HTMLElement", "Node", "Event", "MouseEvent"]) {
  Object.defineProperty(globalThis, key, { value: dom.window[key], configurable: true, writable: true });
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
globalThis.getComputedStyle = dom.window.getComputedStyle.bind(dom.window);

// ── mock 後端：每個情境自己設定候選與主題清單；topicsGate 可以讓 taxonomy-topics 卡住 ──
let scenario = null;
globalThis.fetch = async (url) => {
  const { pathname } = new URL(String(url), "http://localhost");
  const json = (body, status = 200) => ({ ok: status < 400, status, json: async () => body });
  if (pathname === "/api/admin/ai/new-categories") return json({ total: scenario.items.length, items: scenario.items });
  if (pathname === "/api/admin/ai/taxonomy-topics") {
    if (scenario.topicsGate) await scenario.topicsGate;
    return json({ topics: scenario.topics });
  }
  return json({ message: `unexpected ${pathname}` }, 404);
};

const candidate = (topicKey, title = topicKey) => ({
  topic_key: topicKey, topic_title: title, main_category: "Main", sub_category: `新類別-${topicKey}`, count: 2,
  classification_ids: [1, 2], examples: ["範例"], reasons: [], taxonomy_version_ids: [1], version_mismatch: false,
});
const topic = (topicKey, extra = {}) => ({
  topic_key: topicKey, title: `Title ${topicKey}`, is_auto_topic: topicKey.startsWith("auto_"),
  merged_into: null, published_version: null, latest_draft_version: { version_id: 1, version_number: 1 }, ...extra,
});
const published = { version_id: 9, version_number: 1, status: "published" };

// ── 用 vite 載入真正的頁面（Navbar / AuthContext 換成 stub）──
const { createServer } = require("vite");
const vite = await createServer({
  root, logLevel: "error", server: { middlewareMode: true }, appType: "custom",
  resolve: { alias: [
    { find: /^.*components\/feature\/Navbar$/, replacement: path.join(root, "scripts/fixtures/NavbarStub.jsx") },
    { find: /^.*hooks\/AuthContext$/, replacement: path.join(root, "scripts/fixtures/AdminAuthStub.jsx") },
  ] },
});
const { default: NewCategoryPage } = await vite.ssrLoadModule("/src/pages/admin/ai-admin/NewCategoryPage.jsx");
const React = require("react");
const { createRoot } = require("react-dom/client");
const { MemoryRouter } = require("react-router-dom");
const { act } = React;

const settle = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 25)); });
const ui = () => ({
  decision: document.querySelectorAll(".admin-undecided").length > 0,
  cards: document.querySelectorAll("article.review-card").length,
  loading: document.body.textContent.includes("正在確認主題狀態"),
  mergeSelectValues: [...document.querySelectorAll(".admin-undecided select option")].map((o) => o.value).filter(Boolean),
});

let failures = 0;
const check = (label, ok) => { console.log(`[${ok ? "PASS" : "FAIL"}] ${label}`); if (!ok) failures += 1; };

async function mount(config, { afterMount } = {}) {
  scenario = config;
  const container = document.createElement("div");
  document.body.appendChild(container);
  const rootNode = createRoot(container);
  const seenDecision = [];
  await act(async () => { rootNode.render(React.createElement(MemoryRouter, null, React.createElement(NewCategoryPage))); });
  await afterMount?.({ seen: () => seenDecision.push(ui().decision) });
  await settle(); await settle();
  const result = ui();
  await act(async () => { rootNode.unmount(); });
  container.remove();
  return { result, seenDecision };
}

console.log("========== 1. 未發布 auto_ 主題：仍是主題決策流程 ==========");
{
  const { result } = await mount({
    items: [candidate("auto_draft1")],
    topics: [topic("auto_draft1"), topic("career", { published_version: published })],
  });
  check("顯示主題決策流程（A 併入 / B 保留）", result.decision === true);
  check("不顯示候選卡片", result.cards === 0);
}

console.log("\n========== 2. 已發布 auto_ 主題：一般新類別候選卡片 ==========");
{
  const { result } = await mount({
    items: [candidate("auto_pub1")],
    topics: [topic("auto_pub1", { published_version: published })],
  });
  check("不再顯示主題決策流程", result.decision === false);
  check("顯示一般新類別候選卡片（可採用 / 合併）", result.cards === 1);
}

console.log("\n========== 2b. 其他維持原行為 ==========");
{
  const { result } = await mount({
    items: [candidate("auto_merged1")],
    topics: [topic("auto_merged1", { merged_into: "career" }), topic("career", { published_version: published })],
  });
  check("已被併入其他主題的 auto_ 主題：不是未決定（顯示卡片）", result.decision === false && result.cards === 1);
}
{
  const { result } = await mount({
    items: [candidate("career")],
    topics: [topic("career", { published_version: published })],
  });
  check("一般正式主題：顯示卡片", result.decision === false && result.cards === 1);
}

console.log("\n========== 3. 已發布 auto_ 主題可成為 merge target ==========");
{
  const { result } = await mount({
    items: [candidate("auto_draft1")],
    topics: [
      topic("auto_draft1"),                                               // 來源（自己）
      topic("career", { published_version: published }),                  // 正式主題 -> 可選
      topic("auto_pub1", { published_version: published }),               // 已發布 auto_ -> 可選
      topic("auto_unpub2"),                                               // 未發布 auto_ -> 不可選
      topic("auto_pub_merged", { published_version: published, merged_into: "career" }), // 已被併入 -> 不可選
      topic("draft_only"),                                                // 沒有 published -> 不可選
    ],
  });
  check("選項 = 正式主題 + 已發布 auto_ 主題",
    JSON.stringify([...result.mergeSelectValues].sort()) === JSON.stringify(["auto_pub1", "career"]));
  check("不含自己、未發布、已被併入、沒有 published 的主題",
    !["auto_draft1", "auto_unpub2", "auto_pub_merged", "draft_only"].some((key) => result.mergeSelectValues.includes(key)));
}

console.log("\n========== 4. topics 載入中不誤顯示未決定流程 ==========");
for (const [label, extra] of [["已發布 auto_ 主題", { published_version: published }], ["未發布 auto_ 主題", {}]]) {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const during = { decision: null, cards: null, loading: null };
  const { result, seenDecision } = await mount({
    items: [candidate("auto_x1")], topics: [topic("auto_x1", extra)], topicsGate: gate,
  }, {
    afterMount: async ({ seen }) => {
      await settle(); await settle();           // candidates 已載入，topics 仍卡住
      Object.assign(during, ui());
      seen();
      release();
      await settle();
      seen();
    },
  });
  check(`${label}：載入中顯示「確認主題狀態」`, during.loading === true);
  check(`${label}：載入中不顯示未決定流程、也不顯示卡片`, during.decision === false && during.cards === 0);
  const expectDecision = Object.keys(extra).length === 0;
  check(`${label}：載入完成後依真實狀態顯示（${expectDecision ? "未決定流程" : "候選卡片"}）`,
    result.decision === expectDecision && result.cards === (expectDecision ? 0 : 1) && result.loading === false);
  check(`${label}：整個過程沒有先閃出錯誤流程`, expectDecision ? seenDecision[0] === false : seenDecision.every((v) => v === false));
}

console.log("\n========== 5. topics 載入完成但找不到該主題：才退回前綴判斷 ==========");
{
  const { result } = await mount({ items: [candidate("auto_ghost")], topics: [] });
  check("auto_ 前綴且查無此主題 -> 視為未決定", result.decision === true && result.cards === 0);
}
{
  const { result } = await mount({ items: [candidate("ghost_topic")], topics: [] });
  check("非 auto_ 且查無此主題 -> 一般候選卡片", result.decision === false && result.cards === 1);
}

await vite.close();
console.log(failures ? `\n${failures} 項失敗` : "\n全部通過");
process.exit(failures ? 1 : 0);
