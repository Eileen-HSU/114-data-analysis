"""
seed_prompt_templates.py

一次性腳本：把 classify_v2.py 裡的預設 prompt 內容，寫進
Prompt_Template 表，當作初始的草稿版與正式版（兩者一開始相同）。

【使用方式】
    python3 seed_prompt_templates.py

這裡刻意不 import 你完整的 app.py（避免載入所有 routes 才能跑這支小腳本），
改成自己建一個最小夠用的 Flask app，只為了能連上資料庫、取得 app context。
資料庫連線字串請確認跟你 app.py 裡用的一致（通常從 .env 讀）。
"""

import os
from flask import Flask
from dotenv import load_dotenv

load_dotenv()

from extensions import db
from models import Prompt_Template
from services.classify_v2 import DEFAULT_PROMPT_LEADERSHIP, DEFAULT_PROMPT_CAREER
from services.subcategory_methodology import QUESTION_LEADERSHIP, QUESTION_CAREER

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL") or os.environ.get(
    "SQLALCHEMY_DATABASE_URI"
)
db.init_app(app)


def seed():
    with app.app_context():
        seeds = [
            (QUESTION_LEADERSHIP, DEFAULT_PROMPT_LEADERSHIP),
            (QUESTION_CAREER, DEFAULT_PROMPT_CAREER),
        ]
        for key, content in seeds:
            existing = Prompt_Template.query.get(key)
            if existing:
                print(f"prompt_key='{key}' 已存在，略過（如需重置請先手動刪除）")
                continue
            row = Prompt_Template(
                prompt_key=key,
                draft_content=content,
                live_content=content,
                draft_validated=True,  # 初始值等同正式版，視為已驗證
            )
            db.session.add(row)
            print(f"已新增 prompt_key='{key}'")
        db.session.commit()
        print("完成")


if __name__ == "__main__":
    seed()