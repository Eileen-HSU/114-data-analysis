"""
services/confidence_gate.py

Confidence Gate：AI 分類完成後，逐 segment 判斷這筆結果是否需要
特別標記給人工優先審查。

跟既有 review_status（response_classification.py 的
pending_review/confirmed/modified/excluded）是兩個獨立概念，刻意
不共用、不新增新的 review_status 值：
    - review_status   ：人工確認流程目前走到哪裡（User 自己的動作）
    - needs_human_review / review_flag_reason：AI 當時為什麼建議
      優先看這筆——是 AI 產出當下就固定的診斷紀錄，之後
      review_status 不管變成什麼，這兩個欄位都不會被清除或重算。

這裡只有一個純函式，不碰 DB、不呼叫 Gemini：
    - production（routes/classifications/classification.py 的
      _persist_segmentation_result()）呼叫它決定寫進
      Response_Classification 的欄位值
    - sandbox（services/taxonomy_sandbox_service.py）呼叫同一個函式，
      只把結果放進 API 回應，不寫任何 DB record
兩邊共用同一份判斷邏輯，不會出現「production 用一套規則、sandbox
用另一套」的不一致。
"""

# 第一版 operational threshold；之後會用人工標註結果評估是否要調整。
# confidence 是模型自陳信心分數（0.0～1.0），不是 calibrated
# probability，不代表「正確率」，不要在文件或 UI 上這樣描述它。
CONFIDENCE_THRESHOLD = 0.75

REASON_CLASSIFICATION_INCOMPLETE = "classification_incomplete"
REASON_METHODOLOGY_NOT_FOUND = "methodology_not_found"
REASON_INVALID_CONFIDENCE = "invalid_confidence"
REASON_LOW_CONFIDENCE = "low_confidence"


def evaluate_confidence_gate(segment: dict):
    """
    逐 segment 判斷是否需要人工審查。

    Args:
        segment: services.classify_v2 產生的單一 segment dict，
            至少要有 main_category / sub_category / status / confidence
            這幾個 key（跟 _build_classification_result() 的回傳格式
            一致）。

    Returns:
        (needs_human_review: bool, review_flag_reason: str | None)

    判斷優先序（同時符合多個原因時，回傳優先序最高的單一原因）：
        classification_incomplete > methodology_not_found
        > invalid_confidence > low_confidence

    第一版 classification_incomplete 只看 main_category / sub_category
    是否缺失，不把 reasoning / summary / citation 等欄位缺失算進去，
    刻意不擴大這輪 gate 的判斷範圍。
    """
    if not segment.get("main_category") or not segment.get("sub_category"):
        return True, REASON_CLASSIFICATION_INCOMPLETE

    if segment.get("status") == "methodology_not_found":
        return True, REASON_METHODOLOGY_NOT_FOUND

    confidence = segment.get("confidence")
    # bool 是 int 的子類別，isinstance(True, int) 會是 True，
    # 這裡要明確排除，避免 confidence=True 被誤判成合法數值 1。
    if (
        not isinstance(confidence, (int, float))
        or isinstance(confidence, bool)
        or not (0 <= confidence <= 1)
    ):
        return True, REASON_INVALID_CONFIDENCE

    if confidence < CONFIDENCE_THRESHOLD:
        return True, REASON_LOW_CONFIDENCE

    return False, None
