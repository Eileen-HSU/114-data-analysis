import assert from "node:assert/strict";
import { LANGUAGE_STORAGE_KEY, readLanguagePreference, resolveLanguagePreference } from "../src/context/languagePreference.js";

// Login and delayed profile loading must preserve a guest's explicit selection.
for (const account of [undefined, "zh-TW", "en"]) {
  assert.equal(resolveLanguagePreference("en", account), "en");
  assert.equal(resolveLanguagePreference("zh-TW", account), "zh-TW");
}
// Account preferences must never automatically switch even a new device.
assert.equal(resolveLanguagePreference(null, "en"), "zh-TW");
assert.equal(resolveLanguagePreference(null, "zh-TW"), "zh-TW");
assert.equal(resolveLanguagePreference(null, undefined), "zh-TW");
assert.equal(resolveLanguagePreference("invalid", "en"), "zh-TW");
assert.equal(resolveLanguagePreference("invalid", "invalid"), "zh-TW");
// Refresh/logout preserve the selected language; manual switching takes priority.
assert.equal(resolveLanguagePreference("en", undefined), "en");
assert.equal(resolveLanguagePreference("zh-TW", "en"), "zh-TW");
// Every non-React locale reader shares this same read-only persisted source.
const originalStorage = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
try {
  for (const [stored, expected] of [[null, "zh-TW"], ["en", "en"], ["zh-TW", "zh-TW"], ["invalid", "zh-TW"]]) {
    Object.defineProperty(globalThis, "localStorage", { configurable: true, value: {
      getItem(key) { assert.equal(key, LANGUAGE_STORAGE_KEY); return stored; },
      setItem() { assert.fail("Initialization must not write a language preference"); },
    } });
    assert.equal(readLanguagePreference(), expected);
  }
} finally {
  if (originalStorage) Object.defineProperty(globalThis, "localStorage", originalStorage);
  else delete globalThis.localStorage;
}
console.log("Language preference regression checks passed.");
