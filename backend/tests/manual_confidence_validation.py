#!/usr/bin/env python
"""
manual_confidence_validation.py

【手動驗證腳本，不是自動化 test suite 的一部分】
檔名刻意用 manual_ 前綴（不是 test_ 前綴），一般 pytest / 「跑全部
tests/test_*.py」的流程都不會撿到這支腳本，需要人工明確指定路徑
執行。原因：這支腳本會真的打 Gemini API（消耗真實 quota、花費
真實時間、需要真實網路與正式/對應資料庫連線），跟其餘
backend/tests/test_*.py 全部用假 GenerativeModel、不打真實 API 的
風格完全不同，不適合混進自動化 test suite。

目的：
    用「目前 production 正在用的」taxonomy classification prompt
    （services.taxonomy_service.build_classification_prompt()，讀
    目前實際 published 的 Taxonomy_Version）+「目前 production 正在
    用的」分類協調函式（services.classify_v2.classify_response_multi_segment()），
    對 10 個刻意涵蓋不同難度的測試案例，實際呼叫 Gemini，記錄回傳的
    confidence 分布，驗證目前的 confidence rubric（已經加進
    prompt 裡的【分類信心評分規則】）是否真的能讓「應該要低信心」的
    案例產生 <0.75 的 confidence，而不是像修正前那樣幾乎全部落在
    高信心區間。

這支腳本本身：
    - 不修改、不寫入任何 production code 或 DB 資料（只讀 Taxonomy，
      不寫 Response_Classification，也不呼叫任何 persist 函式）。
    - 不修改 CONFIDENCE_THRESHOLD（直接從 services.confidence_gate
      原樣 import 使用，只讀不改）。
    - 不修改 prompt（直接呼叫現有的 build_classification_prompt()，
      不自己另外組字串）。
    - Fail-fast：缺少 GEMINI_API_KEY / DB 連線字串 / 對應
      topic_key 的 published Taxonomy，一律直接印出缺什麼、
      sys.exit(1)，不 fallback、不用假資料繼續跑。

執行方式：
    cd backend
    export SQLALCHEMY_DATABASE_URI="mysql+pymysql://user:pass@host/db_name"
    export GEMINI_API_KEY="..."
    export TOPIC_KEY="leadership_and_dept"   # 選填，預設 leadership_and_dept
    python3 tests/manual_confidence_validation.py

需要的環境變數：
    SQLALCHEMY_DATABASE_URI（或 DATABASE_URL 擇一）
        —— 要能連到「有 published Taxonomy_Version」的資料庫
        （正式環境，或還原正式資料的對應環境）。這支腳本只會讀
        Taxonomy_Version / Taxonomy_Category，不會寫入任何資料，
        但仍然需要一個真實可連線的資料庫，不接受純記憶體假資料庫
        （那樣就驗證不到「目前 production 真正在用的 taxonomy」）。
    GEMINI_API_KEY（或 GOOGLE_API_KEY / PPT_SURVEY_AI_API_KEY 三選一，
        跟 services/gemini_client.py 讀取 key 的優先序一致）
        —— 要能實際呼叫 Gemini API 的有效金鑰。
    TOPIC_KEY（選填，預設 "leadership_and_dept"）
        —— 要驗證哪一個 Topic 目前 published 的 taxonomy。
"""

import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def fail(message: str):
    """Fail-fast：印出清楚缺少什麼，直接結束，不 fallback、不用假資料。"""
    print(f"\n[FAIL-FAST] {message}")
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════
# 1. 環境檢查（fail-fast，沒有任何 fallback）
# ═══════════════════════════════════════════════════════════════

DB_URI = os.environ.get("SQLALCHEMY_DATABASE_URI") or os.environ.get("DATABASE_URL")
if not DB_URI:
    fail(
        "缺少資料庫連線字串：請設定環境變數 SQLALCHEMY_DATABASE_URI"
        "（或 DATABASE_URL），且必須能連到目前有 published"
        " Taxonomy_Version 的資料庫。本腳本不會用記憶體假資料庫"
        "代替，因為那樣驗證不到『目前 production 真正在用的"
        " taxonomy』。"
    )

GEMINI_API_KEY = (
    os.environ.get("GEMINI_API_KEY")
    or os.environ.get("GOOGLE_API_KEY")
    or os.environ.get("PPT_SURVEY_AI_API_KEY")
)
if not GEMINI_API_KEY:
    fail(
        "缺少 Gemini API 金鑰：請設定環境變數 GEMINI_API_KEY"
        "（或 GOOGLE_API_KEY / PPT_SURVEY_AI_API_KEY 三選一，"
        "跟 services/gemini_client.py 讀取金鑰的優先序一致）。"
        "這支腳本的目的就是要實際呼叫 Gemini，沒有金鑰就沒有意義，"
        "不會用假的 confidence 數字繼續跑下去。"
    )

TOPIC_KEY = os.environ.get("TOPIC_KEY", "leadership_and_dept")

# extensions.py 匯入時需要 JWT_SECRET_KEY（跟這支腳本的驗證邏輯本身
# 無關，純粹是既有 Flask app 初始化流程的既有要求），沒設定就給一個
# 明顯是驗證用途的預設值，不影響任何分類結果。
os.environ.setdefault("JWT_SECRET_KEY", "manual-confidence-validation-script")


from flask import Flask  # noqa: E402

from extensions import db  # noqa: E402
import models as m  # noqa: E402,F401  # 匯入以註冊全部 model / relationship
from services import taxonomy_service as ts  # noqa: E402
from services.taxonomy_service import (  # noqa: E402
    PublishedTaxonomyIntegrityError,
    PublishedTaxonomyNotFoundError,
)
from services.classify_v2 import classify_response_multi_segment  # noqa: E402
from services.confidence_gate import CONFIDENCE_THRESHOLD, evaluate_confidence_gate  # noqa: E402


app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = DB_URI
db.init_app(app)

with app.app_context():
    try:
        taxonomy_version = ts.get_published_taxonomy_version(TOPIC_KEY)
    except PublishedTaxonomyNotFoundError as e:
        fail(
            f"topic_key={TOPIC_KEY!r} 目前沒有任何 published Taxonomy_Version："
            f"{e}\n（本腳本不會 fallback 到 legacy DEFAULT_PROMPT_* 或任何"
            "自創分類，這正是 production classification 本身的 fail-closed"
            "規則，這支驗證腳本沿用同一個規則，不另外放寬。）"
        )
    except PublishedTaxonomyIntegrityError as e:
        fail(
            f"topic_key={TOPIC_KEY!r} 的 published Taxonomy 資料完整性有問題："
            f"{e}\n（例如同時有超過一筆 published，或 published 版本沒有任何"
            "category）。這是資料本身的問題，不能靠這支腳本猜一個版本繼續跑。"
        )

    # 直接用現有的 production 入口組 prompt / category_lookup，
    # 不自己另外拼字串、不繞過任何既有邏輯。
    prompt_content = ts.build_classification_prompt(taxonomy_version)
    category_lookup = ts.methodology_lookup_for_taxonomy_version(taxonomy_version)
    version_id = taxonomy_version.version_id

print(f"[OK] 已連上資料庫，topic_key={TOPIC_KEY!r} -> published "
      f"Taxonomy_Version(version_id={version_id})")
print(f"[OK] CONFIDENCE_THRESHOLD（原樣沿用 services/confidence_gate.py，"
      f"本腳本不修改）= {CONFIDENCE_THRESHOLD}")
print(f"[OK] prompt_content 長度：{len(prompt_content)} 字元"
      f"（確認不是空字串／組出來的 prompt 有實際內容）")


# ═══════════════════════════════════════════════════════════════
# 2. 10 個測試案例，涵蓋題目要求的 6 種情境
#    （針對 leadership_and_dept 這個 Topic 的既有 10 個子類別設計；
#    如果用 TOPIC_KEY 指定其他 Topic，案例文字不一定精準對應該
#    Topic 的類別，但腳本本身邏輯不變，Gemini 一樣會照樣跑、照樣
#    回傳 confidence，只是「這筆案例原本設計要測哪種難度」的標籤
#    可能對不上，這點在下面 summary 也會如實呈現，不會假裝符合預期。）
# ═══════════════════════════════════════════════════════════════

TEST_CASES = [
    {
        "case_type": "明確單一類別",
        "note": "清楚落在 A1 工作與生活邊界：下班後被工作訊息打擾，語意明確、無其他競爭主題",
        "input": "主管常常在下班後、甚至假日透過LINE交辦工作，讓我完全沒辦法好好休息，"
                 "已經影響到我的私人生活了。",
    },
    {
        "case_type": "明確單一類別",
        "note": "清楚落在 C1 正向回饋：明確表達滿意、沒有其他模糊主題",
        "input": "目前主管的帶領方式我覺得很好，團隊合作也很順暢，沒有需要改善的地方。",
    },
    {
        "case_type": "相近類別邊界模糊",
        "note": "同時觸及 A1（下班收到訊息）與 B1（跨部門溝通即時性），兩個子類別都說得通",
        "input": "主管常常在下班時間用LINE交代工作，而且不同部門之間的資訊傳遞也很慢，"
                 "常常要等好幾天才有回覆。",
    },
    {
        "case_type": "相近類別邊界模糊",
        "note": "同時觸及 A3（主管覺察力／留意壓力狀態）與 A4（領導風格／依部屬調整帶人方式）",
        "input": "希望主管可以依照每個人的狀況調整帶人的方式，也希望能多留意大家最近的工作壓力。",
    },
    {
        "case_type": "極短回答",
        "note": "只有兩個字，完全沒有具體語意內容",
        "input": "還好。",
    },
    {
        "case_type": "極短回答",
        "note": "同樣極短，且語氣中性、看不出任何傾向",
        "input": "沒有意見。",
    },
    {
        "case_type": "語意不足",
        "note": "有字數但沒有任何具體指涉對象，不知道是在講誰、講什麼事",
        "input": "希望可以再好一點，這樣大家會比較開心。",
    },
    {
        "case_type": "需要推論才能分類",
        "note": "沒有明講原因，要自行腦補『累』是不是跟工作負荷、下班打擾、或其他因素有關",
        "input": "最近常常覺得很累，不知道該怎麼辦。",
    },
    {
        "case_type": "需要推論才能分類",
        "note": "『卡住』沒有說是哪個環節，要自行猜測是跨部門協調、主管溝通、還是其他",
        "input": "溝通這塊我覺得好像哪裡卡住了，希望可以改善。",
    },
    {
        "case_type": "與 taxonomy 不太吻合",
        "note": "跟主管領導／部門合作完全無關的辦公環境瑣事，taxonomy 裡沒有對應的類別",
        "input": "希望公司可以提供免費的咖啡機和零食，辦公室的椅子也希望能換新一點的。",
    },
]

assert len(TEST_CASES) == 10, "本腳本設計為固定 10 個案例，異動請同步調整 summary 說明"


# ═══════════════════════════════════════════════════════════════
# 3. Smoke test：先用一個語意清楚的簡單案例確認 Gemini 金鑰／網路
#    真的可用，避免「金鑰失效／網路被擋」這種系統性問題，讓後面
#    10 筆全部 segmentation 失敗，報表卻看起來像是「confidence
#    都拿不到」的假象，混淆成 rubric 本身的問題。
# ═══════════════════════════════════════════════════════════════

print("\n[SMOKE TEST] 驗證 Gemini 連線與金鑰有效性 ...")
_smoke = classify_response_multi_segment(
    "主管很願意聽取部門的意見，合作起來很順利。",
    prompt_content, TOPIC_KEY, category_lookup=category_lookup,
)
if _smoke["segmentation_status"] == "failed" or not _smoke["segments"]:
    fail(
        "Smoke test 呼叫 Gemini 失敗："
        f"segmentation_status={_smoke['segmentation_status']!r}，"
        f"error_detail={_smoke['segmentation_error_detail']!r}\n"
        "請確認 GEMINI_API_KEY 有效、額度足夠、網路可以連到 Gemini API。"
        "本腳本不會用假資料繼續跑接下來的 10 筆案例。"
    )
print("[OK] Gemini 連線與金鑰驗證通過，開始跑 10 筆驗證案例。\n")


# ═══════════════════════════════════════════════════════════════
# 4. 逐筆實際呼叫 classify_response_multi_segment()（production
#    協調函式本身，不繞過、不重寫）
#
#    刻意不傳 taxonomy_version_id：這支腳本只驗證「目前 confidence
#    rubric 本身」的效果，不想讓 Human Review feedback loop（如果
#    這個 topic 剛好已經有 confirmed/modified 範例）混進來影響這次
#    量測結果，避免搞不清楚「confidence 變低是因為 rubric，還是
#    因為剛好有 feedback 範例」。如果之後想連 feedback loop 一起
#    驗證，可以另外呼叫 classify_response_multi_segment 時帶入
#    taxonomy_version_id=version_id，這裡先不這麼做。
# ═══════════════════════════════════════════════════════════════

rows = []  # 每一列對應輸出表格 + summary 用的一筆紀錄

for i, case in enumerate(TEST_CASES, start=1):
    print(f"--- 案例 {i}/10：{case['case_type']}｜{case['note']} ---")
    print(f"input: {case['input']}")

    result = classify_response_multi_segment(
        case["input"], prompt_content, TOPIC_KEY, category_lookup=category_lookup,
    )

    if not result["segments"]:
        print(
            f"[WARN] 這筆完全沒有產生任何 segment"
            f"（segmentation_status={result['segmentation_status']!r}，"
            f"error_detail={result['segmentation_error_detail']!r}），"
            "如實記錄為一筆『無法分類』結果，不編造 confidence 數值。"
        )
        rows.append({
            "case_index": i,
            "case_type": case["case_type"],
            "input": case["input"],
            "segment_text": None,
            "main_category": None,
            "sub_category": None,
            "confidence": None,
            "needs_human_review": True,
            "review_flag_reason": f"segmentation_{result['segmentation_status']}",
        })
        print()
        continue

    for seg_i, seg in enumerate(result["segments"]):
        needs_review, reason = evaluate_confidence_gate(seg)
        row = {
            "case_index": i,
            "case_type": case["case_type"],
            "input": case["input"],
            "segment_text": case["input"][seg["orig_start"]:seg["orig_end"]],
            "main_category": seg["main_category"],
            "sub_category": seg["sub_category"],
            "confidence": seg["confidence"],
            "needs_human_review": needs_review,
            "review_flag_reason": reason,
        }
        rows.append(row)

        seg_label = f"（第 {seg_i + 1} 個 segment）" if len(result["segments"]) > 1 else ""
        below_threshold = (
            "N/A" if not isinstance(row["confidence"], (int, float))
            else ("是" if row["confidence"] < CONFIDENCE_THRESHOLD else "否")
        )
        print(f"  {seg_label}main_category   : {row['main_category']}")
        print(f"  {seg_label}sub_category    : {row['sub_category']}")
        print(f"  {seg_label}confidence      : {row['confidence']}")
        print(f"  {seg_label}< {CONFIDENCE_THRESHOLD}         : {below_threshold}")
        print(f"  {seg_label}needs_human_review : {row['needs_human_review']}")
        print(f"  {seg_label}review_flag_reason : {row['review_flag_reason']}")
    print()


# ═══════════════════════════════════════════════════════════════
# 5. Summary
# ═══════════════════════════════════════════════════════════════

print("=" * 70)
print("SUMMARY")
print("=" * 70)
print(f"總案例數（原始測試案例）：{len(TEST_CASES)}")
print(f"實際產生的 segment / 分類結果筆數：{len(rows)}"
      f"（可能因為某案例被拆成多個 segment，或某案例 segmentation 失敗"
      "產生 0 筆分類而跟原始案例數不同）")

numeric_confidences = [r["confidence"] for r in rows if isinstance(r["confidence"], (int, float))]
non_numeric_count = len(rows) - len(numeric_confidences)

if numeric_confidences:
    print(f"\nconfidence 最低：{min(numeric_confidences):.4f}")
    print(f"confidence 最高：{max(numeric_confidences):.4f}")
    print(f"confidence 平均：{statistics.mean(numeric_confidences):.4f}")
    if len(numeric_confidences) > 1:
        print(f"confidence 標準差：{statistics.pstdev(numeric_confidences):.4f}")
else:
    print("\n[WARN] 沒有任何一筆拿到數值型 confidence，無法計算最低/最高/平均。")

below = [r for r in rows if isinstance(r["confidence"], (int, float)) and r["confidence"] < CONFIDENCE_THRESHOLD]
at_or_above = [r for r in rows if isinstance(r["confidence"], (int, float)) and r["confidence"] >= CONFIDENCE_THRESHOLD]

print(f"\n< {CONFIDENCE_THRESHOLD} 筆數：{len(below)}")
print(f">= {CONFIDENCE_THRESHOLD} 筆數：{len(at_or_above)}")
if non_numeric_count:
    print(f"無數值型 confidence（分類失敗／未產生 segment）筆數：{non_numeric_count}")

if below:
    print("\n< threshold 的案例明細（case_type / confidence / sub_category）：")
    for r in below:
        print(f"  - [{r['case_type']}] confidence={r['confidence']} -> {r['sub_category']}")

print("\n完整結果（每一列一個 segment，可貼回分析）：")
header = ("case_index", "case_type", "main_category", "sub_category", "confidence", "needs_human_review", "review_flag_reason")
print("\t".join(header))
for r in rows:
    print("\t".join(str(r[h]) for h in header))