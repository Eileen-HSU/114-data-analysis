"""
上傳 / 分析結果的診斷：前後端共用、穩定的 machine-readable code。

前端（frontend/src/pages/workspace/analysisDiagnostics.js）只依 code 顯示
在地化文字，不解析後端訊息字串；scripts/check-admin-status-mapping.mjs
會比對兩邊的 code 清單，任何一邊新增 / 改名另一邊沒跟上，檢查就會失敗。

計數規則（每個欄位、整批都一樣）：
    saved_answer_count = classified_count + failed_count
    classified_count：至少產生一筆有效（非 failed）分類列的回答數
    failed_count    ：routing 失敗、沒有分類架構、拆分失敗、分類全部失敗
                      等「沒有產生任何有效分類」的回答數
    整批的三個數字 = 各欄位加總
"""

ANALYSIS_STATUS_COMPLETED = "completed"
ANALYSIS_STATUS_PARTIAL = "partial"
ANALYSIS_STATUS_FAILED = "failed"
ANALYSIS_STATUS_NO_DATA = "no_data"
ANALYSIS_STATUSES = (ANALYSIS_STATUS_COMPLETED, ANALYSIS_STATUS_PARTIAL, ANALYSIS_STATUS_FAILED, ANALYSIS_STATUS_NO_DATA)

# ── 診斷 code（前端 analysisDiagnostics.js 的 DIAGNOSTIC_CODES 必須逐字一致）──
NO_PUBLISHED_TAXONOMY = "NO_PUBLISHED_TAXONOMY"        # 固定分類模式：主題沒有已發布的分類架構 / 沒有任何主題
ROUTING_UNDETERMINED = "ROUTING_UNDETERMINED"          # 固定分類模式：AI 判斷不出主題
ROUTING_API_FAILED = "ROUTING_API_FAILED"              # 判斷主題時 AI 呼叫失敗（429 / 5xx / timeout / 金鑰 / 回應格式）
SEGMENTATION_FAILED = "SEGMENTATION_FAILED"            # 拆分意義單元失敗
CLASSIFICATION_FAILED = "CLASSIFICATION_FAILED"        # 拆分成功但分類呼叫全部失敗
NO_MEANINGFUL_RESULTS = "NO_MEANINGFUL_RESULTS"        # 有處理但沒有可顯示的分類（沒有文字、或全是「無具體建議」）
PARTIAL_CLASSIFICATION = "PARTIAL_CLASSIFICATION"      # 部分回答成功、部分失敗
OPEN_CLASSIFICATION_FAILED = "OPEN_CLASSIFICATION_FAILED"  # 開放式分類：AI 歸納分類架構失敗

DIAGNOSTIC_CODES = (
    NO_PUBLISHED_TAXONOMY,
    ROUTING_UNDETERMINED,
    ROUTING_API_FAILED,
    SEGMENTATION_FAILED,
    CLASSIFICATION_FAILED,
    NO_MEANINGFUL_RESULTS,
    PARTIAL_CLASSIFICATION,
    OPEN_CLASSIFICATION_FAILED,
)

# API 回應附帶的說明文字（給 API 呼叫端 / log）；畫面顯示由前端依 code 在地化。
MESSAGES = {
    NO_PUBLISHED_TAXONOMY: (
        "這個主題目前沒有已發布的分類架構，原始回答已保存，但沒有進行分類。請到 AI 管理發布分類架構後重新處理。",
        "This topic has no published taxonomy. The answers were saved but not classified; publish a taxonomy in AI admin and reprocess.",
    ),
    ROUTING_UNDETERMINED: (
        "AI 判斷不出這個欄位屬於哪個主題（固定分類模式不會自動建立主題）。原始回答已保存，可以到 AI 管理指派主題。",
        "The AI could not determine a topic for this column (fixed-taxonomy mode does not create topics). Answers were saved; assign a topic in AI admin.",
    ),
    ROUTING_API_FAILED: (
        "判斷主題時 AI 服務呼叫失敗，這個欄位沒有分類，也沒有建立自動主題。原始回答已保存，可以稍後在 AI 管理「未分類」重新判斷。",
        "The AI call failed while determining the topic, so this column was not classified and no automatic topic was created. Answers were saved; re-route them later in AI admin.",
    ),
    SEGMENTATION_FAILED: (
        "AI 拆分回答內容失敗，這些回答沒有分類結果。可以稍後在 AI 管理重新處理。",
        "The AI failed to split the answers into segments, so they were not classified. Retry later in AI admin.",
    ),
    CLASSIFICATION_FAILED: (
        "AI 分類呼叫失敗，這些回答沒有分類結果。可以稍後在 AI 管理重新處理。",
        "The AI classification call failed, so these answers were not classified. Retry later in AI admin.",
    ),
    NO_MEANINGFUL_RESULTS: (
        "資料已處理，但沒有可以顯示的分類結果（例如欄位沒有文字，或內容都沒有具體建議）。",
        "The data was processed but produced nothing to show (for example no text, or no concrete feedback).",
    ),
    PARTIAL_CLASSIFICATION: (
        "部分回答分類成功，部分失敗；失敗的回答已保存，可以稍後在 AI 管理重新處理。",
        "Some answers were classified and some failed; the failed ones were saved and can be retried in AI admin.",
    ),
    OPEN_CLASSIFICATION_FAILED: (
        "開放式分類需要 AI 歸納分類架構，但這一步失敗了，所以沒有分類。原始回答已保存，可以稍後重新處理。",
        "Open classification needs the AI to derive a taxonomy, and that step failed, so nothing was classified. Answers were saved; retry later.",
    ),
}


def message_for(code):
    zh, en = MESSAGES.get(code, (None, None))
    return zh, en


def build_column_diagnostic(saved, classified, failed, failure_code=None, failure_detail=None, displayed_groups=None):
    """一個欄位的 analysis_status / diagnostic_code。

    failure_code：這個欄位「沒有分類成功」的主因（routing / taxonomy /
    segmentation / classification），只在有失敗時使用。
    failure_detail：explain_failure() 的結果（AI_QUOTA_EXCEEDED 之類），給畫面補充原因。
    """
    if saved == 0:
        status, code = ANALYSIS_STATUS_NO_DATA, NO_MEANINGFUL_RESULTS
    elif classified == saved:
        status = ANALYSIS_STATUS_COMPLETED
        code = NO_MEANINGFUL_RESULTS if displayed_groups == 0 else None
    elif classified == 0:
        status, code = ANALYSIS_STATUS_FAILED, failure_code or CLASSIFICATION_FAILED
    else:
        status, code = ANALYSIS_STATUS_PARTIAL, PARTIAL_CLASSIFICATION
    zh, en = message_for(code)
    return {
        "analysis_status": status,
        "diagnostic_code": code,
        "diagnostic_message": zh,
        "diagnostic_message_en": en,
        "failure_code": (failure_detail or {}).get("code") if failed else None,
        "failure_message": (failure_detail or {}).get("message") if failed else None,
        "saved_answer_count": saved,
        "classified_count": classified,
        "failed_count": failed,
    }


def build_batch_diagnostic(columns, displayed_groups):
    saved = sum(c["saved_answer_count"] for c in columns)
    classified = sum(c["classified_count"] for c in columns)
    failed = sum(c["failed_count"] for c in columns)
    statuses = {c["analysis_status"] for c in columns if c["analysis_status"] != ANALYSIS_STATUS_NO_DATA}
    if not statuses:
        status, code = ANALYSIS_STATUS_NO_DATA, NO_MEANINGFUL_RESULTS
    elif statuses == {ANALYSIS_STATUS_COMPLETED}:
        status = ANALYSIS_STATUS_COMPLETED
        code = NO_MEANINGFUL_RESULTS if displayed_groups == 0 else None
    elif statuses == {ANALYSIS_STATUS_FAILED}:
        status = ANALYSIS_STATUS_FAILED
        codes = {c["diagnostic_code"] for c in columns if c["analysis_status"] == ANALYSIS_STATUS_FAILED}
        code = codes.pop() if len(codes) == 1 else CLASSIFICATION_FAILED
    else:
        status, code = ANALYSIS_STATUS_PARTIAL, PARTIAL_CLASSIFICATION
    zh, en = message_for(code)
    return {
        "analysis_status": status,
        "diagnostic_code": code,
        "diagnostic_message": zh,
        "diagnostic_message_en": en,
        "saved_answer_count": saved,
        "classified_count": classified,
        "failed_count": failed,
    }
