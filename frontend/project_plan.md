# DataLens — 資料分析平台

## 1. 專案描述
DataLens 是一個以 AI 輔助的資料分析平台，使用者可以上傳文字或檔案，透過對話式介面進行資料分析，並將分析結果儲存為作品集。目標使用者為需要快速分析資料的研究人員、學生與商業分析師。

## 2. 頁面結構
- `/` - Home（首頁：系統介紹 + Sign Up / Login 按鈕）
- `/signup` - Sign Up（註冊頁）
- `/login` - Login（登入頁）
- `/forgot-password` - Forgot Password（忘記密碼）
- `/profile` - Profile（個人資料，需登入）
- `/collection` - My Collection（作品集管理，需登入）
- `/workspace` - Workspace（分析主畫面，需登入）

## 3. 核心功能
- [x] 首頁系統介紹與導覽
- [x] 未登入時觸碰功能顯示警告 Modal
- [x] 使用者登入 / 註冊 / 忘記密碼（前端 UI，mock 狀態）
- [x] 個人資料頁面
- [x] My Collection：單一檔案 + 資料夾分類管理
- [x] 資料夾展開/收合樣式
- [x] Workspace：左側歷史紀錄 + 底部輸入欄（文字 + 附件）
- [x] 頂端置中 Logo
- [ ] 後端資料分析功能（後續階段）

## 4. 資料模型設計（前端 Mock）
### 使用者狀態（localStorage）
- isLoggedIn: boolean
- user: { name, email, avatar }

### Collection 資料
- files: { id, name, type, createdAt }
- folders: { id, name, files[] }

### Workspace 歷史紀錄
- sessions: { id, title, messages[], createdAt }

## 5. 後端 / 第三方整合計劃
- Supabase: 後續階段接入（Auth + Database）
- Shopify: 不需要
- Stripe: 不需要

## 6. 開發階段計劃

### Phase 1：前端 UI 完整建置（當前階段）
- 目標：建立所有頁面的完整前端畫面與頁面跳轉邏輯
- 交付物：7 個頁面 + 路由 + Mock 登入狀態管理

### Phase 2：後端整合（Supabase）
- 目標：接入真實的使用者認證與資料儲存
- 交付物：Auth 登入/註冊、Collection 資料庫、Workspace 歷史紀錄持久化

### Phase 3：資料分析功能
- 目標：接入 Python 後端 API 進行實際資料分析
- 交付物：檔案解析、分析結果展示、圖表視覺化
