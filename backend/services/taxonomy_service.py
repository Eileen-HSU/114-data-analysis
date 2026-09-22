"""
services/taxonomy_service.py

Phase B 核心：讓 production classification 讀取 Published Taxonomy
（taxonomy.py 的 Topic / Taxonomy_Version / Taxonomy_Category），取代
DEFAULT_PROMPT_* + SUBCATEGORY_METHODOLOGY 兩份分裂資料。

三個對外功能：
    1. get_published_taxonomy_version(topic_key)
       —— 讀「唯一」published 版本，0 筆 / 多筆都 fail-closed。
    2. build_classification_prompt(taxonomy_version)
       —— 動態組出 Gemini system_instruction，取代 DEFAULT_PROMPT_*。
    3. methodology_lookup_for_taxonomy_version(taxonomy_version)
       —— 回傳 sub_category -> {main_category, methodology, citation}
          的查表函式，取代 SUBCATEGORY_METHODOLOGY.get_methodology()。
          分類（prompt）與驗證（lookup）都從同一個 taxonomy_version
          物件產生，不會有兩邊真相來源對不上的問題。

另外提供 publish_taxonomy_version()：同一 topic 底下「發布新版時，
舊 published 版本要先轉成 archived」的 transaction，供 Phase C/D 的
generation/review service 呼叫；Phase B 本身沒有建立新版本的入口，
這裡先把不變量（invariant）用程式碼鎖住。
"""

from extensions import db, taiwan_now


class PublishedTaxonomyNotFoundError(RuntimeError):
    """這個 topic_key 目前沒有任何 published 版本的 Taxonomy_Version。"""


class PublishedTaxonomyIntegrityError(RuntimeError):
    """這個 topic_key 底下同時有超過一個 published 版本，違反
    「每個 Topic 正常情況只能有一個 published taxonomy」的不變量。
    這是資料完整性問題，不能默默挑第一筆繼續跑。"""


def ensure_topic(topic_key: str, title: str = None, question_text: str = None, description: str = None):
    """
    取得或安全建立 Topic（Phase C 新增）。

    「安全」的意思：
        - Topic 已存在時，直接回傳既有那筆，完全不覆寫既有的
          title/question_text/description——避免呼叫端（例如 Taxonomy
          Generation route）不小心用這次生成請求裡順手帶的標題覆蓋掉
          既有、可能是人工調整過的 Topic 中繼資料。
        - Topic 不存在時才真的建立，此時 title 為必填（Topic.title
          本身是 nullable=False，見 taxonomy.py），question_text /
          description 為選填。

    不需要、也不要求呼叫端先建立 Prompt_Template——Topic 的存在跟
    Prompt_Template 完全無關（見 Phase B 的說明：Taxonomy 是分類資料，
    Prompt 是如何使用 taxonomy，兩者刻意不耦合）。

    這裡只 db.session.add() + flush()，不 commit()：交給呼叫端（例如
    generate_taxonomy_draft()）決定 transaction 邊界，確保「Topic
    建立」跟「這次 taxonomy 生成」在同一個 transaction 裡，生成失敗
    時如果 Topic 是這次才新建的，會一併 rollback，不留下沒有任何
    taxonomy 嘗試紀錄的孤兒 Topic；若 Topic 本來就存在，rollback
    自然不影響它。
    """
    from models import Topic

    existing = Topic.query.get(topic_key)
    if existing is not None:
        return existing

    if not title or not title.strip():
        raise ValueError(f"topic_key={topic_key!r} 尚不存在，建立新 Topic 時 title 為必填")

    topic = Topic(
        topic_key=topic_key,
        title=title.strip(),
        question_text=question_text,
        description=description,
    )
    db.session.add(topic)
    db.session.flush()
    return topic


def get_next_version_number(topic_key: str) -> int:
    """
    這個 topic_key 底下下一個安全的 version_number（該 topic 現有最大
    version_number + 1，完全沒有版本時從 1 開始）。

    只讀不寫，呼叫端（generate_taxonomy_draft()）在同一個 transaction
    裡用這個值建立新版本，不假設「剛好只有一筆」或用固定遞增方式，
    避免跟既有版本（不論 draft/in_review/published/archived）撞號。
    """
    from models import Taxonomy_Version

    latest = (
        Taxonomy_Version.query.filter_by(topic_key=topic_key)
        .order_by(Taxonomy_Version.version_number.desc())
        .first()
    )
    return (latest.version_number + 1) if latest else 1



def get_published_taxonomy_version(topic_key: str):
    """
    讀取 topic_key 目前唯一的 published Taxonomy_Version，並確保
    categories 已依 sort_order 排序（Taxonomy_Version.categories 這個
    relationship 本身已經是 order_by=Taxonomy_Category.sort_order，
    見 taxonomy.py）。

    Raises:
        PublishedTaxonomyNotFoundError: 0 筆 published。
        PublishedTaxonomyIntegrityError: >1 筆 published。
    """
    from models import Taxonomy_Version
    from taxonomy import TAXONOMY_VERSION_STATUS_PUBLISHED

    published = Taxonomy_Version.query.filter_by(
        topic_key=topic_key, status=TAXONOMY_VERSION_STATUS_PUBLISHED
    ).all()

    if len(published) == 0:
        raise PublishedTaxonomyNotFoundError(
            f"topic_key='{topic_key}' 目前沒有任何 published Taxonomy_Version，"
            "無法進行 classification（不會 fallback 到動態自創分類）"
        )
    if len(published) > 1:
        version_ids = sorted(v.version_id for v in published)
        raise PublishedTaxonomyIntegrityError(
            f"topic_key='{topic_key}' 同時有 {len(published)} 個 published "
            f"Taxonomy_Version（version_id={version_ids}），違反每個 Topic "
            "只能有一個 published 版本的不變量，需要人工介入修正"
        )

    version = published[0]
    if not version.categories:
        raise PublishedTaxonomyIntegrityError(
            f"topic_key='{topic_key}' 的 published Taxonomy_Version "
            f"(version_id={version.version_id}) 沒有任何 Taxonomy_Category，"
            "無法組出有效的分類 prompt"
        )
    return version


# ── runtime prompt 組成 ──────────────────────────────────────────

_SECONDARY_CATEGORY_RULE = """每則回覆原則上輸出一個主要類別；若同時明確涉及兩個以上獨立主題，
可額外輸出一個次要類別。次要類別必須是與主要類別不同的合法子類別（從上方清單中選）；
若內容只涉及單一主題，secondary_sub_category 請輸出 null，不要為了填欄位而勉強生成。"""

_CONFIDENCE_RUBRIC_BLOCK = """【分類信心評分規則】
confidence 必須反映「這個文字依目前 Taxonomy 能否明確歸入此分類」，不可習慣性給高分。

0.90–1.00：
文字語意明確，與某一類別定義高度吻合，且與其他類別幾乎沒有合理競爭。

0.75–0.89：
主要分類有充分依據，但存在少量語意模糊或相近類別。

0.50–0.74：
存在兩個以上合理候選類別、落在類別邊界、文字過短、語意不足，或需要推論才能分類。
這類必須進 Human Review。

0.00–0.49：
資訊明顯不足、與 Taxonomy 對不上、語意矛盾，或無法可靠判斷。

補充規則（優先於上述級距，任一項成立時 confidence 必須 < 0.75）：
- 不可因為「成功選出一個類別」就給 >= 0.75；選得出類別不代表選得準。
- 若兩個（含）以上類別都合理、都說得通，confidence 必須 < 0.75。
- 若必須自行補足原文未明確說出的資訊（推測、腦補）才能判斷，confidence 必須 < 0.75。
- 極短、模糊、缺乏具體語意證據的回答，即使只想得到一個類別，confidence 必須 < 0.75。
- confidence 代表的是「分類判斷的確定程度」，不是「JSON 格式是否成功產生」；格式輸出成功
  跟分類判斷正確與否是兩件事，不能因為這次順利吐出合法 JSON 就直接給高分。"""


_OUTPUT_FORMAT_BLOCK = """【輸出格式】
絕對不可修改或改寫「問卷回覆內容」原文，僅作為判斷依據。
只回傳以下 JSON 格式，不要加任何其他文字說明：

{
  "main_category": "大類別名稱",
  "sub_category": "完整子類別名稱",
  "secondary_sub_category": "次要子類別名稱，若無則為 null",
  "reasoning": "判斷原因與說明，1-2句話",
  "summary": "受試者建議摘要，1句話",
  "confidence": 0.0 到 1.0 之間的浮點數，代表你對這個分類判斷的自陳信心程度，不是機率或正確率，只是你自己覺得有多確定
}"""


def _category_rule_text(category) -> str:
    """
    組出單一 Taxonomy_Category 的判斷規則描述文字（不含編號、不含
    子類別名稱前綴，呼叫端自己組上去）。

    優先序（Phase B 的 backward-compatible 規則，見需求文件第 3 節）：
        1. definition / include_rules / exclude_rules / boundary_rules
           只要有任何一個非空，就用這幾個結構化欄位組出來。
        2. 上面全部是 NULL、但 source_raw_text 有值（Phase A migration
           進來的既有兩個 Topic 目前就是這個狀況）—— 直接使用整段
           原文，不猜測怎麼拆分成 definition/include/exclude/boundary。
        3. 兩者都沒有 —— 視為資料不完整，拋例外（不能生出一個沒有任何
           判斷依據的空類別去問 Gemini）。
    """
    structured_parts = []
    if category.definition:
        structured_parts.append(category.definition.strip())
    if category.include_rules:
        structured_parts.append(f"納入範圍：{category.include_rules.strip()}")
    if category.exclude_rules:
        structured_parts.append(f"排除範圍：{category.exclude_rules.strip()}")
    if category.boundary_rules:
        structured_parts.append(f"與相近類別界線：{category.boundary_rules.strip()}")

    if structured_parts:
        return " ".join(structured_parts)

    if category.source_raw_text:
        raw = category.source_raw_text.strip()
        # Phase A migration 存的 source_raw_text 格式固定是
        # "{sub_category}：{規則原文}"，這裡只需要冒號後面的部份，
        # 避免跟呼叫端自己組的 "{i}. {sub_category}：" 前綴重複。
        # 找不到冒號（未來手動填入、格式不同）就整段照用，不猜測切法。
        if "：" in raw:
            _label, _, rest = raw.partition("：")
            return rest.strip()
        return raw

    raise PublishedTaxonomyIntegrityError(
        f"Taxonomy_Category(id={category.category_id}, "
        f"sub_category={category.sub_category!r}) 沒有 definition/include/"
        "exclude/boundary_rules，也沒有 source_raw_text，無法組出判斷規則"
    )


def build_classification_prompt(taxonomy_version) -> str:
    """
    從一個（必須是 published，但這裡不重複檢查，呼叫端已經透過
    get_published_taxonomy_version() 確保過）Taxonomy_Version 動態組出
    完整的 Gemini system_instruction，取代 DEFAULT_PROMPT_LEADERSHIP /
    DEFAULT_PROMPT_CAREER。

    輸出格式（JSON schema）跟 legacy prompt 完全一致，因此下游
    _parse_json() / _build_classification_result() 不需要跟著改。

    _CONFIDENCE_RUBRIC_BLOCK（新增）：明確的 confidence 評分級距與
    補充規則，插在 _OUTPUT_FORMAT_BLOCK 之前——只調整「how Gemini 應該
    自我評分」，不動 CONFIDENCE_THRESHOLD（0.75，見
    services/confidence_gate.py，本次刻意不改）、不動 JSON schema 本身
    的欄位結構。目的是矯正「只要成功選出一個類別就習慣性給 >=0.75」
    的偏差，讓 Human Review Confidence Gate 能實際攔到需要人工複核的
    邊界案例，而不是幾乎所有結果都落在高信心區間。
    """
    from services.classify_v2 import GLOBAL_RULES

    categories = taxonomy_version.categories  # 已依 sort_order 排序
    topic = taxonomy_version.topic

    topic_title = topic.title if topic else taxonomy_version.topic_key
    intro = f"你是一個問卷回答分類助手，負責分析「{topic_title}」這題的開放式回覆。"
    if topic and topic.question_text:
        intro += f"\n問卷題目原文：{topic.question_text}"

    # ── 大類別／子類別清單（依 sort_order 出現順序分組，同一
    #    main_category 的子類別合併列在同一組底下，不重新排序）──
    category_list_lines = ["【可用的大類別與子類別，只能從以下清單中選擇，不得自創】", ""]
    current_main = object()  # sentinel，保證第一次一定觸發換組
    for category in categories:
        if category.main_category != current_main:
            current_main = category.main_category
            category_list_lines.append(f"大類別：{current_main}")
        category_list_lines.append(f"- {category.sub_category}")
    category_list_block = "\n".join(category_list_lines)

    # ── 各子類別判斷規則，沿用 legacy numbered list 風格 ──
    rule_paragraphs = []
    for i, category in enumerate(categories, start=1):
        rule_text = _category_rule_text(category)
        rule_paragraphs.append(f"{i}. {category.sub_category}：{rule_text}")
    rules_block = "【各子類別判斷指令與判斷規則】\n\n" + "\n\n".join(rule_paragraphs)

    return "\n\n".join([
        intro,
        category_list_block,
        rules_block,
        GLOBAL_RULES,
        "【次要類別規則】\n" + _SECONDARY_CATEGORY_RULE,
        _CONFIDENCE_RUBRIC_BLOCK,
        _OUTPUT_FORMAT_BLOCK,
    ])


def methodology_lookup_for_taxonomy_version(taxonomy_version):
    """
    回傳一個 sub_category -> {"main_category", "methodology", "citation"}
    或 None 的查表函式，行為對應 legacy
    services.subcategory_methodology.get_methodology()，但資料來源是
    傳入的 taxonomy_version.categories，不是全域常數表——確保
    「Gemini 用哪份 taxonomy 分類，後端就用同一份驗證/查表」。
    """
    table = {
        category.sub_category: {
            "main_category": category.main_category,
            "methodology": category.methodology,
            "citation": category.citation,
        }
        for category in taxonomy_version.categories
    }

    def _lookup(sub_category):
        return table.get(sub_category)

    return _lookup


# ── 發布新版（供 Phase C/D 呼叫；Phase B 本身沒有觸發入口）──────────

def publish_taxonomy_version(topic_key: str, version_id: int):
    """
    在同一個 transaction 內：
        1. 把同一個 topic_key 底下，目前所有 status=published 的舊版本
           （排除自己）轉成 archived。
        2. 把指定 version_id 設為 published。

    這是保證「每個 Topic 最多一個 published 版本」不變量的唯一合法
    入口；Phase B 沒有任何 route 呼叫它（本階段沒有建立新版本的功能），
    但先把這個 service 準備好，Phase C（AI 產生新版）/ Phase D（Admin
    發布 UI）可以直接複用，不用各自重新實作同樣的 transaction 邏輯。
    """
    from models import Taxonomy_Version
    from taxonomy import (
        TAXONOMY_VERSION_STATUS_PUBLISHED,
        TAXONOMY_VERSION_STATUS_ARCHIVED,
    )

    target = Taxonomy_Version.query.get(version_id)
    if target is None or target.topic_key != topic_key:
        raise ValueError(
            f"version_id={version_id} 不存在，或不屬於 topic_key={topic_key!r}"
        )

    now = taiwan_now()
    existing_published = Taxonomy_Version.query.filter_by(
        topic_key=topic_key, status=TAXONOMY_VERSION_STATUS_PUBLISHED
    ).all()
    for old_version in existing_published:
        if old_version.version_id == target.version_id:
            continue
        old_version.status = TAXONOMY_VERSION_STATUS_ARCHIVED
        old_version.archived_at = now

    target.status = TAXONOMY_VERSION_STATUS_PUBLISHED
    target.published_at = now

    db.session.commit()
    return target


# ══════════════════════════════════════════════════════════════
# Phase D：Admin Taxonomy Review / Edit / Publish
# ══════════════════════════════════════════════════════════════
#
# 這一段刻意跟上面 Phase B/C 的內容分開放，但同一個檔案——CRUD 的對象
# 一樣是 Topic/Taxonomy_Version/Taxonomy_Category，沒有理由為了
# 「這是 Phase D 加的」就切成新檔案。跟 Prompt_Template candidate 的
# CRUD（services/prompt_admin_service.py）完全是不同的資料表、不同的
# service 檔案，兩者不共用任何函式，避免混淆「Prompt 草稿」跟
# 「Taxonomy 草稿」（見需求文件第 2 節）。

from sqlalchemy.exc import IntegrityError


class TaxonomyEditNotAllowedError(RuntimeError):
    """試圖直接修改 / 新增 / 刪除一個 published 或 archived
    Taxonomy_Version 底下的 category。這種版本要嘛正在被 production
    使用（published），要嘛是歷史紀錄（archived），都不可以直接改；
    要修改請先 clone_taxonomy_version() 出一份新 draft。"""


class TaxonomyPublishValidationError(RuntimeError):
    """draft/in_review 版本不符合發布前的完整性要求，見
    validate_taxonomy_version_for_publish()。"""


class TaxonomyVersionConflictError(RuntimeError):
    """建立新版本時 version_number 撞號（UniqueConstraint），通常是
    同一個 topic_key 幾乎同時觸發了兩次 generate/clone。呼叫端應該
    轉成 HTTP 409，並提示使用者重試，而不是讓 IntegrityError 直接
    變成一個看不懂的 500。"""


_EDITABLE_REQUIRED_TEXT_FIELDS = ("main_category", "sub_category")
_EDITABLE_OPTIONAL_TEXT_FIELDS = (
    "definition", "include_rules", "exclude_rules", "boundary_rules",
    "methodology", "citation",
)


def get_taxonomy_version(topic_key: str, version_id: int):
    """讀取單一 Taxonomy_Version（確認它確實屬於 topic_key），找不到
    回傳 None（不拋例外——找不到是很正常的路由層 404 情境，不是
    service 層的錯誤）。"""
    from models import Taxonomy_Version

    version = Taxonomy_Version.query.get(version_id)
    if version is None or version.topic_key != topic_key:
        return None
    return version


def _require_editable_version(version):
    from taxonomy import TAXONOMY_VERSION_STATUS_DRAFT, TAXONOMY_VERSION_STATUS_IN_REVIEW

    if version.status not in (TAXONOMY_VERSION_STATUS_DRAFT, TAXONOMY_VERSION_STATUS_IN_REVIEW):
        raise TaxonomyEditNotAllowedError(
            f"status={version.status!r} 的版本不可直接編輯。"
            "published 版本正在被 production classification 使用，"
            "archived 版本是歷史紀錄，兩者都請先用 clone_taxonomy_version() "
            "建立一份新的 draft 再修改。"
        )


def _apply_optional_category_fields(category, data: dict):
    """套用 definition/include_rules/exclude_rules/boundary_rules/
    methodology/citation 這幾個「可以是 NULL」的欄位（見需求文件第
    10、11 節：citation/methodology 允許人工留白或修改，不是不可變的
    AI 建議）。只套用 data 裡真的有出現的 key，沒出現的欄位維持原值，
    讓呼叫端可以只傳想改的欄位（PATCH 語意）。"""
    for field in _EDITABLE_OPTIONAL_TEXT_FIELDS:
        if field not in data:
            continue
        value = data[field]
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{field} 必須是字串或 null")
        setattr(category, field, (value.strip() or None) if isinstance(value, str) else None)


def update_category(topic_key: str, version_id: int, category_id: int, updates: dict):
    """
    修改 draft/in_review 版本底下一筆 category。main_category/
    sub_category 兩個身份欄位不可清空（可以改名，不能改成空字串）；
    definition 等其餘欄位可以是 NULL（草稿編輯過程中本來就可能還沒
    填齊，完整性檢查留給 publish 前的
    validate_taxonomy_version_for_publish()，這裡不重複擋）。

    Raises:
        ValueError: version/category 找不到，或欄位型別不正確。
        TaxonomyEditNotAllowedError: 版本不是 draft/in_review。
        TaxonomyVersionConflictError: 改名後跟同版本另一筆
            (main_category, sub_category) 撞唯一鍵。
    """
    from models import Taxonomy_Category

    version = get_taxonomy_version(topic_key, version_id)
    if version is None:
        raise ValueError("taxonomy version not found")
    _require_editable_version(version)

    category = Taxonomy_Category.query.get(category_id)
    if category is None or category.version_id != version.version_id:
        raise ValueError("category not found")

    for field in _EDITABLE_REQUIRED_TEXT_FIELDS:
        if field not in updates:
            continue
        value = updates[field]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} 不可為空")
        setattr(category, field, value.strip())

    _apply_optional_category_fields(category, updates)

    if "sort_order" in updates:
        value = updates["sort_order"]
        if not isinstance(value, int):
            raise ValueError("sort_order 必須是整數")
        category.sort_order = value

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise TaxonomyVersionConflictError(
            f"(main_category, sub_category) 組合在這個版本裡已經存在"
        )
    return category


def add_category(topic_key: str, version_id: int, data: dict):
    """新增一筆 category 到 draft/in_review 版本。sort_order 不填時
    自動接在目前最大值之後（新增到最後）。"""
    from models import Taxonomy_Category

    version = get_taxonomy_version(topic_key, version_id)
    if version is None:
        raise ValueError("taxonomy version not found")
    _require_editable_version(version)

    main_category = data.get("main_category")
    sub_category = data.get("sub_category")
    if not isinstance(main_category, str) or not main_category.strip():
        raise ValueError("main_category 不可為空")
    if not isinstance(sub_category, str) or not sub_category.strip():
        raise ValueError("sub_category 不可為空")

    sort_order = data.get("sort_order")
    if sort_order is None:
        existing_orders = [c.sort_order for c in version.categories if c.sort_order is not None]
        sort_order = (max(existing_orders) if existing_orders else 0) + 1
    elif not isinstance(sort_order, int):
        raise ValueError("sort_order 必須是整數")

    category = Taxonomy_Category(
        version_id=version.version_id,
        main_category=main_category.strip(),
        sub_category=sub_category.strip(),
        sort_order=sort_order,
    )
    _apply_optional_category_fields(category, data)

    db.session.add(category)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise TaxonomyVersionConflictError(
            f"main_category/sub_category 組合已存在：{main_category!r} / {sub_category!r}"
        )
    return category


def delete_category(topic_key: str, version_id: int, category_id: int):
    """刪除 draft/in_review 版本底下一筆 category。"""
    from models import Taxonomy_Category

    version = get_taxonomy_version(topic_key, version_id)
    if version is None:
        raise ValueError("taxonomy version not found")
    _require_editable_version(version)

    category = Taxonomy_Category.query.get(category_id)
    if category is None or category.version_id != version.version_id:
        raise ValueError("category not found")

    db.session.delete(category)
    db.session.commit()


def reorder_categories(topic_key: str, version_id: int, ordered_category_ids: list):
    """
    依 ordered_category_ids 的順序重新指派 sort_order（1..N）。前端若
    拖拉成本太高，也可以只做「上移/下移」：呼叫端把兩筆的 category_id
    互換位置後，整份目前完整的 id 順序丟進來即可，這裡不假設是
    drag-and-drop 產生的呼叫。

    ordered_category_ids 必須「剛好」包含這個版本目前全部的
    category_id（不能多、不能少、不能有版本外的 id），避免漏掉某筆
    導致它的 sort_order 沒被更新、卻誤以為已經套用新順序。
    """
    version = get_taxonomy_version(topic_key, version_id)
    if version is None:
        raise ValueError("taxonomy version not found")
    _require_editable_version(version)

    categories_by_id = {c.category_id: c for c in version.categories}
    if set(ordered_category_ids) != set(categories_by_id.keys()):
        raise ValueError(
            "ordered_category_ids 必須剛好包含這個版本目前全部的 category_id，不能多也不能少"
        )

    for i, category_id in enumerate(ordered_category_ids, start=1):
        categories_by_id[category_id].sort_order = i

    db.session.commit()
    # relationship 的 order_by 只在「重新查詢」時生效，剛才是原地改
    # 屬性值，這裡明確 expire 掉快取的 collection，確保回傳的順序
    # 反映新的 sort_order，而不是 commit 前就已經載入的舊順序。
    db.session.expire(version, ["categories"])
    return list(version.categories)


def clone_taxonomy_version(topic_key: str, source_version_id: int, created_by: int = None):
    """
    複製一份現有版本（通常是 published）成一個新的 draft 版本，供
    Admin 要修改正式 taxonomy 時使用（需求文件第 6 節：published 不可
    直接改，要先 clone 再改）。原版本（不論是什麼 status）完全不受
    影響——這裡只讀它，不寫它。

    新版本：
        - version_number：該 topic 目前最大版號 + 1
        - status：draft
        - source：manual（clone 是人工操作觸發，不是 AI 生成，也不是
          migration，沿用 taxonomy.py 既有的 source 列舉，不新增值）
        - methodology_note：沿用來源版本的
        - categories：逐筆複製全部欄位，包含 source_raw_text（保留
          稽核追溯用途，不因為是 clone 就清掉）

    Raises:
        ValueError: 來源版本不存在。
        TaxonomyVersionConflictError: version_number 撞號（併發生成/
            clone），呼叫端應回 409 並提示重試。
    """
    from models import Taxonomy_Version, Taxonomy_Category
    from taxonomy import TAXONOMY_VERSION_STATUS_DRAFT, TAXONOMY_VERSION_SOURCE_MANUAL

    source = get_taxonomy_version(topic_key, source_version_id)
    if source is None:
        raise ValueError("taxonomy version not found")

    try:
        version_number = get_next_version_number(topic_key)
        new_version = Taxonomy_Version(
            topic_key=topic_key,
            version_number=version_number,
            status=TAXONOMY_VERSION_STATUS_DRAFT,
            source=TAXONOMY_VERSION_SOURCE_MANUAL,
            methodology_note=source.methodology_note,
            created_by=created_by,
        )
        db.session.add(new_version)
        db.session.flush()

        for c in source.categories:
            db.session.add(Taxonomy_Category(
                version_id=new_version.version_id,
                main_category=c.main_category,
                sub_category=c.sub_category,
                definition=c.definition,
                include_rules=c.include_rules,
                exclude_rules=c.exclude_rules,
                boundary_rules=c.boundary_rules,
                methodology=c.methodology,
                citation=c.citation,
                source_raw_text=c.source_raw_text,
                sort_order=c.sort_order,
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

    return new_version


def validate_taxonomy_version_for_publish(version):
    """
    發布前完整性檢查（需求文件第 7 節）。任何一項不合法就拋
    TaxonomyPublishValidationError，呼叫端據此保證不會呼叫
    publish_taxonomy_version() 發布一份不完整的 taxonomy。

    「至少要有 definition 或 source_raw_text 其中之一」而不是硬性
    要求 definition：這裡刻意跟 _category_rule_text()（production
    runtime prompt builder 判斷「這個 category 有沒有可用規則內容」
    的邏輯）保持同一套標準，不另外發明一套更嚴或更鬆的規則——Phase A
    migration 進來的 legacy 版本本來就是靠 source_raw_text 撐起
    production classification，如果這裡的 publish 檢查比 runtime
    實際使用的標準更嚴格，會出現「已經在跑的正式 taxonomy，若透過
    clone 重新走一次這個 publish 流程，反而會被判定不能發布」的矛盾。
    AI-generated（Phase C）本來在生成當下就已經強制要求 definition，
    自然會滿足這裡的檢查，不受影響。
    """
    from taxonomy import TAXONOMY_VERSION_STATUS_DRAFT, TAXONOMY_VERSION_STATUS_IN_REVIEW

    if version.status not in (TAXONOMY_VERSION_STATUS_DRAFT, TAXONOMY_VERSION_STATUS_IN_REVIEW):
        raise TaxonomyPublishValidationError(
            f"只有 draft/in_review 版本可以發布，目前 status={version.status!r}"
        )

    categories = version.categories
    if not categories:
        raise TaxonomyPublishValidationError("這個版本沒有任何 category，無法發布")

    seen_sub_categories = set()
    for c in categories:
        if not c.main_category or not c.main_category.strip():
            raise TaxonomyPublishValidationError(f"category_id={c.category_id} 缺少 main_category")
        if not c.sub_category or not c.sub_category.strip():
            raise TaxonomyPublishValidationError(f"category_id={c.category_id} 缺少 sub_category")
        if c.sub_category in seen_sub_categories:
            raise TaxonomyPublishValidationError(f"sub_category 重複，無法發布：{c.sub_category!r}")
        seen_sub_categories.add(c.sub_category)

        has_definition = bool(c.definition and c.definition.strip())
        has_raw = bool(c.source_raw_text and c.source_raw_text.strip())
        if not has_definition and not has_raw:
            raise TaxonomyPublishValidationError(
                f"sub_category={c.sub_category!r} 沒有 definition，也沒有 source_raw_text 可用，無法發布"
            )
        if c.sort_order is None:
            raise TaxonomyPublishValidationError(f"sub_category={c.sub_category!r} 缺少 sort_order")


def publish_taxonomy_version_with_validation(topic_key: str, version_id: int):
    """Admin Publish 按鈕的入口：先驗證，通過才呼叫既有的
    publish_taxonomy_version()（同一 transaction 內舊版 archived、
    新版 published）。驗證失敗時完全不觸碰任何版本的 status。"""
    version = get_taxonomy_version(topic_key, version_id)
    if version is None:
        raise ValueError("taxonomy version not found")

    validate_taxonomy_version_for_publish(version)
    return publish_taxonomy_version(topic_key, version_id)


def list_topics_with_status():
    """
    Admin Topic List 用：列出全部 Topic，狀態完全由目前的
    Taxonomy_Version 資料推導（不額外存第二份 status 在 Topic 上，
    見需求文件第 3 節）。

    狀態值：
        no_taxonomy        —— 沒有任何版本
        draft / in_review  —— 有草稿版本，但還沒發布過
        published          —— 有已發布版本，沒有進行中的草稿
        draft_and_published —— 已發布版本 + 同時有草稿正在審核中
    """
    from models import Topic
    from taxonomy import TAXONOMY_VERSION_STATUS_PUBLISHED, TAXONOMY_VERSION_STATUS_ARCHIVED

    topics = Topic.query.order_by(Topic.topic_key).all()
    result = []
    for topic in topics:
        versions = sorted(topic.taxonomy_versions, key=lambda v: v.version_number)
        published = next((v for v in versions if v.status == TAXONOMY_VERSION_STATUS_PUBLISHED), None)
        pending_drafts = [
            v for v in versions
            if v.status not in (TAXONOMY_VERSION_STATUS_PUBLISHED, TAXONOMY_VERSION_STATUS_ARCHIVED)
        ]
        latest_draft = pending_drafts[-1] if pending_drafts else None

        if published and latest_draft:
            status = "draft_and_published"
        elif published:
            status = "published"
        elif latest_draft:
            status = latest_draft.status
        else:
            status = "no_taxonomy"

        result.append({
            "topic_key": topic.topic_key,
            "title": topic.title,
            "question_text": topic.question_text,
            "status": status,
            "published_version": published.to_dict() if published else None,
            "latest_draft_version": latest_draft.to_dict() if latest_draft else None,
        })
    return result


def list_versions_for_topic(topic_key: str):
    """
    列出這個 topic 的「全部」版本（含 archived），依 version_number
    排序，不含 categories（用途是版本選擇清單，不是版本詳情）。

    這是 Topic-centric IA 重構（Sandbox 功能）新增的缺口修補：
    list_topics_with_status() 只回傳「目前 published」跟「最新一筆
    未發布版本」兩個摘要，沒辦法列出 archived 版本或更早的歷史草稿，
    但 Sandbox 明確需要讓 Admin 可以選擇 archived 版本做歷史比較/
    問題重現，所以這裡補一個完整列表函式。
    """
    from models import Taxonomy_Version

    return (
        Taxonomy_Version.query.filter_by(topic_key=topic_key)
        .order_by(Taxonomy_Version.version_number.desc())
        .all()
    )


def delete_taxonomy_version(topic_key: str, version_id: int):
    """
    刪除一個 draft 版本（含底下全部 Taxonomy_Category）。

    只有 status == "draft" 可以刪除；in_review 也不行——這比
    _require_editable_version() 允許 draft/in_review 一起編輯的規則
    更嚴格，所以這裡不重用那個函式，另外寫判斷式。

    Raises:
        ValueError: topic_key/version_id 找不到，或 version 不屬於
            這個 topic（呼叫端應轉 404）。
        TaxonomyEditNotAllowedError: 版本不是 draft，或已經有
            Response_Classification 引用這個版本（呼叫端應轉 409）。
            重用既有例外類別，不為此新增例外階層，兩種情況純粹用
            不同的錯誤訊息文字區分。

    刪除方式：db.session.delete(version) 之後直接 commit，底下的
    Taxonomy_Category 由既有的 ORM cascade
    （Taxonomy_Version.categories 的 cascade="all, delete-orphan"）+
    DB 層 ondelete="CASCADE" 雙重保障自動連鎖刪除，不需要手動
    迴圈刪除 category。不做 version_number renumber，其他版本
    完全不受影響。
    """
    from models import Response_Classification
    from taxonomy import TAXONOMY_VERSION_STATUS_DRAFT

    version = get_taxonomy_version(topic_key, version_id)
    if version is None:
        raise ValueError(f"topic_key={topic_key!r} 找不到 version_id={version_id}")

    if version.status != TAXONOMY_VERSION_STATUS_DRAFT:
        raise TaxonomyEditNotAllowedError(
            f"status={version.status!r} 的版本不允許刪除，只有 draft 版本可以刪除"
        )

    referenced_count = Response_Classification.query.filter_by(taxonomy_version_id=version_id).count()
    if referenced_count > 0:
        raise TaxonomyEditNotAllowedError(
            f"version_id={version_id} 已有 {referenced_count} 筆 Response_Classification 引用此版本，"
            "為避免破壞資料完整性，不允許刪除"
        )

    db.session.delete(version)
    db.session.commit()