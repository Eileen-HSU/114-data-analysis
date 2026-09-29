# 登入流程語言顯示補強

## 實際觀察

上一版在本機完整首頁 → 英文 → 登入 → 工作區流程中，語言狀態與最終介面維持英文，未重現持續切回中文。不過新增逐幀測試後，確實捕捉到 `/login` 在英文設定下曾顯示中文標題「登入帳號」。先前只測試語言狀態的測試無法抓到這個畫面問題。

舊版翻譯使用 `useEffect` 與可取消的 `requestAnimationFrame`，會讓新頁面的原始中文出現在翻譯前的一幀；連續 DOM 更新亦可能反覆延後翻譯。

## 修正

- 使用 `useLayoutEffect` 在初次顯示前套用語言與翻譯。
- DOM 更新時由 MutationObserver 在繪製前直接套用翻譯，不再延到下一個 animation frame。
- 保留 observer 暫停機制，避免翻譯本身反覆觸發 observer。
- 移除登入成功後重複的 login 與 navigate 呼叫。
- 保留前一版「只有手動選擇會更新語言」規則。

## 驗證指令

在 frontend 目錄，Node.js 須已加入 PATH：

```powershell
node scripts/check-language-preference.mjs
node scripts/check-interface-i18n.cjs
npm.cmd run build
npm.cmd run dev -- --host 127.0.0.1 --port 4176
```

另一終端在 frontend 目錄執行（沿用工作目錄的 Playwright）：

```powershell
$env:PLAYWRIGHT_MODULE_PATH = (Resolve-Path '../../.task-tools/node_modules/playwright').Path
$env:CHROME_PATH = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
$env:TEST_BASE_URL = 'http://127.0.0.1:4176'
node scripts/check-login-language.cjs
node scripts/check-language-session.cjs
```

整頁測試操作實際首頁與登入表單，API 回覆以模擬資料提供相反的帳號語言；涵蓋中英文、帳號資料載入、工作區可見文字、重新整理、鍵盤登出及每幀的標題與搜尋提示。原測試在修正前因出現中文標題失敗，修正後通過。

再使用正式建置檔驗證：

```powershell
npm.cmd run preview -- --host 127.0.0.1 --port 4177
# 另一個終端：
$env:TEST_BASE_URL = 'http://127.0.0.1:4177'
node scripts/check-login-language.cjs
```

前端建置有既有 Tailwind at-rule 與 bundle 大小警告。

## 分步提交與推送指令

在專案根目錄：

```powershell
git diff --check
git add frontend/src/context/LanguageContext.jsx frontend/src/pages/auth/LoginPage.jsx frontend/scripts/check-login-language.cjs
git commit -m "fix: translate login navigation before paint and test real login flow"
git push origin main
git add -f frontend/dist
git add docs/LOGIN_LANGUAGE_RENDER_FIX_2026-09-29.md
git commit -m "build: publish login language rendering fix and verification steps"
git push origin main
git fetch origin main
git status --short --branch
git rev-parse HEAD
git rev-parse origin/main
```

## 正式站台待確認

尚未取得使用者目前實際操作的網址，無法判定持續切回中文是否與本次捕捉的顯示時序相同，也未驗證正式站台的部署版本。文件中的兩個 Render 網址在此次檢查回傳 HTTP 503；本機測試通過不代表正式站台已更新。
