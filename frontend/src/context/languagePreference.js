export function resolveLanguagePreference(storedLanguage) {
  // Only an explicit selection on this device controls the interface language.
  const supported = ["zh-TW", "en"];
  if (supported.includes(storedLanguage)) return storedLanguage;
  return "zh-TW";
}
