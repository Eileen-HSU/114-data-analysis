import assert from "node:assert/strict";
import { resolveLanguagePreference } from "../src/context/languagePreference.js";

// Login and delayed profile loading must preserve a guest's explicit selection.
for (const account of [undefined, "zh-TW", "en"]) {
  assert.equal(resolveLanguagePreference("en", account), "en");
  assert.equal(resolveLanguagePreference("zh-TW", account), "zh-TW");
}
// A new device can still use the account preference, with a safe default.
assert.equal(resolveLanguagePreference(null, "en"), "en");
assert.equal(resolveLanguagePreference(null, "zh-TW"), "zh-TW");
assert.equal(resolveLanguagePreference(null, undefined), "zh-TW");
assert.equal(resolveLanguagePreference("invalid", "en"), "en");
assert.equal(resolveLanguagePreference("invalid", "invalid"), "zh-TW");
// Refresh/logout preserve the selected language; manual switching takes priority.
assert.equal(resolveLanguagePreference("en", undefined), "en");
assert.equal(resolveLanguagePreference("zh-TW", "en"), "zh-TW");
console.log("Language preference regression checks passed.");
