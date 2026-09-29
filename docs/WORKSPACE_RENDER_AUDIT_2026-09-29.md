# Workspace render audit — 2026-09-29

## Scope and findings

Fresh clone: `e1d6dd85559c5f4a4225bfaeae248edc8f0c9ac9` from Eileen-HSU/114-data-analysis.
Author: kaolysweet <kaolysweet@gmail.com>. The user confirmed GitHub login `Kaolyccc` for pushes.

Temporary console instrumentation in LanguageContext and LoginPage recorded:

```text
[LOGIN BEFORE] en
[LOGIN AFTER] en
[LANG] render {"language":"en","stored":"en","pathname":"/workspace"}
[LANG] bridge en /workspace
```

With workspace and survey API responses delayed by 1600 ms, the loading view and settled view both had Context=en, storage=en, Navbar=EN. The loading text was already translated by the bridge; the settled sidebar was Conversation history. The observer remained active across navigation and asynchronous updates. No setter call other than the manual EN choice was observed. Instrumentation was removed after diagnosis.

**The reported persistent switch to Chinese was not reproduced on this fresh revision.** There is no evidence that login resets language, that a specific async render leaves Chinese in the final DOM, or that MutationObserver is broken. No incorrect data-localized exclusion was found in the workspace paths inspected. A production URL and reproduction against its deployed revision are still needed to establish the reported production root cause.

A narrower architectural gap is confirmed directly in the source: entry/history loading copy, placeholder/title attributes, survey status and delete-button states were Chinese literals, relying on the DOM bridge. This change renders those strings through the existing translateInterfaceText helper during React render. Existing InterfaceText labels and Navbar t() calls remain in use. It adds no language store, authentication override, timer or observer workaround.

## Changes

- frontend/src/pages/workspace/page.jsx: direct localization for loading copy, input/search hints, control titles, survey status, delete button, known toast messages and attachment notification. User filenames remain interpolated unchanged; AI messages and survey responses are untouched.
- frontend/scripts/check-login-language.cjs: delayed workspace/survey responses; loading label, settled search placeholder and invite toast assertions. Optional TEST_DISABLE_LEGACY_BRIDGE=1 bypasses only workspace bridge calls in Vite's served module, without modifying production code.
- frontend/dist: rebuilt deployment artifact.
- This report: findings, limits and reproducible commands.

Navbar needs no source change: it already renders t() output and its active button follows Context.
After API completion, the changed React expressions read the same Context language on each render; their translations no longer depend on observer timing. A workspace-only bridge bypass verifies the loading and settled labels independently.

## Validation

API responses are mocked; no real credentials or real backend writes are used. Test 1–6 below describe the requested checks, separately from the script's older case numbering.

1. Fresh homepage → choose EN: storage en, active EN.
2. Homepage → Login: language en and English login heading.
3. Submit login → workspace: en retained, active EN, English loading and sidebar.
4. Delayed profile/workspace/survey responses settle: English sidebar/search and invite toast; no automatic storage writes.
5. Chinese login: Chinese loading/sidebar/search and active Chinese button.
6. Reload workspace: selected language retained without storage writes.

Additional scenarios cover opposite/missing profile language, two-factor login, manual switching, navigation and logout. Two-factor login does not request the entry-loading overlay, so its check waits for the settled sidebar instead. The six checks pass in production preview; the workspace bridge-bypass run also passes. The standalone language preference and 301-label interface checks pass. Build succeeds with existing Tailwind at-rule and bundle-size warnings.

## Commands

From the parent workspace:

```powershell
git clone https://github.com/Eileen-HSU/114-data-analysis.git language-fix-114-data-analysis-20260929
cd language-fix-114-data-analysis-20260929
git config user.name kaolysweet
git config user.email kaolysweet@gmail.com
cd frontend
npm.cmd ci --no-audit --no-fund
npm.cmd run dev -- --host 127.0.0.1 --port 4186
```

In another terminal, from frontend:

```powershell
$env:PLAYWRIGHT_MODULE_PATH = (Resolve-Path '../../.task-tools/node_modules/playwright').Path
$env:CHROME_PATH = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
$env:TEST_BASE_URL = 'http://127.0.0.1:4186'
node scripts/check-login-language.cjs
$env:TEST_DISABLE_LEGACY_BRIDGE = '1'
node scripts/check-login-language.cjs
Remove-Item Env:TEST_DISABLE_LEGACY_BRIDGE
node scripts/check-language-preference.mjs
node scripts/check-interface-i18n.cjs
npm.cmd run build
npm.cmd run preview -- --host 127.0.0.1 --port 4187
```

With preview running, from another terminal with the same Playwright/Chrome variables:

```powershell
$env:TEST_BASE_URL = 'http://127.0.0.1:4187'
node scripts/check-login-language.cjs
```

Commit and push each work stage from the repository root:

```powershell
git diff --check
git add frontend/src/pages/workspace/page.jsx
git commit -m "fix: render workspace loading and controls in the selected language"
git push origin main
git add frontend/scripts/check-login-language.cjs
git commit -m "test: check delayed workspace rendering independently of the DOM bridge"
git push origin main
git add -f frontend/dist
git add docs/WORKSPACE_RENDER_AUDIT_2026-09-29.md
git commit -m "build: refresh workspace bundle and document render audit"
git push origin main
git status --short --branch
git rev-parse HEAD
git ls-remote origin refs/heads/main
```
