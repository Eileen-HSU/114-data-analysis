# 資料庫整理（2026-09）

這次整理把不再使用的資料表與欄位從程式和正式資料庫中移除。資料表從 26 張減為 **25 張**。

## 移除了什麼

| 類型 | 項目 | 原因 |
|---|---|---|
| 資料表 | `Prompt_Template` | 正式分類改用已發布的分類架構（Taxonomy）即時組出提示詞；這張表只剩已沒有前端畫面的舊 API 和舊 CLI 在用，一併移除 |
| 資料表 | `AI_Analysis`、`Admin_config`（若存在） | 早期設計殘留，程式早已不使用 |
| 欄位 | `Response_Classification.secondary_main_category`、`secondary_sub_category`、`secondary_methodology`、`secondary_citation`、`final_secondary_main_category`、`final_secondary_sub_category` | 次要分類改為只存在 `Response_Classification_Secondary` 子表，這些是重複的單值鏡像 |
| 欄位 | `User.role` | 管理員改用獨立的 `Admin` 表，角色欄位已沒有作用；使用者 token 與登入回應也不再帶 role |
| 欄位 | `User_Verification.project_id` | 預留給分享對話驗證，從未被寫入 |
| 欄位 | `Chat_History.corrected_change` | 沒有任何程式讀寫 |
| 欄位 | `Survey_Response.res_iden`、`response_token` | 沒有任何程式讀寫；受訪者身分存在 `answer_json.respondent_identity` |
| 欄位 | `Chat_History.ai_category`、`chat_name`、`is_auto_title`、`Uploaded_File.is_survey`（若存在） | 早期設計殘留 |

**沒有移除**：管理後台的「沙盒測試」分頁仍然保留。它測試的是分類架構草稿，與 `Prompt_Template` 無關。

## 執行順序

> 所有步驟都針對正式資料庫 `defaultdb`。步驟 3 會永久刪除資料，請務必先備份。

1. **備份**

   ```
   mysqldump --single-transaction --routines -h <host> -P <port> -u <user> -p defaultdb > backup_before_cleanup.sql
   ```

2. **唯讀檢查**：執行 `01_precheck.sql`，確認以下兩點。
   - 第 4 段的 `Admin` 欄位中必須有 `admin_id`。如果看到 `config_id`／`admin_entry_key`，請先停下，不要繼續。
   - 第 5 段是外鍵現況，可以拿來補手冊第 8 章的「待確認」項目。

3. **部署前**：執行 `02_before_deploy.sql`。這一步只把新版不再寫入的欄位改成可為 NULL，新舊版程式都能正常運作。

4. **部署新版後端，並確認啟動成功**。啟動時會自動把舊的次要分類欄位搬進子表，log 會出現 `[SECONDARY_BACKFILL]`。

5. **部署後**：執行 `03_after_deploy.sql`。
   - 腳本會先檢查次要分類是否都已搬完。沒搬完會以 `ERROR 45000` 中止，這時不會刪任何東西；請重新啟動後端後再執行一次。
   - 腳本可以重複執行，已經刪掉的項目會顯示「略過」。
   - 最後會列出資料表清單，應剛好是下列 25 張。

## 整理後的 25 張資料表

Admin、Admin_Audit_Log、Admin_Verification、Chat_History、Classification_Review、Classification_Review_Message、Export_File、Report、Report_Aggregation、Report_Aggregation_Item、Response_Classification、Response_Classification_Secondary、Response_Segmentation_Status、Survey_Response、Survey_Template、System_Health_Status、Taxonomy_Category、Taxonomy_Version、Topic、Uploaded_Answer、Uploaded_File、User、User_Profile、User_Verification、Workspace

## 前端相容性

API 回應中的 `secondary_main_category`／`secondary_sub_category`／`final_secondary_*` 等 key 仍然保留，由子表的第一個次要分類推導，所以前端不需要修改。唯一的前端改動是登入頁不再讀取 `role`。
