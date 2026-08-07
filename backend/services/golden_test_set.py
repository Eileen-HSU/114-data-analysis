"""

沙盒測試用的測試組：每個子類別各挑一則真實回答（來自整理的
0727網站使用版本.md，人工分類結果），管理者編輯草稿 prompt 後，
用這組資料驗證草稿有沒有把分類架構改壞。

這不是用來評估系統整體準確率的正式測試集（那個要用完整 51 筆資料做），
純粹是「發布前的安全檢查」用的小樣本。
"""

from services.subcategory_methodology import QUESTION_LEADERSHIP, QUESTION_CAREER

GOLDEN_TEST_SET = {
    QUESTION_LEADERSHIP: [
        {
            "answer_text": "主管領導的部分，希望不要在下班後或者假日傳工作訊息 假日很難喘口氣，看到訊息都是壓力的來源",
            "expected_sub_category": "A1 工作與生活邊界",
        },
        {
            "answer_text": "可以有多一點時間交流",
            "expected_sub_category": "A2 回饋與溝通",
        },
        {
            "answer_text": "主管領導：留才的重要性，人才要培育，也要先留得住人",
            "expected_sub_category": "A3 主管覺察力",
        },
        {
            "answer_text": "主要是希望主管可以多花時間針對不同狀況的部屬，給予不同的指導與溝通，有形或無形獎勵（個人化），因為每個人的狀態真的不太一樣。",
            "expected_sub_category": "A4 領導風格",
        },
        {
            "answer_text": "部門：行銷在溝通事情時都是單點且常無整體規劃、且配套措施常不完善，讓業務單位的人沒有太多時間反應，或是事後都還要再去問，過了一陣子才有方案",
            "expected_sub_category": "B1 溝通與協調機制",
        },
        {
            "answer_text": "跨部門合作要能相互體諒支援，不是用來推工作的",
            "expected_sub_category": "B2 支援協作",
        },
        {
            "answer_text": "分工和權責要明確。",
            "expected_sub_category": "B3 權責界定與規範落實",
        },
        {
            "answer_text": "Team 之間 兩個Team 風格跟內部養成就不一樣，被教育的工作標準也不相同，久了當然就各自有一個生態",
            "expected_sub_category": "B4 管理一致性",
        },
        {
            "answer_text": "公司已經把講師照顧得很好。",
            "expected_sub_category": "C1 正向回饋",
        },
        {
            "answer_text": "目前暫無，謝謝！",
            "expected_sub_category": "C2 無具體建議",
        },
    ],
    QUESTION_CAREER: [
        {
            "answer_text": "是否可以增設專案Team的績優獎項(一季一次)，由同仁票選產出，並於月會頒獎及發表心得。",
            "expected_sub_category": "A1 獎酬、激勵與晉升制度",
        },
        {
            "answer_text": "行銷不夠具有市場上的競爭優勢，不管是文宣、還是主題都需要再思考過，可以考慮再多買一些廣告做曝光。",
            "expected_sub_category": "A2 品牌定位與市場曝光",
        },
        {
            "answer_text": "設備投入不要讓設備造成工作上的負擔，加強創新，利用 AI 創造更多效率",
            "expected_sub_category": "A3 設備資源與數位支持",
        },
        {
            "answer_text": "我覺得執課PM是很辛苦又非常重要的一環，PM穩定，業務也會相對穩定，對PM的養成與重視，也許可以更加留意",
            "expected_sub_category": "A4 PM 發展與留才",
        },
        {
            "answer_text": "或許可以和一些外部線上學習平台簽訂特約，以較為優惠的價格進行線上課程的自主學習。",
            "expected_sub_category": "A5 教育訓練",
        },
        {
            "answer_text": "讓績優員工可以有分享工作心得或心法的機會。也就是在月會頒獎後，可以給同仁發表心得的機會。",
            "expected_sub_category": "A6 職涯發展與回饋制度",
        },
        {
            "answer_text": "可以有多一點時間互動說明",
            "expected_sub_category": "A7 雙向溝通",
        },
        {
            "answer_text": "非工作上的團隊凝聚與活動，例如：運動風氣 有別於工作以外的舞台和人生目標，讓員工有跟公司更多的情感連結",
            "expected_sub_category": "A8 工作優化與身心平衡",
        },
        {
            "answer_text": "工作表現的回饋不要隨個人喜好",
            "expected_sub_category": "A9 客觀與具體回饋",
        },
        {
            "answer_text": "目前覺得都還ok",
            "expected_sub_category": "B1 正向回饋",
        },
        {
            "answer_text": "無",
            "expected_sub_category": "B2 無具體建議",
        },
    ],
}