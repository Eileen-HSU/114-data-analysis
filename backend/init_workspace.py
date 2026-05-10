#!/usr/bin/env python
"""
初始化腳本：在 Workspace 表中插入測試資料
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app import app, db
from sqlalchemy import text

print("[INIT] ========== 初始化 Workspace 表 ==========")

with app.app_context():
    try:
        # 檢查 Workspace 表是否為空
        result = db.session.execute(text("SELECT COUNT(*) FROM Workspace"))
        count = result.fetchone()[0]
        print(f"[INIT] Workspace 表目前有 {count} 筆記錄")

        if count == 0:
            # 插入測試 workspace，使用現有的 user_id=1
            db.session.execute(text("""
                INSERT INTO Workspace (user_id, project_name, status, created_at)
                VALUES (1, '測試專案', 'active', NOW())
            """))
            db.session.commit()
            print("[✓] 已插入測試 Workspace 記錄 (user_id=1, project_name='測試專案')")
        else:
            print("[INFO] Workspace 表已有資料，跳過初始化")

        # 驗證插入結果
        result = db.session.execute(text("SELECT project_id, project_name FROM Workspace"))
        rows = result.fetchall()
        print(f"[INIT] Workspace 表內容:")
        for row in rows:
            print(f"  - project_id: {row[0]}, project_name: {row[1]}")

    except Exception as e:
        print(f"[ERROR] 初始化失敗: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

print("\n[INIT] ========== 初始化完成 ==========")
