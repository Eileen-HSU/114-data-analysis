"""

自動判斷一段文字（問卷題目 title，或 Excel 欄位名稱＋範例內容）
屬於系統目前哪一個 Topic（分析框架）。

【Dynamic Topic routing，取代原本寫死兩個固定 Topic 的版本】
候選 Topic 不再是 import-time 就固定好的兩個常數
（leadership_and_dept / career_and_feedback），而是每次呼叫
route_question_type() 時，即時從 DB 查「目前有且僅有一筆 published
Taxonomy_Version 的 Topic」動態組出來（見 _get_routing_candidates()）。
Admin 之後動態建立、Publish 新 Topic，不需要改這支檔案、不需要重新
部署，下一次呼叫就會自動把新 Topic 納入候選——這是這次改動的目的。

只有「目前有 published taxonomy 的 Topic」才會出現在候選清單裡（跟
services.taxonomy_service.get_published_taxonomy_version() 對單一
Topic 用的是同一個不變量，這裡是同一件事的「查全部」版本）：
    - 0 筆 published：這個 Topic 還沒真的可以拿來分類，不進候選。
    - 1 筆 published：正常收錄進候選。
    - >1 筆 published：違反「每個 Topic 最多一個 published 版本」的
      資料完整性假設，這個 Topic 整個排除在候選之外並印一行
      [ROUTING_TOPIC_INTEGRITY_ERROR] log，但**不會**讓這次
      route_question_type() 呼叫整個失敗——其餘資料正常的 Topic
      仍然照常可以被選到，一個異常 Topic 不該拖垮整個 routing。

呼叫時機是「題目建立時」「上傳當下」各一次，不是每則回答一次，
不會隨回答數量增加呼叫次數；下面的重試機制也一樣——重試只發生在
「同一次判斷」內部，不會讓呼叫次數隨回答數量或重試而線性增加。
這次改動完全不動這個呼叫粒度：Excel 仍然是「一個文字欄位 = 一題 =
routing 一次」，Survey 仍然是「一題 routing 一次」，呼叫端
（routes/classifications/classification.py、routes/surveys/survey.py）
原則上不需要跟著改，因為兩邊呼叫的都還是同一個
route_question_type(context_text) -> Optional[str] 函式簽章。

回傳 None 的情況，現在多了一種，但語意上都收斂成同一件事——「這筆
內容目前歸不到任何一個真正可用的 Topic」，呼叫端一律 fallback 成
QUESTION_OTHER，繼續走「其他 / 未歸屬資料」既有流程，這是正常
fallback，不是錯誤狀態，不會因為改成 dynamic routing 就被拿掉：

    1) 輸入是空字串 / 空白字串 —— 不會呼叫 Gemini，直接回傳 None。
    2) 目前完全沒有任何 Topic 有 published taxonomy（候選清單為空）
       —— 不會呼叫 Gemini（呼叫了也沒有任何合法答案可選），直接
       回傳 None。這是 dynamic routing 新增的情況。
    3)「內容真的判斷不出來」：Gemini 有成功回應，只是判斷結果本來
       就是 null、或回傳了不在這次候選清單裡的值（例如候選之間都
       不太吻合、內容太模糊、證據不足）。這種情況不需要重試，
       直接回傳 None——**不可以因為候選變多了就強行選一個最相近的
       Topic**，null 永遠是合法且經常正確的答案。
    4)「Gemini API 暫時性故障」：呼叫本身失敗，例如 429 / quota
       exceeded / rate limit / 5xx / 逾時。這種情況會先重試，重試
       仍失敗才回傳 None。

log 分成五種，方便從後端 log 分辨原因（不再全部只印
`[ROUTING ERROR]`）：
    [ROUTING_RATE_LIMIT]              偵測到 429 / quota / 限流，
                                       準備重試，或重試已用盡
    [ROUTING_API_ERROR]               非限流的其他呼叫 / 解析錯誤，
                                       不重試
    [ROUTING_UNDETERMINED]            Gemini 正常回應，但判斷結果是
                                       「無法歸類」
    [ROUTING_TOPIC_INTEGRITY_ERROR]   組候選清單時發現某個 Topic
                                       同時有 >1 筆 published
                                       Taxonomy_Version，這個 Topic
                                       被排除在候選之外（新增）
    [ROUTING_FALLBACK]                這次呼叫最終回傳 None（不論
                                       上面哪個原因），提醒呼叫端
                                       這裡會需要 fallback 處理
"""

import json
import os
import re
import time
from typing import Optional

from services import gemini_client as genai

genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))


_RETRY_DELAY_PATTERNS = (
    re.compile(r"[Rr]etry in ([\d.]+)s"),
    re.compile(r'"retryDelay"\s*:\s*"([\d.]+)s"'),
)


_MAX_ATTEMPTS = 3
_DEFAULT_RETRY_DELAY_SECONDS = 20.0

# 組 routing prompt 時，每個 Topic 最多列出幾個 main_category/
# sub_category 名稱當「分類摘要」，避免 Topic 底下子類別很多時，
# prompt 被單一 Topic 的清單撐得過長，排擠掉其他候選、也讓
# Gemini 抓不到重點。只是「摘要」，不是完整 taxonomy 定義（完整
# 定義是 Gemini #2 分類階段的事，這裡只需要「足以辨識用途」的程度）。
_MAX_CATEGORY_NAMES_IN_SUMMARY = 12


def _extract_retry_delay_seconds(exc: Exception) -> Optional[float]:
    """從例外訊息裡解析 Gemini 建議的等待秒數；解析不到就回傳 None，
    呼叫端會改用固定預設值。"""
    text = str(exc)
    for pattern in _RETRY_DELAY_PATTERNS:
        match = pattern.search(text)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                continue
    return None


def _is_rate_limit_error(exc: Exception) -> bool:
    """判斷是不是「暫時性」限流 / quota 錯誤（值得重試），而不是
    prompt 有問題、回應格式跑掉之類「重試也沒用」的錯誤。"""
    text = str(exc)
    return (
        "429" in text
        or "ResourceExhausted" in type(exc).__name__
        or "RESOURCE_EXHAUSTED" in text
        or "quota" in text.lower()
    )


def _get_routing_candidates() -> list:
    """
    動態組出這次 route_question_type() 呼叫可以選的候選 Topic 清單。

    只在真的呼叫這個函式時才 import models/taxonomy（lazy import），
    這個模組頂層維持完全不依賴 DB / Flask app context——跟
    services/classify_v2.py、services/taxonomy_service.py 已經確立
    的慣例一致，避免任何「只是想 import 這個模組」的地方（例如某些
    測試、cli.py）被迫連帶需要一個 app context。

    回傳 list，每個元素：
        {
            "topic_key": str,
            "title": str,
            "question_text": str | None,
            "description": str | None,
            "category_summary": list[str],   # 這個 Topic published
                                              # 版本底下的 main_category
                                              # / sub_category 名稱，
                                              # 最多 _MAX_CATEGORY_NAMES_
                                              # IN_SUMMARY 個，依
                                              # sort_order 取前幾個
        }

    Integrity 規則（見檔案開頭說明）：0 筆 published 的 Topic 不會
    出現在這裡（因為查詢本身就是從 published Taxonomy_Version 出發，
    沒有 published 版本的 Topic 不會被撈到，不需要額外過濾）；
    >1 筆 published 的 Topic 會被明確排除並印
    [ROUTING_TOPIC_INTEGRITY_ERROR]，不會讓整次查詢失敗。
    """
    from models import Taxonomy_Version
    from taxonomy import TAXONOMY_VERSION_STATUS_PUBLISHED

    published_versions = Taxonomy_Version.query.filter_by(
        status=TAXONOMY_VERSION_STATUS_PUBLISHED
    ).all()

    versions_by_topic = {}
    for version in published_versions:
        versions_by_topic.setdefault(version.topic_key, []).append(version)

    candidates = []
    for topic_key, versions in versions_by_topic.items():
        if len(versions) > 1:
            version_ids = sorted(v.version_id for v in versions)
            print(
                "[ROUTING_TOPIC_INTEGRITY_ERROR]",
                f"topic_key={topic_key!r} 同時有 {len(versions)} 個 published "
                f"Taxonomy_Version（version_id={version_ids}），這個 Topic 這次"
                "排除在 routing candidates 之外，不影響其他正常 Topic 被選到。",
            )
            continue

        version = versions[0]
        topic = version.topic  # Taxonomy_Version -> Topic 的 backref（見 taxonomy.py）

        category_names = []
        seen_labels = set()
        for category in version.categories:  # 已依 sort_order 排序
            label = (
                f"{category.main_category} / {category.sub_category}"
                if category.main_category else category.sub_category
            )
            if not label or label in seen_labels:
                continue
            seen_labels.add(label)
            category_names.append(label)
            if len(category_names) >= _MAX_CATEGORY_NAMES_IN_SUMMARY:
                break

        candidates.append({
            "topic_key": topic_key,
            "title": topic.title if topic else topic_key,
            "question_text": topic.question_text if topic else None,
            "description": topic.description if topic else None,
            "category_summary": category_names,
        })

    return candidates


def _build_routing_prompt(candidates: list) -> str:
    """
    把 _get_routing_candidates() 的結果組成這次要送給 Gemini 的
    system_instruction。description 不是必填（目前 Topic 建立流程
    也還沒有收集這個欄位的 UI），沒有 description 時改用
    question_text／category_summary 補位，兩者都沒有時就只用
    title——candidates 本身已經保證每個 Topic 至少有 title 跟
    topic_key，不會有完全沒有任何描述線索的候選。
    """
    lines = []
    for c in candidates:
        detail_parts = []
        if c["description"]:
            detail_parts.append(c["description"].strip())
        if c["question_text"]:
            detail_parts.append(f"題目原文參考：{c['question_text'].strip()}")
        if c["category_summary"]:
            detail_parts.append("涵蓋子類別：" + "、".join(c["category_summary"]))

        detail = "；".join(detail_parts) if detail_parts else "（目前沒有額外描述，僅有標題，請主要依標題判斷）"
        lines.append(f"- {c['topic_key']}（{c['title']}）：{detail}")

    candidates_block = "\n".join(lines)
    topic_key_options = "、".join(f'"{c["topic_key"]}"' for c in candidates)

    return f"""你是問卷內容的分類 routing 判斷助手。系統目前有以下這些分析框架（Topic）：

{candidates_block}

請判斷輸入內容（可能是題目名稱，也可能包含實際回答範例）整體上比較
屬於上面哪一個 Topic。如果內容跟上面任何一個 Topic 都無關、內容過於
模糊、證據不足、或無法可靠判斷，請回傳 null，不要用猜的、不要強行
歸類到最相近的那一個——這些內容之後會被歸類到「其他 / 未歸屬資料」，
這是正常結果，不是錯誤，寧可回 null 也不要硬選一個不夠吻合的 Topic。

只回傳以下 JSON 格式，不要加任何其他文字：
{{"question_type": {topic_key_options} 其中之一，或 null}}"""


def route_question_type(context_text: str) -> Optional[str]:
    """
    對外主要介面，函式簽章維持不變。輸入已經組好的判斷用文字
    （呼叫端負責組裝、以及必要的 PII masking，這裡不做遮罩），
    回傳判斷結果（某個目前有 published taxonomy 的 Topic.topic_key）
    或 None。

    最多呼叫 Gemini _MAX_ATTEMPTS 次，只有真的撞到限流才會重試；
    其餘情況（內容判斷不出來、非限流錯誤）都只呼叫一次就回傳。

    候選清單在函式一開始查一次、整個函式（含重試）共用同一份，
    不會每次重試都重新查 DB、也不會讓同一次判斷內的多次嘗試看到
    不一致的候選清單。
    """
    if not context_text or not context_text.strip():
        return None

    candidates = _get_routing_candidates()
    if not candidates:
        # 目前完全沒有任何 Topic 有 published taxonomy，沒有任何
        # 合法答案可選，連 Gemini 都不用呼叫。
        print("[ROUTING_FALLBACK]", "reason=no_candidates")
        return None

    allowed_topic_keys = {c["topic_key"] for c in candidates}
    routing_prompt = _build_routing_prompt(candidates)

    last_error: Optional[Exception] = None

    for attempt in range(_MAX_ATTEMPTS):
        try:
            model = genai.GenerativeModel(
                model_name="gemini-3.1-flash-lite",
                system_instruction=routing_prompt,
            )
            response = model.generate_content(
                context_text,
                generation_config={"temperature": 0},
            )
            cleaned = re.sub(r"```json|```", "", response.text).strip()
            parsed = json.loads(cleaned)
            result = parsed.get("question_type")

            if result in allowed_topic_keys:
                return result

            # Gemini 有成功回應，只是判斷結果是 null、或不在這次
            # 候選清單裡（例如候選改變了、或 Gemini 自己編了一個不
            # 存在的 key）——這是「內容真的判斷不出來」，不是 API
            # 錯誤，不重試。
            print("[ROUTING_UNDETERMINED]", f"raw_result={result!r}", f"allowed={sorted(allowed_topic_keys)}")
            print("[ROUTING_FALLBACK]", "reason=undetermined")
            return None

        except Exception as e:
            last_error = e

            if _is_rate_limit_error(e):
                remaining_attempts = _MAX_ATTEMPTS - attempt - 1
                if remaining_attempts > 0:
                    delay = _extract_retry_delay_seconds(e) or _DEFAULT_RETRY_DELAY_SECONDS
                    print(
                        "[ROUTING_RATE_LIMIT]",
                        f"attempt={attempt + 1}/{_MAX_ATTEMPTS}",
                        f"retry_in={delay}s",
                        repr(e),
                    )
                    time.sleep(delay + 1.0)
                    continue
                print(
                    "[ROUTING_RATE_LIMIT]",
                    f"attempt={attempt + 1}/{_MAX_ATTEMPTS}",
                    "retries_exhausted",
                    repr(e),
                )
                break

            # 非限流錯誤（prompt 有問題、JSON 解析失敗等）：維持原本
            # 行為，不重試，直接視為這次判斷失敗。
            print("[ROUTING_API_ERROR]", f"attempt={attempt + 1}", repr(e))
            break

    print("[ROUTING_FALLBACK]", "reason=api_failure", repr(last_error))
    return None
