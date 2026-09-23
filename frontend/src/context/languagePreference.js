export function resolveLanguagePreference(storedLanguage, accountLanguage) {
  // A selection made on this device takes precedence over a profile loaded at login.
  const supported = ["zh-TW", "en"];
  if (supported.includes(storedLanguage)) return storedLanguage;
  if (supported.includes(accountLanguage)) return accountLanguage;
  return "zh-TW";
}
