// 結果訊息 / 歡迎訊息的語言（三種來源不混用）：node scripts/check-language-output.mjs
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
const sentRequests = [];
const mockFetch = async (input, init = {}) => {
  sentRequests.push({ url: String(input), acceptLanguage: new Headers(init.headers).get("Accept-Language") });
  return { ok: true, status: 200, json: async () => ({}) };
};
dom.window.fetch = mockFetch;
globalThis.fetch = mockFetch;

const { createServer } = require("vite");
const vite = await createServer({ root, logLevel: "error", server: { middlewareMode: true }, appType: "custom" });
const page = await vite.ssrLoadModule("/src/pages/workspace/page.jsx");
const { LanguageProvider } = await vite.ssrLoadModule("/src/context/LanguageContext.jsx");
const React = require("react");
const { createRoot } = require("react-dom/client");
const { MemoryRouter } = require("react-router-dom");
const { act } = React;
const { MessageContent, WELCOME_MSG } = page;

const CHINESE_ROWS = [{
  main_category: "學習", sub_category: "課程需求", respondent_text: "受試者1：想上 Excel 課", aggregated_reasoning: "理由", aggregated_summary: "摘要",
  synthesis_status: "ok", synthesis_error: null, respondent_count: 1, secondary_count: 0, is_new_category: false,
}];
const message = (meta, rows = CHINESE_ROWS) => ({
  id: "a-1", role: "assistant", chatId: null,
  content: `[[CLASSIFICATION_TABLE]]${JSON.stringify({ rows, meta, rating_stats: [] })}`,
});

const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 40)); });
async function render(uiLang, msg) {
  dom.window.localStorage.setItem("dataanalysis_language", uiLang);
  const container = document.createElement("div");
  document.body.appendChild(container);
  const rootNode = createRoot(container);
  await act(async () => {
    rootNode.render(React.createElement(MemoryRouter, null,
      React.createElement(LanguageProvider, null, React.createElement(MessageContent, { message: msg, showToast: () => {} }))));
  });
  await settle(); await settle();   // 讓全域翻譯器（MutationObserver）跑完
  const text = container.textContent;
  const result = { text, html: container.innerHTML, container };
  return { ...result, cleanup: async () => { await act(async () => { rootNode.unmount(); }); container.remove(); } };
}

// 在 LanguageProvider 底下渲染任意內容（用來直接驗證全域翻譯器本身的行為）
async function renderNode(uiLang, node) {
  dom.window.localStorage.setItem("dataanalysis_language", uiLang);
  const container = document.createElement("div");
  document.body.appendChild(container);
  const rootNode = createRoot(container);
  await act(async () => {
    rootNode.render(React.createElement(MemoryRouter, null, React.createElement(LanguageProvider, null, node)));
  });
  await settle(); await settle();
  return { container, cleanup: async () => { await act(async () => { rootNode.unmount(); }); container.remove(); } };
}

let failures = 0;
const check = (label, ok) => { console.log(`[${ok ? "PASS" : "FAIL"}] ${label}`); if (!ok) failures += 1; };

const DONE_ZH = "分類完成，共1個類別。";
const DONE_EN = "Classification complete. Total: 1 categories.";

console.log("========== Accept-Language 只有 installLanguageAwareFetch 一套注入機制 ==========");
{
  const probe = await renderNode("en", React.createElement("div", null, "x"));
  sentRequests.length = 0;
  await dom.window.fetch("/api/anything");
  check("LanguageProvider 載入後，window.fetch 自動帶 Accept-Language（= 介面語言 en）",
    sentRequests.length === 1 && sentRequests[0].acceptLanguage === "en");
  await probe.cleanup();
  const probeZh = await renderNode("zh-TW", React.createElement("div", null, "x"));
  sentRequests.length = 0;
  await dom.window.fetch("/api/anything", { headers: { Authorization: "Bearer t" } });
  check("介面中文：自動帶 zh-TW，呼叫端自己的 header 不受影響", sentRequests[0].acceptLanguage === "zh-TW");
  await probeZh.cleanup();
  const workspaceSource = fs.readFileSync(path.join(root, "src/pages/workspace/page.jsx"), "utf-8");
  check("workspace/page.jsx 沒有自己再注入一套 Accept-Language（不留兩套 header 機制）", !/["']Accept-Language["']/.test(workspaceSource));
  const authHeaderBody = workspaceSource.match(/function getAuthHeader\(\) \{[\s\S]*?\n\}/)?.[0] || "";
  check("getAuthHeader 只處理 Authorization", authHeaderBody.includes("Authorization") && !authHeaderBody.includes("Language"));
}

console.log("\n========== 全域翻譯器：[data-output-lang] 不會被二次翻譯（對照組）==========");
{
  const control = await renderNode("en", React.createElement("div", null,
    React.createElement("p", { id: "plain" }, "新增工作區"),
    React.createElement("p", { id: "decided", "data-output-lang": "zh-TW" }, "新增工作區")));
  check("對照組：沒有標記的固定中文，介面英文時被全域翻譯器翻成英文（證明翻譯器確實在運作）",
    control.container.querySelector("#plain").textContent === "New workspace");
  check("同一句中文加上 data-output-lang -> 維持中文，不被二次翻譯",
    control.container.querySelector("#decided").textContent === "新增工作區");
  await control.cleanup();
  const zhUi = await renderNode("zh-TW", React.createElement("div", null,
    React.createElement("p", { id: "decided", "data-output-lang": "en" }, "New workspace")));
  check("反向：介面中文時，標記為 en 的英文不會被翻回中文", zhUi.container.querySelector("#decided").textContent === "New workspace");
  await zhUi.cleanup();
}

console.log("\n========== 歡迎訊息 = ui_lang ==========");
{
  const en = await render("en", WELCOME_MSG);
  check("介面英文 -> 英文歡迎訊息", en.text.startsWith("Hello!") && !en.text.includes("您好"));
  check("歡迎訊息標記為已決定語言（全域翻譯不再改它）", !!en.container.querySelector('[data-output-lang="en"]'));
  await en.cleanup();
  const zh = await render("zh-TW", WELCOME_MSG);
  check("介面中文 -> 中文歡迎訊息", zh.text.startsWith("您好！") && !zh.text.includes("Hello"));
  await zh.cleanup();
}

console.log("\n========== 系統固定句 = instruction_lang；標題 = ui_lang ==========");
{
  const a = await render("en", message({ language: { ui_lang: "en", instruction_lang: "zh-TW", data_lang: "zh-TW" } }));
  check("介面英文 + 指令中文：系統句維持中文（不被全域翻譯改成英文）", a.text.includes(DONE_ZH) && !a.text.includes("Classification complete"));
  check("介面英文：表格標題是英文（ui_lang）", a.text.includes("Main category") && !a.text.includes("大類別"));
  check("系統句標記 data-output-lang=zh-TW", !!a.container.querySelector('[data-output-lang="zh-TW"]'));
  check("資料內容（類別名稱 / 受試者回答）原封不動", a.text.includes("課程需求") && a.text.includes("想上 Excel 課"));
  await a.cleanup();

  const b = await render("zh-TW", message({ language: { ui_lang: "zh-TW", instruction_lang: "en", data_lang: "en" } }));
  check("介面中文 + 指令英文：系統句是英文", b.text.includes(DONE_EN) && !b.text.includes("分類完成"));
  check("介面中文：表格標題是中文（ui_lang）", b.text.includes("大類別") && !b.text.includes("Main category"));
  await b.cleanup();

  const c = await render("en", message({ language: { ui_lang: "en", instruction_lang: "en", data_lang: "en" } }));
  check("介面英文 + 指令英文：系統句英文、標題英文", c.text.includes(DONE_EN) && c.text.includes("Main category"));
  await c.cleanup();

  const d = await render("zh-TW", message({ language: { ui_lang: "zh-TW", instruction_lang: "zh-TW", data_lang: null } }));
  check("介面中文 + 指令中文：系統句中文、標題中文", d.text.includes(DONE_ZH) && d.text.includes("大類別"));
  await d.cleanup();
}

console.log("\n========== 其他固定句也跟 instruction_lang ==========");
{
  const empty = await render("en", message({ language: { ui_lang: "en", instruction_lang: "zh-TW" } }, []));
  check("沒有分類結果的說明句：指令中文 -> 中文（介面英文也一樣）", empty.text.includes("這批資料沒有產生任何分類結果。"));
  await empty.cleanup();
  const emptyEn = await render("zh-TW", message({ language: { ui_lang: "zh-TW", instruction_lang: "en" } }, []));
  check("沒有分類結果的說明句：指令英文 -> 英文（介面中文也一樣）", emptyEn.text.includes("No classification results were generated for this data."));
  await emptyEn.cleanup();
  const prov = await render("en", message({ provisional_taxonomy: true, language: { ui_lang: "en", instruction_lang: "zh-TW" } }));
  check("暫定分類架構的說明句跟 instruction_lang", prov.text.includes("類別由 AI 依內容自動歸納（暫定）"));
  await prov.cleanup();
}

console.log("\n========== 表格裡系統組的「受試者N：」「（次要分類）」依介面語言 ==========");
{
  const rowsWithLabels = [{ ...CHINESE_ROWS[0], respondent_text: "受試者1：I want more Excel courses\n受試者2：Please add English classes（次要分類）" }];
  const en = await render("en", message({ language: { ui_lang: "en", instruction_lang: "en", data_lang: "en" } }, rowsWithLabels));
  check("介面英文：顯示 Respondent 1: / Respondent 2:，沒有「受試者」", en.text.includes("Respondent 1: I want more Excel courses") && en.text.includes("Respondent 2: Please add English classes") && !en.text.includes("受試者"));
  check("介面英文：（次要分類）顯示成 (secondary category)", en.text.includes("(secondary category)") && !en.text.includes("（次要分類）"));
  check("介面英文：標籤仍有 respondent-label 樣式（粗體標籤沒壞）", en.container.querySelectorAll(".respondent-label").length === 2
    && en.container.querySelector(".respondent-label").textContent === "Respondent 1: ");
  check("回答原文原封不動", en.text.includes("I want more Excel courses") && en.text.includes("Please add English classes"));
  await en.cleanup();
  const zh = await render("zh-TW", message({ language: { ui_lang: "zh-TW", instruction_lang: "zh-TW", data_lang: null } }, rowsWithLabels));
  check("介面中文：維持「受試者1：」「（次要分類）」（原本行為）", zh.text.includes("受試者1：") && zh.text.includes("（次要分類）") && !zh.text.includes("Respondent"));
  check("介面中文：標籤樣式不變", zh.container.querySelectorAll(".respondent-label").length === 2 && zh.container.querySelector(".respondent-label").textContent === "受試者1：");
  await zh.cleanup();
  const oldMsg = await render("en", message({}, rowsWithLabels));
  check("舊訊息（沒有 language）+ 介面英文：同樣顯示英文標籤（標籤屬於 ui_lang）", oldMsg.text.includes("Respondent 1:") && !oldMsg.text.includes("受試者1："));
  await oldMsg.cleanup();
}

console.log("\n========== 匯出元件：預設檔名 / 標題跟介面語言 ==========");
{
  const { default: ExportActions } = await vite.ssrLoadModule("/src/pages/workspace/ExportActions.jsx");
  // 匯出元件要有登入的使用者（user.token）才會送出請求；用真正的 AuthProvider，登入資料來自 localStorage
  const { AuthProvider } = await vite.ssrLoadModule("/src/hooks/AuthContext.jsx");
  const exportBodies = [];
  const realFetch = dom.window.fetch;
  const spyFetch = async (input, init = {}) => {
    if (String(input).includes("/api/exports")) { exportBodies.push(JSON.parse(init.body)); return { ok: false, status: 400, json: async () => ({ error: "x" }) }; }
    return realFetch(input, init);
  };
  async function clickExport(uiLang, sourceFilename) {
    dom.window.localStorage.setItem("dataanalysis_auth", JSON.stringify({ token: "t", user_id: 1 }));
    exportBodies.length = 0;
    const node = React.createElement(AuthProvider, null,
      React.createElement(ExportActions, { rows: [{ main_category: "A" }], ratingStats: [], chatId: 5, sourceFilename }));
    const view = await renderNode(uiLang, node);
    dom.window.fetch = spyFetch; globalThis.fetch = spyFetch;
    await act(async () => { view.container.querySelector("button.assistant-export-btn").dispatchEvent(new window.MouseEvent("click", { bubbles: true })); });
    await settle();
    dom.window.fetch = realFetch; globalThis.fetch = realFetch;
    await view.cleanup();
    return exportBodies[0];
  }
  const en = await clickExport("en", undefined);
  check("介面英文、沒有原始檔名：filename 與 title 是英文（title 會變成 Excel 分頁名稱）",
    !!en && /^Classification_results_\d{4}-/.test(en.title) && en.filename.endsWith("_Classification_results.xlsx") && !/[\u4e00-\u9fff]/.test(en.filename + en.title));
  const zh = await clickExport("zh-TW", undefined);
  check("介面中文、沒有原始檔名：維持原本的「分類結果」", !!zh && zh.title.startsWith("分類結果_") && zh.filename.endsWith("_分類結果.xlsx"));
  const withSource = await clickExport("en", "員工意見.xlsx");
  check("有使用者的原始檔名：原樣使用（使用者的資料不翻譯），只有後綴跟介面語言",
    !!withSource && withSource.title === "員工意見" && withSource.filename === "員工意見_Classification_results.xlsx");
}

console.log("\n========== 舊訊息（沒有 language）維持原本行為 ==========");
{
  const oldEn = await render("en", message({}));
  check("舊訊息 + 介面英文：系統句跟介面語言（英文）", oldEn.text.includes(DONE_EN));
  await oldEn.cleanup();
  const oldZh = await render("zh-TW", message({}));
  check("舊訊息 + 介面中文：系統句中文", oldZh.text.includes(DONE_ZH));
  await oldZh.cleanup();
  const nullInstr = await render("en", message({ language: { ui_lang: "en", instruction_lang: null, data_lang: null } }));
  check("language 存在但 instruction_lang 為 null -> 退回介面語言", nullInstr.text.includes(DONE_EN));
  await nullInstr.cleanup();
}

await vite.close();
console.log(failures ? `\n${failures} 項失敗` : "\n全部通過");
process.exit(failures ? 1 : 0);
