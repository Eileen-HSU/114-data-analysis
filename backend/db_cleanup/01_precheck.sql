SET NAMES utf8mb4;

-- ═══════════════════════════════════════════════════════════════
-- 資料庫整理 步驟 1：唯讀檢查（不會修改任何資料）
-- 對象：MySQL 8（正式資料庫 defaultdb）
-- 用法：mysql ... defaultdb < 01_precheck.sql
-- 把輸出結果保留下來，對照 README.md 判斷能不能繼續。
-- ═══════════════════════════════════════════════════════════════

-- 1) 目前資料庫裡所有資料表（整理完成後應該剛好是 README 列出的 25 張）
SELECT TABLE_NAME, TABLE_ROWS
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = DATABASE()
ORDER BY TABLE_NAME;

-- 2) 這次要刪除的欄位，目前哪些還存在
SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND (TABLE_NAME, COLUMN_NAME) IN (
    ('User', 'role'),
    ('User_Verification', 'project_id'),
    ('Chat_History', 'corrected_change'),
    ('Chat_History', 'ai_category'),
    ('Chat_History', 'chat_name'),
    ('Chat_History', 'is_auto_title'),
    ('Uploaded_File', 'is_survey'),
    ('Survey_Response', 'res_iden'),
    ('Survey_Response', 'response_token'),
    ('Response_Classification', 'secondary_main_category'),
    ('Response_Classification', 'secondary_sub_category'),
    ('Response_Classification', 'secondary_methodology'),
    ('Response_Classification', 'secondary_citation'),
    ('Response_Classification', 'final_secondary_main_category'),
    ('Response_Classification', 'final_secondary_sub_category')
  )
ORDER BY TABLE_NAME, COLUMN_NAME;

-- 3) 這次要刪除的資料表，目前哪些還存在
SELECT TABLE_NAME, TABLE_ROWS
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME IN ('Prompt_Template', 'AI_Analysis', 'Admin_config');

-- 4) Admin 表必須是新結構（有 admin_id）。
--    如果這裡查不到 admin_id，或出現 config_id / admin_entry_key，
--    代表正式資料庫還是舊的「管理員配置」表，請先停下來，不要執行後面的步驟。
SELECT COLUMN_NAME, COLUMN_TYPE, COLUMN_KEY
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'Admin'
ORDER BY ORDINAL_POSITION;

-- 5) 外鍵現況（對照手冊第 8 章的「待確認」項目）
SELECT TABLE_NAME, COLUMN_NAME, CONSTRAINT_NAME, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME
FROM information_schema.KEY_COLUMN_USAGE
WHERE TABLE_SCHEMA = DATABASE() AND REFERENCED_TABLE_NAME IS NOT NULL
ORDER BY TABLE_NAME, COLUMN_NAME;
