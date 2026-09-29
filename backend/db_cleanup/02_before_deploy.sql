SET NAMES utf8mb4;

-- ═══════════════════════════════════════════════════════════════
-- 資料庫整理 步驟 2：部署新版程式「之前」執行
--
-- 新版程式不再寫入 User.role、Survey_Response.response_token 等欄位。
-- 如果這些欄位在資料庫裡是 NOT NULL 又沒有預設值，新版程式新增資料時
-- 會失敗。這一步只把它們改成「可以是 NULL」，不刪任何東西，
-- 舊版與新版程式都能正常運作，可以放心先執行。
-- ═══════════════════════════════════════════════════════════════

DROP PROCEDURE IF EXISTS _cleanup_make_nullable;

DELIMITER $$
CREATE PROCEDURE _cleanup_make_nullable(IN t VARCHAR(64), IN c VARCHAR(64))
BEGIN
    DECLARE col_type TEXT DEFAULT NULL;
    SELECT COLUMN_TYPE INTO col_type
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = t AND COLUMN_NAME = c AND IS_NULLABLE = 'NO'
    LIMIT 1;
    IF col_type IS NOT NULL THEN
        SET @sql = CONCAT('ALTER TABLE `', t, '` MODIFY COLUMN `', c, '` ', col_type, ' NULL DEFAULT NULL');
        PREPARE stmt FROM @sql;
        EXECUTE stmt;
        DEALLOCATE PREPARE stmt;
        SELECT CONCAT('已改為可 NULL：', t, '.', c) AS result;
    ELSE
        SELECT CONCAT('略過（不存在或本來就可 NULL）：', t, '.', c) AS result;
    END IF;
END$$
DELIMITER ;

CALL _cleanup_make_nullable('User', 'role');
CALL _cleanup_make_nullable('Survey_Response', 'response_token');
CALL _cleanup_make_nullable('Survey_Response', 'res_iden');
CALL _cleanup_make_nullable('User_Verification', 'project_id');
CALL _cleanup_make_nullable('Chat_History', 'corrected_change');
CALL _cleanup_make_nullable('Chat_History', 'ai_category');
CALL _cleanup_make_nullable('Chat_History', 'chat_name');
CALL _cleanup_make_nullable('Uploaded_File', 'is_survey');

DROP PROCEDURE IF EXISTS _cleanup_make_nullable;
