"""

沙盒環境的核心邏輯：管理者編輯草稿 prompt 後，
    1. test_draft_prompt()：拿黃金測試組跑一次草稿版 prompt，
       檢查格式是否合法（硬性關卡），並計算準確率（參考指標，不卡關）
    2. publish_prompt()：只有 draft_validated=True 才允許執行，
       把草稿覆蓋到正式版

需要 Flask app context（因為要讀寫資料庫）。
"""

import time

from services.classify_v2 import _run_classification
from services.golden_test_set import GOLDEN_TEST_SET
from models import Prompt_Template
from extensions import db


def test_draft_prompt(prompt_key: str) -> dict:
    """
    用黃金測試組驗證草稿版 prompt。

    Returns:
        {
            "prompt_key": ...,
            "total": 測試筆數,
            "format_valid_count": 格式合法（sub_category 在固定清單裡）的筆數,
            "format_valid_rate": 格式合法比例,
            "accuracy_vs_golden": 跟黃金標籤完全一致的比例（僅供參考，不卡關）,
            "can_publish": bool，格式合法比例是否為 100%,
            "details": [每一筆的詳細比對結果],
        }
    """
    row = Prompt_Template.query.get(prompt_key)
    if row is None:
        raise ValueError(f"找不到 prompt_key='{prompt_key}'")

    golden_items = GOLDEN_TEST_SET.get(prompt_key, [])
    if not golden_items:
        raise ValueError(f"prompt_key='{prompt_key}' 沒有對應的黃金測試組")

    details = []
    format_valid_count = 0
    correct_count = 0

    for i, item in enumerate(golden_items):
        if i > 0:
            # 免費方案 rate limit 是每分鐘 15 次請求，間隔設 5 秒比較安全
            time.sleep(5)

        result = _run_classification(item["answer_text"], row.draft_content, prompt_key)

        # 失敗時自動重試一次（例如觸發 rate limit 這種暫時性錯誤）
        if result["status"] == "failed":
            time.sleep(15)
            result = _run_classification(item["answer_text"], row.draft_content, prompt_key)

        is_format_valid = result["status"] == "completed"
        is_correct = result["sub_category"] == item["expected_sub_category"]

        if is_format_valid:
            format_valid_count += 1
        if is_correct:
            correct_count += 1

        details.append(
            {
                "answer_text": item["answer_text"],
                "expected_sub_category": item["expected_sub_category"],
                "actual_sub_category": result["sub_category"],
                "is_format_valid": is_format_valid,
                "is_correct": is_correct,
            }
        )

    total = len(golden_items)
    format_valid_rate = format_valid_count / total
    can_publish = format_valid_rate == 1.0

    # 測試結果寫回資料庫：只有格式全部合法才標記為「已驗證」，
    # 否則重設為未驗證，避免用舊的驗證結果誤放行發布。
    row.draft_validated = can_publish
    db.session.commit()

    return {
        "prompt_key": prompt_key,
        "total": total,
        "format_valid_count": format_valid_count,
        "format_valid_rate": format_valid_rate,
        "accuracy_vs_golden": correct_count / total,
        "can_publish": can_publish,
        "details": details,
    }


def publish_prompt(prompt_key: str) -> dict:
    """
    把草稿版覆蓋到正式版。只有先跑過 test_draft_prompt() 且通過（100% 格式合法）
    才允許執行，避免管理者跳過測試直接發布壞掉的草稿。
    """
    row = Prompt_Template.query.get(prompt_key)
    if row is None:
        raise ValueError(f"找不到 prompt_key='{prompt_key}'")

    if not row.draft_validated:
        raise PermissionError(
            "草稿尚未通過測試（或編輯後尚未重新測試），不允許發布。"
            "請先呼叫 test_draft_prompt() 並確認 can_publish=True"
        )

    row.live_content = row.draft_content
    db.session.commit()

    return {"prompt_key": prompt_key, "published": True}


def update_draft(prompt_key: str, new_draft_content: str) -> dict:
    """
    管理者編輯草稿內容。編輯後自動把 draft_validated 重設為 False，
    強迫必須重新測試過才能再次發布，不能沿用編輯前的舊驗證結果。
    """
    row = Prompt_Template.query.get(prompt_key)
    if row is None:
        raise ValueError(f"找不到 prompt_key='{prompt_key}'")

    row.draft_content = new_draft_content
    row.draft_validated = False
    db.session.commit()

    return row.to_dict()