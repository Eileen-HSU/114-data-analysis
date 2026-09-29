# 登入前後維持語言（2026-09-29）

## 行為

- 介面語言只依此裝置的手動選擇決定，首次沒有選擇時維持預設繁體中文。
- 登入、帳號個人資料延遲回傳、登出及重新整理，均不套用帳號舊語言。
- 儲存一般個人資料不再送出隱藏的舊語言欄位，也不呼叫語言切換。
- 使用者仍可透過導覽列的「中 / EN」手動切換。

## 操作與提交

在專案根目錄執行，需 Node.js 與 npm 在 PATH：

```powershell
cd frontend
npm.cmd ci --no-audit --no-fund
node scripts/check-language-preference.mjs
node scripts/check-interface-i18n.cjs
npm.cmd run build
```

上述檢查均通過，翻譯檢查涵蓋 301 個固定標籤。建置有 Tailwind at-rule 與 bundle 大小警告，未阻擋產出。

瀏覽器回歸測試使用真實 AuthProvider 與 LanguageProvider，API 為模擬資料，不登入真實使用者帳號。在第一個終端啟動：

```powershell
npm.cmd run dev -- --host 127.0.0.1 --port 4175
```

第二個終端在 frontend 執行（本機沿用工作目錄既有 Playwright）：

```powershell
$env:PLAYWRIGHT_MODULE_PATH = (Resolve-Path '../../.task-tools/node_modules/playwright').Path
$env:CHROME_PATH = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
node scripts/check-language-session.cjs
```

結果通過：未選擇語言、選擇英文、選擇中文的起始狀態，以及登入、等待個人資料期間手動切換、延遲回應、重新整理、登出及手動切回中文。

回到根目錄分步提交：

```powershell
cd ..
git diff --check
git add frontend/src/context/LanguageContext.jsx frontend/src/context/languagePreference.js frontend/src/pages/profile/page.jsx
git commit -m "fix: preserve interface language across authentication and profile saves"
git add frontend/scripts/check-language-preference.mjs frontend/scripts/check-language-session.cjs frontend/scripts/fixtures/language-session.jsx
git commit -m "test: verify language remains stable across session changes"
git add -f frontend/dist
git commit -m "build: refresh frontend for manual-only language switching"
git add docs/LANGUAGE_SESSION_FIX_2026-09-29.md
git commit -m "docs: record language persistence fix and verification"
```

修正提交：`59739402`；測試提交：`97337e46`；建置提交：`fc707f74`。提交作者信箱皆為 `kaolysweet@gmail.com`。

## 推送狀態

本次尚未推送。等待確認目前登入的 `Kaolyccc` 是否為使用者指定信箱的 GitHub 帳號。確認後執行 `git push origin main`，再以 `git fetch origin main` 與 `git status --short --branch` 驗證同步。尚未驗證正式站台部署。
