import json
import os
import re

import google.generativeai as genai

from services.subcategory_methodology import (
    QUESTION_LEADERSHIP,
    QUESTION_CAREER,
    get_methodology,
)
from services.privacy_service import mask_pii, mask_pii_with_mapping, PiiMaskingError
from services.segmentation_service import segment_answer

genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))


# Gemini #2（批次分類）專用：附加在 prompt_content 之後的輸出格式
# 覆蓋說明。不動 prompt_content 本身，只在它後面多接這一段，
# 明確覆蓋 prompt_content 尾端「只回傳單一 JSON」的既有指示，
# 分類定義／判斷規則完全沿用 prompt_content，不重新定義一次。
BATCH_OUTPUT_FORMAT_OVERRIDE = """

【本次輸出格式覆蓋，優先於上方「輸出格式」段落的單筆 JSON 說明】
接下來你會收到 {n} 個編號片段（不是單一段回覆），請忽略上方「只
回傳單一 main_category/sub_category JSON」的指示，改為對「每一個」
片段各自套用上方的分類定義、次要類別規則與判斷標準，並用以下陣列
格式一次回傳所有片段的結果，不要加任何其他文字：

{{"classifications": [
  {{"index": 0, "main_category": "...", "sub_category": "...", "secondary_sub_category": null, "reasoning": "...", "summary": "...", "confidence": "..."}},
  ...
]}}

index 必須恰好包含 0 到 {n_minus_1}，每個各出現一次，不能遺漏也不能
重複。除了「輸出格式從單筆物件改成 classifications 陣列」之外，
分類邏輯、可選類別、次要類別規則、判斷標準完全比照上方規則，
不需要另外調整；片段之間請各自獨立判斷，不要互相影響。"""


# ── 系統層級總分類規則（0731_prompt訓練.md 最後一段，兩題共用）──────────
GLOBAL_RULES = """【系統層級總分類規則】
1. 分類時應以完整語意及主要訴求為判斷基礎，不得只依單一關鍵字分類。
2. 每則回覆原則上輸出一個主要類別；若同時明確涉及兩個以上獨立主題，可增加次要類別。
3. 主要類別應代表受試者最核心的問題、需求或評價；次要類別只用於內容中具有明確但非核心的其他主題。
4. 「無具體建議」與「正向回饋」必須分開：沒有提出建議不等於滿意，只有出現明確認可或滿意語意時，才能歸入正向回饋。
5. 不得加入原文未表達的情緒、動機或因果關係，例如不得自行推定受試者焦慮、不滿、支持或具有離職意圖。
6. 若回覆資訊不足或無法在既有類別間明確判斷，應輸出「低信心」並交由人工複核，不得強行分類。
7. 輸出結果應包含主要類別、次要類別、分類信心及簡短判斷依據，以利後續檢查與模型校正。"""


# ── 動態分類（其他主題）：問卷內容跟前兩個固定主題都對不上時使用 ──────
# 跟上面兩個固定 prompt 不一樣，這裡沒有「只能從清單中選」的限制，
# 改成讓 Gemini 依實際內容自己決定合適的大類別、子類別；輸出格式跟
# 前兩個完全一致（GLOBAL_RULES、JSON schema都相同），才能沿用同一套
# 後續處理（分割、批次分類、彙整）不用另外寫一套。
DYNAMIC_GENERAL_PROMPT = f"""你是一個問卷回答分類助手，負責分析一份開放式問卷回覆。

【這份問卷沒有預先定義的固定類別清單】
請你先通盤理解這批回覆整體在討論什麼主題，然後依內容自己歸納出合適
的大類別（3-6 個字的精簡主題名稱，例如「介面操作」「價格與方案」
「功能建議」）與子類別（更具體的細項，例如「操作流程不直覺」
「希望降低訂閱價格」）。

【重要：類別命名要一致】
同一批回覆裡，語意相近的內容必須套用完全相同的大類別／子類別名稱
文字（逐字一致，包含用字、順序），不可以同一個意思換不同說法
（例如不要一下叫「操作體驗」、一下叫「使用體驗」），這樣才能正確
把相同主題的回覆歸在一起。子類別不需要加編號（不要寫 A1、B2 這種
前綴，這是給有固定清單的題目用的，這裡不適用）。

{GLOBAL_RULES}

【次要類別規則】
每則回覆原則上輸出一個主要類別；若同時明確涉及兩個以上獨立主題，
可額外輸出一個次要類別，一樣要用你已經歸納出的類別名稱，不要另外
發明新名稱。若內容只涉及單一主題，secondary_sub_category 請輸出
null，不要為了填欄位而勉強生成。

【輸出格式】
絕對不可修改或改寫「問卷回覆內容」原文，僅作為判斷依據。
只回傳以下 JSON 格式，不要加任何其他文字說明：

{{
  "main_category": "大類別名稱",
  "sub_category": "子類別名稱",
  "secondary_sub_category": "次要子類別名稱，若無則為 null",
  "reasoning": "判斷原因與說明，1-2句話",
  "summary": "受試者建議摘要，1句話",
  "confidence": "high 或 low"
}}"""


# ── 題目一：主管領導與部門合作 ──────────────────────────────────────
DEFAULT_PROMPT_LEADERSHIP = f"""你是一個問卷回答分類助手，負責分析「主管領導和部門合作」這題的開放式回覆。

【可用的大類別與子類別，只能從以下清單中選擇，不得自創】

大類別：主管領導
- A1 工作與生活邊界
- A2 回饋與溝通
- A3 主管覺察力
- A4 領導風格

大類別：部門合作
- B1 溝通與協調機制
- B2 支援協作
- B3 權責界定與規範落實
- B4 管理一致性

大類別：其他與建議
- C1 正向回饋
- C2 無具體建議

【各子類別判斷指令與判斷規則】

1. A1 工作與生活邊界：當回覆主要涉及下班後、假日、休息時間或私人時間收到工作訊息，以及工作聯繫侵入非工作時間、造成壓力、難以休息、難以喘息或無法心理抽離等情形時，歸入此類別。若回覆主要涉及跨部門責任推諉、資源共享、必要支援或協作態度，則不歸入本類別，應歸入「支援協作」。若回覆主要涉及一般溝通效率、資訊傳遞、會議安排或即時溝通平台，則應歸入「溝通與協調機制」或「回饋與溝通」。若同一回覆同時涉及非工作時間被打擾及其他管理問題，應以「工作聯繫是否侵入私人時間」作為本類別的主要判斷標準。

2. A2 回饋與溝通：當回覆主要涉及感謝、表揚、肯定、日常回饋方式、知識管理、主管或講師與團隊之間的交流，以及希望增加互動或說明時間時，歸入此類別。若回覆重點是對形式化感謝或表揚感到尷尬、壓力或不適，也歸入本類別。若回覆主要涉及跨部門資訊傳遞不即時、缺乏整體規劃、協調會議或溝通平台，則歸入「溝通與協調機制」。若回覆主要涉及跨部門推諉責任、資源共享或必要支援，則歸入「支援協作」。

3. A3 主管覺察力：當回覆主要涉及主管是否能察覺人才流失風險、部屬心理狀態、自我肯定不足、工作壓力、階段性發展狀況，或主管與員工之間的認知落差時，歸入此類別。提及匿名調查、雙向回饋、定期了解員工感受，或希望主管及早發現離職徵兆者，也歸入本類別。若回覆主要要求主管依不同部屬提供不同指導、溝通或激勵方式，則歸入「領導風格」。若回覆主要談績效標準應客觀、明確或不受個人喜好影響，則歸入「客觀與具體回饋」。

4. A4 領導風格：當回覆主要涉及主管的管理方式、溝通風格、指導方式、激勵方式，以及是否能依不同部屬的能力、狀態或需求調整領導方式時，歸入此類別。提及個人化指導、差異化溝通、有形或無形獎勵、情境調整，或認為不同主管風格對整體運作影響有限者，均可歸入本類別。若回覆主要涉及主管是否察覺員工壓力、離職風險或心理狀態，則歸入「主管覺察力」。

5. B1 溝通與協調機制：當回覆主要涉及跨部門資訊傳遞、溝通即時性、整體規劃、配套措施、協調會議、溝通平台、多重轉述、等待回應或資訊落差時，歸入此類別。提及定期跨部門交流、案例分享、跨部門協調會議、即時溝通工具、工作輪調或職務體驗，以改善理解與協作效率者，也歸入本類別。若回覆主要涉及部門之間是否願意實際提供協助、共享資源、避免推諉責任或必要時補位，則歸入「支援協作」。若回覆主要涉及權責不清、分工不明或制度需要再教育，則歸入「權責界定與規範落實」。若回覆主要涉及不同團隊的管理方式、表單、教材或工作標準不一致，則歸入「管理一致性」。

6. B2 支援協作：當回覆主要涉及跨部門之間是否願意實際提供協助、共享資源、相互補位、共同承擔問題，或避免推諉責任、重複作業及單向索取時，歸入此類別。提及必要時提供支援、站在對方角度思考、發揮各自專業、不要把問題丟回其他部門、透過跨團隊專案累積共同經驗者，也歸入本類別。若回覆主要涉及資訊傳遞不即時、缺乏協調會議、溝通平台或整體規劃，則歸入「溝通與協調機制」。若回覆主要涉及分工、責任範圍、制度規範或再教育，則歸入「權責界定與規範落實」。

7. B3 權責界定與規範落實：當回覆主要涉及部門或角色之間的分工、權限、責任範圍、工作歸屬，以及制度、流程或作業規範是否被充分說明與落實時，歸入此類別。提及權責不清、分工模糊、需要持續說明、再教育、制度宣導或確保人員理解作業標準者，也歸入本類別。若回覆主要涉及不同團隊使用不同表單、教材、母片、管理方式或工作標準，則歸入「管理一致性」。若回覆主要涉及資訊傳遞、協調會議或即時溝通平台，則歸入「溝通與協調機制」。

8. B4 管理一致性：當回覆主要涉及不同團隊在管理方式、工作標準、核心產品語言、教材版本、表單格式、母片、字體、Check List、知識分享或作業工具上的不一致時，歸入此類別。提及雙重標準、不同 Team 各自形成不同做法、講師因標準不同而產生迷惘或溝通成本，以及希望統一共通文件與基本作業原則者，也歸入本類別。客戶判斷、經營方式或專案執行上的合理彈性，不應單獨視為管理不一致；只有當差異造成共通標準混亂、合作成本或執行落差時，才歸入本類別。

9. C1 正向回饋：當回覆明確表達對現行主管領導、同事合作、跨部門協作、講師照顧、工作環境或既有制度感到滿意、肯定、良好或獲得幫助時，歸入此類別。常見表達包括「很好」、「滿意」、「已經做得很好」、「有獲得幫助」或「沒有需要改善，因為目前狀況良好」。僅回答「無」、「沒有」、「暫時沒有」而未表達明確正向態度者，不歸入本類別，應歸入「無具體建議」。不得因受試者沒有提出建議，就自行推定其對現況感到滿意。

10. C2 無具體建議：當回覆僅表示「無」、「沒有」、「暫時沒有」、「目前沒有建議」或其他未提供具體意見與改善方向的內容時，歸入此類別。此類回覆只表示目前沒有可供分析的具體內容，不得自行推定受試者滿意、不滿意或認同現行制度。若回覆明確表示「目前很好」、「已經滿意」或「沒有建議，因為現況良好」，則應歸入「正向回饋」。若回覆內容過於簡短、語意不明或無法判斷是否具有實質意見，優先歸入本類別，並標記為低信心分類。

{GLOBAL_RULES}

【次要類別規則】
每則回覆原則上輸出一個主要類別；若同時明確涉及兩個以上獨立主題（例如同時對「主管領導」與「部門合作」都有具體意見），
可額外輸出一個次要類別。次要類別必須是與主要類別不同的合法子類別（從上方清單中選）；
若內容只涉及單一主題，secondary_sub_category 請輸出 null，不要為了填欄位而勉強生成。

【輸出格式】
絕對不可修改或改寫「問卷回覆內容」原文，僅作為判斷依據。
只回傳以下 JSON 格式，不要加任何其他文字說明：

{{
  "main_category": "大類別名稱",
  "sub_category": "完整子類別名稱（含編號，例如 A1 工作與生活邊界）",
  "secondary_sub_category": "次要子類別名稱，若無則為 null",
  "reasoning": "判斷原因與說明，1-2句話",
  "summary": "受試者建議摘要，1句話",
  "confidence": "high 或 low"
}}"""


# ── 題目二：工作表現的回饋及職涯發展 ─────────────────────────────────
DEFAULT_PROMPT_CAREER = f"""你是一個問卷回答分類助手，負責分析「工作表現的回饋及職涯發展」這題的開放式回覆。

【可用的大類別與子類別，只能從以下清單中選擇，不得自創】

大類別：工作表現的回饋及職涯發展
- A1 獎酬、激勵與晉升制度
- A2 品牌定位與市場曝光
- A3 設備資源與數位支持
- A4 PM 發展與留才
- A5 教育訓練
- A6 職涯發展與回饋制度
- A7 雙向溝通
- A8 工作優化與身心平衡
- A9 客觀與具體回饋

大類別：其他與建議
- B1 正向回饋
- B2 無具體建議

【各子類別判斷指令與判斷規則】

1. A1 獎酬、激勵與晉升制度：當回覆主要涉及薪資、獎金、加薪、績優獎項、即時獎勵、薪資透明度、獎金級距、晉升標準、考核辦法或職涯升遷地圖時，歸入此類別。若回覆主要涉及 Mentor、經驗傳承、工作心得分享或職涯典範，則歸入「職涯發展與回饋制度」。若回覆主要涉及績效評價是否客觀、明確及不受個人偏好影響，則歸入「客觀與具體回饋」。

2. A2 品牌定位與市場曝光：當回覆主要涉及公司、商品、課程或服務的品牌定位、市場競爭力、文宣內容、行銷主題、廣告投放、曝光程度或市場辨識度時，歸入此類別。若回覆主要涉及內部員工設備、AI 工具或數位資源，則歸入「設備資源與數位支持」。若回覆主要涉及員工學習 AI、產業趨勢或外部課程，則歸入「教育訓練」。僅當內容明確涉及對外市場、顧客認知或品牌推廣時，才歸入本類別；不得因出現「AI」、「創新」等字詞便歸入本類別。

3. A3 設備資源與數位支持：當回覆主要涉及工作所需的電腦、硬體設備、設備補助、數位工具、AI 工具、系統資源或利用科技提升作業效率時，歸入此類別。若回覆主要關注如何學習 AI、接觸新趨勢、取得線上課程或提升個人能力，則歸入「教育訓練」。若同一回覆同時明確要求工具資源與使用訓練，可採多重分類。

4. A4 PM 發展與留才：當回覆主要涉及執課 PM 的角色重要性、工作負擔、職能培育、工作支持、職位穩定、留任或 PM 穩定對業務運作的影響時，歸入此類別。僅在內容明確指向 PM 角色或 PM 職能時歸入本類別，不得將所有與專案、人員穩定或留才有關的回覆一律歸入。若回覆只是在談一般員工的教育訓練，則歸入「教育訓練」。

5. A5 教育訓練：當回覆主要涉及自主學習、外部線上課程、產業知識、趨勢更新、AI 應用學習、跨世代溝通、內部分享或員工能力提升時，歸入此類別。若回覆主要要求提供電腦、硬體補助、AI 工具或系統資源，則歸入「設備資源與數位支持」。若回覆主要涉及特定 PM 職位的養成與留任，則歸入「PM 發展與留才」。若回覆主要涉及 Mentor 定期 1:1、前輩經驗傳承或職涯方向引導，則歸入「職涯發展與回饋制度」。

6. A6 職涯發展與回饋制度：當回覆主要涉及 Mentor、定期 1:1、職涯方向、前輩榜樣、經驗傳承、績優心得分享、工作心法或持續性的發展支持時，歸入此類別。若回覆主要涉及薪資、加薪、獎金、升遷標準或職涯升遷地圖，則歸入「獎酬、激勵與晉升制度」。若回覆主要涉及主管提供肯定的頻率、互動說明或部門知識分享，則歸入「雙向溝通」。

7. A7 雙向溝通：當回覆主要涉及增加互動說明時間、主管與部屬之間的雙向交流、定期分享所見所學、允許提問與回應，或主管應更主動提供肯定與回饋時，歸入此類別。若回覆主要涉及跨部門資訊傳遞不即時、協調會議或溝通平台，則歸入「溝通與協調機制」。若回覆主要涉及 Mentor 定期 1:1 及職涯方向，則歸入「職涯發展與回饋制度」。判斷重點在於是否強調「雙方能互相說明、提問、回應與肯定」。

8. A8 工作優化與身心平衡：當回覆主要涉及更聰明的工作方式、流程優化、工作與生活平衡、運動風氣、非工作活動、團隊凝聚、情感連結或員工身心恢復時，歸入此類別。若回覆主要涉及下班後或假日收到工作訊息，則歸入「工作與生活邊界」（注意：此為另一題的子類別，若明顯指涉此議題可標記低信心待複核）。若回覆主要涉及設備、AI 工具或硬體補助以提升效率，則歸入「設備資源與數位支持」。

9. A9 客觀與具體回饋：當回覆主要涉及工作表現評價不應依個人喜好、目前缺乏明確回饋、評核標準不一致、回饋內容不具體，或希望建立客觀、公平、可理解的績效標準時，歸入此類別。若回覆主要涉及薪資、獎金、加薪或晉升制度，則歸入「獎酬、激勵與晉升制度」。若回覆主要涉及主管應更常肯定、增加互動或主動回饋，而未質疑評價標準的客觀性，則歸入「雙向溝通」。判斷本類別的核心是「回饋是否客觀、明確、具體且具有公信力」，而非單純回饋頻率。

10. B1 正向回饋：當回覆明確表達對現行工作環境、工作表現回饋、主管或同仁支持、講師會議、同儕互動或既有制度感到滿意、肯定、良好或值得保留時，歸入此類別。僅回答「無」、「沒有」或「暫時沒有」而未表達明確正向態度者，應歸入「無具體建議」。不得將「沒有提出問題」直接視為正向回饋，必須有明確肯定語意。

11. B2 無具體建議：當回覆僅表示「無」、「沒有」、「暫時沒有」、「目前無建議」或未提供任何具體意見、態度及改善方向時，歸入此類別。此類回覆不得被推定為滿意、不滿意、認同或反對現行制度。若回覆明確表示「目前很好」、「已經滿意」或「沒有建議，因為現況良好」，則歸入「正向回饋」。若回覆極短、語意不明或缺乏足夠資訊，歸入本類別，並將分類信心標記為低。

{GLOBAL_RULES}

【次要類別規則】
每則回覆原則上輸出一個主要類別；若同時明確涉及兩個以上獨立主題，可額外輸出一個次要類別。
次要類別必須是與主要類別不同的合法子類別（從上方清單中選）；
若內容只涉及單一主題，secondary_sub_category 請輸出 null，不要為了填欄位而勉強生成。

【輸出格式】
絕對不可修改或改寫「問卷回覆內容」原文，僅作為判斷依據。
只回傳以下 JSON 格式，不要加任何其他文字說明：

{{
  "main_category": "大類別名稱",
  "sub_category": "完整子類別名稱（含編號，例如 A1 獎酬、激勵與晉升制度）",
  "secondary_sub_category": "次要子類別名稱，若無則為 null",
  "reasoning": "判斷原因與說明，1-2句話",
  "summary": "受試者建議摘要，1句話",
  "confidence": "high 或 low"
}}"""


def _parse_json(raw_text: str) -> dict:
    cleaned = re.sub(r"```json|```", "", raw_text).strip()
    return json.loads(cleaned)


def is_text_response(value) -> bool:
    if value is None:
        return False
    # pandas 讀 Excel 空格時是 float('nan')，str(nan) 會變成 "nan" 字串，
    # 不會被底下的空字串/純數字檢查擋掉，要先特別排除
    try:
        if isinstance(value, float) and value != value:  # NaN 的標準檢查寫法
            return False
    except Exception:
        pass
    if str(value).strip() == "" or str(value).strip().lower() == "nan":
        return False
    if str(value).strip().isdigit():
        return False
    return True


def _call_gemini_and_parse(masked_text: str, prompt_content: str, question_type: str) -> dict:
    """
    共用邏輯：把已經遮罩過的文字送進 Gemini、解析結果、查方法論表。
    輸入必須已經是遮罩後文字，這個函式不做任何 PII masking。

    被 _run_classification()（單一整則回答，內部自己遮罩一次）與
    _classify_segment()（意義單元拆分後的單一 segment，遮罩已在
    外層做過一次）共用，避免兩邊邏輯各寫一份。
    """
    result = {
        "main_category": None,
        "sub_category": None,
        "secondary_sub_category": None,
        "reasoning": None,
        "summary": None,
        "confidence": None,
        "methodology": None,
        "citation": None,
        "secondary_methodology": None,
        "secondary_citation": None,
        "status": "pending",
        "error_detail": None,
    }

    try:
        model = genai.GenerativeModel(
            model_name="gemini-3.1-flash-lite",
            system_instruction=prompt_content,
        )
        response = model.generate_content(
            f"問卷回覆內容:\n{masked_text}",
            generation_config={"temperature": 0},
        )
        parsed = _parse_json(response.text)

        result["main_category"] = parsed["main_category"]
        result["sub_category"] = parsed["sub_category"]
        result["secondary_sub_category"] = parsed.get("secondary_sub_category")
        result["reasoning"] = parsed["reasoning"]
        result["summary"] = parsed["summary"]
        result["confidence"] = parsed.get("confidence", "high")

        methodology_info = get_methodology(question_type, result["sub_category"])
        if methodology_info:
            result["methodology"] = methodology_info["methodology"]
            result["citation"] = methodology_info["citation"]
            result["status"] = "completed"
        else:
            result["status"] = "methodology_not_found"
            result["error_detail"] = f"sub_category 不在固定清單裡：{result['sub_category']}"

        # 次要類別是選填的，只有在 AI 真的有輸出、且是合法子類別時才查表補上；
        # 查不到就靜默留空，不影響主要分類的 status
        if result["secondary_sub_category"]:
            secondary_info = get_methodology(question_type, result["secondary_sub_category"])
            if secondary_info:
                result["secondary_methodology"] = secondary_info["methodology"]
                result["secondary_citation"] = secondary_info["citation"]

    except Exception as e:
        print("[CLASSIFY ERROR][GEMINI_API_FAILED]", repr(e))
        result["status"] = "failed"
        result["error_detail"] = f"GEMINI_API_FAILED: {str(e)[:180]}"

    return result


def _run_classification(answer_text: str, prompt_content: str, question_type: str) -> dict:
    """
    底層分類函式（既有邏輯不變）：接受任意 prompt 內容（可能是正式版，
    也可能是沙盒草稿），內部自行遮罩整則 answer_text 後送 Gemini。

    被 classify_response_v2()（批次分類，run_classification.py 用）
    與 prompt_admin_service.py 的沙盒測試直接呼叫，這兩個呼叫端
    這次都不修改，所以這個函式的行為必須維持跟修改前一致，
    只是內部改呼叫共用的 _call_gemini_and_parse()，避免跟新的
    多意義單元流程重複維護兩份幾乎一樣的邏輯。
    """
    try:
        masked_text = mask_pii(answer_text)
    except PiiMaskingError as e:
        print("[CLASSIFY ERROR][PII_MASKING_FAILED]", repr(e))
        return {
            "main_category": None,
            "sub_category": None,
            "secondary_sub_category": None,
            "reasoning": None,
            "summary": None,
            "confidence": None,
            "methodology": None,
            "citation": None,
            "secondary_methodology": None,
            "secondary_citation": None,
            "status": "failed",
            "error_detail": f"PII_MASKING_FAILED: {str(e)[:180]}",
        }

    return _call_gemini_and_parse(masked_text, prompt_content, question_type)


def _build_classification_result(parsed: dict, question_type: str) -> dict:
    """
    把 Gemini 回傳的一筆分類物件（單一 segment 或批次陣列裡的一個
    元素，格式相同）補上方法論查表結果，組成完整的分類結果 dict。
    """
    result = {
        "main_category": parsed["main_category"],
        "sub_category": parsed["sub_category"],
        "secondary_sub_category": parsed.get("secondary_sub_category"),
        "reasoning": parsed["reasoning"],
        "summary": parsed["summary"],
        "confidence": parsed.get("confidence", "high"),
        "methodology": None,
        "citation": None,
        "secondary_methodology": None,
        "secondary_citation": None,
        "status": "pending",
        "error_detail": None,
    }

    methodology_info = get_methodology(question_type, result["sub_category"])
    if methodology_info:
        result["methodology"] = methodology_info["methodology"]
        result["citation"] = methodology_info["citation"]
        result["status"] = "completed"
    else:
        result["status"] = "methodology_not_found"
        result["error_detail"] = f"sub_category 不在固定清單裡：{result['sub_category']}"

    if result["secondary_sub_category"]:
        secondary_info = get_methodology(question_type, result["secondary_sub_category"])
        if secondary_info:
            result["secondary_methodology"] = secondary_info["methodology"]
            result["secondary_citation"] = secondary_info["citation"]

    return result


def _failed_classification_result(error_detail: str) -> dict:
    return {
        "main_category": None,
        "sub_category": None,
        "secondary_sub_category": None,
        "reasoning": None,
        "summary": None,
        "confidence": None,
        "methodology": None,
        "citation": None,
        "secondary_methodology": None,
        "secondary_citation": None,
        "status": "failed",
        "error_detail": error_detail,
    }


def _call_gemini_batch_classification(masked_segments: list, prompt_content: str, question_type: str) -> list:
    """
    Gemini #2：一次把所有已驗證合法的 masked segments 送進去，
    一次回傳每個 segment 的分類結果（固定 2 次呼叫策略的第二次，
    不對每個 segment 各自呼叫一次）。

    用明確的 index 對應每個片段，不依賴陣列順序——Gemini 回傳的
    index 集合只要跟 0~N-1 對不上（缺漏、重複、超出範圍），
    整批視為失敗（fail-closed），不做部分採信。

    回傳長度固定等於 len(masked_segments)，且順序跟輸入一致，
    呼叫端可以直接用 zip() 對應回各自的 orig_start/orig_end。

    prompt_content 的 output-format 衝突處理：
    prompt_content 尾端本來就寫死「只回傳單一 main_category/
    sub_category JSON」，這跟這裡要的 classifications 陣列格式互相
    矛盾。不修改、不複製 prompt_content 本身（分類定義與判斷規則
    完全沿用同一份），只在 system_instruction 裡、prompt_content
    之後，另外附加一段「覆蓋輸出格式」的說明——因為它在同一個
    system_instruction 字串裡、且明確位於原本格式說明之後、並
    明講要覆蓋前面的指示，所以不會產生「system_instruction 跟
    user message 兩邊互相矛盾、system 優先於 user」這種衝突。
    user message 只負責列出片段內容，不再重複格式規則。
    """
    n = len(masked_segments)

    try:
        segments_block = "\n".join(f"[{i}] {text}" for i, text in enumerate(masked_segments))
        user_message = f"片段內容：\n{segments_block}"

        batch_system_instruction = prompt_content + BATCH_OUTPUT_FORMAT_OVERRIDE.format(n=n, n_minus_1=n - 1)

        model = genai.GenerativeModel(
            model_name="gemini-3.1-flash-lite",
            system_instruction=batch_system_instruction,
        )
        response = model.generate_content(
            user_message,
            generation_config={"temperature": 0},
        )
        parsed = _parse_json(response.text)
        items = parsed["classifications"]

        seen_indices = set()
        result_by_index = {}
        for item in items:
            idx = item["index"]
            if not isinstance(idx, int) or not (0 <= idx < n) or idx in seen_indices:
                raise ValueError(f"Gemini 回傳的 index 不合法或重複：{idx!r}")
            seen_indices.add(idx)
            result_by_index[idx] = item

        if seen_indices != set(range(n)):
            raise ValueError(
                f"Gemini 回傳的 index 集合不完整，預期 0~{n - 1}，"
                f"實際收到 {sorted(seen_indices)}"
            )

        return [_build_classification_result(result_by_index[i], question_type) for i in range(n)]

    except Exception as e:
        print("[CLASSIFY ERROR][BATCH_CLASSIFICATION_FAILED]", repr(e))
        error_detail = f"BATCH_CLASSIFICATION_FAILED: {str(e)[:180]}"
        return [_failed_classification_result(error_detail) for _ in range(n)]



def classify_response_multi_segment(answer_text: str, prompt_content: str, question_type: str) -> dict:
    """
    多意義單元分類協調函式：遮罩 → 拆分驗證（Gemini #1）→ 批次分類
    （Gemini #2，一次呼叫涵蓋所有 segment）。固定 2 次 Gemini 呼叫，
    不隨 segment 數量增加而增加呼叫次數。

    只負責「組出資料結構」，不寫入 DB（DB 寫入是呼叫端
    routes/classifications/classification.py 的職責）。segmentation_status
    與每個 segment 各自的 status 是分開的兩件事，呼叫端寫入時要
    分別處理，不要混在一起判斷。

    回傳：
    {
        "segmentation_status": "completed" / "partial_failed" / "failed",
        "segmentation_error_detail": str or None,
        "segments": [
            {
                "orig_start": int, "orig_end": int,
                # 以下欄位跟舊版 _run_classification() 回傳的欄位一致
                "main_category": ..., "sub_category": ..., ..., "status": ...,
            },
            ...
        ],
    }

    如果整則回答遮罩失敗（fail-closed），或拆分完全沒有任何一個
    segment 驗證通過，"segments" 會是空清單，呼叫端應該視這則回答
    為需要人工複核，不建立任何 Response_Classification 列。
    """
    try:
        masked_text, position_map = mask_pii_with_mapping(answer_text)
    except PiiMaskingError as e:
        print("[CLASSIFY ERROR][PII_MASKING_FAILED]", repr(e))
        return {
            "segmentation_status": "failed",
            "segmentation_error_detail": f"PII_MASKING_FAILED: {str(e)[:180]}",
            "segments": [],
        }

    seg_result = segment_answer(masked_text, position_map)
    valid_segments = seg_result["segments"]

    if not valid_segments:
        return {
            "segmentation_status": seg_result["segmentation_status"],
            "segmentation_error_detail": seg_result["error_detail"],
            "segments": [],
        }

    masked_texts = [seg["masked_text"] for seg in valid_segments]
    classifications = _call_gemini_batch_classification(masked_texts, prompt_content, question_type)

    classified_segments = [
        {"orig_start": seg["orig_start"], "orig_end": seg["orig_end"], **classification}
        for seg, classification in zip(valid_segments, classifications)
    ]

    return {
        "segmentation_status": seg_result["segmentation_status"],
        "segmentation_error_detail": seg_result["error_detail"],
        "segments": classified_segments,
    }



def classify_response_v2(answer_text: str, question_type: str) -> dict:
    """
    正式分類流程：從資料庫讀取該題目對應的正式版（live_content）prompt。
    需要 Flask app context（因為要查資料庫），不能在沒有資料庫連線的環境單獨執行。
    """
    from models import Prompt_Template

    row = Prompt_Template.query.get(question_type)
    if row is None:
        raise RuntimeError(
            f"資料庫裡找不到 prompt_key='{question_type}' 的 Prompt_Template，"
            "請先執行 seed_prompt_templates.py 建立初始資料"
        )

    return _run_classification(answer_text, row.live_content, question_type)