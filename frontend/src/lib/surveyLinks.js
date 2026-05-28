export function buildSurveyFillPath(code) {
  const rawCode = typeof code === "object" && code !== null
    ? code.short_code || code.shortCode || code.access_code || code.code
    : code;
  const normalizedCode = String(rawCode || "").trim().toUpperCase();
  return normalizedCode ? `/${encodeURIComponent(normalizedCode)}` : "/survey/fill";
}

export function buildSurveyFillUrl(code, origin = window.location.origin) {
  return `${origin}${buildSurveyFillPath(code)}`;
}
