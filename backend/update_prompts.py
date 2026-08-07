"""

一次性腳本：把 classify_v2.py 裡更新過的 prompt（含次要類別支援），
推進資料庫，走正式的「更新草稿 → 測試 → 發布」流程。

【為什麼需要這支腳本】
    run_classification.py 實際呼叫的是資料庫裡 Prompt_Template.live_content，
    不是 classify_v2.py 裡的常數本身。改了 .py 檔案的 prompt 內容，
    不會自動反映到資料庫，必須執行這支腳本才會真的生效。

【使用方式】
    python3 update_prompts.py

跟 seed_prompt_templates.py 一樣，這裡建立最小的 Flask app，
不依賴完整的 app.py。
"""

import os
import time
from flask import Flask
from dotenv import load_dotenv

load_dotenv()

from extensions import db
from services.prompt_admin_service import update_draft, test_draft_prompt, publish_prompt
from services.classify_v2 import DEFAULT_PROMPT_LEADERSHIP, DEFAULT_PROMPT_CAREER
from services.subcategory_methodology import QUESTION_LEADERSHIP, QUESTION_CAREER

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL") or os.environ.get(
    "SQLALCHEMY_DATABASE_URI"
)
db.init_app(app)


def update_and_publish(prompt_key: str, new_content: str):
    print(f"--- {prompt_key} ---")

    update_draft(prompt_key, new_content)
    print("  已更新草稿")

    result = test_draft_prompt(prompt_key)
    print(f"  測試結果：格式合法比例 {result['format_valid_rate']:.0%}，"
          f"跟黃金標籤一致比例 {result['accuracy_vs_golden']:.0%}")

    if not result["can_publish"]:
        print("  ⚠️ 測試未通過，不會發布，請檢查 prompt 內容是否有誤")
        for d in result["details"]:
            if not d["is_format_valid"]:
                print(f"    格式錯誤：{d['answer_text'][:20]}... -> {d['actual_sub_category']}")
        return

    publish_prompt(prompt_key)
    print("  ✅ 已發布到正式版")


def main():
    with app.app_context():
        update_and_publish(QUESTION_LEADERSHIP, DEFAULT_PROMPT_LEADERSHIP)
        print()
        print("等待 30 秒，避免兩組測試的呼叫次數疊加超過 rate limit...")
        time.sleep(30)
        update_and_publish(QUESTION_CAREER, DEFAULT_PROMPT_CAREER)


if __name__ == "__main__":
    main()