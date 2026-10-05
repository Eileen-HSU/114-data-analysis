"""匯出檔案（Excel / Word）的固定文字：欄位標題、分頁名稱、標籤。

語言 = ui_lang（使用者「匯出當下」的介面語言，來源 Accept-Language）。
  - zh-TW 的每個字串與原本寫死在 export_file_service.py 裡的完全相同（既有輸出逐位元不變）。
  - en 的措辭盡量沿用前端畫面已有的英文（frontend/src/context/interfaceEnglish.js），
    讓畫面上的表格標題與匯出檔的欄位標題是同一套說法。

只翻譯「系統固定文字」。使用者的資料（回答原文、題目、類別名稱、AI 產生的理由 / 摘要）不會被翻譯；
這些內容是什麼語言就是什麼語言。

另外，分類結果的「問卷回覆內容」欄位裡有兩種由系統組出來的固定字樣（見 routes/classifications/
classification.py 的 _build_aggregated_groups）：每行開頭的「受試者N：」與結尾的「（次要分類）」。
英文匯出時用 localize_respondent_text() 在匯出當下轉換，不改已存的資料。
前端畫面也做同樣的轉換（frontend/src/pages/workspace/page.jsx 的 MultilineText）；兩邊共用
backend/tests/fixtures/language_cases.json 的 respondent_text_cases。
"""

import re

from services.language_service import DEFAULT_LANG, normalize_lang

_LABELS = {
    "zh-TW": {
        "headers": ["大類別", "子類別", "問卷回覆內容", "判斷原因與說明", "受試者建議摘要"],
        "sheet_results": "分類結果",
        "sheet_rating": "評分題統計",
        "sheet_survey": "問卷回覆",
        "content_default": "完整內容",
        "content_survey": "問卷回覆內容",
        "hint": "→ {content_label}在第二個分頁「{sheet}」（點這裡或下方的分頁標籤即可切換）",
        "average_label_xlsx": "平均分數：",
        "average_label_docx": "平均分：",
        "no_data": "尚無資料",
        "answered_label": "有效回答：",
        "answered_value": "{n} 份",
        "answered_line_docx": "有效回答：{n} 份",
        "score_header": "{score} 分",
        "count_value": "{n} 人",
        "dist_item": "{score} 分：{n} 人",
        "dist_join": "　",
        "question_n": "題目 {n}",
        "q_rating_sep": "　",
        "q_header_sep": "：",
        "no_answer": "未作答",
        "identity_missing": "（未填寫身分）",
        "anonymous": "匿名受試者 {n}",
        "col_respondent": "受試者",
        "col_submitted": "提交時間",
        "respondent_line": "受試者：{label}",
        "submitted_line": "提交時間：{label}",
        "col_question": "題目",
        "col_answer": "答案",
        "list_join": "、",
        "filename_suffix_survey": "問卷回覆",
    },
    "en": {
        "headers": ["Main category", "Subcategory", "Survey response", "Reasoning and explanation",
                    "Summary of respondent suggestions"],
        "sheet_results": "Classification results",
        "sheet_rating": "Rating summary",
        "sheet_survey": "Survey responses",
        "content_default": "Full content",
        "content_survey": "Survey response",
        "hint": "→ {content_label} is on the second tab \"{sheet}\" (click here or use the tab below to switch)",
        "average_label_xlsx": "Average score: ",
        "average_label_docx": "Average score: ",
        "no_data": "No data",
        "answered_label": "Valid responses: ",
        "answered_value": "{n}",
        "answered_line_docx": "Valid responses: {n}",
        "score_header": "{score} {points}",
        "count_value": "{n} {respondents}",
        "dist_item": "{score} {points}: {n} {respondents}",
        "dist_join": "   ",
        "question_n": "Question {n}",
        "q_rating_sep": ": ",
        "q_header_sep": ": ",
        "no_answer": "No answer",
        "identity_missing": "(identity not provided)",
        "anonymous": "Anonymous respondent {n}",
        "col_respondent": "Respondent",
        "col_submitted": "Submitted",
        "respondent_line": "Respondent: {label}",
        "submitted_line": "Submitted: {label}",
        "col_question": "Question",
        "col_answer": "Answer",
        "list_join": ", ",
        "filename_suffix_survey": "Survey_responses",
    },
}


def plural(n, singular: str, plural_form: str) -> str:
    """英文單複數（1 point / 2 points、1 respondent / 2 respondents）。n 不是數字時用複數。"""
    try:
        return singular if int(n) == 1 else plural_form
    except (TypeError, ValueError):
        return plural_form


def export_labels(lang=None) -> dict:
    """某語言的匯出標籤。lang 不是支援的語言 -> 繁體中文（與原本行為相同）。"""
    return _LABELS[normalize_lang(lang) or DEFAULT_LANG]


_RESPONDENT_LINE_RE = re.compile(r"(?m)^受試者(\d+)：")


def localize_respondent_text(text, lang=None):
    """「問卷回覆內容」欄位裡系統組出來的固定字樣：「受試者N：」「（次要分類）」。
    zh-TW 原樣回傳；en 轉成 "Respondent N: " 與 " (secondary category)"。回答原文不動。"""
    if not isinstance(text, str) or (normalize_lang(lang) or DEFAULT_LANG) != "en":
        return text
    text = _RESPONDENT_LINE_RE.sub(lambda m: f"Respondent {m.group(1)}: ", text)
    return text.replace("（次要分類）", " (secondary category)")
