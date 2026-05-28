import { apiUrl } from "./api";

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

export async function buildExternalSurveyShortUrl(code, origin = window.location.origin) {
  const longUrl = buildSurveyFillUrl(code, origin);

  try {
    const response = await fetch(apiUrl("/api/short-links"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: longUrl }),
    });
    const data = await response.json().catch(() => ({}));
    if (response.ok && data.short_url) return data.short_url;
  } catch (error) {
    console.warn("Short URL creation failed:", error);
  }

  return longUrl;
}
