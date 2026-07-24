"""
分類服務：呼叫 Gemini 3.1 Flash，兩段式判斷
  1. 大類別 / 子類別 / 判斷原因 / 建議摘要（開放式生成）
  2. 方法論比對（封閉式選擇，只能從固定清單選，選不到就是「其他」）
"""

import os
import json
import re
import google.generativeai as genai

genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

# ---------- Prompt 1：大類別/子類別/原因/摘要 ----------
PROMPT_1 = """你是一個問卷回答分類助手。請針對使用者提供的單則問卷回覆內容，判斷其所屬的大類別與子類別，並生成判斷原因與建議摘要。

【參考範例】(既有分類風格，命名時盡量參考此顆粒度與用詞習慣，但不限於此清單，可依內容語意生成新的大類別/子類別):
大類別:主管領導
- A1 職場邊界與尊重
- A2 回饋與溝通
- A3 主管覺察力
- A4 領導風格

大類別:部門合作
- B1 溝通與協調機制
- B2 支援協作
- B3 權責界定與規範落實
- B4 管理一致性

大類別:工作表現的回饋及職涯發展
- 獎酬、激勵與晉升制度
- 品牌或商品定位聲量
- 設備資源與數位支持
- PM發展與留才
- 教育訓練
- 職涯發展與回饋制度
- 雙向溝通
- 工作優化與身心平衡
- 客觀與具體回饋

大類別:其他與建議
- 正向回饋
- 暫時沒有

【規則】
1. 大類別、子類別：依內容語意判斷，命名風格與顆粒度盡量貼近上述範例，若內容明顯不屬於任何既有主題，可自行生成適合的新大類別/子類別名稱
2. 若內容為單純肯定現況或無意見，歸類至「其他與建議」大類別
3. 絕對不可修改或改寫「問卷回覆內容」，僅作為判斷依據
4. 判斷原因與說明：用1-2句話說明分類邏輯
5. 受試者建議摘要：用1句話摘要受試者的核心訴求或現況
6. 只回傳以下 JSON 格式，不要加任何其他文字說明：

{
  "main_category": "",
  "sub_category": "",
  "reasoning": "",
  "summary": ""
}"""

# ---------- Prompt 2：方法論比對（封閉式） ----------
PROMPT_2 = """你是一個方法論比對助手。請根據問卷回覆內容與其判斷原因，從下列固定方法論清單中，選出邏輯最相符的一項。若都不符合，輸出「其他」。絕對不可自創清單以外的方法論名稱。

【方法論清單】
1. 需求邊界歸納法：從個人空間、專業尊重相關的負面反饋中界定管理行為邊界
2. 互動頻率分析法：歸納資訊交換、溝通機制建立的需求
3. 認知差距對照法：對比主管與部屬間的認知落差、心理能量觀察需求
4. 情境差異化歸納：依情境給予個人化、彈性化領導的需求
5. 流程瓶頸分析：資訊落差、缺乏配套、等待回應等組織流程缺失
6. 資源依賴邏輯：跨部門互補、資源共享、不推諉的協作行為
7. 流程衝突溯源法：權責不清導致的流程衝突，需建立正式規範
8. 標準化落差分析法：不同主管/團隊做法不一，需制度透明化
9. 行為強化歸納法：認可專業價值的正向激勵需求
10. 現狀滿意度推定：對現況無負面感受，屬隱性滿意或觀察期
11. 期望需求對置法：薪資透明、晉升地圖、即時獎勵等物質激勵需求
12. 市場競爭力溯源法：廣告曝光、文宣吸引力等品牌市場辨識度問題
13. 效率驅動歸納法：設備、數位工具作為生產力賦能手段的需求
14. 專業成就感溯源法：專業舞台發揮、工作價值感與人才留任
15. 賦能型資源歸納法：AI應用、教育訓練作為組織賦能與數位競爭力
16. 願景導向歸納法：精神榜樣、導師帶領、職涯定向的追求
17. 資訊對等邏輯法：雙向反饋結構缺失，需建立正式溝通管道
18. 產出效能與負荷歸納法：心理壓力溯源至流程不合理，需工作優化
19. 事實導向歸納法：以數據事實為基礎的客觀回饋機制需求
20. 強化學習理論歸納：具體成就認可的心理激勵需求

【規則】
只回傳以下 JSON 格式，不要加任何其他文字：

{
  "methodology": "選出的方法論名稱，或「其他」"
}"""


def _parse_json(raw_text):
    """去除 ```json 標記後解析 JSON，避免格式問題"""
    cleaned = re.sub(r"```json|```", "", raw_text).strip()
    return json.loads(cleaned)


def classify_response(answer_text: str) -> dict:
    """
    輸入一則文字回答，回傳分類結果 dict。
    分類失敗時，呼叫端應接住例外並 fallback 為「其他」。
    """
    if not answer_text or not answer_text.strip():
        raise ValueError("空白內容不分類")

    # --- 第一段：大類別/子類別/原因/摘要 ---
    model1 = genai.GenerativeModel(
        model_name="gemini-3.1-flash-lite",
        system_instruction=PROMPT_1,
    )
    result1 = model1.generate_content(
        f"問卷回覆內容:\n{answer_text}",
        generation_config={"temperature": 0},
    )
    parsed1 = _parse_json(result1.text)

    # --- 第二段：方法論比對 ---
    model2 = genai.GenerativeModel(
        model_name="gemini-3.1-flash-lite",
        system_instruction=PROMPT_2,
    )
    result2 = model2.generate_content(
        f"問卷回覆內容:\n{answer_text}\n\n判斷原因:\n{parsed1['reasoning']}",
        generation_config={"temperature": 0},
    )
    parsed2 = _parse_json(result2.text)

    return {
        "main_category": parsed1["main_category"],
        "sub_category": parsed1["sub_category"],
        "reasoning": parsed1["reasoning"],
        "summary": parsed1["summary"],
        "methodology": parsed2["methodology"],
    }


def is_text_response(value) -> bool:
    """判斷是否為需要分類的文字回答（純數字＝評分題，跳過）"""
    if value is None or str(value).strip() == "":
        return False
    if str(value).strip().isdigit():
        return False
    return True