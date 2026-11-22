"""官方定價頁解析：用模擬頁面測試（不連網）。"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services import ai_price_fetch_service as pf  # noqa: E402

FAILED = []


def check(name, cond):
    print(("[PASS] " if cond else "[FAIL] ") + name)
    if not cond:
        FAILED.append(name)


PAGE = """
<html><script>var x="gemini-9-fake $9.99";</script><body>
<h2>Gemini 3.5 Flash</h2><p><em><code>gemini-3.5-flash</code></em></p>
<h3>Standard</h3><table>
<tr><td>Input price</td><td>Free of charge</td><td>$1.50</td></tr>
<tr><td>Output price (including thinking tokens)</td><td>Free of charge</td><td>$9.00</td></tr></table>
<h3>Batch</h3><table><tr><td>Input price</td><td>$0.75</td></tr><tr><td>Output price</td><td>$4.50</td></tr></table>
<h2>Gemini 3.1 Flash-Lite</h2><p><code>gemini-3.1-flash-lite</code></p>
<table><tr><td>Input price</td><td>Free</td><td>$0.25 (text / image / video)<br>$0.50 (audio)</td></tr>
<tr><td>Output price</td><td>Free</td><td>$1.50</td></tr></table>
<h2>Gemini 3.8 Flash</h2><p><code>gemini-3.8-flash</code></p><p>Preview, pricing coming soon</p>
</body></html>
"""

text = pf.html_to_text(PAGE)
got = pf.parse_prices(text, ["gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-3.8-flash", "gemini-3.6-flash"])
check("3.5-flash 取 Standard 價 1.5 / 9", got.get("gemini-3.5-flash") == {"input": 1.5, "output": 9.0})
check("3.1-flash-lite 取文字價 0.25 / 1.5", got.get("gemini-3.1-flash-lite") == {"input": 0.25, "output": 1.5})
check("沒有金額的模型不回傳", "gemini-3.8-flash" not in got)
check("頁面沒有的模型不回傳", "gemini-3.6-flash" not in got)
check("script 內的假價格不影響", all(v["input"] != 9.99 for v in got.values()))


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


res = pf.fetch_prices(["gemini-3.5-flash", "gemini-3.6-flash"], opener=lambda req, timeout: FakeResp(PAGE.encode()))
check("fetch_prices 回傳價格與找不到的清單", res["prices"]["gemini-3.5-flash"]["input"] == 1.5 and res["not_found"] == ["gemini-3.6-flash"])
check("來源網址固定", res["source"] == pf.PRICING_URL and pf.PRICING_URL.startswith("https://ai.google.dev/"))


def boom(req, timeout):
    raise OSError("blocked")


try:
    pf.fetch_prices(["gemini-3.5-flash"], opener=boom)
    check("連線失敗要丟 PriceFetchError", False)
except pf.PriceFetchError:
    check("連線失敗要丟 PriceFetchError", True)

try:
    pf.fetch_prices(["x"], opener=lambda req, timeout: FakeResp(b"a" * (pf.MAX_BYTES + 10)))
    check("內容過大要拒絕", False)
except pf.PriceFetchError:
    check("內容過大要拒絕", True)

print("全部測試通過！" if not FAILED else "失敗：%s" % FAILED)
sys.exit(1 if FAILED else 0)
