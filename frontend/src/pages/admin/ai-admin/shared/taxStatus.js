import { readLanguagePreference } from "../../../../context/languagePreference";

export const getLang = () => readLanguagePreference() === "en" ? "en" : "zh";

export const t = (zh, en) => (getLang() === "zh" ? zh : en);

const statusTextEn = (value) => ({ validated: "Meets publish criteria", needs_validation: "Needs validation", published: "Published", not_published: "Not published" }[value] || value);
const statusTextZh = (value) => ({ validated: "符合發布標準", needs_validation: "需審核", published: "已發布", not_published: "未發布" }[value] || value);
export const statusText = (value) => (getLang() === "zh" ? statusTextZh(value) : statusTextEn(value));

const taxStatusTextEn = (value) => ({ no_taxonomy: "No taxonomy yet", draft: "Draft", in_review: "In review", published: "Published", draft_and_published: "Published + draft in progress" }[value] || value);
const taxStatusTextZh = (value) => ({ no_taxonomy: "尚無 taxonomy", draft: "草稿", in_review: "審核中", published: "已發布", draft_and_published: "已發布（另有草稿審核中）" }[value] || value);
export const taxStatusText = (value) => (getLang() === "zh" ? taxStatusTextZh(value) : taxStatusTextEn(value));

export const TAX_EDITABLE_STATUSES = ["draft", "in_review"];

const reviewFlagReasonTextEn = (reason) => ({
  low_confidence: "Low confidence",
  invalid_confidence: "Missing or invalid confidence score",
  methodology_not_found: "Returned sub-category not in current taxonomy",
  classification_incomplete: "Incomplete classification result",
  new_category_proposed: "AI proposed a new category",
}[reason] || reason);
const reviewFlagReasonTextZh = (reason) => ({
  low_confidence: "信心分數偏低",
  invalid_confidence: "信心分數缺失或格式異常",
  methodology_not_found: "AI 回傳的子類別不在目前分類清單中",
  classification_incomplete: "分類結果不完整",
  new_category_proposed: "AI 提出新類別（不在目前清單中）",
}[reason] || reason);
export const reviewFlagReasonText = (reason) => (getLang() === "zh" ? reviewFlagReasonTextZh(reason) : reviewFlagReasonTextEn(reason));
