#!/usr/bin/env python
"""
Excel 上傳：哪些欄位被當成「開放式回答」（_detect_candidate_text_columns）。

姓名 / 編號 / 聯絡資料欄不能被當成回答（否則 AI 會把「受試者 A」拿去分類，還產生「填答者識別資訊」的分類架構）。
涵蓋：中文欄位、英文欄位（Name / ID / Email…）、依內容判斷（受試者A、Respondent 3、P01）、不誤傷真正的回答欄。

執行方式：
    cd backend
    python3 tests/test_column_detection.py
"""

import pandas as pd

from admin_test_support import check, finish
from routes.classifications.classification import _detect_candidate_text_columns as detect

ANSWERS_ZH = ["這次的課程內容很紮實，講師講解得很清楚", "整體滿意，案例分享很實用", "課程步調偏快，建議提供講義", "非常喜歡互動環節", "時間安排太緊湊，休息時間太短"]
ANSWERS_EN = ["The course content was very solid and clear", "Overall satisfied, the case studies were practical", "The pace was fast, please give handouts", "I loved the interactive sessions", "The schedule was too tight, breaks too short"]


def cols(**kw):
    return detect(pd.DataFrame(kw))


print("== 英文版 Excel（我們實際遇到的）==")
check("ID / Name / Open-ended Response：只有回答欄", cols(**{"ID": [1, 2, 3, 4, 5], "Name": [f"Respondent {c}" for c in "ABCDE"], "Open-ended Response": ANSWERS_EN}) == ["Open-ended Response"])
for name in ("Name", "name", "Full Name", "First Name", "Last Name", "Username", "Respondent", "Participant ID", "Email Address", "Phone Number", "Mobile", "Number", "#"):
    check(f"欄位名稱 {name!r}：不是回答欄", cols(**{name: ["Alice Chen", "Bob Lin", "Carol Wu", "David Lee", "Erin Hsu"], "Comment": ANSWERS_EN}) == ["Comment"])

print("== 中文版 Excel（維持原行為）==")
check("編號 / 姓名 / 開放式回答：只有回答欄", cols(**{"編號": [1, 2, 3, 4, 5], "姓名": ["王小明", "李小華", "陳大文", "林小美", "黃志強"], "開放式回答": ANSWERS_ZH}) == ["開放式回答"])
for name in ("受試者", "填答者", "填答人", "學號", "員工編號", "手機號碼", "暱稱"):
    check(f"欄位名稱 {name!r}：不是回答欄", cols(**{name: ["王小明", "李小華", "陳大文", "林小美", "黃志強"], "意見": ANSWERS_ZH}) == ["意見"])

print("== 欄位名稱看不出來，改看內容 ==")
check("內容全是「受試者A…E」（欄名是任意的）", cols(**{"Column B": [f"受試者{c}" for c in "ABCDE"], "Feedback": ANSWERS_ZH}) == ["Feedback"])
check("內容全是「Respondent A…E」", cols(**{"Who": [f"Respondent {c}" for c in "ABCDE"], "Feedback": ANSWERS_EN}) == ["Feedback"])
check("內容全是「填答人 1…5」", cols(**{"X": [f"填答人 {i}" for i in range(1, 6)], "Feedback": ANSWERS_ZH}) == ["Feedback"])
check("內容全是代號 P01…P05 / S-12", cols(**{"Code2": ["P01", "P02", "P03", "P04", "P05"], "Feedback": ANSWERS_EN}) == ["Feedback"])
check("80% 以上是標籤才排除：4/5 是標籤 -> 排除", cols(**{"Who": ["受試者A", "受試者B", "受試者C", "受試者D", "不具名的一位老師"], "Feedback": ANSWERS_ZH}) == ["Feedback"])

print("== 不誤傷真正的回答欄 ==")
check("回答剛好提到「受試者」", cols(**{"Feedback": ["受試者A覺得課程很好", "受試者B希望增加練習", "受試者C認為太快", "受試者D想要講義", "受試者E喜歡互動"]}) == ["Feedback"])
check("短但有意義的回答（Good / 很好）", cols(**{"Feedback": ["很好", "不錯", "太快了", "很實用", "滿意"]}) == ["Feedback"])
check("English short answers", cols(**{"Feedback": ["Great course", "Too fast", "More practice", "Loved it", "Needs handouts"]}) == ["Feedback"])
check("多個開放式問題：全部保留，順序不變", cols(**{"Q1": ANSWERS_EN, "Name": ["a b", "c d", "e f", "g h", "i j"], "Q2": ANSWERS_EN}) == ["Q1", "Q2"])
check("數字欄 / 空欄仍然排除", cols(**{"Score": [1, 2, 3, 4, 5], "Empty": [None] * 5, "Feedback": ANSWERS_EN}) == ["Feedback"])

finish()
