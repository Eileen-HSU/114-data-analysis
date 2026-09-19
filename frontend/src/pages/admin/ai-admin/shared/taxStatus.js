export const getLang = () => {
  if (typeof window !== "undefined") {
    try {
      const stored = localStorage.getItem("dataanalysis_language");
      if (stored) return stored.startsWith("zh") ? "zh" : "en";
    } catch (e) {
      /* ignore localStorage errors */
    }
  }
  return (typeof navigator !== "undefined" && navigator.language && navigator.language.startsWith("zh")) ? "zh" : "en";
};

export const t = (zh, en) => (getLang() === "zh" ? zh : en);

const statusTextEn = (value) => ({ validated: "Meets publish criteria", needs_validation: "Needs validation", published: "Published", not_published: "Not published" }[value] || value);
const statusTextZh = (value) => ({ validated: "符合發布標準", needs_validation: "需審核", published: "已發布", not_published: "未發布" }[value] || value);
export const statusText = (value) => (getLang() === "zh" ? statusTextZh(value) : statusTextEn(value));

const taxStatusTextEn = (value) => ({ no_taxonomy: "No taxonomy yet", draft: "Draft", in_review: "In review", published: "Published", draft_and_published: "Published + draft in progress" }[value] || value);
const taxStatusTextZh = (value) => ({ no_taxonomy: "尚無 taxonomy", draft: "草稿", in_review: "審核中", published: "已發布", draft_and_published: "已發布（另有草稿審核中）" }[value] || value);
export const taxStatusText = (value) => (getLang() === "zh" ? taxStatusTextZh(value) : taxStatusTextEn(value));

export const TAX_EDITABLE_STATUSES = ["draft", "in_review"];
