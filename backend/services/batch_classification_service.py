"""

批次分類協調服務：對「同一個可比較群組」（survey 的同一 question_id，
或 Excel 的同一 upload_batch_id + source_column）內的多筆回答，先做
TF-IDF 去重判斷，再決定每一筆是要完整跑一次分類，還是可以嘗試沿用
既有結果（不管是這批次剛算出來的，還是資料庫裡舊的已分析回答）。

設計原則（對應已定案的架構）：
- 這裡完全不碰 Gemini 對「已知答案要不要重複分類」這件事之外的邏輯
  ——實際呼叫 Gemini 的動作，一律透過既有的
  classify_v2.classify_response_multi_segment()，這個檔案不重新
  實作分類/拆分邏輯，也不修改 classify_v2.py / segmentation_service.py /
  privacy_service.py / response_dedup_service.py。
- duplicate 的沿用判斷分兩層：
    第一層（軟性）：response_dedup_service.dedupe_by_similarity()，
        cosine similarity 篩出候選。
    第二層（硬性、決定性）：_relocate_segments()，把候選代表項的每個
        segment 原文，逐字在這筆自己的原文裡重新定位。全部找得到、
        依序不重疊，才真正沿用；任何一段找不到，整筆 fallback 成
        完整呼叫 classify_response_multi_segment()。
  這個二層設計保證：就算 TF-IDF 誤判了兩則其實不夠像的文字為候選，
  也不會產生錯誤資料，最多只是白白多驗證一次、退回正常流程。
- 這裡的比對全部發生在「原文」層級（未遮罩），因為這一步完全是
  後端本地字串比對，不會送去 Gemini，不受 PII masking 邊界規範。
- 不寫 DB。這個檔案只負責「決定每筆 pending 項目最終的分類結果」，
  DB 寫入交給呼叫端（routes/classifications/classification.py）。
"""

from typing import Any, Dict, List, Optional

from services.classify_v2 import classify_response_multi_segment
from services.response_dedup_service import dedupe_by_similarity


def _relocate_segments(
    candidate_segments: List[Dict[str, Any]],
    candidate_answer_text: str,
    target_answer_text: str,
) -> Optional[List[Dict[str, Any]]]:
    """
    把候選代表項（candidate）已驗證通過的每個 segment，依序在
    target_answer_text 裡逐字重新定位。

    Args:
        candidate_segments: 候選代表項的 segments，每個元素至少要有
            "orig_start"、"orig_end"，其餘任意分類欄位（main_category
            等）會原樣沿用進回傳結果。
        candidate_answer_text: 候選代表項自己的原文，用來切出每個
            segment 實際的文字內容。
        target_answer_text: 這筆待處理回答自己的原文，是重新定位的
            目標字串。

    Returns:
        全部 segment 都成功定位時，回傳新的 segment 清單（orig_start/
        orig_end 是 target_answer_text 自己的座標，其餘分類欄位原樣
        沿用自 candidate_segments 對應的元素）。
        只要有任何一段定位失敗（找不到、或會跟前一段重疊），回傳
        None，呼叫端應該視為整筆沿用失敗，改用完整分類流程處理。

    純本地字串比對，不呼叫 Gemini、不需要位置對照表——candidate 跟
    target 都是原文，直接逐字搜尋即可。
    """
    if not candidate_segments:
        return None  # 代表項本身沒有任何 segment，沒有東西可以沿用

    relocated: List[Dict[str, Any]] = []
    search_from = 0

    # 依 orig_start 排序，確保依序搜尋、天然保證不重疊
    ordered = sorted(candidate_segments, key=lambda s: s["orig_start"])

    for seg in ordered:
        segment_text = candidate_answer_text[seg["orig_start"]:seg["orig_end"]]

        if not segment_text:
            return None  # 空字串片段沒有意義，視為定位失敗

        found_at = target_answer_text.find(segment_text, search_from)
        if found_at == -1:
            return None  # 找不到，整筆定位失敗

        new_start = found_at
        new_end = found_at + len(segment_text)

        relocated_seg = dict(seg)  # 複製一份，保留除了座標以外的所有分類欄位
        relocated_seg["orig_start"] = new_start
        relocated_seg["orig_end"] = new_end
        relocated.append(relocated_seg)

        search_from = new_end  # 下一段只往後找，天然保證依序不重疊

    return relocated


def run_batch_analysis(
    existing_references: List[Dict[str, Any]],
    pending_items: List[Dict[str, Any]],
    prompt_content: str,
    question_type: str,
) -> List[Dict[str, Any]]:
    """
    對外主要介面。輸入一批「已分析回答」（可作為沿用參考，但不會被
    重新處理）與一批「待處理回答」，回傳每個待處理回答最終的分類結果。

    Args:
        existing_references: 已經分析過、可以被沿用參考的回答。
            每個元素：{"identifier": Any, "answer_text": str,
                      "segments": [{"orig_start": int, "orig_end": int,
                                    ...分類欄位}, ...]}
        pending_items: 這次真正要處理的回答。
            每個元素：{"identifier": Any, "answer_text": str}
        prompt_content: 對應這個 question_type 的分類 prompt 內容。
        question_type: leadership_and_dept / career_and_feedback。

    Returns:
        跟 pending_items 順序、數量一致的清單，每個元素形狀跟
        classify_response_multi_segment() 的回傳值相同（多了一個
        "reused_from" 欄位，標記這筆沿用自哪個 identifier，全新處理
        則為 None；這個欄位僅供除錯/統計用途，不影響呼叫端寫入邏輯，
        呼叫端可以選擇忽略它）：
        {
            "segmentation_status": ...,
            "segmentation_error_detail": ...,
            "segments": [...],
            "reused_from": identifier or None,
        }

    這裡不寫 DB，也不呼叫 response_dedup_service.py 以外、classify_v2.py
    以外的分類邏輯。
    """
    if not pending_items:
        return []

    # ── 組合清單：existing_references 排在前面，pending_items 排在後面 ──
    # dedupe_by_similarity() 的規則是「歸到第一個出現的索引」，
    # 把已分析回答排在前面，天然讓演算法優先判斷新回答像不像舊回答，
    # 不需要額外寫邏輯去「優先比對舊資料」。
    combined_texts = (
        [ref["answer_text"] for ref in existing_references]
        + [item["answer_text"] for item in pending_items]
    )
    n_existing = len(existing_references)

    keep_indices, duplicate_map = dedupe_by_similarity(combined_texts)
    keep_indices_set = set(keep_indices)

    # pending_items 在 combined_texts 裡的索引範圍是 [n_existing, n_existing+len(pending_items))
    def _combined_index(pending_local_index: int) -> int:
        return n_existing + pending_local_index

    def _is_existing(combined_index: int) -> bool:
        return combined_index < n_existing

    # ── 第一步：找出這批 pending_items 裡，哪些需要「全新處理」 ──
    # （在 keep_indices 裡的，代表 TF-IDF 沒有幫它找到任何可沿用對象）
    fresh_results: Dict[int, Dict[str, Any]] = {}  # combined_index -> 分類結果

    for local_i, item in enumerate(pending_items):
        combined_i = _combined_index(local_i)
        if combined_i in keep_indices_set:
            result = classify_response_multi_segment(
                item["answer_text"], prompt_content, question_type
            )
            fresh_results[combined_i] = result

    # ── 建立「combined_index -> 原文 + segments」的查詢表 ──
    # 代表項可能來自 existing_references（舊資料，segments 已知），
    # 也可能來自本批次剛算出來的 fresh_results（segments 剛算好）。
    def _get_candidate(combined_index: int):
        if _is_existing(combined_index):
            ref = existing_references[combined_index]
            return ref["answer_text"], ref["segments"]
        else:
            local_i = combined_index - n_existing
            result = fresh_results.get(combined_index)
            if result is None:
                return None, None
            return pending_items[local_i]["answer_text"], result["segments"]

    # ── 第二步：處理 duplicate（含 fallback）──
    final_results: List[Optional[Dict[str, Any]]] = [None] * len(pending_items)

    for local_i, item in enumerate(pending_items):
        combined_i = _combined_index(local_i)

        if combined_i in keep_indices_set:
            # 全新處理過的，直接用剛才算好的結果
            result = dict(fresh_results[combined_i])
            result["reused_from"] = None
            final_results[local_i] = result
            continue

        # 這是 duplicate_map 裡的項目，找它的代表項
        representative_combined_i = duplicate_map[combined_i]
        candidate_answer_text, candidate_segments = _get_candidate(representative_combined_i)

        relocated = None
        if candidate_answer_text is not None:
            relocated = _relocate_segments(
                candidate_segments, candidate_answer_text, item["answer_text"]
            )

        if relocated is not None:
            # 沿用成功：組出結果，segmentation_status 視為 completed
            # （這則回答的拆分順利「完成」，只是完成的手段是定位沿用）
            representative_identifier = (
                existing_references[representative_combined_i]["identifier"]
                if _is_existing(representative_combined_i)
                else pending_items[representative_combined_i - n_existing]["identifier"]
            )
            final_results[local_i] = {
                "segmentation_status": "completed",
                "segmentation_error_detail": None,
                "segments": relocated,
                "reused_from": representative_identifier,
            }
        else:
            # 定位失敗，fallback 成完整處理，比照一般回答
            result = classify_response_multi_segment(
                item["answer_text"], prompt_content, question_type
            )
            result = dict(result)
            result["reused_from"] = None
            final_results[local_i] = result

    return final_results