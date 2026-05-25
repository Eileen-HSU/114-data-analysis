#!/usr/bin/env python3
"""
修復問卷邀請碼大小寫問題的遷移腳本
將所有現有的邀請碼轉換為大寫
"""

import os
import sys
from dotenv import load_dotenv
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# 必須在導入之前加載環境變數
load_dotenv()

# 添加當前目錄到 Python 路徑
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 設置數據庫連接
basedir = os.path.abspath(os.path.dirname(__file__))
db_url = os.getenv("DATABASE_URL")

if db_url:
    parsed_url = urlsplit(db_url)
    query_params = []
    for key, value in parse_qsl(parsed_url.query, keep_blank_values=True):
        normalized_key = key.lower().replace("_", "-")
        if normalized_key == "ssl-mode":
            continue
        if key == "ssl_ca" and value == "ca.pem":
            value = os.path.join(basedir, "ca.pem")
        query_params.append((key, value))

    db_url = urlunsplit((
        parsed_url.scheme,
        parsed_url.netloc,
        parsed_url.path,
        urlencode(query_params),
        parsed_url.fragment,
    ))

db_url = db_url or os.environ.get('SQLALCHEMY_DATABASE_URI')

print(f"📌 數據庫 URL: {db_url[:50]}..." if db_url else "⚠️  未設置數據庫 URL")

if not db_url:
    print("❌ 錯誤: 未設置 DATABASE_URL 或 SQLALCHEMY_DATABASE_URI", file=sys.stderr)
    sys.exit(1)

# 導入 Flask 應用和模型
from flask import Flask
from extensions import db
from models import Survey_Template

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

def fix_access_codes():
    """修複所有問卷的邀請碼為大寫"""
    with app.app_context():
        try:
            # 查詢所有問卷
            surveys = Survey_Template.query.all()
            fixed_count = 0
            
            for survey in surveys:
                original_code = survey.access_code
                # 轉換為大寫
                new_code = original_code.upper() if original_code else original_code
                
                if original_code != new_code:
                    survey.access_code = new_code
                    fixed_count += 1
                    print(f"✓ 已修復: {original_code} → {new_code}")
            
            if fixed_count > 0:
                db.session.commit()
                print(f"\n✅ 成功修復 {fixed_count} 個問卷的邀請碼")
            else:
                print("✅ 所有邀請碼已經是大寫，無需修復")
                
        except Exception as e:
            print(f"❌ 修復失敗: {e}", file=sys.stderr)
            db.session.rollback()
            sys.exit(1)

if __name__ == "__main__":
    print("開始修復問卷邀請碼大小寫問題...")
    fix_access_codes()
