// 殘留／舊候選區塊 + Topic「解除合併」的前端測試：
//   node scripts/check-residual-and-unmerge-ui.mjs
// 在 jsdom 渲染真正的 NewCategoryPage / TaxonomyPanel，mock 後端 API，驗證：
//   NewCategoryPage
//     1. 殘留候選集中在獨立區塊，不混進正常候選卡片
//     2. 區塊永遠顯示排除的強提示；merged 主題的殘留有「重試併入」，legacy 沒有
//     3. 排除：確認對話框含強提示；取消就不送；確認才送 acknowledged=true
//     4. 重試併入：確認對話框；呼叫既有 merge-into
//   TaxonomyPanel
//     5. 已併入主題有「解除合併」；確認對話框寫明「只影響之後的新資料…不會自動移回」
//     6. 取消不送；確認後呼叫 unmerge，橫幅消失、顯示留在目標主題的筆數
import { JSDOM } from "jsdom";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(path.join(root, "package.json"));

const dom = new JSDOM("<!doctype html><div id=root></div>", { url: "http://localhost/admin", pretendToBeVisual: true });
for (const key of ["window", "document", "navigator", "localStorage", "HTMLElement", "Node", "Event", "MouseEvent"]) {
  Object.defineProperty(globalThis, key, { value: dom.window[key], configurable: true, writable: true });
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
globalThis.getComputedStyle = dom.window.getComputedStyle.bind(dom.window);

const IMPACT = "排除後，這些回答將不再納入分析、彙整、匯出與報告。此操作可透過 reopen 復原。";
const UNMERGE_NOTE = "解除後只影響之後的新資料；已重新分類到目標主題的既有回答不會自動移回。";

// ── 可控的 confirm 與 mock 後端 ──
const confirms = [];
let confirmAnswer = true;
dom.window.confirm = (message) => { confirms.push(String(message)); return confirmAnswer; };

let mock = null;
const calls = [];
globalThis.fetch = async (url, options = {}) => {
  const { pathname } = new URL(String(url), "http://localhost");
  const method = (options.method || "GET").toUpperCase();
  const body = options.body ? JSON.parse(options.body) : null;
  calls.push({ method, pathname, body });
  const json = (payload, status = 200) => ({ ok: status < 400, status, json: async () => payload });
  const handled = mock.handle?.({ method, pathname, body, json });
  if (handled) return handled;
  if (pathname === "/api/admin/ai/new-categories") return json(mock.listing());
  if (pathname === "/api/admin/ai/taxonomy-topics") return json({ topics: mock.topics() });
  if (/^\/api\/admin\/ai\/topics\/[^/]+\/taxonomy\/\d+$/.test(pathname)) {
    return json({ taxonomy_version: { version_id: Number(pathname.split("/").pop()), version_number: 1, status: "draft", categories: [] } });
  }
  if (/^\/api\/admin\/ai\/topics\/[^/]+\/answers/.test(pathname)) return json({ sources: [], groups: [], total: 0 });
  return json({});
};
const posts = () => calls.filter((c) => c.method === "POST");

const { createServer } = require("vite");
const vite = await createServer({
  root, logLevel: "error", server: { middlewareMode: true }, appType: "custom",
  resolve: { alias: [
    { find: /^.*components\/feature\/Navbar$/, replacement: path.join(root, "scripts/fixtures/NavbarStub.jsx") },
    { find: /^.*hooks\/AuthContext$/, replacement: path.join(root, "scripts/fixtures/AdminAuthStub.jsx") },
  ] },
});
const { default: NewCategoryPage } = await vite.ssrLoadModule("/src/pages/admin/ai-admin/NewCategoryPage.jsx");
const { default: TaxonomyPanel } = await vite.ssrLoadModule("/src/pages/admin/ai-admin/TopicDetail/TaxonomyPanel.jsx");
const { api: apiClient } = await vite.ssrLoadModule("/src/pages/admin/ai-admin/shared/apiClient.js");
const React = require("react");
const { createRoot } = require("react-dom/client");
const { MemoryRouter, Routes, Route } = require("react-router-dom");
const { act } = React;

const settle = async (times = 3) => { for (let i = 0; i < times; i += 1) await act(async () => { await new Promise((r) => setTimeout(r, 25)); }); };
const text = () => document.body.textContent;
const buttonIn = (scope, label) => [...scope.querySelectorAll("button")].find((b) => b.textContent.trim() === label);
const click = async (el) => { await act(async () => { el.dispatchEvent(new window.MouseEvent("click", { bubbles: true })); }); await settle(); };
let failures = 0;
const check = (label, ok) => { console.log(`[${ok ? "PASS" : "FAIL"}] ${label}`); if (!ok) failures += 1; };

async function mount(element, config) {
  mock = config;
  calls.length = 0; confirms.length = 0; confirmAnswer = true;
  await apiClient("/reset-cache", "t", { method: "POST" }); // 清掉 apiClient 的 GET 快取（POST 會清）
  calls.length = 0;
  const container = document.createElement("div");
  document.body.appendChild(container);
  const rootNode = createRoot(container);
  await act(async () => { rootNode.render(element); });
  await settle(4);
  return async () => { await act(async () => { rootNode.unmount(); }); container.remove(); };
}

const group = (extra) => ({
  topic_key: "norm_topic", topic_title: "Title norm_topic", main_category: "Main A", sub_category: "工時過長", count: 2,
  classification_ids: [1, 2], examples: ["加班太多"], reasons: [], taxonomy_version_ids: [1], version_mismatch: false, ...extra,
});
const mergedGroup = group({ topic_key: "auto_left", topic_title: "Title auto_left", sub_category: "殘留類別", count: 3,
  residual_reasons: ["topic_merged"], merged_into: "norm_topic" });
const legacyGroup = group({ topic_key: null, topic_title: null, main_category: "Legacy Main", sub_category: "舊類別", count: 1,
  residual_reasons: ["legacy", "no_topic"], merged_into: null });
const topicsList = () => [
  { topic_key: "norm_topic", title: "Title norm_topic", is_auto_topic: false, merged_into: null, published_version: { version_id: 9, version_number: 1 } },
  { topic_key: "auto_left", title: "Title auto_left", is_auto_topic: true, merged_into: "norm_topic", published_version: null },
];
const page = () => React.createElement(MemoryRouter, null, React.createElement(NewCategoryPage));

console.log("========== 1. 殘留候選：獨立區塊 ==========");
{
  const state = { residual: [mergedGroup, legacyGroup] };
  const unmount = await mount(page(), {
    listing: () => ({ items: [group()], total: 1, residual_items: state.residual, residual_total: state.residual.length }),
    topics: topicsList,
  });
  const normalCards = document.querySelectorAll("article.review-card:not(.admin-residual-card)");
  const section = document.querySelector("section.admin-residual");
  const residualCards = section ? [...section.querySelectorAll("article.admin-residual-card")] : [];
  check("正常候選卡片只有 1 張（殘留沒有混進來）", normalCards.length === 1 && !normalCards[0].textContent.includes("殘留類別"));
  check("殘留集中在獨立區塊（2 組）、標題標出組數", residualCards.length === 2 && section.textContent.includes("殘留／舊候選（2 組）"));
  check("區塊永遠顯示排除的強提示（不必點進去才看到）", section.textContent.includes(IMPACT));
  check("說明這些不計入「新類別候選」", section.textContent.includes("不計入「新類別候選」數量"));
  const [mergedCard, legacyCard] = residualCards;
  check("merged 主題殘留：顯示原因（含目標主題名）、有「重試併入」與「排除」",
    mergedCard.textContent.includes("主題已併入「Title norm_topic」") && !!buttonIn(mergedCard, "重試併入") && !!buttonIn(mergedCard, "排除"));
  check("legacy 殘留：顯示原因、沒有重試併入、仍可排除",
    legacyCard.textContent.includes("舊版資料、找不到所屬主題") && !buttonIn(legacyCard, "重試併入") && !!buttonIn(legacyCard, "排除"));
  check("沒有所屬主題的群組標示「（沒有所屬主題）」", legacyCard.textContent.includes("（沒有所屬主題）"));

  console.log("\n========== 3. 排除：強提示 ==========");
  confirmAnswer = false;
  await click(buttonIn(legacyCard, "排除"));
  check("取消對話框 -> 不送任何寫入請求", posts().length === 0);
  check("對話框含強提示、群組名稱與筆數",
    confirms.length === 1 && confirms[0].includes(IMPACT) && confirms[0].includes("Legacy Main / 舊類別") && confirms[0].includes("1 筆"));

  confirmAnswer = true;
  mock.handle = ({ method, pathname, json }) => {
    if (method === "POST" && pathname === "/api/admin/ai/new-categories/exclude") {
      state.residual = state.residual.filter((g) => g.sub_category !== "舊類別");
      return json({ batch_id: "b1", success_ids: [5], success_count: 1, skipped: [], skipped_count: 0, failed: [], failed_count: 0 });
    }
    return null;
  };
  await click(buttonIn(document.querySelectorAll("article.admin-residual-card")[1], "排除"));
  const exclude = posts().find((c) => c.pathname === "/api/admin/ai/new-categories/exclude");
  check("確認後才送出，且帶 acknowledged=true 與群組資訊",
    !!exclude && exclude.body.acknowledged === true && exclude.body.topic_key === null
    && exclude.body.main_category === "Legacy Main" && exclude.body.sub_category === "舊類別");
  check("排除後重新載入，該殘留卡片消失、另一組還在",
    document.querySelectorAll("article.admin-residual-card").length === 1 && !text().includes("Legacy Main / 舊類別"));
  check("成功訊息顯示在頁面頂端（卡片消失後仍看得到）", text().includes("已排除 1 筆"));

  console.log("\n========== 4. 重試併入 ==========");
  confirmAnswer = false; confirms.length = 0;
  await click(buttonIn(document.querySelector("article.admin-residual-card"), "重試併入"));
  check("取消 -> 不送 merge-into", !posts().some((c) => c.pathname.endsWith("/merge-into")));
  check("確認對話框說明會處理整個主題、已人工確認的會跳過", confirms[0].includes("整個主題") && confirms[0].includes("已人工確認的回答會跳過")
    && confirms[0].includes("Title auto_left") && confirms[0].includes("Title norm_topic"));
  confirmAnswer = true;
  mock.handle = ({ method, pathname, json }) => {
    if (method === "POST" && pathname === "/api/admin/ai/topics/auto_left/merge-into") {
      state.residual = [];
      return json({ moved_count: 3, skipped_count: 0, skipped: [] });
    }
    return null;
  };
  await click(buttonIn(document.querySelector("article.admin-residual-card"), "重試併入"));
  const retry = posts().find((c) => c.pathname === "/api/admin/ai/topics/auto_left/merge-into");
  check("確認後呼叫既有 merge-into，目標 = 原合併目標", !!retry && retry.body.target_topic_key === "norm_topic");
  check("完成後殘留區塊消失、顯示結果", !document.querySelector("section.admin-residual") && text().includes("已重試併入：重新分類 3 筆"));
  await unmount();
}

console.log("\n========== 重試併入遇到資料庫忙碌：訊息要講清楚 ==========");
{
  const unmount = await mount(page(), {
    listing: () => ({ items: [], total: 0, residual_items: [mergedGroup], residual_total: 1 }),
    topics: topicsList,
    handle: ({ method, pathname, json }) => (method === "POST" && pathname === "/api/admin/ai/topics/auto_left/merge-into"
      ? json({ moved_count: 1, skipped_count: 3, aborted: true, unprocessed_count: 5,
               skipped: [{ code: "DATABASE_BUSY", message: "資料庫忙碌" }, { code: "DATABASE_BUSY", message: "資料庫忙碌" },
                         { code: "CONCURRENT_MODIFICATION", message: "x" }] })
      : null),
  });
  await click(buttonIn(document.querySelector("article.admin-residual-card"), "重試併入"));
  check("中止時說明已暫停、還有幾筆沒處理、可稍後再按重試（已處理的不會重做）",
    text().includes("資料庫忙碌，已先暫停，還有 5 筆沒處理") && text().includes("已處理的不會重做"));
  check("同時被其他操作更動的也有說明（可能有人同時處理）", text().includes("1 筆在處理期間被其他操作更動") && text().includes("可能有人同時在處理同一個主題"));
  check("仍顯示搬了幾筆、略過幾筆", text().includes("重新分類 1 筆，3 筆略過"));
  await unmount();
}

console.log("\n========== 錯誤：後端擋下時卡片留著並顯示原因 ==========");
{
  const unmount = await mount(page(), {
    listing: () => ({ items: [], total: 0, residual_items: [legacyGroup], residual_total: 1 }),
    topics: topicsList,
    handle: ({ method, pathname, json }) => (method === "POST" && pathname.endsWith("/exclude")
      ? json({ code: "ACK_REQUIRED", message: "後端拒絕" }, 400) : null),
  });
  await click(buttonIn(document.querySelector("article.admin-residual-card"), "排除"));
  check("失敗：卡片還在、顯示後端訊息", !!document.querySelector("article.admin-residual-card") && text().includes("後端拒絕"));
  await unmount();
}

console.log("\n========== 2b. 沒有殘留時不顯示區塊 ==========");
{
  const unmount = await mount(page(), { listing: () => ({ items: [group()], total: 1, residual_items: [], residual_total: 0 }), topics: topicsList });
  check("沒有殘留候選 -> 沒有殘留區塊", !document.querySelector("section.admin-residual") && !text().includes("殘留／舊候選"));
  await unmount();
}
{
  const unmount = await mount(page(), { listing: () => ({ items: [group()], total: 1 }), topics: topicsList });
  check("舊版 API 回應（沒有 residual 欄位）也不會壞", document.querySelectorAll("article.review-card").length === 1);
  await unmount();
}

console.log("\n========== 5. TaxonomyPanel：解除合併 ==========");
const panel = (key) => React.createElement(MemoryRouter, { initialEntries: [`/admin/ai/topics/${key}`] },
  React.createElement(Routes, null, React.createElement(Route, { path: "/admin/ai/topics/:topicKey", element: React.createElement(TaxonomyPanel) })));
{
  const state = { merged: true };
  const topicsNow = () => [
    { topic_key: "auto_x", title: "Title auto_x", is_auto_topic: true, merged_into: state.merged ? "career" : null,
      published_version: null, latest_draft_version: state.merged ? null : { version_id: 7, version_number: 1, status: "draft" } },
    { topic_key: "career", title: "Title career", is_auto_topic: false, merged_into: null, published_version: { version_id: 9, version_number: 1 } },
  ];
  const unmount = await mount(panel("auto_x"), {
    topics: topicsNow,
    handle: ({ method, pathname, json }) => {
      if (method === "POST" && pathname === "/api/admin/ai/topics/auto_x/unmerge") {
        state.merged = false;
        return json({ topic_key: "auto_x", merged_into: null, previous_merged_into: "career", restored_version_ids: [7],
          restore_skipped_reason: null, answers_staying_on_target: 3, answers_left_on_source: 0, message: "ok" });
      }
      return null;
    },
  });
  const banner = document.querySelector(".topic-merged-banner");
  check("已併入的主題：橫幅有「解除合併」", !!banner && !!buttonIn(banner, "解除合併"));
  check("橫幅直接寫明只影響之後的新資料、不會自動移回", banner.textContent.includes(UNMERGE_NOTE));

  confirmAnswer = false;
  await click(buttonIn(banner, "解除合併"));
  check("確認對話框明確寫出「只影響之後的新資料；已重新分類…不會自動移回」", confirms.length === 1 && confirms[0].includes(UNMERGE_NOTE));
  check("取消 -> 不送 unmerge、橫幅還在", !posts().some((c) => c.pathname.endsWith("/unmerge")) && !!document.querySelector(".topic-merged-banner"));

  confirmAnswer = true;
  await click(buttonIn(document.querySelector(".topic-merged-banner"), "解除合併"));
  check("確認後呼叫 POST /topics/auto_x/unmerge", posts().some((c) => c.pathname === "/api/admin/ai/topics/auto_x/unmerge"));
  check("解除後橫幅與「解除合併」按鈕都消失（成功訊息文字不算）",
    !document.querySelector(".topic-merged-banner") && !buttonIn(document.body, "解除合併") && !buttonIn(document.body, "處理中…"));
  check("顯示留在目標主題的筆數與已恢復草稿", text().includes("3 筆回答不會自動移回") && text().includes("已恢復 1 個草稿版本"));
  check("恢復的草稿版本被載入顯示（taxonomy/7）", calls.some((c) => c.method === "GET" && c.pathname === "/api/admin/ai/topics/auto_x/taxonomy/7"));
  await unmount();
}
{
  const unmount = await mount(panel("career"), {
    topics: () => [{ topic_key: "career", title: "Title career", is_auto_topic: false, merged_into: null,
      published_version: { version_id: 9, version_number: 1 }, latest_draft_version: null }],
  });
  check("沒被合併的主題沒有「解除合併」", !document.querySelector(".topic-merged-banner") && !buttonIn(document.body, "解除合併"));
  await unmount();
}

await vite.close();
console.log(failures ? `\n${failures} 項失敗` : "\n全部通過");
process.exit(failures ? 1 : 0);
