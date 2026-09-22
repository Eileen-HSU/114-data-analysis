"""
Human Review feedback loop：把「已經人工審核過」的 Response_Classification
結果，轉成可以插進 Gemini #2（批次分類，見 services/classify_v2.py
_call_gemini_batch_classification()）system_instruction 的「已審核
範例」文字區塊，讓未來的分類判斷能參考人工已經校準過的實際案例。

這個檔案只負責「查資料 + 組字串」，不呼叫 Gemini、不寫 DB、不修改
review_status / final_* 欄位——那些是 services/review_service.py 的
職責，這裡純粹是唯讀的下游消費者。

規則（對應本次需求文件）：
    - review_status = confirmed：AI 判斷已被人工直接接受（User 沒有
      進 Review Conversation），範例要用 AI original 欄位
      （main_category / sub_category / secondary_sub_category /
      reasoning），因為 final_* 欄位在 confirmed 情況下本來就是 None。
    - review_status = modified：曾進過 Review Conversation 並確認，
      範例要改用 final_* 欄位（Human Review 最終確認結果）——不可以
      用 AI original，那正是被人工修正掉的版本。
    - pending_review：人還沒看過，不能反過來影響未來分類判斷。
    - excluded：人工判定這筆不該納入分析，同樣不採用。
    - 只能使用「相同 taxonomy_version_id」的案例：不同 Topic、或同一
      Topic 不同版本的分類定義與判斷標準不互通，混用會讓範例本身
      自相矛盾。
    - taxonomy_version_id 為 NULL 的舊資料（Phase B 之前，沒有對應
      Taxonomy_Version 的分類結果）一律不採用，不猜測、不回填版本。
    - 每次最多回傳 8 筆：modified 優先，最多 5 筆；不足 8 筆時，用
      confirmed 補滿剩餘額度；modified 或 confirmed 任一邊筆數不足
      時，不強行湊數，也不會互相搶對方的名額。
    - 範例的 segment_text 一律先過既有的
      services.privacy_service.mask_pii()（沿用同一份 PII 遮罩規則，
      不重新實作、不跳過）；單筆遮罩失敗（PiiMaskingError）只 skip
      那一筆，不能讓整批範例查詢失敗，也不能讓呼叫端（正式分類流程）
      被拖垮。
"""

from models import Response_Classification
from classification_models import (
    REVIEW_STATUS_CONFIRMED,
    REVIEW_STATUS_MODIFIED,
)
from services.privacy_service import mask_pii, PiiMaskingError

# 單次批次分類最多帶入的已審核範例數量。
DEFAULT_LIMIT = 8
# modified 範例的優先名額上限（confirmed 只能補剩下的名額，不能反過來
# 擠壓 modified 的名額）。
MAX_MODIFIED = 5

# 查詢時的多抓緩衝倍率：因為個別範例可能在 mask_pii() 階段失敗被
# skip，抓多一點候選才不會因為少數幾筆遮罩失敗，就讓最終範例數量
# 明顯低於原本可以湊到的上限。純粹是查詢效率考量，不影響任何篩選
# 規則本身。
_OVERFETCH_FACTOR = 3
_OVERFETCH_MIN_EXTRA = 10


def _segment_text(row: Response_Classification) -> str:
    """從完整 answer_text 依 segment_start/segment_end 切出這個
    segment 的原文（未遮罩）。跟 services/review_service.py 的
    同名輔助函式邏輯完全一致，這裡獨立寫一份是因為兩個檔案是各自
    獨立的唯讀消費者，沒有共用狀態，沒必要為了三行邏輯互相 import。
    """
    return row.answer_text[row.segment_start:row.segment_end]


def _example_from_row(row: Response_Classification):
    """把一筆 Response_Classification 轉成一筆「已審核範例」dict。

    依 review_status 決定要用 AI original 還是 final_* 欄位；
    segment_text 會先過 mask_pii()，遮罩失敗時回傳 None，呼叫端
    （get_reviewed_examples）負責 skip 這一筆，不中斷整批查詢。
    """
    if row.review_status == REVIEW_STATUS_MODIFIED:
        main_category = row.final_main_category
        sub_category = row.final_sub_category
        secondary_sub_category = row.final_secondary_sub_category
        reasoning = row.final_reasoning
    else:
        # 只有 confirmed 會走到這裡（get_reviewed_examples 已經先用
        # SQL 篩掉 pending_review / excluded），用 AI original 欄位。
        main_category = row.main_category
        sub_category = row.sub_category
        secondary_sub_category = row.secondary_sub_category
        reasoning = row.reasoning

    try:
        masked_segment_text = mask_pii(_segment_text(row))
    except PiiMaskingError as e:
        print("[REVIEW_FEEDBACK][EXAMPLE_MASKING_FAILED]", repr(e))
        return None

    return {
        "classification_id": row.classification_id,
        "review_status": row.review_status,
        "segment_text": masked_segment_text,
        "main_category": main_category,
        "sub_category": sub_category,
        "secondary_sub_category": secondary_sub_category,
        "reasoning": reasoning,
    }


def _collect(query, quota: int) -> list:
    """依 quota 從 query（已經排好序）依序取值，逐筆呼叫
    _example_from_row()，遮罩失敗的直接跳過、不佔用名額，直到湊滿
    quota 或候選用盡為止。"""
    if quota <= 0:
        return []

    fetch_size = max(quota * _OVERFETCH_FACTOR, quota + _OVERFETCH_MIN_EXTRA)
    candidates = query.limit(fetch_size).all()

    examples = []
    for row in candidates:
        if len(examples) >= quota:
            break
        example = _example_from_row(row)
        if example is not None:
            examples.append(example)
    return examples


def get_reviewed_examples(taxonomy_version_id, limit: int = DEFAULT_LIMIT) -> list:
    """
    查詢可用於 feedback 的已審核範例（唯讀，不寫 DB）。

    Args:
        taxonomy_version_id: 這次批次分類實際使用的
            Taxonomy_Version.version_id。傳 None 代表這次分類沒有
            對應的 Published Taxonomy version（legacy 呼叫路徑、
            prompt_admin 黃金測試、或其他不走 Phase B taxonomy 的
            情境）——直接回傳空清單，不查詢、不誤用其他版本的審核
            紀錄，也不會意外把 taxonomy_version_id IS NULL 的舊資料
            當成範例撈出來。
        limit: 最多回傳幾筆，預設 8。

    Returns:
        依「modified 優先、最多 5 筆，confirmed 補滿剩餘額度」排列的
        範例 list；每筆遮罩失敗的候選會被排除，所以實際回傳筆數可能
        小於 limit（甚至為 0）。
    """
    if taxonomy_version_id is None or limit is None or limit <= 0:
        return []

    modified_quota = min(MAX_MODIFIED, limit)

    modified_query = (
        Response_Classification.query
        .filter_by(
            taxonomy_version_id=taxonomy_version_id,
            review_status=REVIEW_STATUS_MODIFIED,
        )
        .order_by(Response_Classification.classification_id.desc())
    )
    examples = _collect(modified_query, modified_quota)

    remaining = limit - len(examples)
    if remaining > 0:
        confirmed_query = (
            Response_Classification.query
            .filter_by(
                taxonomy_version_id=taxonomy_version_id,
                review_status=REVIEW_STATUS_CONFIRMED,
            )
            .order_by(Response_Classification.classification_id.desc())
        )
        examples.extend(_collect(confirmed_query, remaining))

    return examples[:limit]


def build_review_feedback_prompt(examples: list) -> str:
    """
    把 get_reviewed_examples() 回傳的範例，組成要插進 Gemini #2
    system_instruction 的文字區塊。

    examples 為空清單時回傳空字串："" + 任何字串 = 原字串，所以呼叫端
    （services/classify_v2.py）直接把回傳值接在 prompt_content 後面
    即可，不需要額外判斷要不要插入這段——這正是「無 example 時舊行為
    不變」的實作方式：沒有範例時，system_instruction 組出來的結果
    跟完全沒有這個 feedback loop 功能時逐字元相同。

    只組字串，不做任何 DB / Gemini 呼叫，不驗證 examples 內容是否合法
    （合法性由 get_reviewed_examples() 的查詢條件保證）。
    """
    if not examples:
        return ""

    lines = []
    for i, ex in enumerate(examples, start=1):
        secondary = ex["secondary_sub_category"] or "無"
        reasoning = ex["reasoning"] or "（無）"
        lines.append(
            f"{i}. 內容片段：「{ex['segment_text']}」\n"
            f"   人工確認結果：大類別「{ex['main_category']}」、"
            f"子類別「{ex['sub_category']}」、次要子類別「{secondary}」\n"
            f"   判斷依據：{reasoning}"
        )

    examples_block = "\n".join(lines)

    return f"""

【已通過人工審核的分類範例，僅供參考校準，不得覆蓋上方分類定義與判斷規則】
以下是過去經人工複核（Human Review）確認或修正過的實際案例，代表
這個 Topic 目前這一版分類標準對這些內容的正確判斷結果。請把這些
案例當作額外的校準參考：遇到語意相近的內容時，判斷方向應盡量與這些
已確認案例保持一致；但分類定義、可選類別清單與判斷規則仍完全以上方
內容為準，不得為了遷就這些範例而自創或誤用不存在的類別，範例之間也
請各自獨立參考，不要互相影響。

{examples_block}"""