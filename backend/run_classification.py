"""

讀取 vine滿意度質化資料.xlsx，對每一題的每一則有效回答呼叫 Gemini 分類，
存成 CSV，供後續跟人工分類結果（0727網站使用版本.md）比對。

【使用前準備】
    1. 確認 .env 或環境變數已設定 GEMINI_API_KEY
    2. pip install google-generativeai pandas openpyxl
    3. 把這個檔案、classify_v2.py、subcategory_methodology.py
       放在同一個資料夾底下
    4. 把 vine滿意度質化資料_部門標記_隨機_.xlsx 也放在同一個資料夾
       （或修改下面 EXCEL_PATH 指到正確路徑）

【執行】
    python3 run_classification.py

執行完會在同資料夾產生 classification_results.csv，
欄位：respondent_id, question, answer_text,
      ai_main_category, ai_sub_category, ai_reasoning, ai_summary,
      ai_confidence, ai_methodology, ai_citation, status
"""

import csv
import os
import time

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

from flask import Flask
from extensions import db
from services.classify_v2 import (
    classify_response_v2,
    is_text_response,
    QUESTION_LEADERSHIP,
    QUESTION_CAREER,
)

# classify_response_v2 現在會查資料庫讀取正式版 prompt（Prompt_Template.live_content），
# 所以這支腳本需要建立 Flask app context 才能執行，跟 seed_prompt_templates.py 同樣的做法。
app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL") or os.environ.get(
    "SQLALCHEMY_DATABASE_URI"
)
db.init_app(app)

EXCEL_PATH = "vine滿意度質化資料（部門標記＋隨機）ㄐㄠ.xlsx"
OUTPUT_PATH = "classification_results.csv"

# Excel 欄位對應到哪個題目的分類架構
COLUMN_QUESTION_MAP = {
    "針對主管領導和部門合作這兩項，如果您有機會直接向管理層提出各一項建議，您會提出什麼建議？為什麼這項建議對您和公司很重要？": QUESTION_LEADERSHIP,
    "關於工作表現的回饋及職涯發展，您認為公司再強化或提供哪些協助將能更好地激勵您和您的同事？": QUESTION_CAREER,
}


def main():
    if not os.environ.get("GEMINI_API_KEY"):
        print("錯誤：找不到 GEMINI_API_KEY，請確認 .env 檔案或環境變數已設定")
        return

    with app.app_context():
        _run_all()


def _run_all():
    df = pd.read_excel(EXCEL_PATH)

    rows_to_process = []
    for col in df.columns:
        question_type = COLUMN_QUESTION_MAP.get(col)
        if question_type is None:
            print(f"警告：欄位「{col[:30]}...」不在 COLUMN_QUESTION_MAP 裡，略過")
            continue
        for idx, value in df[col].items():
            if is_text_response(value):
                rows_to_process.append(
                    {
                        "respondent_id": idx + 1,
                        "question": col,
                        "question_type": question_type,
                        "answer_text": str(value).strip(),
                    }
                )

    print(f"共 {len(rows_to_process)} 筆待分類回答，開始呼叫 Gemini...")

    results = []
    for i, row in enumerate(rows_to_process, 1):
        print(f"[{i}/{len(rows_to_process)}] 分類中：{row['answer_text'][:20]}...")

        classification = classify_response_v2(row["answer_text"], row["question_type"])

        # 失敗時自動重試一次：rate limit 這類暫時性錯誤，
        # 通常多等一下、重打一次就會成功，不需要整批重跑
        if classification["status"] == "failed":
            print(f"    第一次失敗（{classification['error_detail'][:50]}...），15秒後重試...")
            time.sleep(15)
            classification = classify_response_v2(row["answer_text"], row["question_type"])
            if classification["status"] == "failed":
                print(f"    重試後仍失敗：{classification['error_detail'][:50]}")

        results.append(
            {
                "respondent_id": row["respondent_id"],
                "question": row["question"][:30] + "...",
                "answer_text": row["answer_text"],
                "ai_main_category": classification["main_category"],
                "ai_sub_category": classification["sub_category"],
                "ai_secondary_sub_category": classification["secondary_sub_category"],
                "ai_reasoning": classification["reasoning"],
                "ai_summary": classification["summary"],
                "ai_confidence": classification["confidence"],
                "ai_methodology": classification["methodology"],
                "ai_citation": classification["citation"],
                "ai_secondary_methodology": classification["secondary_methodology"],
                "ai_secondary_citation": classification["secondary_citation"],
                "status": classification["status"],
                "error_detail": classification.get("error_detail"),
            }
        )

        # 免費方案 rate limit 是每分鐘 15 次請求，間隔設 5 秒比較安全
        # （60秒 / 15次 = 4秒，抓一點緩衝空間）
        time.sleep(5)

    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)

    print(f"\n完成！結果已存至 {OUTPUT_PATH}")

    # 簡單統計，跑完馬上看得到大概的狀況
    status_counts = {}
    for r in results:
        status_counts[r["status"]] = status_counts.get(r["status"], 0) + 1
    print("狀態統計：", status_counts)


if __name__ == "__main__":
    main()