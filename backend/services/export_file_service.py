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


def build_xlsx(rows: list, title: str = "分類結果") -> bytes:
    """把 rows 產生成 .xlsx 檔案，回傳檔案的原始 bytes。"""
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

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


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


def build_docx(rows: list, title: str = "分類結果") -> bytes:
    """把 rows 產生成 .docx 檔案，回傳檔案的原始 bytes。

    如果 rows 帶有 source_column（Excel 上傳來源）或 question_id
    （問卷來源）這類「屬於哪一題」的中繼資料，且不只一種值，會依題目
    切成多張各自完整（各自有表頭）的表格，避免不同題目的分類結果被
    混在同一張表裡看不出界線。沒有這類中繼資料時（例如比較舊的匯出
    資料）維持原本「整批 rows 一張表」的行為。
    """
    doc = Document()

    
    section = doc.sections[0]
    section.orientation = WD_ORIENT.PORTRAIT
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.left_margin = Cm(1.5)
    section.right_margin = Cm(1.5)

    heading = doc.add_heading(title or "分類結果", level=1)
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in heading.runs:
        _apply_docx_font(run, size_pt=run.font.size.pt if run.font.size else 18, bold=True)

    usable_width = section.page_width - section.left_margin - section.right_margin
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