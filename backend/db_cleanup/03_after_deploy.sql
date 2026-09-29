SET NAMES utf8mb4;

-- ═══════════════════════════════════════════════════════════════
-- 資料庫整理 步驟 3：新版程式部署、啟動成功「之後」執行
--
-- 會永久刪除欄位與資料表，執行前一定要先完整備份（見 README.md）。
--
-- 安全檢查：新版程式啟動時會把 Response_Classification 舊的次要分類
-- 欄位搬進 Response_Classification_Secondary 子表。如果還有資料沒搬完，
-- 這支腳本會在第一步就中止（ERROR 45000），不會刪任何東西。
-- ═══════════════════════════════════════════════════════════════

DROP PROCEDURE IF EXISTS _cleanup_assert_secondaries_migrated;
DROP PROCEDURE IF EXISTS _cleanup_drop_column;
DROP PROCEDURE IF EXISTS _cleanup_drop_table;

DELIMITER $$

CREATE PROCEDURE _cleanup_assert_secondaries_migrated()
BEGIN
    DECLARE pending INT DEFAULT 0;

    IF EXISTS (SELECT 1 FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'Response_Classification'
                 AND COLUMN_NAME = 'secondary_sub_category') THEN
        SET @n = 0;
        SET @sql = 'SELECT COUNT(*) INTO @n FROM `Response_Classification` rc
                    WHERE rc.`secondary_sub_category` IS NOT NULL AND rc.`secondary_sub_category` <> ''''
                      AND NOT EXISTS (SELECT 1 FROM `Response_Classification_Secondary` s
                                      WHERE s.`classification_id` = rc.`classification_id` AND s.`kind` = ''ai'')';
        PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
        SET pending = pending + @n;
    END IF;

    IF EXISTS (SELECT 1 FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'Response_Classification'
                 AND COLUMN_NAME = 'final_secondary_sub_category') THEN
        SET @n = 0;
        SET @sql = 'SELECT COUNT(*) INTO @n FROM `Response_Classification` rc
                    WHERE rc.`final_secondary_sub_category` IS NOT NULL AND rc.`final_secondary_sub_category` <> ''''
                      AND NOT EXISTS (SELECT 1 FROM `Response_Classification_Secondary` s
                                      WHERE s.`classification_id` = rc.`classification_id` AND s.`kind` = ''final'')';
        PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
        SET pending = pending + @n;
    END IF;

    IF pending > 0 THEN
        SET @msg = CONCAT('還有 ', pending, ' 筆次要分類尚未搬進子表，請先重新啟動新版後端讓它完成回填，再執行本腳本');
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = @msg;
    END IF;
    SELECT '次要分類皆已搬進子表，可以繼續' AS result;
END$$

CREATE PROCEDURE _cleanup_drop_column(IN t VARCHAR(64), IN c VARCHAR(64))
BEGIN
    DECLARE fk_name VARCHAR(64);
    DECLARE done INT DEFAULT 0;
    DECLARE fk_cursor CURSOR FOR
        SELECT CONSTRAINT_NAME FROM information_schema.KEY_COLUMN_USAGE
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = t AND COLUMN_NAME = c
          AND REFERENCED_TABLE_NAME IS NOT NULL;
    DECLARE CONTINUE HANDLER FOR NOT FOUND SET done = 1;

    -- 先拿掉這個欄位上的外鍵（例如 User_Verification.project_id）
    OPEN fk_cursor;
    fk_loop: LOOP
        FETCH fk_cursor INTO fk_name;
        IF done THEN LEAVE fk_loop; END IF;
        SET @sql = CONCAT('ALTER TABLE `', t, '` DROP FOREIGN KEY `', fk_name, '`');
        PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
    END LOOP;
    CLOSE fk_cursor;

    IF EXISTS (SELECT 1 FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = t AND COLUMN_NAME = c) THEN
        SET @sql = CONCAT('ALTER TABLE `', t, '` DROP COLUMN `', c, '`');
        PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
        SELECT CONCAT('已刪除欄位：', t, '.', c) AS result;
    ELSE
        SELECT CONCAT('略過（欄位不存在）：', t, '.', c) AS result;
    END IF;
END$$

CREATE PROCEDURE _cleanup_drop_table(IN t VARCHAR(64))
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.TABLES
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = t) THEN
        SET @sql = CONCAT('DROP TABLE `', t, '`');
        PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
        SELECT CONCAT('已刪除資料表：', t) AS result;
    ELSE
        SELECT CONCAT('略過（資料表不存在）：', t) AS result;
    END IF;
END$$

DELIMITER ;

-- 1) 安全檢查：次要分類沒搬完就中止
CALL _cleanup_assert_secondaries_migrated();

-- 2) 次要分類舊的單值欄位（資料已在 Response_Classification_Secondary）
CALL _cleanup_drop_column('Response_Classification', 'secondary_main_category');
CALL _cleanup_drop_column('Response_Classification', 'secondary_sub_category');
CALL _cleanup_drop_column('Response_Classification', 'secondary_methodology');
CALL _cleanup_drop_column('Response_Classification', 'secondary_citation');
CALL _cleanup_drop_column('Response_Classification', 'final_secondary_main_category');
CALL _cleanup_drop_column('Response_Classification', 'final_secondary_sub_category');

-- 3) 沒有程式使用的欄位
CALL _cleanup_drop_column('User', 'role');
CALL _cleanup_drop_column('User_Verification', 'project_id');
CALL _cleanup_drop_column('Chat_History', 'corrected_change');
CALL _cleanup_drop_column('Survey_Response', 'res_iden');
CALL _cleanup_drop_column('Survey_Response', 'response_token');

-- 4) 舊版設計殘留的欄位（程式早已沒有，存在才刪）
CALL _cleanup_drop_column('Chat_History', 'ai_category');
CALL _cleanup_drop_column('Chat_History', 'chat_name');
CALL _cleanup_drop_column('Chat_History', 'is_auto_title');
CALL _cleanup_drop_column('Uploaded_File', 'is_survey');

-- 5) 已淘汰的資料表
CALL _cleanup_drop_table('Prompt_Template');
CALL _cleanup_drop_table('AI_Analysis');
CALL _cleanup_drop_table('Admin_config');

DROP PROCEDURE IF EXISTS _cleanup_assert_secondaries_migrated;
DROP PROCEDURE IF EXISTS _cleanup_drop_column;
DROP PROCEDURE IF EXISTS _cleanup_drop_table;

-- 6) 整理後的資料表清單（應該剛好 25 張，見 README.md）
SELECT TABLE_NAME FROM information_schema.TABLES
WHERE TABLE_SCHEMA = DATABASE()
ORDER BY TABLE_NAME;
