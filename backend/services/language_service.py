"""語言判斷與語言來源（三種來源各自獨立，不混用）。

    ui_lang            介面語言。來源：請求的 Accept-Language。
                       用於按鈕、標題、歡迎訊息、匯出欄位名稱。
    instruction_lang   使用者「這一次」文字指令的語言。來源：指令文字本身。
                       用於「分類完成，共 N 個類別」這類系統固定回覆句。
                       沒有文字指令（只上傳檔案、選問卷）時 fallback 到 ui_lang。
    data_lang          實際資料內容的語言。來源：原始回答文字。
                       用於 AI 產生的摘要、理由、說明內容。
                       無法可靠判斷時 fallback 到 ui_lang。

目前只支援 zh-TW 與 en。語言偵測只辨識「中文」與「英文」，不是「有 CJK 字元就是中文」：
日文、韓文、俄文、阿拉伯文、泰文、帶重音的拉丁文字（法 / 西 / 德文…）、以及中英文混合
而分不出主要語言的內容，一律回傳 None（呼叫端自己決定 fallback）。

前端 frontend/src/context/languagePreference.js 有同一套規則（指令語言要在送出前就決定），兩邊共用
backend/tests/fixtures/language_cases.json 的測試案例，確保行為一致。改規則時兩邊一起改。
"""

import re
from collections import Counter

SUPPORTED_LANGS = ("zh-TW", "en")
DEFAULT_LANG = "zh-TW"

# 偵測門檻（前端 language.js 使用相同數值）
ZH_SHARE_MIN = 0.6        # 中文佔「資訊量」比例達到這個值才算中文
EN_ZH_SHARE_MAX = 0.1     # 中文佔比低於這個值才算英文；介於兩者之間 = 混合 -> None
OTHER_LETTER_MAX = 0.1    # 其他文字系統 / 帶重音拉丁字母超過這個比例 -> None
EN_STOPWORD_MIN_WORDS = 4  # 英文超過這個字數時，至少要出現一個常見英文虛詞
DATA_SAMPLE_MAX = 300      # 資料語言最多抽樣幾列
DATA_DECIDED_MIN_SHARE = 0.5   # 抽樣中至少這個比例判斷得出語言
DATA_DOMINANT_MIN_SHARE = 0.8  # 判斷得出的列裡，主要語言至少佔這個比例

_URL_RE = re.compile(r"https?://\S+|www\.\S+|\S+@\S+\.\S+", re.I)
_HAN_RE = re.compile("[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0002fa1f]")
_WORD_RE = re.compile(r"[A-Za-z]+(?:['\u2019][A-Za-z]+)*")
# 其他文字系統（假名、韓文、西里爾、阿拉伯、希伯來、天城文、泰文…）與帶重音的拉丁字母
_OTHER_RE = re.compile(
    "[\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u024f\u0370-\u03ff\u0400-\u04ff\u0590-\u06ff"
    "\u0900-\u0dff\u0e00-\u0eff\u1100-\u11ff\u3040-\u30ff\u31f0-\u31ff\u3130-\u318f\uac00-\ud7af]"
)
_EN_STOPWORDS = frozenset(
    "the a an and or but is are was were be to of in on for with this that it as at by from not no "
    "i we you they my our your can could please how what why which do does did have has had will would "
    "should there their than then so if more very too all any some".split()
)


def normalize_lang(value):
    """'zh' / 'zh-TW' / 'zh-Hant-TW' / 'zh-CN' / 'EN' / 'en-US' -> 'zh-TW' / 'en'；其他 -> None。
    簡體（zh-CN）也歸為 zh-TW：介面只有一種中文，輸出一律繁體。"""
    if not isinstance(value, str):
        return None
    tag = value.strip().lower().replace("_", "-")
    if tag == "zh" or tag.startswith("zh-"):
        return "zh-TW"
    if tag == "en" or tag.startswith("en-"):
        return "en"
    return None


def parse_accept_language(header):
    """依 q 值由高到低，回傳第一個支援的語言；沒有支援的 -> None。"""
    if not isinstance(header, str) or not header.strip():
        return None
    candidates = []
    for order, part in enumerate(header.split(",")):
        piece = part.strip()
        if not piece:
            continue
        tag, _, params = piece.partition(";")
        quality = 1.0
        match = re.search(r"q\s*=\s*([0-9.]+)", params)
        if match:
            try:
                quality = float(match.group(1))
            except ValueError:
                quality = 0.0
        candidates.append((-quality, order, tag.strip()))
    for _neg_q, _order, tag in sorted(candidates):
        lang = normalize_lang(tag)
        if lang:
            return lang
    return None


def ui_lang_from_request(default=DEFAULT_LANG):
    """目前請求的介面語言（Accept-Language）。不在請求中、或沒有支援的語言 -> default。"""
    from flask import has_request_context, request

    if not has_request_context():
        return default
    return parse_accept_language(request.headers.get("Accept-Language")) or default


def detect_text_lang(text):
    """一段文字是「中文」(zh-TW) 或「英文」(en)；無法可靠判斷 -> None。

    把「中文字」與「英文單字」換算成同一個資訊量（一個英文單字約等於兩個中文字）再比較；
    網址 / 信箱 / 數字 / 標點不算。短到沒有資訊的內容（"ok"、"好"、"123"）-> None。"""
    if not isinstance(text, str):
        return None
    cleaned = _URL_RE.sub(" ", text)
    han = len(_HAN_RE.findall(cleaned))
    other = len(_OTHER_RE.findall(cleaned))
    words = _WORD_RE.findall(cleaned)
    latin_letters = sum(len(w) for w in words)
    letters = han + other + latin_letters
    if letters < 2 or han + len(words) == 0:
        return None
    if other / letters >= OTHER_LETTER_MAX:
        return None  # 日 / 韓 / 俄 / 阿拉伯 / 泰文、或帶重音的拉丁文字（法 / 西 / 德文）
    zh_share = han / (han + 2 * len(words))
    if han >= 2 and zh_share >= ZH_SHARE_MIN:
        return "zh-TW"
    if zh_share <= EN_ZH_SHARE_MAX and latin_letters >= 3:
        # 單獨一個全大寫縮寫（"NPS"）看不出是不是英文
        if len(words) < 2 and not any(any(c.islower() for c in w) for w in words):
            return None
        if len(words) >= EN_STOPWORD_MIN_WORDS and not any(w.lower() in _EN_STOPWORDS for w in words):
            return None  # 沒有任何英文虛詞，可能是別種拉丁語系文字
        return "en"
    return None  # 中英混合，分不出主要語言


def detect_data_lang(texts):
    """一批資料內容的語言：'zh-TW' / 'en' / None（無法可靠判斷）。

    最多抽樣 DATA_SAMPLE_MAX 列（均勻取樣、結果固定）。要求：判斷得出語言的列至少佔一半，
    而且主要語言佔判斷得出的列至少 80%；否則（混合、其他語言）-> None，不逐列處理。"""
    non_empty = [t for t in (texts or []) if isinstance(t, str) and t.strip()]
    if not non_empty:
        return None
    if len(non_empty) > DATA_SAMPLE_MAX:
        step = len(non_empty) / DATA_SAMPLE_MAX
        sample = [non_empty[int(i * step)] for i in range(DATA_SAMPLE_MAX)]
    else:
        sample = non_empty
    counts = Counter(detect_text_lang(t) for t in sample)
    zh, en = counts.get("zh-TW", 0), counts.get("en", 0)
    decided = zh + en
    if decided == 0 or decided / len(sample) < DATA_DECIDED_MIN_SHARE:
        return None
    lang, dominant = ("zh-TW", zh) if zh >= en else ("en", en)
    if dominant / decided < DATA_DOMINANT_MIN_SHARE:
        return None
    return lang


def resolve_instruction_lang(instruction_text, ui_lang=None):
    """這一次的回覆語言：指令文字的語言；沒有文字指令 / 判斷不出來 -> ui_lang。"""
    return detect_text_lang(instruction_text) or normalize_lang(ui_lang) or DEFAULT_LANG


def resolve_data_lang(texts, ui_lang=None):
    """AI 產生內容（摘要 / 理由 / 說明）的語言：資料語言；無法可靠判斷 -> ui_lang。"""
    return detect_data_lang(texts) or normalize_lang(ui_lang) or DEFAULT_LANG


def language_meta(ui_lang, instruction_lang=None, data_lang=None):
    """放進回應 / 結果 JSON 的語言資訊（三種來源分開記，不改資料庫結構）。"""
    return {
        "ui_lang": normalize_lang(ui_lang) or DEFAULT_LANG,
        "instruction_lang": normalize_lang(instruction_lang),
        "data_lang": normalize_lang(data_lang),
    }


# ── 提示詞用的語言要求（zh-TW 的字串與原本寫死的句子完全相同，行為不變）──

_ANSWER_RULE = {
    "zh-TW": "一律使用繁體中文回答。",
    "en": "Answer entirely in English (translate into English any fixed phrases quoted in these rules).",
}
_SUMMARY_RULE = {
    "zh-TW": "使用繁體中文。",
    "en": "Write the summary in English.",
}


def answer_language_rule(lang):
    return _ANSWER_RULE[normalize_lang(lang) or DEFAULT_LANG]


def summary_language_rule(lang):
    return _SUMMARY_RULE[normalize_lang(lang) or DEFAULT_LANG]


# ── AI 產生內容（逐筆理由 / 摘要、彙整摘要、報告摘要）的語言：規則 A ──
#
#   英文介面 -> 英文；繁體中文介面 -> 繁體中文。跟「資料語言」無關（中文資料 + 英文介面 = 英文理由）。
#   這取代了最早的「摘要跟資料語言走」。data_lang 仍會記在回應的 language 資訊裡，但不再決定 AI 內容的語言。
#
# 語言怎麼決定（優先順序）：
#   1. 呼叫端明確傳入的 lang
#   2. 目前請求的介面語言（Accept-Language）—— 使用者上傳 / 分析 / 重新整理當下
#   3. 沒有請求環境（背景自動重試、排程）：沒辦法知道使用者的介面語言，只能退回「這批資料的語言」
#      （英文資料重試 -> 英文；判斷不出來 -> 繁體中文）。這是已知限制：背景重試不保證等於使用者當時的介面語言。

def resolve_output_lang(lang=None, texts=None):
    explicit = normalize_lang(lang)
    if explicit:
        return explicit
    from flask import has_request_context

    if has_request_context():
        return ui_lang_from_request()
    return detect_data_lang(texts) or DEFAULT_LANG


# 附加在分類提示詞「最後面」的輸出語言要求。繁體中文 -> 空字串（提示詞逐字不變）。
# 類別名稱（main_category / sub_category）是要對照分類架構的標籤，一定不能翻譯。
_CLASSIFICATION_LANGUAGE_BLOCK = {
    "zh-TW": "",
    "en": (
        "\n\n[OUTPUT LANGUAGE — overrides any earlier wording about language]\n"
        "Write the values of \"reasoning\" and \"summary\" in English, even if the respondent's text or the "
        "instructions above are in another language. Keep main_category and sub_category EXACTLY as they appear "
        "in the category list above (do not translate, shorten or reformat them), and keep every other field "
        "unchanged.\n"
    ),
}


def classification_language_block(lang):
    return _CLASSIFICATION_LANGUAGE_BLOCK[normalize_lang(lang) or DEFAULT_LANG]
