"""

在原始問卷回答送進 Gemini API 之前，先在 Flask 後端本地完成 PII 遮罩。

設計原則：

1. 這個檔案只負責「產生要送給 Gemini 的遮罩後文字」，不會、也不應該被拿去
   覆寫資料庫欄位或最終報表輸出。呼叫端（classify_v2.py）必須自行確保
   DB 儲存與最終輸出仍使用原始 answer_text。

2. 為了避免因中文姓名辨識而引入大型 Transformer / GLiNER 模型（增加部署時
   的 RAM、image size、cold start、model download、inference time），
   Presidio 的 NlpEngine 只使用 spaCy 的「空白（blank）中文 pipeline」
   （_BlankChineseNlpEngine），不下載、也不載入任何預訓練模型；它只提供
   Presidio 架構上要求的基本斷詞介面。中文姓名判斷完全由
   ChinesePersonNameRecognizer 自行以規則（姓氏表 + 排除清單 + 前後文）
   完成，不依賴 spaCy 的 NER 結果。

3. Fail-closed：mask_pii() 內部任何一步只要失敗，一律拋出 PiiMaskingError，
   不會 catch 例外後 fallback 成回傳原始文字。呼叫端看到這個例外時，必須
   中止該次 Gemini 呼叫並記錄錯誤，不可以把未遮罩原文送出去。
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

from presidio_analyzer import (
    AnalyzerEngine,
    EntityRecognizer,
    Pattern,
    PatternRecognizer,
    RecognizerRegistry,
    RecognizerResult,
)
from presidio_analyzer.nlp_engine import SpacyNlpEngine
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

logger = logging.getLogger(__name__)

_LANGUAGE = "zh"


class PiiMaskingError(RuntimeError):
    """
    PII 遮罩流程失敗時拋出。

    採 fail-closed 設計：呼叫端看到這個例外，必須中止該次 Gemini 呼叫，
    不可以 catch 之後改送未遮罩的原文。
    """


# ═══════════════════════════════════════════════════════════════
# NLP Engine：只做斷詞，不載入任何預訓練模型
# ═══════════════════════════════════════════════════════════════
class _BlankChineseNlpEngine(SpacyNlpEngine):
    """
    Presidio 的 AnalyzerEngine 架構上一定要有一個 NlpEngine 才能執行
    （即使所有 recognizer 都是規則式、不需要 NER），所以這裡提供一個
    最輕量的版本：使用 spacy.blank("zh")，只做字元級斷詞，
    完全不下載、不載入 en_core_web_lg / zh_core_web_* 等預訓練模型。
    """

    def __init__(self):
        super().__init__(models=[{"lang_code": _LANGUAGE, "model_name": "blank:zh"}])

    def load(self) -> None:
        import spacy

        self.nlp = {_LANGUAGE: spacy.blank(_LANGUAGE)}


# ═══════════════════════════════════════════════════════════════
# Custom Recognizer 1：Email（沿用 Presidio 內建邏輯的簡化版）
# ═══════════════════════════════════════════════════════════════
class SimpleEmailRecognizer(PatternRecognizer):
    ENTITY = "EMAIL_ADDRESS"

    PATTERNS = [
        Pattern(
            # 注意：刻意不用 \w，因為 \w 在 Unicode 模式下會吃進中文字，
            # 沒有 ASCII 邊界的話會把整句中文都併進 email local part。
            name="email",
            regex=r"[A-Za-z0-9][A-Za-z0-9._%+-]*@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}",
            score=0.9,
        )
    ]

    def __init__(self):
        super().__init__(
            supported_entity=self.ENTITY,
            patterns=self.PATTERNS,
            supported_language=_LANGUAGE,
            name="SimpleEmailRecognizer",
        )


# ═══════════════════════════════════════════════════════════════
# Custom Recognizer 2：台灣手機
# ═══════════════════════════════════════════════════════════════
class TaiwanMobileRecognizer(PatternRecognizer):
    """
    涵蓋 0912345678 / 0912-345-678 / 0912 345 678 等常見格式。
    """

    ENTITY = "TW_MOBILE_PHONE"

    PATTERNS = [
        Pattern(
            name="tw_mobile",
            regex=r"(?<!\d)09\d{2}[-\s]?\d{3}[-\s]?\d{3}(?!\d)",
            score=0.85,
        )
    ]

    def __init__(self):
        super().__init__(
            supported_entity=self.ENTITY,
            patterns=self.PATTERNS,
            supported_language=_LANGUAGE,
            name="TaiwanMobileRecognizer",
        )


# ═══════════════════════════════════════════════════════════════
# Custom Recognizer 3：台灣市內電話
# ═══════════════════════════════════════════════════════════════
class TaiwanLandlineRecognizer(PatternRecognizer):
    """
    涵蓋 02-2345-6789 / 02 2345 6789 / (02)23456789 等常見格式。
    台灣手機一律以 09 開頭，市話區碼不會是 09，所以用 validate_result
    再擋一次，避免跟 TaiwanMobileRecognizer 的判斷範圍重疊、互相干擾。
    """

    ENTITY = "TW_LANDLINE_PHONE"

    PATTERNS = [
        Pattern(
            name="tw_landline",
            regex=r"(?<!\d)\(?0[2-8]\d{0,2}\)?[-\s]?\d{3,4}[-\s]?\d{4}(?!\d)",
            score=0.6,
        )
    ]

    def __init__(self):
        super().__init__(
            supported_entity=self.ENTITY,
            patterns=self.PATTERNS,
            supported_language=_LANGUAGE,
            name="TaiwanLandlineRecognizer",
        )

    def validate_result(self, pattern_text: str) -> Optional[bool]:
        digits = re.sub(r"\D", "", pattern_text)
        if digits.startswith("09"):
            # 交給 TaiwanMobileRecognizer 判斷，這裡直接判定不成立
            return False
        if not (8 <= len(digits) <= 10):
            return False
        return True


# ═══════════════════════════════════════════════════════════════
# Custom Recognizer 4：台灣身分證字號（含 checksum 驗證，privacy-first）
# ═══════════════════════════════════════════════════════════════
class TaiwanNationalIdRecognizer(EntityRecognizer):
    """
    格式：1 個大寫英文字母 + 9 碼數字（例如 A123456789）。

    Privacy-first 設計：checksum 沒過「不代表一定不是敏感資料」，所以
    不是單純「checksum 沒過就不遮」。判斷邏輯分三種情況：

    1. checksum 通過：高信心，直接視為合法身分證字號，遮罩。
    2. checksum 沒過，但符合格式，且鄰近文字出現「身分證」「身分證字號」
       「身份證」「身份證字號」等明確 context：仍然遮罩（中信心）。
       這是為了涵蓋使用者填單打錯一碼、OCR / 轉檔誤差等常見情況——
       文字已經明講「這是身分證字號」時，即使 checksum 沒通過，
       把它送去 Gemini 的隱私風險還是存在，寧可多遮一點。
    3. checksum 沒過、附近也沒有身分證相關 context：不遮罩。
       避免把單純「英文字母 + 9 碼數字」的亂數（例如貨運追蹤碼、
       系統序號）誤判成身分證字號。

    因為需要看「候選字串附近的文字」才能判斷有沒有 context，
    validate_result() 只拿得到候選字串本身、看不到上下文，
    所以這裡直接繼承 EntityRecognizer、自己覆寫 analyze()，
    而不是用 PatternRecognizer 的 validate_result()。
    """

    ENTITY = "TW_NATIONAL_ID"

    _ID_PATTERN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]\d{9}(?![A-Za-z0-9])")

    # 「身分證」與「身份證」都是常見寫法，兩種都收
    _CONTEXT_KEYWORDS = ("身分證字號", "身分證", "身份證字號", "身份證")
    _CONTEXT_WINDOW_BEFORE = 15  # 候選字串前面看幾個字
    _CONTEXT_WINDOW_AFTER = 10   # 候選字串後面看幾個字

    _SCORE_CHECKSUM_VALID = 0.85
    _SCORE_CHECKSUM_INVALID_WITH_CONTEXT = 0.65

    # 內政部戶役政公告的縣市碼對照表
    _LETTER_VALUES = {
        "A": 10, "B": 11, "C": 12, "D": 13, "E": 14, "F": 15, "G": 16,
        "H": 17, "I": 34, "J": 18, "K": 19, "L": 20, "M": 21, "N": 22,
        "O": 35, "P": 23, "Q": 24, "R": 25, "S": 26, "T": 27, "U": 28,
        "V": 29, "W": 32, "X": 30, "Y": 31, "Z": 33,
    }
    _WEIGHTS = [1, 9, 8, 7, 6, 5, 4, 3, 2, 1, 1]

    def __init__(self):
        super().__init__(
            supported_entities=[self.ENTITY],
            supported_language=_LANGUAGE,
            name="TaiwanNationalIdRecognizer",
        )

    def load(self) -> None:
        return None

    @classmethod
    def _is_valid_checksum(cls, national_id: str) -> bool:
        national_id = national_id.upper()
        if len(national_id) != 10 or not national_id[0].isalpha():
            return False
        digits = national_id[1:]
        if not digits.isdigit():
            return False

        letter_value = cls._LETTER_VALUES.get(national_id[0])
        if letter_value is None:
            return False

        n1, n2 = divmod(letter_value, 10)
        values = [n1, n2] + [int(d) for d in digits]
        weighted_sum = sum(v * w for v, w in zip(values, cls._WEIGHTS))
        return weighted_sum % 10 == 0

    def _has_nearby_id_context(self, text: str, start: int, end: int) -> bool:
        window = text[
            max(0, start - self._CONTEXT_WINDOW_BEFORE):end + self._CONTEXT_WINDOW_AFTER
        ]
        return any(keyword in window for keyword in self._CONTEXT_KEYWORDS)

    def analyze(self, text: str, entities: List[str], nlp_artifacts=None) -> List[RecognizerResult]:
        if self.ENTITY not in entities:
            return []

        results: List[RecognizerResult] = []
        for m in self._ID_PATTERN.finditer(text):
            candidate = m.group()
            start, end = m.start(), m.end()

            if self._is_valid_checksum(candidate):
                score = self._SCORE_CHECKSUM_VALID
            elif self._has_nearby_id_context(text, start, end):
                score = self._SCORE_CHECKSUM_INVALID_WITH_CONTEXT
            else:
                # checksum 沒過、附近也沒有身分證相關字眼 → 不遮罩
                continue

            results.append(
                RecognizerResult(
                    entity_type=self.ENTITY,
                    start=start,
                    end=end,
                    score=score,
                    recognition_metadata={
                        RecognizerResult.RECOGNIZER_NAME_KEY: self.name
                    },
                )
            )
        return results



# ═══════════════════════════════════════════════════════════════
# Custom Recognizer 5：員工編號（尚未確認格式，先留可擴充結構）
# ═══════════════════════════════════════════════════════════════
class TaiwanEmployeeIdRecognizer(EntityRecognizer):
    """
    TODO: 目前 repo / 資料中沒有明確的員工編號格式規範，
    先建立可擴充的骨架，analyze() 目前一律回傳空清單（不偵測任何東西），
    避免因為過度寬鬆的 Regex 造成大量誤判。

    等實際格式確認後（例如「員編 EMP-0001」、純數字工號等），
    只要把對應的 Pattern 加進 PATTERNS，並把 analyze() 換成呼叫
    PatternRecognizer 風格的比對邏輯即可，不需要更動 privacy_service.py
    其他部分（mask_pii 已經預留 TW_EMPLOYEE_ID 這個 entity type
    與對應的顯示標籤【員工編號】）。

    注意：這個 recognizer 目前刻意「不」加進 _build_analyzer() 的
    registry 裡（因為它本來就偵測不到任何東西，加了也沒作用）；
    等實作完成、有真正的 Pattern 之後，記得回到 _build_analyzer()
    把它加進 registry.add_recognizer(...)。
    """

    ENTITY = "TW_EMPLOYEE_ID"

    PATTERNS: List[Pattern] = []  # TODO: 待員工編號格式確認後補上

    def __init__(self):
        super().__init__(
            supported_entities=[self.ENTITY],
            supported_language=_LANGUAGE,
            name="TaiwanEmployeeIdRecognizer",
        )

    def load(self) -> None:
        return None

    def analyze(self, text: str, entities: List[str], nlp_artifacts=None) -> List[RecognizerResult]:
        # TODO: 格式確認後在這裡實作真正的比對邏輯
        return []


# ═══════════════════════════════════════════════════════════════
# Custom Recognizer 6：中文姓名（保守、Precision 優先）
# ═══════════════════════════════════════════════════════════════
class ChinesePersonNameRecognizer(EntityRecognizer):
    """
    完全不依賴 spaCy NER / 大型模型，純規則判斷：

    1. 只有「常見中文姓氏表」裡的姓氏（單姓 / 複姓）開頭才可能被視為姓名，
       姓氏表刻意排除本身就是常用詞彙的字（例如「管」，避免「管理」被誤判）。
    2. 姓氏後面 1～2 個中文字視為候選名字，但候選結果如果完整落在
       EXCLUSION_PHRASES（常見詞彙排除清單，例如「方法」「高興」「林場」）
       裡，直接排除，不當作姓名。
    3. 「姓氏 + 1 個字」的候選（例如「王偉」）風險較高（很多常用詞都符合這個
       長度與結構），基礎分數刻意壓低，需要前後文佐證（例如緊接著「覺得」
       「表示」等動詞，或前面出現「先生」「主管」等稱謂）才會通過門檻；
       「姓氏 + 2 個字」的候選（例如「王小明」）與複姓組合，基礎分數較高，
       不需要額外前後文即可通過門檻。
    4. 最終只有分數 >= SCORE_THRESHOLD 才會被視為姓名並遮罩。

    設計目標是 Precision 優先於 Recall：允許漏掉少數難以判斷的人名
    （false negative），但盡量避免一般問卷用詞被誤遮罩（false positive）。
    """

    ENTITY = "PERSON_ZH"

    SINGLE_SURNAMES = {
        "陳", "林", "黃", "張", "李", "王", "吳", "劉", "蔡", "楊",
        "許", "鄭", "謝", "郭", "洪", "曾", "邱", "廖", "賴", "徐",
        "周", "葉", "蘇", "莊", "呂", "江", "何", "蕭", "羅", "高",
        "潘", "簡", "朱", "鍾", "游", "詹", "方", "沈", "余", "施",
        "盧", "梁", "顏", "柯", "孫", "魏", "翁", "戴", "董", "唐",
        "傅", "馮", "程", "連", "馬", "趙", "胡", "韓", "曹", "彭",
        "袁", "鄧", "姚", "汪", "范", "石", "金", "錢", "邵", "任",
        "古", "倪", "尹", "涂", "卓", "龍", "巫", "凌", "童", "萬",
        "尤", "阮", "溫", "紀", "包", "常", "牛",
    }

    COMPOUND_SURNAMES = {
        "歐陽", "司馬", "諸葛", "上官", "夏侯", "令狐", "東方", "長孫",
        "司徒", "公孫", "慕容", "尉遲", "皇甫", "澹台", "拓跋", "宇文",
        "太史", "端木", "軒轅", "獨孤", "南宮", "西門", "呼延",
    }

    # 常見詞彙排除清單：完整候選字串命中這裡就一律不視為姓名。
    # 這份清單不求窮盡，而是「已知容易誤判」的優先防呆，
    # 剩下未列出的詞彙仍可能漏網（見報告第 13 點）。
    EXCLUSION_PHRASES = {
        "方法", "方式", "方向", "方案", "方位", "方面",
        "林場", "林業", "林蔭",
        "高興", "高中", "高手", "高度", "高層", "高峰", "高溫", "高低",
        "王國", "王朝", "王牌",
        "黃金", "黃色", "黃昏",
        "朱紅",
        "馬上", "馬路", "馬達",
        "徐緩",
        "江山", "江湖",
        "陳列", "陳舊", "陳述", "陳情",
        "沈默",
        "石頭", "石油",
        "金錢", "金額", "金牌", "金融",
        "古代", "古老", "古蹟",
        "連續", "連結", "連接", "連線",
        "程度", "程序",
        "唐突",
        "萬一", "萬能", "萬歲",
        "毛病", "毛巾",
        "包括", "包含", "包裝",
        "常常", "常見", "常態",
        "任何", "任務", "任職",
        # 需求文件第七節列舉、不得被誤遮罩的一般詞彙（防呆用，
        # 即使目前姓氏表本來就不會命中這些詞的第一個字，仍保留於此）
        "教育訓練", "工作中", "職涯發展", "主管", "管理", "部門", "溝通", "回饋",
    }

    # 候選姓名「後面」緊接著這些詞，代表候選字串很可能是句子主詞（人名）
    CONTEXT_BOOST_AFTER = {
        "覺得", "認為", "表示", "提到", "反映", "建議", "希望",
        "提出", "分享", "指出", "詢問", "抱怨", "說", "談到",
    }

    # 候選姓名「前面」幾個字內出現這些詞，代表附近有稱謂 / 引用語境
    CONTEXT_BOOST_BEFORE = {
        "先生", "小姐", "經理", "主任", "老師", "同事", "同仁",
        "受訪者", "學員", "叫做", "姓名", "訪談",
    }

    SCORE_COMPOUND = 0.8
    SCORE_SINGLE_2CHAR = 0.65
    SCORE_SINGLE_1CHAR = 0.45
    CONTEXT_BOOST = 0.2
    SCORE_THRESHOLD = 0.6

    def __init__(self):
        super().__init__(
            supported_entities=[self.ENTITY],
            supported_language=_LANGUAGE,
            name="ChinesePersonNameRecognizer",
        )

    def load(self) -> None:
        # 純規則判斷，沒有模型需要載入
        return None

    @staticmethod
    def _is_han(ch: str) -> bool:
        return "\u4e00" <= ch <= "\u9fff"

    def _best_match_at(self, text: str, pos: int):
        n = len(text)
        best = None  # (start, end, score)

        surname_options = []
        if text[pos:pos + 2] in self.COMPOUND_SURNAMES:
            surname_options.append((2, self.SCORE_COMPOUND))
        if text[pos] in self.SINGLE_SURNAMES:
            surname_options.append((1, None))

        for surname_len, fixed_score in surname_options:
            # 先檢查「姓氏 + 1 個字」這個最短候選是否命中排除清單。
            # 如果連最短候選都是常見詞彙（例如「林場」「方法」），
            # 就代表這個位置根本不是姓名的起點，直接放棄這個 surname_len，
            # 不要再嘗試往後多吃一個字去湊「姓氏 + 2 個字」
            # （否則「林場管理」會被誤判成「林場管」這個不存在的名字，
            # 反而繞過了排除清單）。
            short_end = pos + surname_len + 1
            if short_end <= n:
                short_given = text[pos + surname_len:short_end]
                if (
                    all(self._is_han(c) for c in short_given)
                    and text[pos:short_end] in self.EXCLUSION_PHRASES
                ):
                    continue

            # 優先嘗試較長的 2 字給定名（更像完整姓名，precision 較高）
            for given_len in (2, 1):
                end = pos + surname_len + given_len
                if end > n:
                    continue
                given = text[pos + surname_len:end]
                if not all(self._is_han(c) for c in given):
                    continue

                candidate = text[pos:end]
                if candidate in self.EXCLUSION_PHRASES:
                    continue

                if fixed_score is not None:
                    score = fixed_score
                elif given_len == 2:
                    score = self.SCORE_SINGLE_2CHAR
                else:
                    score = self.SCORE_SINGLE_1CHAR

                following = text[end:end + 3]
                preceding = text[max(0, pos - 4):pos]
                if any(following.startswith(w) for w in self.CONTEXT_BOOST_AFTER):
                    score += self.CONTEXT_BOOST
                if any(w in preceding for w in self.CONTEXT_BOOST_BEFORE):
                    score += self.CONTEXT_BOOST
                score = min(score, 0.95)

                if score >= self.SCORE_THRESHOLD:
                    if best is None or (end - pos, score) > (best[1] - best[0], best[2]):
                        best = (pos, end, score)

            if best is not None:
                # 複姓命中就不用再退回單姓判斷同一個起始位置
                break

        return best

    def analyze(self, text: str, entities: List[str], nlp_artifacts=None) -> List[RecognizerResult]:
        if self.ENTITY not in entities:
            return []

        results: List[RecognizerResult] = []
        n = len(text)
        i = 0
        while i < n:
            match = self._best_match_at(text, i)
            if match:
                start, end, score = match
                results.append(
                    RecognizerResult(
                        entity_type=self.ENTITY,
                        start=start,
                        end=end,
                        score=score,
                        recognition_metadata={
                            RecognizerResult.RECOGNIZER_NAME_KEY: self.name
                        },
                    )
                )
                i = end
            else:
                i += 1
        return results


# ═══════════════════════════════════════════════════════════════
# Analyzer / Anonymizer 初始化（模組載入時建立一次，重複使用）
# ═══════════════════════════════════════════════════════════════
_MASK_LABELS: Dict[str, str] = {
    SimpleEmailRecognizer.ENTITY: "【EMAIL】",
    TaiwanMobileRecognizer.ENTITY: "【手機號碼】",
    TaiwanLandlineRecognizer.ENTITY: "【電話】",
    TaiwanNationalIdRecognizer.ENTITY: "【身分證字號】",
    TaiwanEmployeeIdRecognizer.ENTITY: "【員工編號】",
    ChinesePersonNameRecognizer.ENTITY: "【姓名】",
}

_ENTITIES_TO_DETECT = list(_MASK_LABELS.keys())


def _build_analyzer() -> AnalyzerEngine:
    registry = RecognizerRegistry(supported_languages=[_LANGUAGE])
    registry.add_recognizer(SimpleEmailRecognizer())
    registry.add_recognizer(TaiwanMobileRecognizer())
    registry.add_recognizer(TaiwanLandlineRecognizer())
    registry.add_recognizer(TaiwanNationalIdRecognizer())
    # TaiwanEmployeeIdRecognizer 目前是空骨架（沒有任何 Pattern，analyze()
    # 一律回傳 []），先不加進 registry；等實際員工編號格式確認、補上
    # PATTERNS 與比對邏輯後，再解除下面這行註解。
    # registry.add_recognizer(TaiwanEmployeeIdRecognizer())
    registry.add_recognizer(ChinesePersonNameRecognizer())

    nlp_engine = _BlankChineseNlpEngine()
    nlp_engine.load()

    return AnalyzerEngine(
        nlp_engine=nlp_engine,
        registry=registry,
        supported_languages=[_LANGUAGE],
    )


_analyzer: Optional[AnalyzerEngine] = None
_anonymizer: Optional[AnonymizerEngine] = None


def _get_engines():
    global _analyzer, _anonymizer
    if _analyzer is None:
        _analyzer = _build_analyzer()
    if _anonymizer is None:
        _anonymizer = AnonymizerEngine()
    return _analyzer, _anonymizer


def mask_pii(text: str) -> str:
    """
    對外主要介面：把 text 內偵測到的 PII 換成對應的標記文字
    （例如【姓名】【EMAIL】【手機號碼】【電話】【身分證字號】），
    其餘文字原封不動保留。

    只應該用在「準備送給 Gemini 的文字」，回傳值不可以被寫回
    answer_text 或 Response_Classification.answer_text。

    採 fail-closed：任何步驟失敗都會拋出 PiiMaskingError，
    不會 fallback 成回傳原始 text。
    """
    if text is None:
        raise PiiMaskingError("mask_pii 收到 None，無法進行 PII 遮罩")

    if not isinstance(text, str):
        raise PiiMaskingError(f"mask_pii 需要 str，收到 {type(text)}")

    if text.strip() == "":
        return text

    try:
        analyzer, anonymizer = _get_engines()

        analyzer_results = analyzer.analyze(
            text=text,
            language=_LANGUAGE,
            entities=_ENTITIES_TO_DETECT,
        )

        operators = {
            entity_type: OperatorConfig("replace", {"new_value": label})
            for entity_type, label in _MASK_LABELS.items()
        }

        anonymized = anonymizer.anonymize(
            text=text,
            analyzer_results=analyzer_results,
            operators=operators,
        )
        return anonymized.text

    except PiiMaskingError:
        raise
    except Exception as exc:  # noqa: BLE001 - fail-closed，任何錯誤都要往外拋
        logger.exception("PII masking failed")
        raise PiiMaskingError(f"PII masking 失敗：{exc}") from exc


# ═══════════════════════════════════════════════════════════════
# mask_pii_with_mapping()：mask_pii() 的擴充版，額外提供「遮罩後文字
# 座標 ↔ 原文座標」的對照能力，供意義單元拆分流程使用。
#
# 這是新增的功能，mask_pii() 本身完全不變——任何現有呼叫端
# （classify_v2.py、test_privacy_service.py）不需要跟著修改。
# ═══════════════════════════════════════════════════════════════
class PlaceholderBoundaryError(ValueError):
    """
    查詢的遮罩後文字區間，切在某個遮罩標籤（例如「【姓名】」）中間，
    無法對應回一段有意義的原文區間時拋出。

    呼叫端（segmentation_service）遇到這個例外，應該把對應的
    segment 視為驗證失敗，不可以硬猜一個位置繼續往下處理。
    """


class PiiPositionMap:
    """
    描述一份「原文 ↔ 遮罩後文字」的對照關係。

    內部把整份文字切成一串「區塊」（block），依遮罩後文字的位置
    由前到後排列，每個區塊要嘛是「原樣保留」（identity），
    要嘛是「被整段換成一個標籤」（replaced）。任何一個區塊，
    原文長度跟遮罩後文字長度可以不一樣（因為標籤字數不等於被
    遮罩的原文字數），但區塊本身在各自的座標系統裡都是連續、
    不重疊、涵蓋整份文字首尾的。

    對外只需要用 to_original_range(masked_start, masked_end)，
    不需要理解內部區塊怎麼組成的。
    """

    class _Block:
        __slots__ = ("orig_start", "orig_end", "masked_start", "masked_end", "is_replacement")

        def __init__(self, orig_start, orig_end, masked_start, masked_end, is_replacement):
            self.orig_start = orig_start
            self.orig_end = orig_end
            self.masked_start = masked_start
            self.masked_end = masked_end
            self.is_replacement = is_replacement

    def __init__(self, blocks):
        self._blocks = blocks  # 依 masked_start 由小到大排序

    def _find_block(self, masked_pos: int, prefer_end_of_prev: bool = False):
        """
        找出涵蓋 masked_pos 這個位置的區塊。

        prefer_end_of_prev：masked_pos 剛好落在兩個區塊交界處時
        （等於某區塊的 masked_end，也等於下一個區塊的 masked_start），
        要回傳「前一個區塊、當作它的結尾」還是「下一個區塊、當作它的
        開頭」。查詢區間的右端點（end）要用 True，左端點（start）
        要用 False，這樣邊界情況才會對應到直覺上正確的區塊。
        """
        for block in self._blocks:
            if block.masked_start <= masked_pos < block.masked_end:
                return block
            if masked_pos == block.masked_end and prefer_end_of_prev:
                return block
        if masked_pos == self._blocks[-1].masked_end:
            return self._blocks[-1]
        raise PlaceholderBoundaryError(
            f"masked_pos={masked_pos} 超出文字範圍，找不到對應區塊"
        )

    def to_original_range(self, masked_start: int, masked_end: int):
        """
        把「遮罩後文字」裡的 [masked_start, masked_end) 區間，
        換算成「原文」裡對應的 [orig_start, orig_end) 區間。

        如果這個區間切在某個遮罩標籤中間（不是從標籤的開頭開始，
        或不是在標籤的結尾結束），視為不合法，拋出
        PlaceholderBoundaryError，呼叫端必須把這個 segment
        視為驗證失敗，不可以硬猜一個位置繼續處理。
        """
        if masked_start > masked_end:
            raise PlaceholderBoundaryError("masked_start 不可以大於 masked_end")

        start_block = self._find_block(masked_start, prefer_end_of_prev=False)
        end_block = self._find_block(masked_end, prefer_end_of_prev=True)

        # 起點如果落在一個「被換成標籤」的區塊裡，必須恰好是那個
        # 標籤的開頭，不可以是標籤中間某個字元的位置
        if start_block.is_replacement and masked_start != start_block.masked_start:
            raise PlaceholderBoundaryError(
                f"起點 {masked_start} 切在遮罩標籤中間，不是合法邊界"
            )
        # 終點如果落在一個「被換成標籤」的區塊裡，必須恰好是那個
        # 標籤的結尾
        if end_block.is_replacement and masked_end != end_block.masked_end:
            raise PlaceholderBoundaryError(
                f"終點 {masked_end} 切在遮罩標籤中間，不是合法邊界"
            )

        orig_start = self._map_position(start_block, masked_start)
        orig_end = self._map_position(end_block, masked_end)
        return orig_start, orig_end

    @staticmethod
    def _map_position(block, masked_pos: int) -> int:
        """
        把區塊內的一個遮罩後座標，換算成原文座標。

        identity 區塊：字元一一對應，直接按比例位移即可。
        replacement 區塊：標籤長度跟原文長度不一定相同（例如「王小明」
        3 個字換成「【姓名】」4 個字），內部不存在一一對應關係，只有
        區塊的起點對應原文起點、區塊的終點對應原文終點這兩個有意義的
        位置合法（呼叫此函式前，to_original_range() 已經確保
        masked_pos 一定落在這兩個邊界之一，不會是中間位置）。
        """
        if not block.is_replacement:
            return block.orig_start + (masked_pos - block.masked_start)
        if masked_pos == block.masked_start:
            return block.orig_start
        return block.orig_end


def _build_position_map(original_text: str, analyzer_results, anonymized_text: str, items) -> PiiPositionMap:
    """
    用「原文座標的偵測結果」＋「遮罩後座標的替換紀錄」，組出
    PiiPositionMap。

    items 是 anonymizer.anonymize() 回傳的 EngineResult.items，
    實測順序是「由後往前」（因為 anonymizer 內部是從文字尾端
    開始替換，避免前面的替換影響後面的座標），這裡先反轉成
    「由前往後」，才能跟依 start 排序過的 analyzer_results 一一對應。
    """
    sorted_results = sorted(analyzer_results, key=lambda r: (r.start, r.end))
    ordered_items = list(reversed(items))

    if len(sorted_results) != len(ordered_items):
        # 理論上用 merge_entities_with_spaces=False 呼叫 anonymize()
        # 之後，兩者數量必須一致；如果不一致，代表對照關係已經不可信，
        # 不能硬湊，直接視為失敗
        raise PiiMaskingError(
            f"位置對照建立失敗：偵測到 {len(sorted_results)} 個 PII，"
            f"但遮罩紀錄有 {len(ordered_items)} 筆，數量對不上"
        )

    blocks = []
    orig_cursor = 0
    masked_cursor = 0

    for result, item in zip(sorted_results, ordered_items):
        if result.start > orig_cursor:
            gap_len = result.start - orig_cursor
            blocks.append(
                PiiPositionMap._Block(
                    orig_cursor, result.start,
                    masked_cursor, masked_cursor + gap_len,
                    is_replacement=False,
                )
            )
            masked_cursor += gap_len

        if item.start != masked_cursor:
            raise PiiMaskingError(
                "位置對照建立失敗：遮罩後文字座標與預期不符"
            )

        blocks.append(
            PiiPositionMap._Block(
                result.start, result.end,
                item.start, item.end,
                is_replacement=True,
            )
        )
        orig_cursor = result.end
        masked_cursor = item.end

    if orig_cursor < len(original_text):
        gap_len = len(original_text) - orig_cursor
        blocks.append(
            PiiPositionMap._Block(
                orig_cursor, len(original_text),
                masked_cursor, masked_cursor + gap_len,
                is_replacement=False,
            )
        )
        masked_cursor += gap_len

    if not blocks:
        # 完全沒有偵測到任何 PII：整份文字是單一個 identity 區塊
        blocks.append(
            PiiPositionMap._Block(0, len(original_text), 0, len(anonymized_text), is_replacement=False)
        )

    if masked_cursor != len(anonymized_text):
        raise PiiMaskingError(
            "位置對照建立失敗：組出來的區塊長度跟遮罩後文字長度對不上"
        )

    return PiiPositionMap(blocks)


def mask_pii_with_mapping(text: str):
    """
    mask_pii() 的擴充版：除了遮罩後文字，額外回傳一份
    PiiPositionMap，可以把「遮罩後文字的區間」換算回「原文的區間」。

    回傳：(masked_text: str, position_map: PiiPositionMap)

    用途：意義單元拆分流程（segmentation_service）需要先在
    masked_text 上定位 Gemini 回傳的 segment_text，驗證通過後，
    再用這份對照表換算出 segment 在「原始 answer_text」裡的
    orig_start / orig_end，供寫入 Response_Classification 使用。

    跟 mask_pii() 的差異只在於「同時保留位置資訊」，實際偵測、
    遮罩的邏輯（用哪些 recognizer、標籤文字是什麼）完全相同，
    不是另一套遮罩規則，兩個函式的遮罩結果對同一份輸入永遠一致。

    採 fail-closed，行為比照 mask_pii()：任何步驟失敗一律拋出
    PiiMaskingError（或其子類別 PlaceholderBoundaryError 由呼叫端
    自行處理個別 segment 的驗證失敗，不在這個函式內吞掉)。
    """
    if text is None:
        raise PiiMaskingError("mask_pii_with_mapping 收到 None，無法進行 PII 遮罩")

    if not isinstance(text, str):
        raise PiiMaskingError(f"mask_pii_with_mapping 需要 str，收到 {type(text)}")

    if text.strip() == "":
        empty_map = PiiPositionMap([PiiPositionMap._Block(0, len(text), 0, len(text), is_replacement=False)])
        return text, empty_map

    try:
        analyzer, anonymizer = _get_engines()

        analyzer_results = analyzer.analyze(
            text=text,
            language=_LANGUAGE,
            entities=_ENTITIES_TO_DETECT,
        )

        operators = {
            entity_type: OperatorConfig("replace", {"new_value": label})
            for entity_type, label in _MASK_LABELS.items()
        }

        anonymized = anonymizer.anonymize(
            text=text,
            analyzer_results=analyzer_results,
            operators=operators,
            # 【修正｜2026-08-27】原本這裡多傳了 merge_entities_with_spaces=False，
            # 但這個參數從未存在於 presidio-anonymizer 任何一個版本（查過 2.2.1～
            # 2.2.364 全部沒有），只要一呼叫就會 TypeError，導致 PII 遮罩（含位置
            # 對照）100% 失敗。拿掉這個參數，改成跟 mask_pii() 一樣的呼叫方式，
            # 兩者本來就共用同一個 _get_engines()。下面 _build_position_map()
            # 本身有針對「找不到逐字相符內容」做 fail-closed 錯誤處理，
            # 不會因為拿掉這個參數就悄悄跑出錯的位置對照。
        )

        position_map = _build_position_map(
            original_text=text,
            analyzer_results=analyzer_results,
            anonymized_text=anonymized.text,
            items=anonymized.items,
        )

        return anonymized.text, position_map

    except PiiMaskingError:
        raise
    except Exception as exc:  # noqa: BLE001 - fail-closed，任何錯誤都要往外拋
        logger.exception("PII masking (with mapping) failed")
        raise PiiMaskingError(f"PII masking（含位置對照）失敗：{exc}") from exc