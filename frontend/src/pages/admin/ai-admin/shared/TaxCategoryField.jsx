import { useState } from "react";
import { t } from "./taxStatus";

// 離開輸入框時自動儲存，並在欄位旁顯示儲存狀態（儲存中／已儲存／失敗）。
// onSave 要回傳 Promise；失敗時 reject。
export default function TaxCategoryField({ cat, field, label, multiline, onSave }) {
  const Tag = multiline ? "textarea" : "input";
  const [state, setState] = useState("idle");
  const status = {
    saving: <small className="tax-field-status">{t("儲存中…", "Saving…")}</small>,
    saved: <small className="tax-field-status tax-field-status--ok">{t("已儲存 ✓", "Saved ✓")}</small>,
    failed: <small className="tax-field-status tax-field-status--err">{t("儲存失敗", "Save failed")}</small>,
  }[state];
  return (
    <label className="tax-field">
      <span>{label} {status}</span>
      <Tag
        defaultValue={cat[field] || ""}
        rows={multiline ? 2 : undefined}
        onBlur={async (e) => {
          const value = e.target.value;
          if (value === (cat[field] || "")) return;
          setState("saving");
          try {
            await onSave(cat.category_id, { [field]: value || null });
            setState("saved");
          } catch {
            setState("failed");
          }
        }}
      />
    </label>
  );
}
