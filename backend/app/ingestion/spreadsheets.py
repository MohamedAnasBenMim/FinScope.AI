import csv
import io
from datetime import date, datetime
from pathlib import Path

import openpyxl
import xlrd
from app.config import Settings
from app.errors import ParsingFailed
from app.ingestion.normalized import NormalizedBlock, table_markdown
from app.ingestion.validation import decode_text
from openpyxl.utils import get_column_letter


def cell_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def sheet_blocks(
    rows: list[list[str]], sheet: str, formulas: dict[str, str], config: Settings
) -> list[NormalizedBlock]:
    """Split only at blank rows; retain original Excel coordinates including blank columns."""
    blocks = []
    group = []
    start = 1

    def emit():
        if not group:
            return
        end = start + len(group) - 1
        width = max(map(len, group))
        cell_range = f"A{start}:{get_column_letter(width)}{end}"
        relevant_formulas = {
            k: v
            for k, v in formulas.items()
            if start <= openpyxl.utils.cell.coordinate_from_string(k)[1] <= end
        }
        blocks.append(
            NormalizedBlock(
                type="spreadsheet",
                text=table_markdown(group),
                sheet_name=sheet,
                section=sheet,
                table_id=f"{sheet}:{start}",
                cell_range=cell_range,
                metadata={
                    "rows": list(group),
                    "row_start": start,
                    "column_start": 1,
                    "formulas": relevant_formulas,
                    "header_rows": 1 if len(group) > 1 else 0,
                },
            )
        )

    for number, row in enumerate(rows, 1):
        if any(v.strip() for v in row):
            if not group:
                start = number
            group.append(row)
            if len(group) >= config.TABLE_CHUNK_ROWS * 10:
                emit()
                group = []
        else:
            emit()
            group = []
    emit()
    return blocks


def parse_spreadsheet(path: Path, extension: str, config: Settings) -> list[NormalizedBlock]:
    blocks = []
    total_cells = 0
    if extension == ".xlsx":
        values = openpyxl.load_workbook(path, data_only=True, read_only=True, keep_links=False)
        formulas_book = openpyxl.load_workbook(path, data_only=False, read_only=True, keep_links=False)
        try:
            for sheet in values:
                total_cells += (sheet.max_row or 0) * (sheet.max_column or 0)
                if total_cells > config.MAX_SPREADSHEET_CELLS:
                    raise ParsingFailed("Workbook exceeds MAX_SPREADSHEET_CELLS.")
                formulas = {
                    cell.coordinate: str(cell.value)
                    for row in formulas_book[sheet.title]
                    for cell in row
                    if cell.data_type == "f"
                }
                rows = []
                for row in sheet:
                    rows.append(
                        [
                            cell_value(cell.value)
                            if cell.value is not None
                            else (
                                f"[formula: {formulas[cell.coordinate]}; cached value unavailable]"
                                if getattr(cell, "coordinate", "") in formulas
                                else ""
                            )
                            for cell in row
                        ]
                    )
                blocks.extend(sheet_blocks(rows, sheet.title, formulas, config))
        finally:
            values.close()
            formulas_book.close()
    elif extension == ".xls":
        with xlrd.open_workbook(str(path), on_demand=True) as workbook:
            for sheet in workbook.sheets():
                total_cells += sheet.nrows * sheet.ncols
                if total_cells > config.MAX_SPREADSHEET_CELLS:
                    raise ParsingFailed("Workbook exceeds MAX_SPREADSHEET_CELLS.")
                rows = []
                for r in range(sheet.nrows):
                    rows.append(
                        [
                            cell_value(xlrd.xldate_as_datetime(c.value, workbook.datemode))
                            if c.ctype == xlrd.XL_CELL_DATE
                            else cell_value(c.value)
                            for c in sheet.row(r)
                        ]
                    )
                blocks.extend(sheet_blocks(rows, sheet.name, {}, config))
    else:
        text = decode_text(path.read_bytes())
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
        rows = list(csv.reader(io.StringIO(text), dialect))
        if sum(map(len, rows)) > config.MAX_SPREADSHEET_CELLS:
            raise ParsingFailed("CSV exceeds MAX_SPREADSHEET_CELLS.")
        blocks = sheet_blocks(rows, "CSV", {}, config)
    return blocks
