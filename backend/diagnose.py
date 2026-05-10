#!/usr/bin/env python
"""
診斷腳本：驗證後端資料庫連接與 Survey_Template 表狀態
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app import app, db
from models import Survey_Template
from sqlalchemy import text

print("[INFO] ========== 資料庫診斷開始 ==========")

with app.app_context():
    try:
        # 1. 驗證資料庫連接
        print(f"\n[1] SQLAlchemy 資料庫 URI: {app.config['SQLALCHEMY_DATABASE_URI']}")
        
        # 2. 測試連接
        db.session.execute(text("SELECT 1"))
        print("[✓] 資料庫連接成功！")
        
        # 3. 檢查 Survey_Template 表
        query = db.session.query(Survey_Template).all()
        count = len(query)
        print(f"\n[2] Survey_Template 表現有 {count} 筆記錄")
        
        if count > 0:
            print("最新 5 筆記錄：")
            for survey in query[-5:]:
                print(f"  - ID={survey.template_id}, Access_Code='{survey.access_code}', Created={survey.share_uuid}")
        else:
            print("  表為空")
        
        # 檢查所有表
        try:
            result = db.session.execute(text("SHOW TABLES"))
            tables = result.fetchall()
            print(f"\n[0] 資料庫中的所有表:")
            for table in tables:
                print(f"  - {table[0]}")
        except Exception as e:
            print(f"\n[0] 無法列出表: {str(e)}")
        
        # 檢查 Workspace 表
        try:
            result = db.session.execute(text("SELECT project_id FROM Workspace LIMIT 5"))
            workspace_rows = result.fetchall()
            print(f"\n[2.5] Workspace 表檢查: 找到 {len(workspace_rows)} 筆記錄")
            if workspace_rows:
                print("Workspace project_id 列表:")
                for row in workspace_rows:
                    print(f"  - project_id: {row[0]}")
            else:
                print("  Workspace 表為空")
        except Exception as e:
            print(f"\n[2.5] Workspace 表檢查失敗: {str(e)}")
        
        # 檢查 Workspace 表結構
        try:
            result = db.session.execute(text("DESCRIBE Workspace"))
            columns = result.fetchall()
            print(f"\n[2.6] Workspace 表結構:")
            for col in columns:
                print(f"  - {col[0]}: {col[1]} {'NULL' if col[2] == 'YES' else 'NOT NULL'} {'AUTO_INCREMENT' if col[5] == 'auto_increment' else ''}")
        except Exception as e:
            print(f"\n[2.6] Workspace 表結構檢查失敗: {str(e)}")
        
        # 檢查 User 表
        try:
            result = db.session.execute(text("SELECT user_id, email FROM User LIMIT 5"))
            user_rows = result.fetchall()
            print(f"\n[2.7] User 表檢查: 找到 {len(user_rows)} 筆記錄")
            if user_rows:
                print("User 記錄:")
                for row in user_rows:
                    print(f"  - user_id: {row[0]}, email: {row[1]}")
            else:
                print("  User 表為空")
        except Exception as e:
            print(f"\n[2.7] User 表檢查失敗: {str(e)}")
        
        # 4. 驗證 Survey_Template 模型映射
        print(f"\n[3] Survey_Template 模型：")
        print(f"  - __tablename__: {Survey_Template.__tablename__}")
        print(f"  - 欄位列表: {[c.name for c in Survey_Template.__table__.columns]}")
        
        print("\n[INFO] ========== 診斷完成 ==========")
        
    except Exception as e:
        print(f"\n[ERROR] 診斷失敗: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
