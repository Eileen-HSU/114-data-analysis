#!/usr/bin/env python
"""
初始化腳本：自動建立資料表並插入測試資料
"""
import sys
import os
from sqlalchemy import text, func

# 確保可以匯入同層級的 app.py
sys.path.insert(0, os.path.dirname(__file__))

try:
    from app import app, db
except ImportError as e:
    print(f"[ERROR] 無法匯入 app 或 db，請確認 app.py 檔案存在且無語法錯誤。")
    print(f"錯誤訊息: {e}")
    sys.exit(1)

print("\n[INIT] ========== 開始執行初始化流程 ==========")

with app.app_context():
    try:
        # 1. 自動建立所有定義在 Models 中的資料表
        print("[INIT] 正在檢查並建立資料表 (db.create_all)...")
        db.create_all()
        print("[✓] 資料表建立/檢查完成")

        # 2. 檢查 Workspace 表是否為空
        # 使用 try-except 包裹查詢，避免因為表不存在導致程式崩潰
        result = db.session.execute(text("SELECT COUNT(*) FROM Workspace"))
        count = result.fetchone()[0]
        print(f"[INIT] Workspace 表目前有 {count} 筆記錄")

        if count == 0:
            # 3. 插入測試資料
            # 注意：這裡假設你的 User 表中已經有 ID 為 1 的使用者
            # 如果沒有 User ID 1，且有外鍵約束，這步驟會失敗
            print("[INIT] 正在插入測試資料...")
            
            # 使用更具相容性的方式處理時間
            sql = text("""
                INSERT INTO Workspace (user_id, project_name, status, created_at)
                VALUES (:user_id, :name, :status, :time)
            """)
            
            db.session.execute(sql, {
                "user_id": 1,
                "name": "測試專案",
                "status": "active",
                "time": func.now()
            })
            
            db.session.commit()
            print("[✓] 已成功插入測試 Workspace 記錄 (user_id=1)")
        else:
            print("[INFO] Workspace 表已有資料，跳過插入步驟")

        # 4. 驗證最終結果
        print("\n[INIT] 目前資料庫中的專案列表:")
        result = db.session.execute(text("SELECT project_id, project_name FROM Workspace"))
        rows = result.fetchall()
        for row in rows:
            print(f"   - ID: {row[0]} | 名稱: {row[1]}")

    except Exception as e:
        db.session.rollback()
        print(f"\n[ERROR] 初始化過程發生錯誤:")
        print(f"詳細訊息: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

print("\n[INIT] ========== 初始化流程完成 ==========\n")