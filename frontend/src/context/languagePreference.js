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
