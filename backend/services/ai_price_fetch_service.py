"""
從 Google 官方定價頁讀取各模型的 Input／Output 單價（美金／每百萬 token）。

只讀、不寫資料庫：結果交給 Admin 在畫面上確認後才儲存。
- 網址固定，不接受任何外部輸入（避免被當成任意網址的代理）。
- 頁面改版或找不到的模型一律不回傳，由 Admin 手動填。
- 解析的是頁面文字：模型代碼（例如 gemini-3.5-flash）之後第一次出現的
  「Input price」與「Output price」各取第一個金額（Standard 標準價）。
"""

import html
import re
import urllib.request

PRICING_URL = "https://ai.google.dev/gemini-api/docs/pricing"
MAX_BYTES = 3 * 1024 * 1024
TIMEOUT_SECONDS = 10
SECTION_CHARS = 6000  # 每個模型往後最多看這麼多字，避免讀到別的模型的價格
MAX_PRICE = 1000.0

_MODEL_CODE = re.compile(r"gemini-[0-9][0-9a-z.\-]*[0-9a-z]", re.I)
_AMOUNT = re.compile(r"\$\s*([0-9]+(?:\.[0-9]+)?)")


class PriceFetchError(Exception):
    pass


def html_to_text(raw):
    raw = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", "\n", raw)
    text = html.unescape(raw)
    return re.sub(r"[ \t\r\f\v ]+", " ", re.sub(r"\n\s*", "\n", text))


def _first_amount(text, label):
    m = re.search(label + r"\b", text, re.I)
    if not m:
        return None
    # 標題之後 400 字內的第一個金額；超過代表這列沒有金額（例如只有 Free）
    window = text[m.end(): m.end() + 400]
    window = re.split(r"Output price|Input price", window, maxsplit=1, flags=re.I)[0]
    a = _AMOUNT.search(window)
    if not a:
        return None
    value = float(a.group(1))
    return value if 0 < value <= MAX_PRICE else None


def parse_prices(text, model_names):
    """回傳 {model: {"input": x, "output": y}}；只含兩個價格都讀到的模型。"""
    codes = [(m.start(), m.group(0).lower()) for m in _MODEL_CODE.finditer(text)]
    result = {}
    for name in model_names:
        target = name.lower()
        start = next((pos for pos, code in codes if code == target), None)
        if start is None:
            continue
        end = next((pos for pos, code in codes if pos > start and code != target), start + SECTION_CHARS)
        section = text[start: min(end, start + SECTION_CHARS)]
        inp = _first_amount(section, r"Input price")
        out = _first_amount(section, r"Output price")
        if inp is not None and out is not None:
            result[name] = {"input": inp, "output": out}
    return result


def fetch_page_text(opener=None):
    req = urllib.request.Request(PRICING_URL, headers={"User-Agent": "Mozilla/5.0 (price-reader)"})
    try:
        with (opener or urllib.request.urlopen)(req, timeout=TIMEOUT_SECONDS) as resp:
            raw = resp.read(MAX_BYTES + 1)
    except Exception as exc:  # noqa: BLE001
        raise PriceFetchError("無法連線到 Google 定價頁，請稍後再試或手動填寫") from exc
    if len(raw) > MAX_BYTES:
        raise PriceFetchError("定價頁內容過大，已放棄讀取")
    return html_to_text(raw.decode("utf-8", errors="replace"))


def fetch_prices(model_names, opener=None):
    text = fetch_page_text(opener)
    found = parse_prices(text, list(model_names))
    return {"source": PRICING_URL, "prices": found,
            "not_found": [n for n in model_names if n not in found]}
