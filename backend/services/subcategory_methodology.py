"""
subcategory_methodology.py

子類別 -> (大類別, 方法論名稱, 文獻) 的固定查表。

【重要】這張表取代了原本設計的 PROMPT_2（AI 從 20 條通用清單選方法論）。
    團隊實際定案的分類架構裡，每個子類別本身就固定對應一組專屬命名的
    分析架構與文獻（見 0727網站使用版本.md），不是從通用清單裡選出來的。
    因為子類別本身是封閉、固定的集合，一旦 Gemini 判斷出 sub_category，
    直接查這張表就能拿到方法論名稱與文獻，完全不需要再呼叫一次 AI。

    資料來源：0727網站使用版本.md（團隊人工分類的正式定案版本）
    每一筆的 citation 均逐字保留原文獻資訊，不由 AI 生成，避免捏造引用。

兩份問卷題目對應不同的分類架構：
    QUESTION_LEADERSHIP：主管領導與部門合作建議
    QUESTION_CAREER：工作表現的回饋及職涯發展協助
"""

QUESTION_LEADERSHIP = "leadership_and_dept"
QUESTION_CAREER = "career_and_feedback"


# key 為完整子類別字串（含編號，如 "A1 工作與生活邊界"），
# 因為不同題目底下可能有相同編號但不同意涵的子類別（如兩題各自都有一個
# 「其他與建議」大類別底下的「正向回饋」/「無具體建議」），
# 用完整字串當 key 才不會混淆。
SUBCATEGORY_METHODOLOGY = {
    QUESTION_LEADERSHIP: {
        "A1 工作與生活邊界": {
            "main_category": "主管領導",
            "methodology": "非工作時間之工作邊界分析",
            "citation": "Park, Y. A., Liu, Y., & Headrick, L. (2020). When work is wanted after hours: Testing weekly stress of information communication technology demands using boundary theory. Journal of Organizational Behavior, 41(6), 518–534. https://doi.org/10.1002/job.2461",
        },
        "A2 回饋與溝通": {
            "main_category": "主管領導",
            "methodology": "互動與溝通需求分析",
            "citation": "Malone, T. W., & Crowston, K. (1994). The interdisciplinary study of coordination. ACM Computing Surveys, 26(1), 87–119. https://doi.org/10.1145/174666.174668",
        },
        "A3 主管覺察力": {
            "main_category": "主管領導",
            "methodology": "主管與部屬認知落差分析",
            "citation": "Graen, G. B., & Uhl-Bien, M. (1995). Relationship-based approach to leadership: Development of leader-member exchange (LMX) theory of leadership over 25 years. The Leadership Quarterly, 6(2), 219–247. https://doi.org/10.1016/1048-9843(95)90036-5",
        },
        "A4 領導風格": {
            "main_category": "主管領導",
            "methodology": "基本一致與個人化領導分析",
            "citation": "Rafferty, A. E., & Griffin, M. A. (2006). Refining individualized consideration: Distinguishing developmental leadership and supportive leadership. Journal of Occupational and Organizational Psychology, 79(1), 37–61. https://doi.org/10.1348/096317905X36731",
        },
        "B1 溝通與協調機制": {
            "main_category": "部門合作",
            "methodology": "流程瓶頸分析",
            "citation": "Malone, T. W., & Crowston, K. (1994). The interdisciplinary study of coordination. ACM Computing Surveys, 26(1), 87–119. https://doi.org/10.1145/174666.174668",
        },
        "B2 支援協作": {
            "main_category": "部門合作",
            "methodology": "互惠與責任承擔分析",
            "citation": "Jolly, P. M., Kong, D. T., & Kim, K. Y. (2021). Social support at work: An integrative review. Journal of Organizational Behavior, 42(2), 229–251. https://doi.org/10.1002/job.2485",
        },
        "B3 權責界定與規範落實": {
            "main_category": "部門合作",
            "methodology": "角色界定與規範內化分析",
            "citation": "Rizzo, J. R., House, R. J., & Lirtzman, S. I. (1970). Role conflict and ambiguity in complex organizations. Administrative Science Quarterly, 15(2), 150–163.",
        },
        "B4 管理一致性": {
            "main_category": "部門合作",
            "methodology": "跨團隊管理與作業一致性分析",
            "citation": "Spee, P., Jarzabkowski, P., & Smets, M. (2016). The influence of routine interdependence and skillful accomplishment on the coordination of standardizing and customizing. Organization Science, 27(3), 759–781. https://doi.org/10.1287/orsc.2016.1050",
        },
        "C1 正向回饋": {
            "main_category": "其他與建議",
            "methodology": "組織支持與正向回饋分析",
            "citation": "Eisenberger, R., Huntington, R., Hutchison, S., & Sowa, D. (1986). Perceived organizational support. Journal of Applied Psychology, 71(3), 500–507. https://doi.org/10.1037/0021-9010.71.3.500",
        },
        "C2 無具體建議": {
            "main_category": "其他與建議",
            "methodology": "中性與資訊不足回覆分析",
            "citation": "Krosnick, J. A. (1991). Response strategies for coping with the cognitive demands of attitude measures in surveys. Applied Cognitive Psychology, 5(3), 213–236. https://doi.org/10.1002/acp.2350050305",
        },
    },
    QUESTION_CAREER: {
        "A1 獎酬、激勵與晉升制度": {
            "main_category": "工作表現的回饋及職涯發展",
            "methodology": "獎酬與職涯期望分析",
            "citation": "Vroom, V. H. (1964). Work and motivation. Wiley.",
        },
        "A2 品牌定位與市場曝光": {
            "main_category": "工作表現的回饋及職涯發展",
            "methodology": "品牌權益與市場曝光分析",
            "citation": "Keller, K. L. (1993). Conceptualizing, measuring, and managing customer-based brand equity. Journal of Marketing, 57(1), 1–22. https://doi.org/10.1177/002224299305700101",
        },
        "A3 設備資源與數位支持": {
            "main_category": "工作表現的回饋及職涯發展",
            "methodology": "科技資源與工作效能分析",
            "citation": "Goodhue, D. L., & Thompson, R. L. (1995). Task-technology fit and individual performance. MIS Quarterly, 19(2), 213–236. https://doi.org/10.2307/249689",
        },
        "A4 PM 發展與留才": {
            "main_category": "工作表現的回饋及職涯發展",
            "methodology": "關鍵職能價值辨分析",
            "citation": "Hackman, J. R., & Oldham, G. R. (1976). Motivation through the design of work: Test of a theory. Organizational Behavior and Human Performance, 16(2), 250–279. https://doi.org/10.1016/0030-5073(76)90016-7",
        },
        "A5 教育訓練": {
            "main_category": "工作表現的回饋及職涯發展",
            "methodology": "知識賦能與趨勢接軌分析",
            "citation": "Spreitzer, G. M. (1995). Psychological empowerment in the workplace: Dimensions, measurement, and validation. Academy of Management Journal, 38(5), 1442–1465. https://doi.org/10.5465/256865",
        },
        "A6 職涯發展與回饋制度": {
            "main_category": "工作表現的回饋及職涯發展",
            "methodology": "職涯支持與導師需求分析",
            "citation": "Jyoti, J., & Sharma, P. (2015). Impact of mentoring functions on career development: Moderating role of mentoring culture and mentoring structure. Global Business Review, 16(4), 700–718. https://doi.org/10.1177/0972150915581110",
        },
        "A7 雙向溝通": {
            "main_category": "工作表現的回饋及職涯發展",
            "methodology": "雙向互動與回饋需求分析",
            "citation": "Graen, G. B., & Uhl-Bien, M. (1995). Relationship-based approach to leadership: Development of leader–member exchange (LMX) theory of leadership over 25 years: Applying a multi-level multi-domain perspective. The Leadership Quarterly, 6(2), 219–247. https://doi.org/10.1016/1048-9843(95)90036-5",
        },
        "A8 工作優化與身心平衡": {
            "main_category": "工作表現的回饋及職涯發展",
            "methodology": "工作資源與恢復機制分析",
            "citation": "Sonnentag, S., & Fritz, C. (2007). The Recovery Experience Questionnaire: Development and validation of a measure for assessing recuperation and unwinding from work. Journal of Occupational Health Psychology, 12(3), 204–221. https://doi.org/10.1037/1076-8998.12.3.204",
        },
        "A9 客觀與具體回饋": {
            "main_category": "工作表現的回饋及職涯發展",
            "methodology": "客觀績效標準與回饋分析",
            "citation": "Kluger, A. N., & DeNisi, A. (1996). The effects of feedback interventions on performance. Psychological Bulletin, 119(2), 254–284. https://doi.org/10.1037/0033-2909.119.2.254",
        },
        "B1 正向回饋": {
            "main_category": "其他與建議",
            "methodology": "歸納式質性內容分析",
            "citation": "Elo, S., & Kyngäs, H. (2008). The qualitative content analysis process. Journal of Advanced Nursing, 62(1), 107–115. https://doi.org/10.1111/j.1365-2648.2007.04569.x",
        },
        "B2 無具體建議": {
            "main_category": "其他與建議",
            "methodology": "中性與資訊不足回覆分析",
            "citation": "Krosnick, J. A. (1991). Response strategies for coping with the cognitive demands of attitude measures in surveys. Applied Cognitive Psychology, 5(3), 213–236. https://doi.org/10.1002/acp.2350050305",
        },
    },
}


def get_methodology(question_type: str, sub_category: str) -> dict:
    """
    查表拿方法論名稱與文獻。

    Args:
        question_type: QUESTION_LEADERSHIP 或 QUESTION_CAREER
        sub_category: Gemini 判斷出的完整子類別字串（如 "A1 工作與生活邊界"）

    Returns:
        {"main_category": ..., "methodology": ..., "citation": ...}
        查無對應時回傳 None（代表 Gemini 輸出的子類別跟固定清單對不上，
        需要人工檢查——這通常代表 Gemini 判斷有誤，或子類別名稱打字不一致）
    """
    table = SUBCATEGORY_METHODOLOGY.get(question_type, {})
    return table.get(sub_category)


def all_subcategories(question_type: str) -> list[str]:
    """回傳該題目底下所有合法的子類別字串，用來組進 prompt 裡限制 Gemini 只能選這些。"""
    return list(SUBCATEGORY_METHODOLOGY.get(question_type, {}).keys())