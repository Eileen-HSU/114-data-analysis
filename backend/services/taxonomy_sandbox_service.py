"""
services/taxonomy_sandbox_service.py

Admin Sandbox：讓 Admin 用「指定的某個 Taxonomy Version」（可以是
published、draft、in_review，也可以是 archived——見本檔案開頭關於
archived 的說明）試跑一批文字，直接看 production 等級的分類邏輯會怎麼
判斷，但完全不寫入任何正式資料。

【不寫入的架構保證，不是「記得不要寫」這種人為紀律】
這個檔案只 import 以下四個函式，全部經過確認完全不觸碰 DB 寫入：
    - services.taxonomy_service.get_taxonomy_version()          唯讀
    - services.taxonomy_service.build_classification_prompt()   純計算
    - services.taxonomy_service.methodology_lookup_for_taxonomy_version()  純計算
    - services.classify_v2.classify_response_multi_segment()    純計算（含
      Gemini 呼叫，但函式本身不 db.session.add/commit 任何東西——DB
      寫入是 routes/classifications/classification.py 的
      _persist_segmentation_result() 才會做的事，這裡完全不 import 它）
這個檔案裡不會出現 Response_Classification、Uploaded_Answer 的
db.session.add，也不會呼叫 taxonomy_service.py 裡任何一個會寫 DB 的
函式（update_category / add_category / delete_category /
reorder_categories / clone_taxonomy_version / publish_taxonomy_version）。
對應的測試會在跑完 sandbox 後驗證這兩張表的筆數完全沒變。

【關於 archived 版本】
API 層允許測試 archived 版本（Admin 可能需要做歷史版本比較、問題
重現、regression 診斷），因此這裡的驗證不會擋 status == "archived"。
但這只是 API 層的允許，不代表鼓勵——前端預設版本選單只列
published/draft/in_review，archived 版本要另外展開「顯示封存版本」
才看得到，並清楚標示「封存版本」，避免 Admin 誤以為那是目前有效的
候選版本。
"""

from services.classify_v2 import classify_response_multi_segment
from services.taxonomy_service import (
    get_taxonomy_version,
    build_classification_prompt,
    methodology_lookup_for_taxonomy_version,
    PublishedTaxonomyIntegrityError,
)

# ── 批次上限：獨立於 taxonomy_generation_service 的常數，數值刻意
#    小很多——sandbox 是 Admin 手動貼幾則測試文字，不是「歸納一整批
#    問卷回答」，不該共用同一組上限，兩邊之後也可能各自調整，共用
#    反而會互相牽制。────────────────────────────────────────────
MAX_ANSWER_COUNT = 20
MAX_SINGLE_ANSWER_CHARS = 2000
MAX_TOTAL_ANSWER_CHARS = 20_000


class SandboxValidationError(RuntimeError):
    """輸入不合法（topic/version 找不到、answer_texts 格式或大小超限、
    version 沒有 categories 等）。呼叫端（route）應轉成 4xx，且這個
    例外一律代表「完全沒有呼叫 Gemini」。"""


class SandboxExecutionError(RuntimeError):
    """理論上的防禦性例外：目前 classify_response_multi_segment() 本身
    的設計是「吞掉 Gemini/解析失敗，轉成帶 error_detail 的正常回傳值」
    （跟 production classification 完全一致的既有行為，這裡不去改
    它），所以正常情況下這個例外不會被觸發。保留它只是防禦未來萬一
    有真的會往外拋例外的路徑；Gemini 失敗時 sandbox 實際上會回傳
    HTTP 200，"segmentation_status"/segment "status" 帶著失敗原因，
    這跟 methodology_not_found 是同一種「原樣透傳診斷資訊」的模式。"""


def _validate_answer_texts(answer_texts):
    if not isinstance(answer_texts, list) or not answer_texts:
        # 防禦性檢查：正常情況下 route 層已經先擋掉這個情況回 400，
        # 這裡出現代表有其他呼叫端跳過 route 直接呼叫這個函式。
        raise SandboxValidationError("answer_texts 必須是非空陣列")

    cleaned = [text.strip() for text in answer_texts if isinstance(text, str) and text.strip()]
    if not cleaned:
        raise SandboxValidationError("answer_texts 沒有任何可用的非空文字")

    if len(cleaned) > MAX_ANSWER_COUNT:
        raise SandboxValidationError(
            f"answer_texts 數量 {len(cleaned)} 超過上限 {MAX_ANSWER_COUNT}，請縮小這批測試文字的範圍"
        )

    total_chars = 0
    for i, text in enumerate(cleaned):
        if len(text) > MAX_SINGLE_ANSWER_CHARS:
            raise SandboxValidationError(
                f"第 {i + 1} 筆測試文字長度 {len(text)} 字，超過單筆上限 {MAX_SINGLE_ANSWER_CHARS} 字"
            )
        total_chars += len(text)
    if total_chars > MAX_TOTAL_ANSWER_CHARS:
        raise SandboxValidationError(
            f"這批測試文字總字數 {total_chars}，超過上限 {MAX_TOTAL_ANSWER_CHARS}，請縮小範圍"
        )

    return cleaned


def run_sandbox_classification(topic_key: str, version_id: int, answer_texts: list) -> dict:
    """
    Args:
        topic_key, version_id: 指定要用哪一版 Taxonomy 試跑。
        answer_texts: 這次要測試的文字（未遮罩），逐筆用
            classify_response_multi_segment() 的正式流程處理。

    Returns:
        {
            "topic_key": ...,
            "taxonomy_version": {"version_id", "version_number", "status"},
            "results": [
                {"input": ..., "segmentation_status": ..., "segmentation_error_detail": ..., "segments": [...]},
                ...
            ],
        }

    Raises:
        SandboxValidationError: topic/version 找不到、不屬於該
            topic、沒有 categories、answer_texts 不合法或超限。
        SandboxExecutionError: Gemini 呼叫或輸出解析失敗。

    這個函式完全不 db.session.add/commit 任何東西（見本檔開頭說明），
    呼叫端（route）也不應該在拿到結果後自行補寫任何 DB。
    """
    version = get_taxonomy_version(topic_key, version_id)
    if version is None:
        raise ValueError(f"topic_key={topic_key!r} 找不到 version_id={version_id}")
    if not version.categories:
        raise SandboxValidationError(
            f"topic_key={topic_key!r} version_id={version_id} 沒有任何 category，無法測試"
        )

    cleaned_answers = _validate_answer_texts(answer_texts)

    try:
        prompt_content = build_classification_prompt(version)
    except PublishedTaxonomyIntegrityError as e:
        raise SandboxValidationError(str(e)) from e

    category_lookup = methodology_lookup_for_taxonomy_version(version)

    results = []
    for text in cleaned_answers:
        try:
            result = classify_response_multi_segment(text, prompt_content, topic_key, category_lookup=category_lookup)
        except Exception as e:
            print("[SANDBOX ERROR][GEMINI_CALL_FAILED]", repr(e))
            raise SandboxExecutionError(f"分類過程發生錯誤：{e}") from e
        results.append({
            "input": text,
            "segmentation_status": result["segmentation_status"],
            "segmentation_error_detail": result["segmentation_error_detail"],
            "segments": result["segments"],
        })

    return {
        "topic_key": topic_key,
        "taxonomy_version": {
            "version_id": version.version_id,
            "version_number": version.version_number,
            "status": version.status,
        },
        "results": results,
    }
