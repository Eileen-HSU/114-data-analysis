"""
開放式分類（open-set classification）。

【產品定案（取代原本的 fail-closed）】既有的分類架構只是「參考值」：
    1. 既有主題：優先從分類清單選；真的都不適合時，AI 可以提出「新類別」，
       照樣歸類（status=new_category、needs_human_review），不再被丟掉。
       管理員在「新類別候選」採用後，新類別會加進該主題的分類架構草稿。
    2. 參考值只當範例：新主題的分類架構由 AI 依這批回答歸納，既有兩套
       分類只作為格式 / 寫法範例（few-shot），不是唯一允許的答案。
    3. 沒有主題的資料也要能分析：判斷不出主題、或主題沒有已發布分類架構
       時，不再是零結果——系統依欄位名稱 / 題目文字建立「自動主題」
       （topic_key = auto_<hash>），用 AI 歸納出暫定分類架構（draft）後
       立即分類。之後遇到類似的資料會沿用同一個自動主題（routing 也會
       把自動主題列為候選），不會每次都重新產生。

【仍然保留的防線】
    - 暫定（draft）分類與新類別都會標示「待管理員審核」，Human Review
      Confidence Gate 會 flag；正式報告只納入人工確認過的結果。
    - AI 歸納失敗（額度不足、格式錯誤…）時不會亂分類：該批資料維持
      「未分類」，原因寫進 routing_status / routing_detail，可以在 Admin
      「其他 / 未歸屬資料」重新處理。
    - OPEN_CLASSIFICATION_ENABLED=0 可以切回原本的封閉式（fail-closed）行為。
"""

import hashlib
import os
import re
import unicodedata

from extensions import db

AUTO_TOPIC_PREFIX = "auto_"
NEW_CATEGORY_STATUS = "new_category"
REVIEW_FLAG_NEW_CATEGORY = "new_category_proposed"

# 自動歸納分類架構時，最多取多少則回答當樣本（taxonomy_generation_service
# 上限是 500 則 / 200,000 字；這裡取保守值，避免 prompt 過大）。
_MAX_GENERATION_SAMPLES = 120
_MAX_SAMPLE_CHARS = 600

OPEN_SET_RULES = """【開放式分類規則（清單只是參考，不是唯一答案）】
1. 優先從上方清單中選擇最符合的子類別；只要有合理符合的既有子類別，就必須使用既有名稱（逐字一致）。
2. 只有在清單中「完全沒有」合適的子類別時，才可以提出新的子類別：
   - main_category：優先沿用清單中的大類別；真的都不適合才提出新的大類別（3-8 個字）。
   - sub_category：精簡具體的新名稱（4-12 個字），不要加 A1、B2 之類的編號前綴。
   - 同一批片段裡，同一個新概念必須使用完全相同的新名稱。
   - confidence 請依實際把握程度評分；提出新類別通常代表需要人工確認。
3. 不可以為了避免提出新類別而把內容硬塞進不相符的既有類別。"""


def open_mode_enabled() -> bool:
    return os.environ.get("OPEN_CLASSIFICATION_ENABLED", "1") != "0"


def is_auto_topic(topic_key) -> bool:
    return bool(topic_key) and str(topic_key).startswith(AUTO_TOPIC_PREFIX)


def _normalize_label(label: str) -> str:
    text = unicodedata.normalize("NFKC", str(label or "")).strip().lower()
    return re.sub(r"[\s\W_]+", "", text)


def auto_topic_key(label: str) -> str:
    """【舊版】只依欄位名稱產生的全域 key。新資料改用 auto_topic_identity()
    （含範圍與內容特徵）；保留給舊的自動主題辨識 / 相容用。"""
    digest = hashlib.sha1(_normalize_label(label).encode("utf-8")).hexdigest()[:12]
    return f"{AUTO_TOPIC_PREFIX}{digest}"


# ═══════════════════════════════════════════════════════════════
# 自動主題 identity：範圍 + 題意 + 內容特徵
# ═══════════════════════════════════════════════════════════════
#
# 只用欄位名稱當全域 identity 會把「意見」、「開放式回答」這種通用欄位名
# 的不相干資料併在一起，也會讓不同使用者 / workspace 的資料共用同一份由
# 別人回答歸納出來的分類架構。規則：
#   1. 自動主題一律有範圍（scope）：Excel 上傳 = "project:<id>"（沒有帶
#      project 時 "user:<id>"）；問卷 = "user:<owner id>"。不同範圍永遠不沿用。
#   2. 同範圍、同一個正規化後的欄位名稱 / 題目文字，而且內容特徵相似度
#      >= REUSE_SIMILARITY_THRESHOLD 才沿用；否則建立新的暫定（provisional）主題。
#   3. topic key = auto_ + sha1(scope | label | 內容特徵摘要)[:12]：穩定、可重現，
#      不含任何原始回答或個資；內容特徵只存雜湊值（Topic.auto_signature）。
#   4. 重複的自動主題可以在 Admin「整個主題併入其他主題」合併。

GENERIC_LABELS = frozenset(
    _label for _label in (
        "意見", "建議", "其他建議", "回饋", "開放式回答", "其他", "備註", "其他意見", "意見回饋",
        "comment", "comments", "feedback", "suggestion", "suggestions", "other", "others", "remark", "remarks",
        "note", "notes", "openended", "openendedresponse", "response", "answer",
    )
)
REUSE_SIMILARITY_THRESHOLD = 0.25
_SIGNATURE_SIZE = 120


def is_generic_label(label) -> bool:
    return _normalize_label(label) in GENERIC_LABELS


# 問卷回答裡到處都會出現、不能代表主題的字元 bigram（語氣、程度、常見動詞）
_STOP_BIGRAMS = frozenset((
    "希望", "增加", "太少", "太多", "不多", "很多", "可以", "應該", "覺得", "沒有", "一點", "多一", "點的",
    "我們", "公司", "非常", "比較", "目前", "一些", "有些", "不會", "不是", "還是", "而且", "但是", "因為",
    "所以", "如果", "能夠", "提供", "更多", "改善", "問題", "的話", "一下", "時候", "什麼", "這個", "那個",
))


def _features(text):
    """內容特徵：英文單字 + 每個片語內的中文字元 bigram（不跨標點），去掉
    常見虛詞 bigram。NFKC、小寫。"""
    normalized = unicodedata.normalize("NFKC", str(text or "")).lower()
    words = re.findall(r"[a-z0-9]{3,}", normalized)
    features = list(words)
    for chunk in re.split(r"[\s\W_a-z0-9]+", normalized):
        for i in range(len(chunk) - 1):
            bigram = chunk[i:i + 2]
            if bigram not in _STOP_BIGRAMS and not bigram.endswith("的") and not bigram.startswith("的"):
                features.append(bigram)
    return features


def content_signature(texts) -> list:
    """內容特徵：出現最多的 bigram / 單字，各自雜湊成 8 碼 hex（排序後的清單）。
    輸入應該是已遮罩的文字；即使如此也只存雜湊，不存原文。"""
    counts = {}
    for text in texts or []:
        for feature in _features(text):
            counts[feature] = counts.get(feature, 0) + 1
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:_SIGNATURE_SIZE]
    return sorted(hashlib.sha1(f.encode("utf-8")).hexdigest()[:8] for f, _ in top)


def signature_similarity(a, b) -> float:
    """overlap coefficient：|A∩B| / min(|A|, |B|)。回答數量不同的兩批資料
    （一批 3 則、一批 100 則）也能比較，不會因為特徵數量差很多而永遠偏低。"""
    set_a, set_b = set(a or []), set(b or [])
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / min(len(set_a), len(set_b))


def _masked(texts):
    from services.privacy_service import PiiMaskingError, mask_pii

    masked = []
    for text in _generation_samples(texts):
        try:
            masked.append(mask_pii(text))
        except PiiMaskingError:
            continue
    return masked


def auto_topic_identity(label, scope, sample_texts) -> dict:
    """決定這批資料要沿用哪個自動主題、或建立新的。

    Returns {"topic_key", "reused", "similarity", "scope", "label", "signature", "generic"}
    """
    import json

    from models import Topic

    label_norm = _normalize_label(label)[:255]
    scope = (scope or "global")[:100]
    signature = content_signature(_masked(sample_texts))

    best_key, best_score = None, 0.0
    candidates = Topic.query.filter_by(auto_scope=scope, auto_label=label_norm).all()
    for topic in candidates:
        try:
            other = json.loads(topic.auto_signature or "[]")
        except ValueError:
            other = []
        score = signature_similarity(signature, other)
        if score > best_score:
            best_key, best_score = topic.topic_key, score

    if best_key is not None and best_score >= REUSE_SIMILARITY_THRESHOLD:
        return {"topic_key": best_key, "reused": True, "similarity": round(best_score, 3), "scope": scope,
                "label": label_norm, "signature": signature, "generic": label_norm in GENERIC_LABELS}

    digest_source = f"{scope}|{label_norm}|{','.join(signature)}"
    key = f"{AUTO_TOPIC_PREFIX}{hashlib.sha1(digest_source.encode('utf-8')).hexdigest()[:12]}"
    return {"topic_key": key, "reused": False, "similarity": round(best_score, 3), "scope": scope,
            "label": label_norm, "signature": signature, "generic": label_norm in GENERIC_LABELS}


def _record_identity(identity):
    """自動主題建立 / 沿用後，補上 identity 欄位（只在還沒有時寫入）。"""
    import json

    from models import Topic

    topic = db.session.get(Topic, identity["topic_key"])
    if topic is None or topic.auto_scope:
        return
    topic.auto_scope = identity["scope"]
    topic.auto_label = identity["label"]
    topic.auto_signature = json.dumps(identity["signature"])
    db.session.commit()


def usable_version_for(topic_key):
    """回傳 (version, provisional)。

    - 有唯一的 published 版本：(published, False)
    - 開放模式下沒有 published：最新一個有分類的 draft / in_review（暫定）
    - 都沒有：(None, False)
    """
    from models import Taxonomy_Version
    from services.taxonomy_service import (
        PublishedTaxonomyIntegrityError,
        PublishedTaxonomyNotFoundError,
        get_published_taxonomy_version,
    )

    try:
        return get_published_taxonomy_version(topic_key), False
    except PublishedTaxonomyIntegrityError:
        raise
    except PublishedTaxonomyNotFoundError:
        pass
    if not open_mode_enabled():
        return None, False
    drafts = (
        Taxonomy_Version.query.filter(
            Taxonomy_Version.topic_key == topic_key,
            Taxonomy_Version.status.in_(("draft", "in_review")),
        )
        .order_by(Taxonomy_Version.version_number.desc())
        .all()
    )
    for version in drafts:
        if version.categories:
            return version, True
    return None, False


def _reference_material():
    """既有已發布主題只當範例（few-shot）與 citation 白名單。"""
    from models import Taxonomy_Version
    from services.taxonomy_generation_service import load_reference_material

    keys = sorted({
        v.topic_key for v in Taxonomy_Version.query.filter_by(status="published").all()
        if not is_auto_topic(v.topic_key)
    })
    return load_reference_material(keys)


def _generation_samples(texts):
    samples = []
    for text in texts or []:
        if not isinstance(text, str) or not text.strip():
            continue
        samples.append(text.strip()[:_MAX_SAMPLE_CHARS])
        if len(samples) >= _MAX_GENERATION_SAMPLES:
            break
    return samples


def _generate_draft(topic_key, sample_texts, title, question_text):
    from services.taxonomy_generation_service import generate_taxonomy_draft

    examples, citations = _reference_material()
    return generate_taxonomy_draft(
        topic_key=topic_key,
        answer_texts=_generation_samples(sample_texts),
        topic_title=(title or topic_key)[:200],
        question_text=question_text,
        global_instructions=(
            "系統自動歸納（開放式分類）：依這批回答內容歸納分類架構；既有主題的分類只作為"
            "格式與寫法範例，不是必須沿用的答案。這是暫定版本，需由管理員審核後發布。"
        ),
        reference_examples=examples,
        reference_citations=citations,
        created_by=None,
    )


def follow_merge(topic_key):
    """主題被管理員合併到其他主題時，改用目標主題（最多追 5 層，避免循環）。"""
    from models import Topic

    seen = set()
    while topic_key and topic_key not in seen and len(seen) < 5:
        seen.add(topic_key)
        topic = db.session.get(Topic, topic_key)
        if topic is None or not topic.merged_into:
            return topic_key
        topic_key = topic.merged_into
    return topic_key


def resolve_taxonomy(topic_key, *, sample_texts=None, title=None, question_text=None) -> dict:
    """分類前取得要用的分類架構與 prompt。

    Returns dict：
        prompt / lookup / version_id  —— 可以分類時有值，否則為 None
        topic_key                    —— 實際使用的主題
        provisional                  —— True 代表用的是暫定（draft）分類架構
        generated                    —— True 代表這次才用 AI 歸納出來
        error                        —— 無法分類時的原因（中文）
    """
    from services.taxonomy_service import (
        PublishedTaxonomyIntegrityError,
        TaxonomyVersionConflictError,
        build_classification_prompt,
        methodology_lookup_for_taxonomy_version,
    )

    merged_target = follow_merge(topic_key)
    if merged_target != topic_key:
        # 已合併的主題：直接用目標主題，不會再為它產生新的自動分類架構
        topic_key, sample_texts = merged_target, None
    result = {
        "prompt": None, "lookup": None, "version_id": None, "topic_key": topic_key,
        "provisional": False, "generated": False, "error": None,
    }
    try:
        version, provisional = usable_version_for(topic_key)
    except PublishedTaxonomyIntegrityError as exc:
        result["error"] = f"主題 {topic_key} 的分類架構資料有問題：{exc}"
        return result

    if version is None and open_mode_enabled() and sample_texts:
        try:
            version = _generate_draft(topic_key, sample_texts, title, question_text)
            provisional = True
            result["generated"] = True
        except TaxonomyVersionConflictError:
            db.session.rollback()
            version, provisional = usable_version_for(topic_key)  # 另一個請求剛好先建好了
        except Exception as exc:  # AI 歸納失敗：不亂分類，交給呼叫端標記未分類
            db.session.rollback()
            print("[OPEN_CLASSIFICATION][TAXONOMY_GENERATION_FAILED]", repr(exc))
            result["error"] = f"AI 自動歸納分類架構失敗：{str(exc)[:300]}"
            return result

    if version is None:
        result["error"] = result["error"] or f"主題 {topic_key} 沒有可用的分類架構"
        return result

    result.update(
        prompt=build_classification_prompt(version, open_set=open_mode_enabled()),
        lookup=methodology_lookup_for_taxonomy_version(version),
        version_id=version.version_id,
        provisional=provisional,
    )
    return result


def resolve_for_unrouted(label, sample_texts, question_text=None, scope=None) -> dict:
    """判斷不出主題的資料：依「範圍 + 題意 + 內容特徵」建立 / 沿用自動主題
    （見 auto_topic_identity()）。"""
    identity = auto_topic_identity(question_text or label, scope, sample_texts)
    title = f"自動歸納：{str(label).strip()[:180]}"
    result = resolve_taxonomy(identity["topic_key"], sample_texts=sample_texts, title=title,
                              question_text=question_text or label)
    if result["prompt"] is not None:
        _record_identity(identity)
    result["auto_identity"] = {k: identity[k] for k in ("reused", "similarity", "scope", "generic")}
    return result
