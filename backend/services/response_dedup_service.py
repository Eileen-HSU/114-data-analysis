"""

問卷開放式回答的「去重」模組：在送進 Gemini API 分類之前，先判斷哪些
回答彼此重複／高度相似，避免對完全相同或幾乎相同的內容重複呼叫 API。

這個模組只決定「要不要重複呼叫 Gemini」，不影響「要不要把原文存進
資料庫」——每一筆原始回答，不管有沒有被判定為重複，都還是要各自存
一筆進資料庫，只是分類結果可能是複製代表項的。這裡不接任何現有
分類流程，是否整合是後續另外決定的事。

設計依據（實測結論，不是常見預設做法）：

1. 「無意見」類回答（無 / 暫無 / 沒有建議…）用固定清單比對，不用 TF-IDF。
   原因：scikit-learn 預設的 TfidfVectorizer 會濾掉中文單字詞（例如「無」
   這種一個字的詞會直接從詞彙表消失），而且「暫無」「沒有」「無」這幾個
   詞意思相同、但斷詞後字面完全不同，詞級 TF-IDF 抓不到這種同義詞層級
   的相似性。固定清單比對反而更準確、更可控。

2. 有實質內容的回答，才用 TF-IDF，而且是「字元級 n-gram」（analyzer='char',
   ngram_range=(2,3)），不是詞級。字元級 n-gram 不依賴斷詞準不準，對
   「近乎逐字複製貼上」的重複內容偵測效果比詞級 TF-IDF 好很多。

threshold 預設 0.5，是拿真實資料實測調出來的數字，不是隨便設的常見值
（例如 0.8），沿用時不要自行改動這個預設值。
"""

import re
from typing import Dict, List, Tuple

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# ═══════════════════════════════════════════════════════════════
# 無意見清單（正規化後完全相符才算命中）
# ═══════════════════════════════════════════════════════════════
NO_CONTENT_PHRASES = {
    "無", "沒有", "暫無", "暫時沒有", "目前暫無", "目前沒有",
    "無意見", "沒意見", "沒有意見", "目前無意見",
    "謝謝", "無謝謝", "目前都很好", "都很好", "目前都好",
    "沒有建議", "沒有建議可以提出", "無建議",
    "目前覺得都還ok", "目前已經很好", "目前很好",
    "目前暫無謝謝", "暫無謝謝",
}

# 正規化時要一併把清單本身也正規化一次，保險起見（避免清單裡的字串
# 本身帶有這裡定義的標點符號時，比對邏輯不一致）。
_NORMALIZED_NO_CONTENT_PHRASES = None  # 延遲初始化，見 _normalize() 定義完之後

# 結尾的部門／場次標記，例如「（講師）」「(T1)」「（專案）」。
# 半形／全形括號都要處理，括號內最多抓 10 個字元，避免誤刪正常內容裡的括號
# （例如一段很長的括號說明，就不會被這個 pattern 誤判成 metadata 標記）。
_TRAILING_BRACKET_PATTERN = re.compile(r"[（(][^（）()]{0,10}[）)]\s*$")

# 常見標點符號與空白字元，比對前要去掉（全字串範圍去除，不是只去頭尾）。
_PUNCT_WHITESPACE_PATTERN = re.compile(r"[，。！？、,.!?\s]")


def _normalize(text: str) -> str:
    """
    正規化文字，供比對用：
    1. 反覆去除結尾的部門／場次標記（可能不只一組，例如「內容（講師）（T1）」）
    2. 去除常見標點符號與空白字元（整串去除，不只頭尾）
    """
    if text is None:
        return ""

    normalized = str(text).strip()

    # 反覆剝除結尾括號標記，直到剝不動為止
    while True:
        stripped = _TRAILING_BRACKET_PATTERN.sub("", normalized).strip()
        if stripped == normalized:
            break
        normalized = stripped

    normalized = _PUNCT_WHITESPACE_PATTERN.sub("", normalized)
    return normalized


_NORMALIZED_NO_CONTENT_PHRASES = {_normalize(p) for p in NO_CONTENT_PHRASES}


def is_no_content_response(text: str) -> bool:
    """判斷單一文字是不是屬於「無意見」清單（正規化後比對）。"""
    return _normalize(text) in _NORMALIZED_NO_CONTENT_PHRASES


def dedupe_by_similarity(
    texts: List[str], threshold: float = 0.5
) -> Tuple[List[int], Dict[int, int]]:
    """
    對一批文字做去重判斷，決定哪些真的需要各自送進 Gemini 分類。

    Args:
        texts: 一批問卷回答原文（list of str）。
        threshold: 字元級 TF-IDF cosine similarity 的重複判定門檻，
            預設 0.5（實測調出來的數字，不建議隨意更改）。

    Returns:
        (keep_indices, duplicate_map)
        keep_indices: 真的需要送去分類的索引清單（原始 texts 裡的索引，
            由小到大排序）。
        duplicate_map: {重複項的索引: 應該沿用哪個代表項索引}，
            代表項本身不會出現在這個字典的 key 裡（代表項在 keep_indices
            裡，不是"重複於別人"）。

    設計：
        第一層：先過一遍無意見清單，命中的全部歸到「該清單裡第一個
            出現」的索引底下，不進入 TF-IDF 計算。
        第二層：剩下有實質內容的回答，才用字元級 n-gram TF-IDF 算
            cosine similarity（計算前一樣先用 _normalize() 處理過，
            去掉結尾部門/場次標記與標點空白，理由跟第一層一致——
            正規化是「比對前」的處理，TF-IDF 相似度也是一種比對，
            不能只對無意見清單做正規化、卻讓 TF-IDF 吃到帶雜訊的原文），
            超過 threshold 就視為重複，一樣歸到第一個出現的索引底下。
            回傳的 keep_indices/duplicate_map 仍然對應原始 texts 的
            索引，不會因為內部用了正規化後的文字而跟著改變。

    邊界情況：
        - 輸入只有 0 或 1 筆時直接回傳，不做任何比對。
        - 有實質內容的部分如果全部是空字串（或其他導致 TF-IDF
          詞彙表為空的情況），TfidfVectorizer 會丟 ValueError，
          這裡用 try/except 接住，保守處理成這部分全部都不算重複
          （每一筆都各自送去分類，不要因為判斷不了而誤刪資料）。
    """
    n = len(texts)
    if n <= 1:
        return list(range(n)), {}

    keep_indices: List[int] = []
    duplicate_map: Dict[int, int] = {}

    # ── 第一層：無意見清單 ──
    no_content_representative = None
    substantive_indices: List[int] = []

    for i, text in enumerate(texts):
        if is_no_content_response(text):
            if no_content_representative is None:
                no_content_representative = i
                keep_indices.append(i)
            else:
                duplicate_map[i] = no_content_representative
        else:
            substantive_indices.append(i)

    # ── 第二層：有實質內容的回答，字元級 n-gram TF-IDF ──
    if len(substantive_indices) == 1:
        keep_indices.append(substantive_indices[0])

    elif len(substantive_indices) >= 2:
        substantive_texts = [_normalize(texts[i]) for i in substantive_indices]

        try:
            vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(2, 3))
            tfidf_matrix = vectorizer.fit_transform(substantive_texts)
            similarity_matrix = cosine_similarity(tfidf_matrix)

            # local index（相對於 substantive_texts）-> 代表項的 local index
            representative_of: Dict[int, int] = {}

            for local_i in range(len(substantive_texts)):
                if local_i in representative_of:
                    continue  # 已經被前面某個代表項收編，不用再當代表項
                representative_of[local_i] = local_i  # 自己是代表項

                for local_j in range(local_i + 1, len(substantive_texts)):
                    if local_j in representative_of:
                        continue
                    if similarity_matrix[local_i, local_j] >= threshold:
                        representative_of[local_j] = local_i

            for local_i, local_rep in representative_of.items():
                global_i = substantive_indices[local_i]
                if local_i == local_rep:
                    keep_indices.append(global_i)
                else:
                    global_rep = substantive_indices[local_rep]
                    duplicate_map[global_i] = global_rep

        except ValueError:
            # 詞彙表為空（例如全部是空字串）：保守處理成全部都不算重複，
            # 每一筆都各自送去分類。
            keep_indices.extend(substantive_indices)

    keep_indices.sort()
    return keep_indices, duplicate_map


def get_dedupe_stats(texts: List[str], threshold: float = 0.5) -> dict:
    """
    回傳去重前後的統計數字，方便寫報告或測試用。

    Returns:
        {
            "total": 總筆數,
            "needed_calls": 真的需要呼叫 Gemini 的筆數,
            "saved_calls": 省下的呼叫次數,
            "saved_ratio": 省下比例（0~1 之間的浮點數；total 為 0 時回傳 0.0）,
        }
    """
    total = len(texts)
    keep_indices, _duplicate_map = dedupe_by_similarity(texts, threshold=threshold)
    needed_calls = len(keep_indices)
    saved_calls = total - needed_calls
    saved_ratio = (saved_calls / total) if total > 0 else 0.0

    return {
        "total": total,
        "needed_calls": needed_calls,
        "saved_calls": saved_calls,
        "saved_ratio": saved_ratio,
    }