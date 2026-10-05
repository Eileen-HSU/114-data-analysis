// 語言判斷（前端）測試：node scripts/check-language.mjs
// 與後端共用同一份案例 backend/tests/fixtures/language_cases.json，確保 JS 與 Python 兩套實作行為一致。
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  DEFAULT_LANG, buildLanguageMeta, detectTextLang, localizeRespondentText, normalizeLang, resolveInstructionLang, welcomeText,
} from "../src/context/languagePreference.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const cases = JSON.parse(fs.readFileSync(path.join(here, "../../backend/tests/fixtures/language_cases.json"), "utf-8"));

let failures = 0;
const check = (label, ok) => { console.log(`[${ok ? "PASS" : "FAIL"}] ${label}`); if (!ok) failures += 1; };

const badNormalize = cases.normalize_cases.filter((c) => normalizeLang(c.value) !== c.expected).map((c) => c.value);
check(`normalizeLang：${cases.normalize_cases.length} 個共用案例（失敗：${JSON.stringify(badNormalize)}）`, badNormalize.length === 0);

const badText = cases.text_cases.filter((c) => detectTextLang(c.text) !== c.expected).map((c) => `${c.name} -> ${detectTextLang(c.text)}`);
check(`detectTextLang：${cases.text_cases.length} 個共用案例（與後端同一份；失敗：${JSON.stringify(badText)}）`, badText.length === 0);

check("日文含漢字不會被當成中文（不是「有 CJK 就是中文」）", detectTextLang("日本語の分析") === null);
check("法文不會被當成英文", detectTextLang("Bonjour, je voudrais analyser les résultats") === null);
check("中英混合分不出主要語言 -> null", detectTextLang("分析 Q1 survey") === null);

check("resolveInstructionLang：指令語言優先於介面語言",
  resolveInstructionLang("Please summarize", "zh-TW") === "en" && resolveInstructionLang("請摘要", "en") === "zh-TW");
check("resolveInstructionLang：只有檔案、沒有文字指令 -> ui_lang",
  resolveInstructionLang("", "en") === "en" && resolveInstructionLang(undefined, "zh-TW") === "zh-TW" && resolveInstructionLang("   ", "en") === "en");
check("resolveInstructionLang：判斷不出來（123 / ok / 混合 / 其他語言）-> ui_lang",
  ["123", "ok", "分析 Q1 survey", "ありがとうございます"].every((t) => resolveInstructionLang(t, "en") === "en"));
check("resolveInstructionLang：ui_lang 也不合法 -> 預設 zh-TW", resolveInstructionLang("", "fr") === DEFAULT_LANG);

check("buildLanguageMeta：三種來源分開記", JSON.stringify(buildLanguageMeta({ uiLang: "en", instructionLang: "zh", dataLang: null }))
  === JSON.stringify({ ui_lang: "en", instruction_lang: "zh-TW", data_lang: null }));
check("welcomeText 依 ui_lang", welcomeText("en").startsWith("Hello!") && welcomeText("zh-TW").startsWith("您好！") && welcomeText("fr").startsWith("您好！"));

const badRespondent = [];
for (const c of cases.respondent_text_cases) {
  if (localizeRespondentText(c.input, "en") !== c.en) badRespondent.push(`${c.name} (en)`);
  if (localizeRespondentText(c.input, "zh-TW") !== c["zh-TW"]) badRespondent.push(`${c.name} (zh-TW)`);
}
check(`localizeRespondentText：${cases.respondent_text_cases.length} 個共用案例（en / zh-TW；與後端匯出同一份；失敗：${JSON.stringify(badRespondent)}）`, badRespondent.length === 0);
check("localizeRespondentText：非字串原樣、不合法語言視為繁中", localizeRespondentText(null, "en") === null && localizeRespondentText("受試者1：a", "fr") === "受試者1：a");

console.log(failures ? `\n${failures} 項失敗` : "\n全部通過");
process.exit(failures ? 1 : 0);
