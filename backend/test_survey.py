#!/usr/bin/env python
"""
測試腳本：模擬前端建立問卷的請求
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import json
from app import app

# 模擬前端發送的 payload
test_payload = {
    "title": "測試問卷標題",
    "description": "這是一個測試問卷",
    "questions": [
        {
            "id": "test-1",
            "type": "short",
            "title": "您的姓名是？",
            "required": True,
            "options": []
        }
    ],
    "user_id": 1
}

print("[TEST] ========== 測試建立問卷 ==========")
print(f"[TEST] 發送 payload: {json.dumps(test_payload, ensure_ascii=False, indent=2)}")

with app.test_client() as client:
    try:
        response = client.post('/api/surveys',
                             data=json.dumps(test_payload),
                             content_type='application/json')

        print(f"\n[TEST] 回應狀態碼: {response.status_code}")
        print(f"[TEST] 回應內容: {response.get_json()}")

        if response.status_code == 201:
            print("\n[✓] 測試成功！")
        else:
            print(f"\n[✗] 測試失敗，狀態碼: {response.status_code}")

    except Exception as e:
        print(f"\n[ERROR] 測試過程中發生例外: {str(e)}")
        import traceback
        traceback.print_exc()

print("\n[TEST] ========== 測試完成 ==========")
