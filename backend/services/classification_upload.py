"""Read supported analysis uploads before any AI or database work."""
from io import BytesIO
from pathlib import Path

MAX_UPLOAD_BYTES = 2 * 1024 * 1024
ALLOWED_EXTENSIONS = {".xlsx", ".xls", ".docx"}


class UploadValidationError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def read_analysis_upload(file):
    extension = Path(file.filename or "").suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise UploadValidationError("僅支援 Excel（.xlsx、.xls）或 Word（.docx）檔案。")
    content = file.stream.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise UploadValidationError("檔案大小不可超過 2MB。", 413)
    try:
        import pandas as pd
        if extension != ".docx":
            return pd.read_excel(BytesIO(content))
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        document = Document(BytesIO(content))
        answers = []
        for block in document.iter_inner_content():
            if isinstance(block, Paragraph):
                if block.text.strip():
                    answers.append(block.text.strip())
            elif isinstance(block, Table):
                for row in block.rows:
                    text = " · ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                    if text:
                        answers.append(text)
        if not answers:
            raise UploadValidationError("Word 檔案沒有可分析的文字內容。")
        return pd.DataFrame({"Word": answers})
    except UploadValidationError:
        raise
    except Exception as error:
        raise UploadValidationError("無法讀取檔案，請確認檔案格式正確且未加密。") from error
