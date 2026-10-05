#!/usr/bin/env python
"""
手動驗證（需要真的 Gemini 金鑰）：規則 A —— 英文介面時，AI 的理由 / 摘要是英文，而且類別名稱沒被翻譯。

為什麼要手動驗證：自動測試只能證明「提示詞有要求英文」，沒辦法證明模型真的照做。最壞的情況是模型把
sub_category 也翻成英文：後端不會崩潰，而是對不上分類架構，被當成「新類別」(new_category) 悄悄塞進新類別候選，
比崩潰更難發現。所以這裡檢查的重點是：回傳的 sub_category 還在原本的分類清單裡。

沒有 GEMINI_API_KEY 時明確 SKIP（不假裝成功）：

    cd backend
    GEMINI_API_KEY=... python3 tests/test_gemini_output_language.py

會呼叫真的 Gemini 約 2 次（中文資料 + 英文介面、英文資料 + 中文介面各一次）。
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()
if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
    print("SKIP: 沒有設定 GEMINI_API_KEY，略過真實 Gemini 的輸出語言驗證")
    sys.exit(0)

from services import classify_v2  # noqa: E402
from services.safe_error import safe_error_summary  # noqa: E402

HAN = re.compile(r"[\u4e00-\u9fff]")
CATEGORIES = {
    "A1 教育訓練": ("職涯發展", "教育訓練與學習資源"),
    "A2 升遷制度": ("職涯發展", "升遷與晉升制度"),
    "B1 主管溝通": ("領導與合作", "主管的溝通與回饋"),
}
PROMPT = (
    "你是一個問卷回答分類助手，負責分析員工開放式回覆。\n"
    "請從下列固定分類清單中，為回覆選擇最適合的 main_category 與 sub_category：\n"
    + "\n".join(f"- {main} / {sub}（代碼 {code}）" for code, (main, sub) in CATEGORIES.items())
    + "\n只回傳 JSON。"
)
LOOKUP = lambda sub: {"main_category": next((m for m, s in CATEGORIES.values() if s == sub), None), "methodology": "m", "citation": "c"} \
    if sub in [s for _m, s in CATEGORIES.values()] else None
ALLOWED_SUBS = {s for _m, s in CATEGORIES.values()}

failed = 0


def check(label, ok, detail=""):
    global failed
    print(("[PASS] " if ok else "[FAIL] ") + label + (f"\n         {detail}" if detail else ""))
    failed += (not ok)


def run(texts, lang):
    try:
        return classify_v2._call_gemini_batch_classification(texts, PROMPT, LOOKUP, "", lang=lang)
    except Exception as exc:
        print("[FAIL] Gemini 呼叫失敗：", safe_error_summary(exc))
        sys.exit(1)


print("========== 中文資料 + 英文介面（規則 A 的核心）==========")
texts = ["希望公司多提供課程讓我們進修，目前學習資源太少。", "我的主管很少給回饋，溝通有點不順。"]
for text, item in zip(texts, run(texts, "en")):
    reasoning, summary = item.get("reasoning") or "", item.get("summary") or ""
    print(f"   輸入：{text}\n   -> {item.get('main_category')} / {item.get('sub_category')}\n   -> reasoning: {reasoning}\n   -> summary:   {summary}")
    check("reasoning 與 summary 沒有漢字（是英文）", not HAN.search(reasoning) and not HAN.search(summary) and bool(reasoning) and bool(summary))
    check("sub_category 仍在原本的分類清單裡（沒有被翻譯成英文）", item.get("sub_category") in ALLOWED_SUBS and item.get("status") == "completed",
          f"收到：{item.get('sub_category')!r}、狀態：{item.get('status')!r}")

print("\n========== 英文資料 + 中文介面 ==========")
texts = ["I would like more training courses and learning resources."]
for item in run(texts, "zh-TW"):
    reasoning = item.get("reasoning") or ""
    print(f"   -> {item.get('sub_category')}\n   -> reasoning: {reasoning}")
    check("reasoning 含中文（中文介面維持繁體中文）", bool(HAN.search(reasoning)))
    check("sub_category 仍在原本的分類清單裡", item.get("sub_category") in ALLOWED_SUBS and item.get("status") == "completed")

print("\n" + ("全部通過" if not failed else f"{failed} 項失敗"))
sys.exit(1 if failed else 0)
