import { translateInterfaceText, useLanguage } from "../../context/LanguageContext";

const countSuffixes = new Set(["人作答", "人", "人回覆", "份回答", "題", "題評分題", "題非評分題", "份有效回答", "個類別。", "筆回答，點此查看全部 →", "分", "題已填"]);
const countPrefixes = new Set(["分類完成，共", "共", "還有", "平均", "查看全部"]);

// Render only fixed UI copy, including labels inside protected analysis tables.
export default function InterfaceText({ children }) {
  const { language } = useLanguage();
  const text = translateInterfaceText(children, language);
  if (language === "en" && countSuffixes.has(children)) return ` ${text}`;
  if (language === "en" && countPrefixes.has(children)) return `${text} `;
  return text;
}
