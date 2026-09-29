# Authentication 與語言狀態稽核

## 根因與證據範圍

重新下載時的版本 `f741447c` 有以下自動改語言路徑：

```text
AuthContext 載入 /api/profile/:id
→ data.language 寫入 user.language
→ LanguageContext 的 useEffect([user?.language])
→ resolveLanguagePreference(storedLanguage, user.language)
→ setLanguageState(next) + localStorage.setItem(..., next)
```

該版 helper 在裝置缺少有效設定時會採用帳號語言，因此 authentication/profile 更新曾是修改介面語言的 trigger，違反本次要求。但當 storage 已是有效的 `en`，該版 helper 仍優先採用 `en`：不能只憑上述路徑就斷言已證明使用者線上所有重現條件。

前次提交已移除 LanguageContext 監聽 user.language 的 effect。本次以 `b1a79601` 為起點，確認仍有：

1. AuthContext 把 profile.language 寫入 auth user 副本。
2. 手動切換同時更新 auth user.language，讓語言與 authentication 互相影響。
3. LanguageProvider 的 useEffect([language]) 在 mount/reload 重寫 persistence；新增寫入追蹤測試在修改前抓到初次載入寫入 `zh-TW`，StrictMode 下兩次。
4. Profile 表單仍保存未使用的 language 副本。
5. 問卷與管理頁的非 React helper 使用獨立的 navigator.language fallback，與 LanguageContext 的預設不一致。

本次移除以上耦合與自動寫入，並統一讀取規則。最新程式的完整登入測試未重現持續切回中文。尚未取得使用者實際網站網址，不能把本機驗證當成已確認正式站台的根因或部署成功。

## 全流程檢查

| 檢查位置 | 結果 |
| --- | --- |
| LoginPage submit / success | 只處理驗證、login、navigate；不呼叫語言 setter |
| LoginTwoFactorPage / SignUpPage | sessionStorage 只保存驗證資料；不初始化 locale |
| AuthContext 載入 profile | 移除 data.language 寫入 auth user 的邏輯 |
| App / main / router | LanguageProvider 位於路由外，不因登入或換頁重新建立；無 default-language assignment |
| Workspace / admin 初始化 | 無語言 setter；唯讀 helper 統一既有設定來源 |
| Profile 初始化與儲存 | 移除表單語言副本；儲存一般資料不切換語言 |
| LanguageContext | useState initializer 只讀一次既有設定；語言 setter 的應用程式呼叫點只有 Navbar 的中/EN 按鈕 |
| localStorage | 沿用 dataanalysis_language；只有 setter 寫入，登出不刪除 |
| sessionStorage / cookies | 未找到應用程式 locale 寫入或作為 locale 初始化來源的邏輯 |
| i18next / locale | 套件雖列為依賴，src 無另行初始化 i18next 的語言 store |
| API language | profile 回傳語言不影響 UI；fetch header 讀取共同設定，axios header 跟隨 Context |
| 預設值 / reload | 沒有有效既存語言才回傳 zh-TW，讀取不寫回；reload 讀回手動選擇 |

## 本次修改檔案

- `frontend/src/context/LanguageContext.jsx`：刪除初始化持久化 effect 與 updateUser(language)，維持唯一 active language state。只有手動 setter 寫入 storage；讀 auth 僅用於手動選擇後授權既有 profile 儲存 API，不讀取帳號語言。
- `frontend/src/context/languagePreference.js`：集中既有 storage key 與無副作用的 readLanguagePreference，沒有新增另一份語言 state。
- `frontend/src/hooks/AuthContext.jsx`：不再把 profile.language 套入 auth user。
- `frontend/src/pages/profile/page.jsx`：刪除初始值、cache 與 API 表單資料中的 language 副本。
- `frontend/src/lib/api.js`、`frontend/src/lib/surveyChatContent.js`、`frontend/src/pages/admin/ai-admin/shared/taxStatus.js`、`frontend/src/pages/profile/components/SurveyDetailPage.jsx`、`frontend/src/pages/survey/CreateSurveyPage.jsx`：共用唯讀設定與同一 fallback，移除獨立的 navigator 語言判定；未變更翻譯文字。
- `frontend/scripts/check-login-language.cjs`：擴充完整登入驗收與 persistence 寫入監控。
- `frontend/scripts/check-language-preference.mjs`、`frontend/scripts/check-language-session.cjs`、`frontend/scripts/fixtures/language-session.jsx`：檢查唯讀初始化及延遲 profile 回應。
- `frontend/dist`：更新正式建置檔。

## 六個驗收情境

使用 Playwright 操作實際首頁、Navbar、登入表單、workspace、survey、profile。API 使用模擬資料，不使用真實帳號密碼。

| Case | 驗證 |
| --- | --- |
| 1 | 首頁選 English → Login → workspace → English |
| 2 | 首頁選中文 → Login → workspace → 中文 |
| 3 | English 登入 → reload → English，語言 storage 無寫入 |
| 4 | 中文登入 → reload → 中文，語言 storage 無寫入 |
| 5 | 登入後手動切中文再切 English → survey → profile 初始化 → English |
| 6 | 接 Case 5，透過 Navbar 登出 → 首頁 → English |

額外組合：profile 回傳相反語言、沒有 language 欄位、英文雙因子登入；另以 Provider 測試檢查載入 profile 期間切 English，延遲回傳後仍為 English。

驗證內容包括 Context 狀態（Provider 測試）、html.lang、Navbar active 語言、workspace 文字、逐幀英文 UI、localStorage setItem/removeItem/clear 追蹤、API Accept-Language、瀏覽器錯誤。API header 比對會等待上一個請求完成，避免把切換前已發出的請求誤判為切換後請求。

結果：以上六個情境與額外組合在本機開發版及正式建置預覽均通過；Provider 延遲回應測試、唯讀設定測試、301 個翻譯標籤檢查及 build 均通過。Build 仍有既有 Tailwind at-rule 與 bundle 大小警告，未阻擋產出。

## 執行指令

工作目錄為 frontend，Node.js 已在 PATH；沿用工作目錄現有 Playwright：

```powershell
node scripts/check-language-preference.mjs
node scripts/check-interface-i18n.cjs
npm.cmd run dev -- --host 127.0.0.1 --port 4176
# 另一終端：
$env:PLAYWRIGHT_MODULE_PATH = (Resolve-Path '../../.task-tools/node_modules/playwright').Path
$env:CHROME_PATH = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
$env:TEST_BASE_URL = 'http://127.0.0.1:4176'
node scripts/check-login-language.cjs
node scripts/check-language-session.cjs
npm.cmd run build
npm.cmd run preview -- --host 127.0.0.1 --port 4177
# 另一終端：
$env:TEST_BASE_URL = 'http://127.0.0.1:4177'
node scripts/check-login-language.cjs
```

## Git 提交與同步

在專案根目錄執行：

```powershell
git diff --check
git add frontend/src/context/LanguageContext.jsx frontend/src/context/languagePreference.js frontend/src/hooks/AuthContext.jsx frontend/src/pages/profile/page.jsx frontend/src/lib/api.js frontend/src/lib/surveyChatContent.js frontend/src/pages/admin/ai-admin/shared/taxStatus.js frontend/src/pages/profile/components/SurveyDetailPage.jsx frontend/src/pages/survey/CreateSurveyPage.jsx
git commit -m "fix: isolate manual language preference from authentication initialization"
git push origin main
git add frontend/scripts/check-login-language.cjs frontend/scripts/check-language-preference.mjs frontend/scripts/check-language-session.cjs frontend/scripts/fixtures/language-session.jsx
git commit -m "test: verify six language persistence cases and forbid automatic writes"
git push origin main
git add -f frontend/dist
git add docs/LANGUAGE_AUTH_AUDIT_2026-09-29.md
git commit -m "build: update frontend and document authentication language audit"
git push origin main
git fetch origin main
git status --short --branch
git rev-parse HEAD
git rev-parse origin/main
```

首次推送時遠端已新增 `9669507b`（資料庫整理，登入資料移除 role 欄位），Git 正常拒絕 non-fast-forward。保留三個本地分步提交後以 `git fetch origin main`、`git rebase origin/main` 整合，未強制推送。重新執行 `npm.cmd run build` 與正式建置登入驗收，將新建置和本段紀錄加入最後一個尚未推送的建置提交（`git add -f frontend/dist`、`git add docs/LANGUAGE_AUTH_AUDIT_2026-09-29.md`、`git commit --amend --no-edit`），再推送與核對同步。
