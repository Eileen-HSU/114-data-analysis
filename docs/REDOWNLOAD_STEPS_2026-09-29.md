# 重新下載專案操作紀錄（2026-09-29）

來源：https://github.com/Eileen-HSU/114-data-analysis

本次採用全新資料夾下載，保留原有工作資料夾。下載時 main 最新提交為 `f741447c`。

## 1. 重新下載完整 Git 專案

在原工作目錄執行：

```powershell
git clone https://github.com/Eileen-HSU/114-data-analysis.git redownload-114-data-analysis-20260929
cd redownload-114-data-analysis-20260929
```

## 2. 設定本專案的提交作者

```powershell
git config user.name kaolysweet
git config user.email kaolysweet@gmail.com
```

此設定僅影響本專案的提交作者；GitHub 推送使用實際登入的帳號憑證。

## 3. 檢查下載內容及分支

```powershell
git remote -v
git branch --show-current
git log -1 --oneline
git status --short
```

下載後位於 `main`，工作目錄乾淨，包含 `backend`、`frontend`、`requirements.txt`、`render.yaml` 及部署文件。本次只重新下載與記錄操作，未安裝依賴或變更應用程式。

## 4. 提交操作紀錄

```powershell
git add docs/REDOWNLOAD_STEPS_2026-09-29.md
git commit -m "docs: record project redownload steps"
```

## 5. 推送與驗證

確認登入帳號對應使用者指定帳號後執行：

```powershell
git push origin main
git fetch origin main
git status --short --branch
git rev-parse HEAD
git rev-parse origin/main
```

兩個提交雜湊相同即表示本地提交與遠端同步。後續每個實際修改步驟均可依序更新操作紀錄、提交及推送；純查詢指令則記錄於文件。
