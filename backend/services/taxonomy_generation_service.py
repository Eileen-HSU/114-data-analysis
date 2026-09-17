"""
services/taxonomy_generation_service.py

Phase C 核心：Stage A（Taxonomy Generation）。輸入一批同一 Topic 的
開放式回答，讓 Gemini 依歸納式質性內容分析邏輯，一次歸納出一份完整、
跨整批資料一致的 taxonomy（不是逐筆回答各自命名），寫成一個新的
draft/in_review Taxonomy_Version，交給 Admin 人工審核（Phase D）。

跟 services/classify_v2.py（Stage B：Classification）刻意分開：
    - classify_v2.py：已知合法分類清單，對「單一」回答做封閉式分類。
    - 這裡：清單本身還不存在，對「一整批」回答做開放式歸納。
兩者的 Gemini 呼叫目的完全不同，共用的只有已經驗證過的 retry/
rate-limit 處理（_generate_with_retry）跟 JSON 解析（_parse_json），
直接從 classify_v2 import 重用，不重新發明第三套規則。

安全設計摘要：
    - Gemini 輸出必須是嚴格 JSON schema（見 _build_generation_prompt），
      解析後在寫入 DB 前完整驗證（_validate_and_normalize_categories），
      任何一項不合法就整批 fail-closed，不寫入任何一筆 Taxonomy_Version
      / Taxonomy_Category。
    - citation 不信任 Gemini 自由生成：只有在呼叫端明確提供的
      reference_citations 白名單裡才會被保留，其餘一律丟棄成 NULL，
      避免生成不存在的文獻／作者／年份／DOI（見需求文件第 4 節）。
    - 新版本一律 status=draft，source=ai_generated；不覆寫、不
      archive 既有 published 版本，也絕不呼叫
      services.taxonomy_service.publish_taxonomy_version()。
    - 全部寫入包在同一個 DB transaction：任何步驟失敗都 rollback，
      不留下孤兒 Topic（若這次才新建）、半套 Taxonomy_Version 或
      Taxonomy_Category。
"""

import json

from extensions import db
from services.classify_v2 import _generate_with_retry, _parse_json
from services.privacy_service import mask_pii, PiiMaskingError
from services.taxonomy_service import ensure_topic, get_next_version_number, TaxonomyVersionConflictError
from sqlalchemy.exc import IntegrityError
from taxonomy import (
    TAXONOMY_VERSION_STATUS_DRAFT,
    TAXONOMY_VERSION_SOURCE_AI_GENERATED,
)

import google.generativeai as genai


# ── Phase D：輸入批次安全上限（Phase C 遺留的 unresolved risk）───────
# 刻意不精算 Gemini token 數（避免引入額外依賴），改用簡單、可調的
# 數量/字數常數守門。超過時明確拒絕（422），不做偷偷截斷——截斷會讓
# Admin 誤以為整批資料都已經納入歸納，但「歸納式質性分析要跨整批
# 資料一致」的方法論本身就要求 Admin 清楚知道實際分析了哪些資料，
# 悄悄漏掉一部分違反這個前提。
MAX_ANSWER_COUNT = 500
MAX_SINGLE_ANSWER_CHARS = 2000
MAX_TOTAL_ANSWER_CHARS = 200_000


def _validate_batch_size(answer_texts: list):
    if len(answer_texts) > MAX_ANSWER_COUNT:
        raise TaxonomyGenerationValidationError(
            f"answer_texts 數量 {len(answer_texts)} 超過上限 {MAX_ANSWER_COUNT} 筆，"
            "請縮小這批資料的範圍後再試一次"
        )
    total_chars = 0
    for i, text in enumerate(answer_texts):
        length = len(text) if isinstance(text, str) else 0
        if length > MAX_SINGLE_ANSWER_CHARS:
            raise TaxonomyGenerationValidationError(
                f"第 {i + 1} 筆回答長度 {length} 字，超過單筆上限 {MAX_SINGLE_ANSWER_CHARS} 字"
            )
        total_chars += length
    if total_chars > MAX_TOTAL_ANSWER_CHARS:
        raise TaxonomyGenerationValidationError(
            f"這批回答總字數 {total_chars}，超過上限 {MAX_TOTAL_ANSWER_CHARS}，"
            "請縮小這批資料的範圍後再試一次"
        )


class TaxonomyGenerationError(RuntimeError):
    """Gemini 呼叫本身失敗（API 錯誤、逾時等），不是輸出格式問題。"""


class TaxonomyGenerationValidationError(RuntimeError):
    """Gemini 有回應，但輸出不是合法、完整、可信任的 taxonomy JSON。
    這個例外一律代表「沒有任何 DB 寫入」，呼叫端可以放心重試或
    調整輸入後再呼叫一次。"""


# ── 規則欄位可接受的型別：字串 / 字串陣列 / 物件（見需求文件第 3 節
#    「boundary_rules 可以是 JSON list/object，依目前 Taxonomy_Category
#    欄位實際設計」——欄位本身是 Text，這裡統一正規化成單一字串存入，
#    不需要為此新增欄位或改欄位型別）──
_RULE_FIELDS = ("include_rules", "exclude_rules", "boundary_rules")


def _normalize_rule_text(value, field_name: str, sub_category: str):
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, list):
        if not all(isinstance(item, str) for item in value):
            raise TaxonomyGenerationValidationError(
                f"sub_category={sub_category!r} 的 {field_name} 陣列元素必須全部是字串"
            )
        joined = "；".join(item.strip() for item in value if item.strip())
        return joined or None
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    raise TaxonomyGenerationValidationError(
        f"sub_category={sub_category!r} 的 {field_name} 型別不正確：{type(value).__name__}"
    )


def _validate_and_normalize_categories(raw_categories, reference_citations=None) -> list:
    """
    在任何 DB 寫入之前，完整驗證 Gemini 回傳的 categories 陣列。
    任何一項不合法就整批拋 TaxonomyGenerationValidationError，
    呼叫端據此保證「不建立半套 Taxonomy_Version、不留孤兒 category」。

    驗證項目（對應需求文件第 8 節）：
        - categories 是非空陣列
        - 每個元素是物件，main_category / sub_category / definition
          都是非空字串（definition 是硬性要求，不像既有 legacy 資料
          可以只有 source_raw_text）
        - 同一批 sub_category 不得重複
        - include_rules / exclude_rules / boundary_rules 型別正確
          （str / list[str] / dict，其餘型別拒絕）
        - methodology 若有值必須是字串
        - citation 只有在 reference_citations 白名單裡才保留，其餘
          一律強制設為 None（見本檔開頭說明，防止 hallucination）

    sort_order 刻意不採信 Gemini 給的數值：回傳的清單依「模型輸出的
    陣列順序」重新指派 1..N，保證合法且穩定，不依賴模型是否誠實給了
    連續、不重複的數字。
    """
    if not isinstance(raw_categories, list) or not raw_categories:
        raise TaxonomyGenerationValidationError("categories 必須是非空陣列")

    reference_citation_set = {c.strip() for c in (reference_citations or []) if isinstance(c, str) and c.strip()}

    normalized = []
    seen_sub_categories = set()

    for i, raw in enumerate(raw_categories):
        label = f"第 {i + 1} 個 category"
        if not isinstance(raw, dict):
            raise TaxonomyGenerationValidationError(f"{label} 不是 JSON 物件")

        main_category = raw.get("main_category")
        sub_category = raw.get("sub_category")
        definition = raw.get("definition")

        if not isinstance(main_category, str) or not main_category.strip():
            raise TaxonomyGenerationValidationError(f"{label} 缺少合法的 main_category")
        if not isinstance(sub_category, str) or not sub_category.strip():
            raise TaxonomyGenerationValidationError(f"{label} 缺少合法的 sub_category")

        sub_category = sub_category.strip()

        if not isinstance(definition, str) or not definition.strip():
            raise TaxonomyGenerationValidationError(
                f"sub_category={sub_category!r} 缺少 definition，"
                "AI-generated taxonomy 不允許省略（見需求文件第 8 節）"
            )

        if sub_category in seen_sub_categories:
            raise TaxonomyGenerationValidationError(f"sub_category 重複出現：{sub_category!r}")
        seen_sub_categories.add(sub_category)

        rule_fields = {
            field: _normalize_rule_text(raw.get(field), field, sub_category)
            for field in _RULE_FIELDS
        }

        methodology = raw.get("methodology")
        if methodology is not None and not isinstance(methodology, str):
            raise TaxonomyGenerationValidationError(
                f"sub_category={sub_category!r} 的 methodology 型別不正確（必須是字串或 null）"
            )
        methodology = (methodology.strip() or None) if isinstance(methodology, str) else None

        citation = raw.get("citation")
        if citation is not None and not isinstance(citation, str):
            raise TaxonomyGenerationValidationError(
                f"sub_category={sub_category!r} 的 citation 型別不正確（必須是字串或 null）"
            )
        citation = citation.strip() if isinstance(citation, str) else None
        if citation and citation not in reference_citation_set:
            # 不在白名單內：視為未經驗證的生成內容，一律丟棄，不寫入 DB。
            # 這是機制層面的防線，不只是靠 prompt 拜託模型不要編造。
            print(
                f"[TAXONOMY_GENERATION] 丟棄未經驗證的 citation "
                f"(sub_category={sub_category!r}, citation={citation!r})：不在 reference_citations 白名單內"
            )
            citation = None
        elif not citation:
            citation = None

        normalized.append({
            "main_category": main_category.strip(),
            "sub_category": sub_category,
            "definition": definition.strip(),
            **rule_fields,
            "methodology": methodology,
            "citation": citation,
        })

    return normalized


# ── Generation prompt：獨立於 classify_v2 的分類 prompt，不重用 ──────

_GENERATION_OUTPUT_SCHEMA = """只回傳以下 JSON 格式，不要加任何其他文字說明、不要用 markdown code fence：

{
  "categories": [
    {
      "main_category": "大類別名稱",
      "sub_category": "子類別名稱（建議含簡短代碼，例如 A1、A2）",
      "definition": "這個子類別在說什麼，必填，不可省略",
      "include_rules": "什麼樣的回覆內容應該歸入這個子類別",
      "exclude_rules": "什麼樣的內容不應該歸入這個子類別，或 null",
      "boundary_rules": "跟其他相近子類別的判斷界線，或 null",
      "methodology": "如果你能歸納出這個子類別對應的分析方法/理論名稱，填入簡短建議名稱；不確定就填 null，不要編造",
      "citation": "只有在下面提供的 reference 資料裡有明確對應時才填，否則一律填 null，絕對不可以自己生成作者、年份、期刊、DOI 或任何看起來像文獻的字串",
      "sort_order": 1
    }
  ]
}"""


def _build_generation_prompt(
    topic_title: str,
    question_text: str,
    global_instructions: str,
    reference_examples: list,
    reference_citations: list,
) -> str:
    intro = (
        "你正在對一批「同一份問卷、同一題」的開放式回覆做歸納式質性內容分析"
        "（inductive qualitative content analysis）。\n"
        f"這一題的主題是「{topic_title}」。"
    )
    if question_text:
        intro += f"\n問卷題目原文：{question_text}"

    core_rules = """
【你的任務】
請閱讀「全部」回覆之後，才開始歸納分類架構——不是針對每一則回覆各自
決定一個類別名稱。分類名稱必須跨整批資料一致：如果兩則回覆在講同一件
事，它們最後必須被歸進同一個 sub_category，而不是各自產生語意重複但
名稱不同的類別。

【嚴格禁止】
- 不得加入原始回覆沒有表達的動機、情緒或因果推論。
- 若某個類別缺乏足夠資料支持（例如全部樣本裡只有一則、且內容含糊），
  不要硬造這個類別。
- 不得把既有其他研究案例的分類架構當作這批資料必須符合的清單——即使
  下面提供了 reference 範例，那只是「好的 taxonomy 長什麼樣子」的格式
  範例，不是你這次一定要產生的類別名單。你的類別必須完全依這批資料的
  實際內容歸納，可以跟 reference 完全不同，也可以完全沒有 reference
  裡出現的任何類別名稱。
- 「無具體建議」「正向回饋」這類類別，只有在這批資料裡真的觀察到這種
  內容時才建立，不可以因為其他案例有這種類別就跟著加一個。
- citation 絕對不可以憑空生成。沒有在下面提供的 reference 資料中看到
  對應文獻時，一律填 null。
"""

    reference_block = ""
    if reference_examples:
        # 只給「格式範例」用的少量結構樣本，不是整份既有 taxonomy，
        # 避免 token 過高，也避免被誤認為必須產生一樣的類別
        # （見需求文件第 11 節）。
        example_json = json.dumps(reference_examples, ensure_ascii=False, indent=2)
        reference_block = f"""
【格式參考（來自其他研究案例，只作為「好的 taxonomy 應該長怎樣」的
範例，不是這次的類別清單，你的分類完全不需要、也不應該跟這些一樣）】
{example_json}
"""
        if reference_citations:
            citation_list = "、".join(reference_citations)
            reference_block += (
                f"\n上面範例中出現過的合法 citation（如果你判斷這批新資料的某個子類別"
                f"確實對應到其中一個，才可以原樣使用；沒有明確對應一律填 null）：\n{citation_list}\n"
            )

    global_block = f"\n【額外分析原則】\n{global_instructions}\n" if global_instructions else ""

    return "\n".join([intro, core_rules, global_block, reference_block, _GENERATION_OUTPUT_SCHEMA])


def _mask_answers(answer_texts: list) -> list:
    """對整批回答逐一遮罩，跟 classify_v2.py 一致的隱私處理方式：
    絕不把明文 PII 送進 Gemini。單筆遮罩失敗只跳過那一筆並記錄，
    不因為一筆壞資料讓整批歸納失敗；全部都失敗才視為輸入不可用。"""
    masked = []
    for i, text in enumerate(answer_texts):
        if not isinstance(text, str) or not text.strip():
            continue
        try:
            masked.append(mask_pii(text))
        except PiiMaskingError as e:
            print(f"[TAXONOMY_GENERATION] 第 {i + 1} 筆回答遮罩失敗，跳過（不計入本次生成）：{e!r}")
    return masked


def load_reference_material(reference_topic_keys: list, max_examples_per_topic: int = 2):
    """
    從既有（通常是已 published）Topic 抽出少量結構範例 +
    citation 白名單，供 generate_taxonomy_draft() 的
    reference_examples / reference_citations 使用。

    只抽 max_examples_per_topic 筆（依 sort_order 前幾筆），不是整份
    taxonomy——避免 token 過高，也避免讓 Gemini 誤以為必須產生一樣的
    類別（見需求文件第 11 節）。citation 白名單則收集該 topic 目前
    published 版本「全部」非空 citation：這些是已經人工審核過、真實
    存在的文獻，Gemini 只有在明確對應時才可以原樣重用，不在名單內的
    一律在 _validate_and_normalize_categories() 被丟棄。

    某個 topic_key 沒有 published 版本時直接略過（reference 是
    best-effort，不因為找不到就讓整個生成請求失敗）。
    """
    from services.taxonomy_service import get_published_taxonomy_version, PublishedTaxonomyNotFoundError, PublishedTaxonomyIntegrityError

    examples = []
    citations = []
    for topic_key in reference_topic_keys or []:
        try:
            version = get_published_taxonomy_version(topic_key)
        except (PublishedTaxonomyNotFoundError, PublishedTaxonomyIntegrityError) as e:
            print(f"[TAXONOMY_GENERATION] reference topic_key={topic_key!r} 無法取得 published taxonomy，略過：{e}")
            continue

        for category in version.categories[:max_examples_per_topic]:
            examples.append({
                "main_category": category.main_category,
                "sub_category": category.sub_category,
                "definition": category.definition,
                "include_rules": category.include_rules,
                "exclude_rules": category.exclude_rules,
                "boundary_rules": category.boundary_rules,
            })
        for category in version.categories:
            if category.citation and category.citation.strip():
                citations.append(category.citation.strip())

    # 去重但保留順序
    seen = set()
    unique_citations = []
    for c in citations:
        if c not in seen:
            seen.add(c)
            unique_citations.append(c)

    return examples, unique_citations


def generate_taxonomy_draft(
    topic_key: str,
    answer_texts: list,
    topic_title: str = None,
    question_text: str = None,
    global_instructions: str = None,
    reference_examples: list = None,
    reference_citations: list = None,
    created_by: int = None,
):
    """
    Stage A 主入口：一批回答 -> AI 歸納 -> 驗證 -> 寫入新的 draft
    Taxonomy_Version（含全部 Taxonomy_Category）。

    Args:
        topic_key: 這批回答所屬的 Topic。若尚不存在會被安全建立
            （見 services.taxonomy_service.ensure_topic()），此時
            topic_title 為必填；若已存在，topic_title/question_text
            會被忽略（不覆寫既有 Topic 中繼資料）。
        answer_texts: 這批要拿來歸納的原始回答（未遮罩），至少要有
            內容非空的一筆，否則直接 fail-closed。
        global_instructions: 額外的系統級分析原則（例如特定研究方法
            要求），會存進新版本的 Taxonomy_Version.methodology_note
            （既有欄位，不新增欄位）。
        reference_examples: few-shot 格式範例（小量、非整份既有
            taxonomy），每個元素建議只含
            main_category/sub_category/definition/include_rules/
            exclude_rules/boundary_rules 幾個 key 做示範。
        reference_citations: 允許被保留的 citation 白名單；不在清單
            內的 citation 一律被丟棄成 None（見本檔開頭防
            hallucination 說明）。
        created_by: 觸發這次生成的 Admin id（可為 None）。

    Returns:
        新建立的 Taxonomy_Version（status=draft，已 commit，
        .categories 已載入）。

    Raises:
        TaxonomyGenerationValidationError: 輸入或 Gemini 輸出不合法，
            未寫入任何資料。
        TaxonomyGenerationError: Gemini 呼叫本身失敗（API 錯誤等），
            未寫入任何資料。
        ValueError: topic_key 不存在且未提供 topic_title。

    重要：這個函式只建立 draft 版本，絕對不會呼叫
    services.taxonomy_service.publish_taxonomy_version()，也不會動到
    任何既有 published 版本。
    """
    masked_answers = _mask_answers(answer_texts or [])
    if not masked_answers:
        raise TaxonomyGenerationValidationError("answer_texts 沒有任何可用的非空回答，無法進行歸納")
    _validate_batch_size(masked_answers)

    prompt = _build_generation_prompt(
        topic_title=topic_title or topic_key,
        question_text=question_text,
        global_instructions=global_instructions,
        reference_examples=reference_examples,
        reference_citations=reference_citations,
    )

    numbered_answers = "\n".join(f"{i + 1}. {text}" for i, text in enumerate(masked_answers))
    user_message = f"以下是這批共 {len(masked_answers)} 則開放式回覆：\n\n{numbered_answers}"

    try:
        model = genai.GenerativeModel(model_name="gemini-3.1-flash-lite", system_instruction=prompt)
        response = _generate_with_retry(model, user_message)
        parsed = _parse_json(response.text)
    except TaxonomyGenerationValidationError:
        raise
    except Exception as e:
        print("[TAXONOMY_GENERATION ERROR][GEMINI_API_FAILED]", repr(e))
        raise TaxonomyGenerationError(f"Gemini 呼叫或輸出解析失敗：{e}") from e

    if not isinstance(parsed, dict) or "categories" not in parsed:
        raise TaxonomyGenerationValidationError("Gemini 回傳的 JSON 缺少 categories 欄位")

    normalized_categories = _validate_and_normalize_categories(
        parsed["categories"], reference_citations=reference_citations
    )

    # ── 驗證全部通過，才開始真正寫 DB；以下全部在同一個 transaction ──
    from models import Taxonomy_Version, Taxonomy_Category

    try:
        ensure_topic(topic_key, title=topic_title, question_text=question_text)
        version_number = get_next_version_number(topic_key)

        version = Taxonomy_Version(
            topic_key=topic_key,
            version_number=version_number,
            status=TAXONOMY_VERSION_STATUS_DRAFT,
            source=TAXONOMY_VERSION_SOURCE_AI_GENERATED,
            methodology_note=global_instructions,
            created_by=created_by,
        )
        db.session.add(version)
        db.session.flush()

        for sort_order, category in enumerate(normalized_categories, start=1):
            db.session.add(Taxonomy_Category(
                version_id=version.version_id,
                sort_order=sort_order,
                **category,
            ))

        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise TaxonomyVersionConflictError(
            f"topic_key={topic_key!r} 的版本號發生衝突（可能有另一個請求同時在建立新版本），請重試一次"
        )
    except Exception:
        db.session.rollback()
        raise

    return version


# ── 選用：從既有回答表撈一批文字（跟核心生成邏輯完全分開，
#    generate_taxonomy_draft() 不呼叫這個函式，呼叫端自己決定要不要
#    用它取代自己組 answer_texts）──

def collect_answer_texts_from_uploaded_answers(question_type: str, limit: int = None) -> list:
    """
    從 Uploaded_Answer 撈出指定 question_type 的原始回答文字，
    供呼叫端組成 generate_taxonomy_draft() 的 answer_texts 參數。

    刻意獨立於 generate_taxonomy_draft() 之外：這個 service 不假設
    「回答一定來自 Uploaded_Answer」，未來如果要從 Survey_Response
    （依 Survey_Template.question_json 找出對應 question_id 再撈
    answer_json）取資料，可以另外寫一個平行的 collect 函式，不需要
    改動生成邏輯本身。
    """
    from models import Uploaded_Answer

    query = Uploaded_Answer.query.filter_by(question_type=question_type).order_by(Uploaded_Answer.id.asc())
    if limit:
        query = query.limit(limit)
    return [row.answer_text for row in query.all()]
