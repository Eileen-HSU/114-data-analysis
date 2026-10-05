export const LANGUAGE_STORAGE_KEY = "dataanalysis_language";

export function resolveLanguagePreference(storedLanguage) {
  // Only an explicit selection on this device controls the interface language.
  const supported = ["zh-TW", "en"];
  if (supported.includes(storedLanguage)) return storedLanguage;
  return "zh-TW";
}

// Shared read-only initialization; authentication never supplies a fallback.
export function readLanguagePreference() {
  try {
    return resolveLanguagePreference(localStorage.getItem(LANGUAGE_STORAGE_KEY));
  } catch {
    return resolveLanguagePreference(null);
  }
}

// ════════════════════════════════════════════════════════════════
// 語言判斷與語言來源（三種來源各自獨立，不混用）。
//
//   ui_lang            介面語言。來源：Accept-Language / 使用者在這台裝置選的介面語言（readLanguagePreference）。
//                      用於按鈕、標題、歡迎訊息、匯出欄位名稱。
//   instruction_lang   使用者「這一次」文字指令的語言。來源：指令文字本身。
//                      用於「分類完成，共 N 個類別」這類系統固定回覆句。
//                      沒有文字指令（只上傳檔案、選問卷）時 fallback 到 ui_lang。
//   data_lang          實際資料內容的語言。後端依原始回答判斷，回應的 language.data_lang 帶回來（前端不判斷）。
//                      用於 AI 產生的摘要、理由、說明內容。
//
// 目前只支援 zh-TW 與 en。偵測只辨識「中文」與「英文」，不是「有 CJK 字元就是中文」：
// 日文、韓文、俄文、阿拉伯文、泰文、帶重音的拉丁文字（法 / 西 / 德文…）、中英混合分不出主要語言 -> null。
//
// 下面這一段與 backend/services/language_service.py 是同一套規則（指令語言要在送出前就決定），
// 兩邊共用 backend/tests/fixtures/language_cases.json。改規則時兩邊一起改。
// 這支檔案不 import 任何東西（node 可以直接跑測試），所以固定句（要用 LanguageContext 的翻譯函式）放在 page.jsx，
// 不放這裡，避免與 LanguageContext 循環引用。

export const SUPPORTED_LANGS = ["zh-TW", "en"];
export const DEFAULT_LANG = "zh-TW";

const ZH_SHARE_MIN = 0.6;
const EN_ZH_SHARE_MAX = 0.1;
const OTHER_LETTER_MAX = 0.1;
const EN_STOPWORD_MIN_WORDS = 4;

const URL_RE = /https?:\/\/\S+|www\.\S+|\S+@\S+\.\S+/gi;
const HAN_RE = /[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u{20000}-\u{2fa1f}]/gu;
const WORD_RE = /[A-Za-z]+(?:['\u2019][A-Za-z]+)*/g;
const OTHER_RE = /[\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u024f\u0370-\u03ff\u0400-\u04ff\u0590-\u06ff\u0900-\u0dff\u0e00-\u0eff\u1100-\u11ff\u3040-\u30ff\u31f0-\u31ff\u3130-\u318f\uac00-\ud7af]/g;
const EN_STOPWORDS = new Set(
  ("the a an and or but is are was were be to of in on for with this that it as at by from not no " +
    "i we you they my our your can could please how what why which do does did have has had will would " +
    "should there their than then so if more very too all any some").split(" "),
);

const count = (re, text) => (text.match(re) || []).length;

// 'zh' / 'zh-TW' / 'zh-Hant-TW' / 'zh-CN' / 'EN' / 'en-US' -> 'zh-TW' / 'en'；其他 -> null。簡體也歸為 zh-TW。
export function normalizeLang(value) {
  if (typeof value !== "string") return null;
  const tag = value.trim().toLowerCase().replace(/_/g, "-");
  if (tag === "zh" || tag.startsWith("zh-")) return "zh-TW";
  if (tag === "en" || tag.startsWith("en-")) return "en";
  return null;
}

// 一段文字是「中文」(zh-TW) 或「英文」(en)；無法可靠判斷 -> null。
export function detectTextLang(text) {
  if (typeof text !== "string") return null;
  const cleaned = text.replace(URL_RE, " ");
  const han = count(HAN_RE, cleaned);
  const other = count(OTHER_RE, cleaned);
  const words = cleaned.match(WORD_RE) || [];
  const latinLetters = words.reduce((sum, w) => sum + w.length, 0);
  const letters = han + other + latinLetters;
  if (letters < 2 || han + words.length === 0) return null;
  if (other / letters >= OTHER_LETTER_MAX) return null;
  const zhShare = han / (han + 2 * words.length);
  if (han >= 2 && zhShare >= ZH_SHARE_MIN) return "zh-TW";
  if (zhShare <= EN_ZH_SHARE_MAX && latinLetters >= 3) {
    if (words.length < 2 && !words.some((w) => /[a-z]/.test(w))) return null;
    if (words.length >= EN_STOPWORD_MIN_WORDS && !words.some((w) => EN_STOPWORDS.has(w.toLowerCase()))) return null;
    return "en";
  }
  return null;
}

// 這一次的回覆語言：指令文字的語言；沒有文字指令 / 判斷不出來 -> ui_lang。
export function resolveInstructionLang(instructionText, uiLang) {
  return detectTextLang(instructionText) || normalizeLang(uiLang) || DEFAULT_LANG;
}

// 放進結果 JSON 的語言資訊（三種來源分開記）。dataLang 由後端回應帶回來。
export function buildLanguageMeta({ uiLang, instructionLang, dataLang }) {
  return {
    ui_lang: normalizeLang(uiLang) || DEFAULT_LANG,
    instruction_lang: normalizeLang(instructionLang),
    data_lang: normalizeLang(dataLang),
  };
}

// 歡迎訊息：跟介面語言（ui_lang）。
const WELCOME = {
  "zh-TW": "您好！我是 DataAnalysis AI 助手。請上傳您的資料檔案（CSV、Excel 或 TXT），或直接輸入您的分析問題，我將為您提供深度洞察。",
  en: "Hello! I'm the DataAnalysis AI assistant. Upload your data file (CSV, Excel or TXT), or type your analysis question, and I'll help you find deeper insights.",
};
export const welcomeText = (uiLang) => WELCOME[normalizeLang(uiLang) || DEFAULT_LANG];

// 「問卷回覆內容」欄位裡系統組出來的固定字樣：每行開頭的「受試者N：」與結尾的「（次要分類）」。
// 英文介面時轉成 "Respondent N: " 與 " (secondary category)"；回答原文不動。
// 與 backend/services/export_labels.py 的 localize_respondent_text 同一套規則（匯出檔用後端那份），
// 兩邊共用 backend/tests/fixtures/language_cases.json 的 respondent_text_cases。
const RESPONDENT_LINE_RE = /^受試者(\d+)：/gm;
export function localizeRespondentText(text, lang) {
  if (typeof text !== "string" || normalizeLang(lang) !== "en") return text;
  return text.replace(RESPONDENT_LINE_RE, (_m, n) => `Respondent ${n}: `).split("（次要分類）").join(" (secondary category)");
}
