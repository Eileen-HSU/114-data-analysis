#!/usr/bin/env python
"""
手動 smoke test：用真的 Gemini API 呼叫一次（確認金鑰、網路、模型名稱）。

原本 import 已經不在 requirements 裡的舊 SDK（google.generativeai），在任何
環境都會 ModuleNotFoundError；改用專案實際使用的 services.gemini_client
（google-genai）。沒有設定 GEMINI_API_KEY（或 GOOGLE_API_KEY）時明確 SKIP，
不假裝成功。

    cd backend
    GEMINI_API_KEY=... python3 tests/test_gemini.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()
if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or os.environ.get("PPT_SURVEY_AI_API_KEY")):
    print("SKIP: 沒有設定 GEMINI_API_KEY，略過真實 Gemini API smoke test")
    sys.exit(0)

from services import gemini_client  # noqa: E402
from services.safe_error import safe_error_summary  # noqa: E402

try:
    response = gemini_client.GenerativeModel("gemini-3.1-flash-lite").generate_content("請說一句話測試")
except Exception as exc:  # 真的失敗：非 0 結束，訊息去除敏感資訊
    print("[FAIL] Gemini API 呼叫失敗：", safe_error_summary(exc))
    sys.exit(1)
text = (getattr(response, "text", "") or "").strip()
print(("[PASS] " if text else "[FAIL] ") + "Gemini 回應：" + (text[:80] or "（空白）"))
sys.exit(0 if text else 1)
