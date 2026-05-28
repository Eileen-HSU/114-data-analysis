export function buildSurveyFillPath(code) {
  const normalizedCode = String(code || "").trim().toUpperCase();
  return normalizedCode ? `/${encodeURIComponent(normalizedCode)}` : "/survey/fill";
}

export function buildSurveyFillUrl(code, origin = window.location.origin) {
  return `${origin}${buildSurveyFillPath(code)}`;
}
