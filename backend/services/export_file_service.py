"""

匯出檔案產生器：把分類結果的 rows（大類別、子類別、問卷回覆內容、判斷原因與
說明、受試者建議摘要）產生成真正的 Excel（.xlsx）或 Word（.docx）檔案。

CSV 沒有放在這裡——CSV 是純文字格式，前端組字串就能產生，不需要動用
後端套件；這裡只處理 Excel、Word 這兩種需要真正函式庫才能產生的二進位
格式。

兩種格式都遵循跟 CSV 匯出、前端表格顯示一致的規則：
  - 5 欄：大類別、子類別、問卷回覆內容、判斷原因與說明、受試者建議摘要
  - 大類別連續相同時合併儲存格（Excel 用 merge_cells，Word 用手動合併
    儲存格），不逐列重複

Word（build_docx）額外處理「多題目」的情況：如果 rows 帶有
source_column（Excel 上傳來源）或 question_id（問卷來源）這類題目
中繼資料，且不只一種值，會依題目切成多張各自完整（各自有表頭）的
表格；沒有這類中繼資料時維持「整批 rows 一張表」的舊行為，不受影響。
Excel（build_xlsx）完全沒有異動這部分邏輯。
"""

import io
from zoneinfo import ZoneInfo

import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from docx import Document
from docx.shared import Pt, Cm, Emu
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.enum.section import WD_ORIENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

COLUMN_HEADERS = ["大類別", "子類別", "問卷回覆內容", "判斷原因與說明", "受試者建議摘要"]


DOCX_CJK_FONT = "微軟正黑體"


def _row_values(row: dict) -> list:
    return [
        row.get("main_category", ""),
        row.get("sub_category", ""),
        row.get("respondent_text", ""),
        row.get("aggregated_reasoning", ""),
        row.get("aggregated_summary", ""),
    ]


def build_xlsx(rows: list, title: str = "分類結果", rating_stats: list | None = None) -> bytes:
    """把 rows 產生成 .xlsx 檔案，回傳檔案的原始 bytes。

    rating_stats 是【新增｜問卷 Chat 分析評分題統計】的可選參數，預設
    None，行為與呼叫端完全相容：
      - 不傳／傳 None／傳空陣列 []：跟這個參數新增之前的行為逐位元組
        相同，不會多一張 sheet，既有呼叫端（分類結果匯出、Excel 上傳
        分類）完全不受影響。
      - 傳非空陣列：在既有分類結果 sheet 之外，另外插入一張「評分題
        統計」sheet（放在最前面，索引 0），下面既有的分類結果建置邏輯
        （表頭、合併儲存格、欄寬…）一行都不動。
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = title[:31] if title else "分類結果"  # Excel 分頁名稱上限 31 字元

    
    header_font = Font(name="微軟正黑體", bold=True, color="FFFFFFFF")
    header_fill = PatternFill(start_color="FFF43F5E", end_color="FFF43F5E", fill_type="solid")
    body_font = Font(name="微軟正黑體")
    wrap_alignment = Alignment(wrap_text=True, vertical="top", horizontal="left")
    center_alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
    thin_border = Border(
        left=Side(style="thin", color="FF000000"),
        right=Side(style="thin", color="FF000000"),
        top=Side(style="thin", color="FF000000"),
        bottom=Side(style="thin", color="FF000000"),
    )

    for col_idx, header in enumerate(COLUMN_HEADERS, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center_alignment
        cell.border = thin_border

    for row_idx, row in enumerate(rows, start=2):
        values = _row_values(row)
        for col_idx, value in enumerate(values, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.font = body_font
            cell.alignment = wrap_alignment
            cell.border = thin_border

    # 大類別（第一欄）連續相同時合併儲存格，比照前端畫面上的 rowSpan 效果
    merge_start_row = 2
    for row_idx in range(3, len(rows) + 3):
        current_main = rows[row_idx - 2]["main_category"] if row_idx - 2 < len(rows) else None
        prev_main = rows[row_idx - 3]["main_category"] if row_idx - 3 < len(rows) else None
        if current_main != prev_main:
            if row_idx - 1 > merge_start_row:
                ws.merge_cells(start_row=merge_start_row, start_column=1, end_row=row_idx - 1, end_column=1)
                ws.cell(row=merge_start_row, column=1).alignment = center_alignment
            merge_start_row = row_idx

    column_widths = [16, 20, 46, 40, 34]
    for col_idx, width in enumerate(column_widths, start=1):
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    ws.freeze_panes = "A2"

    # 【新增｜評分題統計 sheet】只在有評分題統計時才建立，插在最前面
    # （index=0），讓使用者打開檔案先看到評分題總覽、再看質化分類細節。
    # rating_stats 為 None 或空陣列時完全不執行這段，既有分類結果 sheet
    # （上面已經建置完成）逐位元組不變。
    if rating_stats:
        _write_rating_stats_sheet(wb, rating_stats, index=0)
        wb.active = 0

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _write_rating_stats_sheet(wb, rating_stats: list, *, index: int = 0):
    """在既有 workbook 裡插入一張「評分題統計」sheet。

    只服務 build_xlsx() 的評分統計附加需求，跟既有分類結果 sheet 的
    建置邏輯（COLUMN_HEADERS、_row_values、合併儲存格）完全獨立，
    不共用、也不會互相影響。
    """
    ws = wb.create_sheet(title="評分題統計", index=index)

    header_font = Font(name="微軟正黑體", bold=True, color="FFFFFFFF")
    header_fill = PatternFill(start_color="FFF43F5E", end_color="FFF43F5E", fill_type="solid")
    body_font = Font(name="微軟正黑體")
    wrap_alignment = Alignment(wrap_text=True, vertical="top", horizontal="left")
    center_alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
    thin_border = Border(
        left=Side(style="thin", color="FF000000"),
        right=Side(style="thin", color="FF000000"),
        top=Side(style="thin", color="FF000000"),
        bottom=Side(style="thin", color="FF000000"),
    )

    headers = ["題目", "平均分", "有效回答數"] + [f"{score} 分人數" for score in range(6)]
    for col_idx, header in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center_alignment
        cell.border = thin_border

    for row_idx, stat in enumerate(rating_stats, start=2):
        distribution = stat.get("distribution") or {}
        question_number = stat.get("question_number")
        title_text = stat.get("title") or ""
        question_label = f"Q{question_number}：{title_text}" if question_number else title_text
        average = stat.get("average")
        values = [
            question_label,
            average if average is not None else "無資料",
            stat.get("answered_count", 0),
        ] + [distribution.get(str(score), 0) for score in range(6)]
        for col_idx, value in enumerate(values, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.font = body_font
            cell.border = thin_border
            cell.alignment = wrap_alignment if col_idx == 1 else center_alignment

    column_widths = [40, 10, 12] + [10] * 6
    for col_idx, width in enumerate(column_widths, start=1):
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    ws.freeze_panes = "A2"
    return ws


def _apply_docx_font(run, size_pt: float, bold: bool = False):
    """同時設定西方字型與中文（east-asia）字型，確保 Word 開啟後中文
    確實套用微軟正黑體，不會只有英數字對、中文掉回系統預設字體。
    """
    run.font.size = Pt(size_pt)
    run.font.bold = bold
    run.font.name = DOCX_CJK_FONT
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.append(rFonts)
    rFonts.set(qn("w:eastAsia"), DOCX_CJK_FONT)


def _set_cell_shading(cell, fill_hex: str):
    """套用儲存格底色（表頭淡灰底用）。python-docx 沒有對應的高階 API，
    要直接操作 XML 加上 <w:shd>。
    """
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill_hex)
    tcPr.append(shd)


def _set_repeat_header_row(row):
    """把某一列標記成「表格跨頁時，每一頁都重複顯示」的表頭列
    （Word 對應功能：表格內容 -> 重複標題列）。這樣長表格自然跨頁時，
    每一頁最上面都還看得到欄位名稱，不用使用者自己往回翻頁對欄位。
    """
    trPr = row._tr.get_or_add_trPr()
    tblHeader = OxmlElement("w:tblHeader")
    tblHeader.set(qn("w:val"), "true")
    trPr.append(tblHeader)


def _set_table_fixed_layout(table):
    """強制固定欄寬（不要讓 Word 依內容自動重新分配欄寬），
    不然「問卷回覆內容要是最寬欄」這個要求在 Word 實際開啟時可能會
    因為某一欄剛好內容很長，被自動版面配置悄悄搶走寬度。
    """
    tblPr = table._tbl.tblPr
    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    tblPr.append(layout)
    # autofit=False 是 python-docx 官方建議跟 fixed layout 搭配的寫法，
    # 兩者一起設才會在各版本 Word 都可靠地吃到我們指定的欄寬。
    table.autofit = False


def _write_cell_paragraphs(cell, text: str, *, size_pt: float, bold: bool,
                            align, extra_paragraph_spacing: bool = False):
    """把（可能包含多個受試者、以 \\n 分隔的）文字寫進儲存格，每一段
    各自是獨立的段落，而不是同一段落裡用換行符號硬塞。

    這是「每位受試者之間保留明顯段落間距」的關鍵：如果只是把整串文字
    （含 \\n）丟給 cell.text，python-docx 會把 \\n 轉成同一段落內的
    換行（<w:br/>），視覺上看起來只是貼在一起、段落前後距一律是 0，
    做不出「明顯」的間距。改成每個受試者各自一個 paragraph，並在段落
    設定 space_after，才有真正的段落間距。

    extra_paragraph_spacing 只對「問卷回覆內容」欄開，其餘欄位
    （子類別、判斷原因、建議摘要）內容通常較短或本來就是單一敘述，
    不需要放大段落間距。
    """
    lines = str(text or "").split("\n")
    if not lines:
        lines = [""]

    # cell 一開始一定至少有一個空段落，重複使用它當第一行，避免多出
    # 一個看起來像「多空一行」的空白段落。
    first_paragraph = cell.paragraphs[0]
    for existing_run in list(first_paragraph.runs):
        existing_run.text = ""

    for idx, line in enumerate(lines):
        paragraph = first_paragraph if idx == 0 else cell.add_paragraph()
        paragraph.alignment = align
        if extra_paragraph_spacing and idx < len(lines) - 1:
            # 只在「不是最後一行」時加下段距，最後一行加了反而會在
            # cell 底部留一截看起來像多的空白。
            paragraph.paragraph_format.space_after = Pt(8)
        else:
            paragraph.paragraph_format.space_after = Pt(0)
        run = paragraph.add_run(line)
        _apply_docx_font(run, size_pt=size_pt, bold=bold)

    cell.vertical_alignment = WD_ALIGN_VERTICAL.TOP


def _question_scope_key(row: dict):
    """判斷一筆 row 屬於哪一個「題目」，用來決定要不要分表。

    優先看 source_column（Excel 上傳來源，每欄文字題各自是一個
    「題目」），其次看 question_id（問卷來源，每一題各自一個
    question_id）。兩者都沒有就回傳 None——這代表這批 rows 沒有題目
    範圍的中繼資料（例如比較舊、資料結構還沒帶這兩個欄位的匯出紀錄），
    這種情況全部當同一組，不會因為缺資訊就亂猜、也不會因此噴錯，
    維持原本「整批 rows 一張表」的行為。
    """
    return row.get("source_column") or row.get("question_id")


def _group_rows_by_question(rows: list):
    """把 rows 依題目分組，回傳 [(question_label, group_rows), ...]，
    保持每組第一次出現的順序（不重新排序 rows 本身的相對順序）。

    只要「所有 row 的題目 key 都是 None」，就代表這批資料整體沒有
    題目範圍資訊，回傳單一組、question_label 為 None，呼叫端看到
    question_label 是 None 時不額外加小標題，維持原本「一張表」的
    排版，不會無中生有切出好幾張其實是同一題的表格。
    """
    if not rows:
        return []

    keys = [_question_scope_key(r) for r in rows]
    if all(k is None for k in keys):
        return [(None, rows)]

    order = []
    buckets = {}
    for row, key in zip(rows, keys):
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(row)

    return [(key, buckets[key]) for key in order]



_COLUMN_WIDTH_RATIOS = [0.10, 0.13, 0.38, 0.22, 0.17]  # 大類別/子類別/問卷回覆/判斷原因/建議摘要
_HEADER_FILL = "D9D9D9"  # 淡灰底
_BODY_FONT_SIZE = 10
_HEADER_FONT_SIZE = 11


def _build_classification_table(doc: Document, rows: list, col_widths: list):
    """建立單一張「大類別/子類別/問卷回覆內容/判斷原因與說明/受試者
    建議摘要」5 欄分類表，對應一個題目範圍（或整批沒有題目範圍資訊
    的 rows）。多題目時，呼叫端會針對每個題目分別呼叫這個函式，
    各自建立一張全新的 table，每張都有自己完整的表頭。
    """
    table = doc.add_table(rows=1, cols=len(COLUMN_HEADERS))
    table.style = "Table Grid"  # 黑色細格線
    _set_table_fixed_layout(table)

    header_row = table.rows[0]
    hdr_cells = header_row.cells
    for i, header in enumerate(COLUMN_HEADERS):
        cell = hdr_cells[i]
        _write_cell_paragraphs(
            cell, header, size_pt=_HEADER_FONT_SIZE, bold=True,
            align=WD_ALIGN_PARAGRAPH.CENTER,
        )
        _set_cell_shading(cell, _HEADER_FILL)  # 表頭淡灰底
    _set_repeat_header_row(header_row)  # 跨頁時每頁都重複表頭

    
    column_style = [
        {"bold": True, "align": WD_ALIGN_PARAGRAPH.CENTER, "extra_spacing": False},
        {"bold": True, "align": WD_ALIGN_PARAGRAPH.LEFT, "extra_spacing": False},
        {"bold": False, "align": WD_ALIGN_PARAGRAPH.LEFT, "extra_spacing": True},
        {"bold": False, "align": WD_ALIGN_PARAGRAPH.LEFT, "extra_spacing": False},
        {"bold": False, "align": WD_ALIGN_PARAGRAPH.LEFT, "extra_spacing": False},
    ]

    row_start_index = {}  # main_category -> 這張表裡的起始 row index（不含表頭）
    prev_main_category = None
    for r_idx, row in enumerate(rows):
        cells = table.add_row().cells
        values = _row_values(row)
        main_category = row.get("main_category", "")
        is_continuation = r_idx > 0 and prev_main_category == main_category

        for c_idx, value in enumerate(values):
            style = column_style[c_idx]
            
            if c_idx == 0 and is_continuation:
                continue
            _write_cell_paragraphs(
                cells[c_idx], value,
                size_pt=_BODY_FONT_SIZE, bold=style["bold"], align=style["align"],
                extra_paragraph_spacing=style["extra_spacing"],
            )

        table_row_idx = r_idx + 1  # +1 因為第 0 列是表頭
        if is_continuation:
            first_row_idx = row_start_index[main_category]
            first_cell = table.rows[first_row_idx].cells[0]
            this_cell = table.rows[table_row_idx].cells[0]
            first_cell.merge(this_cell)
        else:
            row_start_index[main_category] = table_row_idx

        prev_main_category = main_category

    for row in table.rows:
        for i, width in enumerate(col_widths):
            row.cells[i].width = width
    
    for i, width in enumerate(col_widths):
        table.columns[i].width = width

    return table


_RATING_STATS_COLUMN_HEADERS = ["題目", "平均分", "有效回答數", "0分", "1分", "2分", "3分", "4分", "5分"]
_RATING_STATS_COL_WIDTH_RATIOS = [0.34, 0.10, 0.12, 0.074, 0.074, 0.074, 0.074, 0.074, 0.074]


def _build_rating_stats_table(doc: Document, rating_stats: list, col_widths: list):
    """建立「評分題統計」表格：題目 / 平均分 / 有效回答數 / 0~5 分人數。

    只服務 build_docx() 的評分統計附加需求，重用既有純排版 helper
    （_write_cell_paragraphs／_set_cell_shading／_set_repeat_header_row／
    _set_table_fixed_layout），不跟 _build_classification_table() 共用
    任何分類結果專屬的欄位定義或合併儲存格邏輯。
    """
    table = doc.add_table(rows=1, cols=len(_RATING_STATS_COLUMN_HEADERS))
    table.style = "Table Grid"
    _set_table_fixed_layout(table)

    header_row = table.rows[0]
    for cell, header in zip(header_row.cells, _RATING_STATS_COLUMN_HEADERS):
        _write_cell_paragraphs(
            cell, header, size_pt=_HEADER_FONT_SIZE, bold=True,
            align=WD_ALIGN_PARAGRAPH.CENTER,
        )
        _set_cell_shading(cell, _HEADER_FILL)
    _set_repeat_header_row(header_row)

    for stat in rating_stats:
        distribution = stat.get("distribution") or {}
        question_number = stat.get("question_number")
        title_text = stat.get("title") or ""
        question_label = f"Q{question_number}：{title_text}" if question_number else title_text
        average = stat.get("average")
        average_text = str(average) if average is not None else "無資料"

        values = [question_label, average_text, str(stat.get("answered_count", 0))] + [
            str(distribution.get(str(score), 0)) for score in range(6)
        ]
        cells = table.add_row().cells
        for c_idx, value in enumerate(values):
            _write_cell_paragraphs(
                cells[c_idx], value, size_pt=_BODY_FONT_SIZE, bold=(c_idx == 0),
                align=WD_ALIGN_PARAGRAPH.LEFT if c_idx == 0 else WD_ALIGN_PARAGRAPH.CENTER,
            )

    for row in table.rows:
        for i, width in enumerate(col_widths):
            row.cells[i].width = width
    for i, width in enumerate(col_widths):
        table.columns[i].width = width

    return table


def build_docx(rows: list, title: str = "分類結果", rating_stats: list | None = None) -> bytes:
    """把 rows 產生成 .docx 檔案，回傳檔案的原始 bytes。

    如果 rows 帶有 source_column（Excel 上傳來源）或 question_id
    （問卷來源）這類「屬於哪一題」的中繼資料，且不只一種值，會依題目
    切成多張各自完整（各自有表頭）的表格，避免不同題目的分類結果被
    混在同一張表裡看不出界線。沒有這類中繼資料時（例如比較舊的匯出
    資料）維持原本「整批 rows 一張表」的行為。

    rating_stats 是【新增｜問卷 Chat 分析評分題統計】的可選參數，預設
    None，行為與呼叫端完全相容：
      - 不傳／傳 None／傳空陣列 []：不會多輸出任何段落或表格，既有
        分類結果輸出逐段落相同，既有呼叫端不受影響。
      - 傳非空陣列：在既有分類結果標題／表格**之前**，先輸出一段
        「評分題統計」標題＋表格，兩者之間用分頁隔開，不會把評分統計
        跟分類結果擠在同一頁。
    """
    doc = Document()

    
    section = doc.sections[0]
    section.orientation = WD_ORIENT.PORTRAIT
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.left_margin = Cm(1.5)
    section.right_margin = Cm(1.5)

    usable_width = section.page_width - section.left_margin - section.right_margin

    # 【新增｜評分題統計】只在有評分題統計時才輸出，放在既有分類結果
    # 之前；輸出完之後強制分頁，避免跟下面的分類結果標題擠在同一頁。
    if rating_stats:
        rating_heading = doc.add_heading("評分題統計", level=1)
        rating_heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for run in rating_heading.runs:
            _apply_docx_font(run, size_pt=run.font.size.pt if run.font.size else 18, bold=True)

        rating_col_widths = [Emu(int(usable_width * ratio)) for ratio in _RATING_STATS_COL_WIDTH_RATIOS]
        _build_rating_stats_table(doc, rating_stats, rating_col_widths)
        doc.add_page_break()

    heading = doc.add_heading(title or "分類結果", level=1)
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in heading.runs:
        _apply_docx_font(run, size_pt=run.font.size.pt if run.font.size else 18, bold=True)

    col_widths = [Emu(int(usable_width * ratio)) for ratio in _COLUMN_WIDTH_RATIOS]

    groups = _group_rows_by_question(rows)
    multiple_tables = len(groups) > 1

    for idx, (question_label, group_rows) in enumerate(groups):
        if multiple_tables:
            if idx > 0:
                doc.add_paragraph()
            subheading = doc.add_heading(question_label or f"題目 {idx + 1}", level=2)
            for run in subheading.runs:
                _apply_docx_font(run, size_pt=run.font.size.pt if run.font.size else 14, bold=True)

        _build_classification_table(doc, group_rows, col_widths)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ═══════════════════════════════════════════════════════════════
# 【新增｜問卷原始回覆匯出】build_survey_xlsx / build_survey_docx
#
# 這兩個函式跟上面 build_xlsx() / build_docx() 完全獨立，處理的是不同
# 語意、不同形狀的資料：
#   - build_xlsx / build_docx：AI 分類後的結果，固定 5 欄
#     （大類別/子類別/問卷回覆內容/判斷原因與說明/受試者建議摘要）。
#   - build_survey_xlsx / build_survey_docx：問卷「原始回覆」，
#     一位受試者一列（Excel）或一位受試者一個區塊（Word），
#     欄位數量依題目數量動態決定。
# 不共用資料形狀、不共用欄位定義，只共用純排版工具函式
# （_apply_docx_font / _set_cell_shading / _set_repeat_header_row /
#  _set_table_fixed_layout / _write_cell_paragraphs），
# 以上四個既有函式維持原樣未修改。
# ═══════════════════════════════════════════════════════════════

_SURVEY_TAIPEI_TZ = ZoneInfo("Asia/Taipei")

_SURVEY_HEADER_FILL = "D9D9D9"  # 淡灰底，跟分類結果 Word 表頭同色
_SURVEY_BODY_FONT_SIZE = 10
_SURVEY_HEADER_FONT_SIZE = 11
_SURVEY_COL_WIDTH_RATIOS = [0.32, 0.68]  # 題目欄 / 答案欄


def _survey_question_text(question) -> str:
    """題目文字：title 或 question_title 都要相容，兩套 key 在專案裡並存
    （例如 SurveyDetailPage.jsx 讀值也是 title || question_title）。"""
    if not isinstance(question, dict):
        return ""
    return str(question.get("title") or question.get("question_title") or "").strip()


def _survey_question_header(question, index: int) -> str:
    return f"Q{index}：{_survey_question_text(question)}"


def _survey_safe_rating_int(raw):
    """把 rating 答案安全轉成 0~5 的整數；轉不出來或超出範圍回傳 None
    （代表資料異常，呼叫端要有保底顯示，不能整份匯出因此壞掉）。

    刻意不用 bool：Python 的 bool 是 int 的子類別，True/False 轉出來會
    變成 1/0，混進 rating 分數裡會是很難查的資料錯誤。
    """
    if isinstance(raw, bool):
        return None
    try:
        if isinstance(raw, (int, float)):
            value = int(raw)
        else:
            value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    if 0 <= value <= 5:
        return value
    return None


def _survey_cell_value(question, answers: dict, *, for_excel: bool):
    """算出某一題、某位受試者的顯示值。

    【關鍵】「未作答」的判斷方式必須是 question_id 是否存在於 answers
    這個 dict 的 key 裡，不能用 `answers.get(qid) or "未作答"` 這種
    falsy fallback——rating 題答 0 分時，`0` 在 Python 是 falsy，
    這種寫法會把「答 0 分」誤判成「沒有作答」，是這次最需要避開的地雷。
    """
    if not isinstance(question, dict):
        return "未作答"
    qid = question.get("id")
    if not isinstance(answers, dict) or qid not in answers:
        return "未作答"

    raw = answers.get(qid)
    q_type = question.get("type")

    if q_type == "rating":
        rating_value = _survey_safe_rating_int(raw)
        if rating_value is None:
            # 資料異常保底（例如存進去的不是可辨識的 0~5 值）：
            # 不要讓一筆髒資料讓整份匯出直接失敗，原樣印出文字讓人事後
            # 查得出來，而不是靜默吃掉或報錯。
            return "" if raw is None else str(raw)
        # Excel 給數值（方便使用者算平均/排序），Word 一律用字串顯示。
        return rating_value if for_excel else str(rating_value)

    if isinstance(raw, (list, tuple)):
        return "、".join(str(item) for item in raw if item is not None)

    if raw is None:
        # key 存在但值是 null：不是「沒作答」，是「作答了但存了 null」，
        # 目前系統理論上不會有這種資料（前端未作答的題目 key 根本不會
        # 出現），這裡當保底處理，避免印出字面上的 "None"。
        return "未作答"

    return str(raw)


def _survey_format_submitted_at(dt) -> str:
    """把 submitted_at 轉成可讀的台灣時間字串。

    如果 dt 已經帶 timezone（正常情況下 taiwan_now() 存的就是
    tz-aware 的 Asia/Taipei 時間），用 astimezone() 正確轉換；如果讀出來
    是 naive datetime（部分資料庫 driver 讀回來會遺失 tzinfo），
    直接視為「本來就是台灣時間」補上 tzinfo，不能再手動 +8，
    不然遇到已經帶 tzinfo 的情況會被重複偏移。這個判斷方式比照
    routes/surveys/survey.py 裡 normalize_deadline() 既有的作法。
    """
    if dt is None:
        return ""
    if dt.tzinfo is not None:
        dt = dt.astimezone(_SURVEY_TAIPEI_TZ)
    else:
        dt = dt.replace(tzinfo=_SURVEY_TAIPEI_TZ)
    return dt.strftime("%Y/%m/%d %H:%M")


def _survey_respondent_label(response: dict, identity_mode: str, sequence_number: int) -> str:
    """decide「受試者」欄怎麼顯示。

    identified：直接用 respondent_identity；anonymous（或其他未知值，
    保守當匿名處理）：依 submitted_at 排序後的序號顯示「匿名受試者 N」，
    不能直接把 response_id 當受試者編號（response_id 會因為刪除/補資料
    等情境跳號，容易讓使用者誤以為資料不見了）。sequence_number 由
    呼叫端依 responses 目前的順序算出（呼叫端已經依 submitted_at
    asc 排序）。
    """
    if identity_mode == "identified":
        identity = str((response or {}).get("respondent_identity") or "").strip()
        return identity or "（未填寫身分）"
    return f"匿名受試者 {sequence_number}"


def build_survey_xlsx(*, title: str, questions: list, responses: list, identity_mode: str) -> bytes:
    """把問卷「原始回覆」產生成 .xlsx，wide format：一位受試者一列，
    欄位為「受試者 | 提交時間 | Q1：題目全文 | Q2：題目全文 | ...」。

    參數：
        questions: Survey_Template.question_json["items"]，維持原始
            順序，這裡不會、也不應該重新排序。
        responses: 已經依 submitted_at 由舊到新排序過的 list，每筆是
            {"answers": dict, "respondent_identity": str|None,
             "submitted_at": datetime|None}；排序責任在呼叫端
            （routes/surveys/survey.py 的匯出 API），這裡只負責排版。
        identity_mode: "anonymous" 或 "identified"。

    樣式沿用既有 build_xlsx() 的視覺規則（微軟正黑體、粗體白字表頭、
    紅底、細框線、wrap_text、凍結表頭列），但這是全新的表格形狀，
    不會、也不需要動到 build_xlsx() 本身一行程式碼。
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    sheet_title = (title or "問卷回覆").strip()[:31]  # Excel 分頁名稱上限 31 字元
    ws.title = sheet_title or "問卷回覆"

    header_font = Font(name="微軟正黑體", bold=True, color="FFFFFFFF")
    header_fill = PatternFill(start_color="FFF43F5E", end_color="FFF43F5E", fill_type="solid")
    body_font = Font(name="微軟正黑體")
    wrap_alignment = Alignment(wrap_text=True, vertical="top", horizontal="left")
    center_alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
    thin_border = Border(
        left=Side(style="thin", color="FF000000"),
        right=Side(style="thin", color="FF000000"),
        top=Side(style="thin", color="FF000000"),
        bottom=Side(style="thin", color="FF000000"),
    )

    questions = questions or []
    headers = ["受試者", "提交時間"] + [
        _survey_question_header(q, idx) for idx, q in enumerate(questions, start=1)
    ]
    for col_idx, header in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center_alignment
        cell.border = thin_border

    for row_idx, response in enumerate(responses or [], start=2):
        sequence_number = row_idx - 1
        answers = (response or {}).get("answers") or {}
        respondent_label = _survey_respondent_label(response, identity_mode, sequence_number)
        submitted_label = _survey_format_submitted_at((response or {}).get("submitted_at"))

        row_values = [respondent_label, submitted_label] + [
            _survey_cell_value(q, answers, for_excel=True) for q in questions
        ]
        for col_idx, value in enumerate(row_values, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.font = body_font
            cell.border = thin_border
            # rating 是數值時置中比較好讀，其餘欄位一律靠左並自動換行
            # （注意用 type 判斷、不是用 truthy 判斷，rating=0 也要置中）。
            is_numeric_rating = isinstance(value, int) and not isinstance(value, bool)
            cell.alignment = center_alignment if is_numeric_rating else wrap_alignment

    column_widths = [16, 18] + [32] * len(questions)
    for col_idx, width in enumerate(column_widths, start=1):
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    ws.freeze_panes = "A2"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_survey_docx(*, title: str, questions: list, responses: list, identity_mode: str) -> bytes:
    """把問卷「原始回覆」產生成 .docx，採「一位受試者一區塊」：

        受試者：王小明
        提交時間：2026/09/20 13:30
        ┌────────────────────┬──────┐
        │ 題目                │ 答案 │
        ├────────────────────┼──────┤
        │ Q1：課程整體滿意度   │ 5    │
        └────────────────────┴──────┘

    刻意不做「每題一欄」的橫向大表：題目一多，橫向表格在 Word
    頁面寬度下欄位會被壓到無法閱讀。跨頁行為維持 python-docx 預設
    （不對 row 設定 cantSplit、不對段落設定 keep-with-next），
    所以單一受試者的回答內容較長、跨頁時可以自然分頁，不會被強制
    整塊塞在同一頁。
    """
    doc = Document()

    section = doc.sections[0]
    section.orientation = WD_ORIENT.PORTRAIT
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.left_margin = Cm(1.5)
    section.right_margin = Cm(1.5)

    heading = doc.add_heading(title or "問卷回覆", level=1)
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in heading.runs:
        _apply_docx_font(run, size_pt=run.font.size.pt if run.font.size else 18, bold=True)

    usable_width = section.page_width - section.left_margin - section.right_margin
    col_widths = [Emu(int(usable_width * ratio)) for ratio in _SURVEY_COL_WIDTH_RATIOS]

    questions = questions or []
    question_headers = [
        _survey_question_header(q, idx) for idx, q in enumerate(questions, start=1)
    ]

    for idx, response in enumerate(responses or [], start=1):
        answers = (response or {}).get("answers") or {}
        respondent_label = _survey_respondent_label(response, identity_mode, idx)
        submitted_label = _survey_format_submitted_at((response or {}).get("submitted_at"))

        info_paragraph = doc.add_paragraph()
        # 每位受試者之間留明顯間距：不是第一位時，段落上緣多留一段空間，
        # 比單純插入空白段落更好控制精確間距、也不會在文件最上方多一段
        # 看起來像排版錯誤的空白。
        info_paragraph.paragraph_format.space_before = Pt(18) if idx > 1 else Pt(6)
        info_paragraph.paragraph_format.space_after = Pt(2)
        info_run = info_paragraph.add_run(f"受試者：{respondent_label}")
        _apply_docx_font(info_run, size_pt=12, bold=True)

        time_paragraph = doc.add_paragraph()
        time_paragraph.paragraph_format.space_after = Pt(6)
        time_run = time_paragraph.add_run(f"提交時間：{submitted_label}")
        _apply_docx_font(time_run, size_pt=10, bold=False)

        table = doc.add_table(rows=1, cols=2)
        table.style = "Table Grid"
        _set_table_fixed_layout(table)

        header_row = table.rows[0]
        for cell, text in zip(header_row.cells, ["題目", "答案"]):
            _write_cell_paragraphs(
                cell, text, size_pt=_SURVEY_HEADER_FONT_SIZE, bold=True,
                align=WD_ALIGN_PARAGRAPH.CENTER,
            )
            _set_cell_shading(cell, _SURVEY_HEADER_FILL)
        _set_repeat_header_row(header_row)

        for q_header, question in zip(question_headers, questions):
            row_cells = table.add_row().cells
            _write_cell_paragraphs(
                row_cells[0], q_header, size_pt=_SURVEY_BODY_FONT_SIZE, bold=True,
                align=WD_ALIGN_PARAGRAPH.LEFT,
            )
            answer_value = _survey_cell_value(question, answers, for_excel=False)
            _write_cell_paragraphs(
                row_cells[1], str(answer_value), size_pt=_SURVEY_BODY_FONT_SIZE, bold=False,
                align=WD_ALIGN_PARAGRAPH.LEFT,
            )

        for row in table.rows:
            for col_idx, width in enumerate(col_widths):
                row.cells[col_idx].width = width
        for col_idx, width in enumerate(col_widths):
            table.columns[col_idx].width = width

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()