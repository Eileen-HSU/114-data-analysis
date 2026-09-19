export default function TaxCategoryField({ cat, field, label, multiline, onSave }) {
  const Tag = multiline ? "textarea" : "input";
  return (
    <label className="tax-field">
      {label}
      <Tag
        defaultValue={cat[field] || ""}
        rows={multiline ? 2 : undefined}
        onBlur={(e) => {
          const value = e.target.value;
          if (value !== (cat[field] || "")) onSave(cat.category_id, { [field]: value || null });
        }}
      />
    </label>
  );
}
