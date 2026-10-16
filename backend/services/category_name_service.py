"""
大類別 / 子類別名稱的「顯示用」翻譯。

名稱本身是分類比對的識別字（資料庫、分類器、審核、合併都用原本的名稱），所以**不改資料、不改 schema**，
只在「給使用者看」的最後一步翻譯：
  - 介面語言 = 繁體中文：原樣回傳（輸出與改動前完全相同）。
  - 介面語言 = 英文：
      1. 內建分類（兩個內建題目的大類別 / 子類別）用固定對照表，不呼叫 AI、結果穩定；
      2. 其他（管理員自訂、AI 新產生的類別）一次批次請 Gemini 翻譯，結果存在行程內快取；
      3. 翻譯失敗 / 回傳不合格（空白、仍含漢字）-> 退回原名稱，不影響主流程，下次再試。
  - 「A1 」「B2 」這種代碼前綴保留，只翻譯後面的名稱。
"""

import json
import logging
import re
import threading

from services.language_service import DEFAULT_LANG, normalize_lang

log = logging.getLogger(__name__)

_HAN = re.compile(r"[㐀-鿿]")
_CODE_PREFIX = re.compile(r"^([A-Za-z]\d+)(\s+)(.*)$", re.S)

# 一次最多翻譯幾個名稱（避免單次提示過大）
_MAX_BATCH = 60

BUILTIN_EN = {
    # 大類別
    "主管領導": "Supervisor Leadership",
    "部門合作": "Departmental Collaboration",
    "其他與建議": "Other & Suggestions",
    "工作表現的回饋及職涯發展": "Performance Feedback & Career Development",
    # 題目一：主管領導與部門合作
    "工作與生活邊界": "Work-Life Boundaries",
    "回饋與溝通": "Feedback & Communication",
    "主管覺察力": "Supervisor Awareness",
    "領導風格": "Leadership Style",
    "溝通與協調機制": "Communication & Coordination Mechanisms",
    "支援協作": "Support & Collaboration",
    "權責界定與規範落實": "Role Clarity & Policy Enforcement",
    "管理一致性": "Management Consistency",
    "正向回饋": "Positive Feedback",
    "無具體建議": "No Specific Suggestion",
    # 題目二：工作表現的回饋及職涯發展
    "獎酬、激勵與晉升制度": "Compensation, Incentives & Promotion System",
    "品牌定位與市場曝光": "Brand Positioning & Market Exposure",
    "設備資源與數位支持": "Equipment, Resources & Digital Support",
    "PM 發展與留才": "PM Development & Retention",
    "教育訓練": "Training & Education",
    "職涯發展與回饋制度": "Career Development & Feedback System",
    "雙向溝通": "Two-Way Communication",
    "工作優化與身心平衡": "Work Optimization & Well-Being",
    "客觀與具體回饋": "Objective & Specific Feedback",
}

_cache: dict = {}
_cache_lock = threading.Lock()


def _split_code(name: str):
    m = _CODE_PREFIX.match(name)
    if m:
        return m.group(1) + m.group(2), m.group(3)
    return "", name


def _clean(value) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or _HAN.search(value):
        return None
    return value


def _ai_translate(bodies: list) -> dict:
    """批次翻譯（body -> English）。任何失敗都回傳空 dict（由呼叫端退回原名稱）。"""
    if not bodies:
        return {}
    token = None
    try:
        from services import gemini_client as genai

        # 翻譯專用 key：額度與分類 / 摘要分開，翻譯被限流不會影響主流程。沒設定就沿用原本的 key。
        token = genai.use_api_key(genai.translation_api_key()) if genai.translation_api_key() else None
        model = genai.GenerativeModel(
            model_name="gemini-3.1-flash-lite",
            system_instruction=(
                "You translate category names of a survey-analysis taxonomy into concise, natural English "
                "(Title Case, no code prefix, no trailing punctuation). Return ONLY a JSON object that maps "
                "each given original name to its English translation. Keep every key exactly as given."
            ),
        )
        resp = model.generate_content(
            json.dumps(bodies, ensure_ascii=False),
            generation_config={"temperature": 0},
        )
        text = re.sub(r"```json|```", "", resp.text or "").strip()
        data = json.loads(text)
        if not isinstance(data, dict):
            return {}
        return {k: v for k, v in data.items() if k in bodies}
    except Exception as exc:  # noqa: BLE001 - 翻譯只是顯示用，失敗不能影響主流程
        log.warning("類別名稱翻譯失敗，沿用原名稱：%s", str(exc)[:160])
        return {}
    finally:
        if token is not None:
            genai.reset_api_key(token)


def translate_category_names(names, lang=None) -> dict:
    """回傳 {原名稱: 顯示名稱}。非英文一律原樣；永遠不拋例外。"""
    unique = []
    for n in names or []:
        if isinstance(n, str) and n and n not in unique:
            unique.append(n)
    result = {n: n for n in unique}
    if normalize_lang(lang) in (None, DEFAULT_LANG) or normalize_lang(lang) != "en":
        return result

    pending = []  # 需要 AI 翻譯的 body
    parts = {}
    for n in unique:
        prefix, body = _split_code(n)
        parts[n] = (prefix, body)
        if not _HAN.search(body):
            continue  # 本來就不含中文
        if body in BUILTIN_EN:
            continue
        with _cache_lock:
            cached = _cache.get(body)
        if cached is None and body not in pending:
            pending.append(body)

    for i in range(0, len(pending), _MAX_BATCH):
        chunk = pending[i:i + _MAX_BATCH]
        for body, english in _ai_translate(chunk).items():
            english = _clean(english)
            if english:
                with _cache_lock:
                    _cache[body] = english

    for n, (prefix, body) in parts.items():
        english = BUILTIN_EN.get(body)
        if english is None:
            with _cache_lock:
                english = _cache.get(body)
        if english:
            result[n] = prefix + english
    return result


def localize_category_rows(rows, lang=None) -> list:
    """匯出用：回傳複本，main_category / sub_category 換成顯示名稱。非英文原樣回傳同一份 rows。"""
    if normalize_lang(lang) != "en" or not rows:
        return rows
    names = []
    for r in rows:
        if isinstance(r, dict):
            names += [r.get("main_category"), r.get("sub_category")]
    table = translate_category_names(names, lang)
    out = []
    for r in rows:
        if isinstance(r, dict):
            r = dict(r)
            for k in ("main_category", "sub_category"):
                if isinstance(r.get(k), str):
                    r[k] = table.get(r[k], r[k])
        out.append(r)
    return out


def _reset_cache_for_tests():
    with _cache_lock:
        _cache.clear()
