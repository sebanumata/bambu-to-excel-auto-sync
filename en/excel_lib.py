"""Shared logic for building/updating prints_log.xlsx from a list of print records."""
import json
from datetime import datetime, date
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

HEADER_FILL = "1F4E78"
STATUS_FILL = {
    "Success": "C6EFCE",
    "Cancelled": "FFC7CE",
    "Printing": "FFEB9C",
}
STATUS_FONT_COLOR = {
    "Success": "006100",
    "Cancelled": "9C0006",
    "Printing": "9C6500",
}


def load_records(json_path: Path) -> list[dict]:
    if not json_path.exists():
        return []
    with open(json_path, encoding="utf-8") as f:
        raw = json.load(f)
    for r in raw:
        r["dt"] = datetime.fromisoformat(r["dt"])
    return raw


def save_records(records: list[dict], json_path: Path) -> None:
    serializable = []
    for r in records:
        r2 = dict(r)
        r2["dt"] = r["dt"].isoformat()
        serializable.append(r2)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2)


def format_hours(hours: float) -> str:
    if hours < 1:
        return f"{round(hours * 60)}min"
    return f"{round(hours, 1)}h"


def duration_to_hours(s: str) -> float:
    s = str(s).strip()
    if s.endswith("h"):
        return float(s[:-1])
    if s.endswith("min"):
        return float(s[:-3]) / 60
    if s.endswith("s"):
        return float(s[:-1]) / 3600
    raise ValueError(f"unrecognized duration: {s!r}")


def _write_data_row(ws, row: int, idx: int, r: dict, border: Border) -> None:
    ws.cell(row=row, column=1, value=idx)
    ws.cell(row=row, column=2, value=r["dt"].date())
    ws.cell(row=row, column=2).number_format = "DD/MM/YYYY"
    ws.cell(row=row, column=3, value=r["dt"].strftime("%H:%M"))
    ws.cell(row=row, column=4, value=r["archivo"])
    ws.cell(row=row, column=5, value=r["duracion"])
    ws.cell(row=row, column=6, value=r["impresora"])
    ws.cell(row=row, column=7, value=r["placa"])
    ecell = ws.cell(row=row, column=8, value=r["estado"])

    fill_hex = STATUS_FILL.get(r["estado"])
    font_hex = STATUS_FONT_COLOR.get(r["estado"])
    if fill_hex:
        ecell.fill = PatternFill(start_color=fill_hex, end_color=fill_hex, fill_type="solid")
    ecell.font = Font(name="Arial", color=font_hex) if font_hex else Font(name="Arial")

    for col in range(1, 9):
        cell = ws.cell(row=row, column=col)
        cell.border = border
        if col != 8:
            cell.font = Font(name="Arial")
        if col in (1, 2, 3, 7):
            cell.alignment = Alignment(horizontal="center")


def rebuild_excel(records: list[dict], xlsx_path: Path) -> None:
    """Full rewrite from scratch. Only use for manual/one-off fixes — the live
    sync service should use append_missing_records() instead, since this wipes
    any edits the user made directly in the spreadsheet."""
    records = sorted(records, key=lambda r: r["dt"])

    wb = Workbook()
    ws = wb.active
    ws.title = "Prints"

    headers = ["#", "Date", "Time", "File", "Duration", "Printer", "Plate", "Status"]
    ws.append(headers)

    header_font = Font(name="Arial", bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color=HEADER_FILL, end_color=HEADER_FILL, fill_type="solid")
    header_align = Alignment(horizontal="center", vertical="center")
    thin = Side(style="thin", color="D9D9D9")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    for col in range(1, len(headers) + 1):
        c = ws.cell(row=1, column=col)
        c.font = header_font
        c.fill = header_fill
        c.alignment = header_align
        c.border = border

    for idx, r in enumerate(records, start=1):
        _write_data_row(ws, idx + 1, idx, r, border)

    widths = {1: 6, 2: 12, 3: 8, 4: 55, 5: 10, 6: 16, 7: 9, 8: 13}
    for col, w in widths.items():
        ws.column_dimensions[get_column_letter(col)].width = w

    n = len(records)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:H{n + 1}"

    ws2 = wb.create_sheet("Summary")
    ws2["A1"] = "Print Summary"
    ws2["A1"].font = Font(name="Arial", bold=True, size=14)

    ws2["A3"] = "Status"
    ws2["B3"] = "Count"
    ws2["C3"] = "%"
    for c in ("A3", "B3", "C3"):
        ws2[c].font = Font(name="Arial", bold=True, color="FFFFFF")
        ws2[c].fill = header_fill
        ws2[c].alignment = header_align

    # Whole-column ranges so future rows (added by the sync service) never
    # require these formulas to be touched again.
    ws2["A4"] = "Success"
    ws2["B4"] = '=COUNTIF(Prints!H:H,"Success")'
    ws2["A5"] = "Cancelled"
    ws2["B5"] = '=COUNTIF(Prints!H:H,"Cancelled")'
    ws2["A6"] = "Printing"
    ws2["B6"] = '=COUNTIF(Prints!H:H,"Printing")'
    ws2["A7"] = "Total"
    ws2["B7"] = "=SUM(B4:B6)"
    ws2["A7"].font = Font(name="Arial", bold=True)
    ws2["B7"].font = Font(name="Arial", bold=True)

    for row in range(4, 7):
        ws2.cell(row=row, column=3, value=f"=B{row}/$B$7")
        ws2.cell(row=row, column=3).number_format = "0.0%"

    ws2["A9"] = "First print:"
    ws2["B9"] = "=MIN(Prints!B:B)"
    ws2["B9"].number_format = "DD/MM/YYYY"
    ws2["A10"] = "Last print:"
    ws2["B10"] = "=MAX(Prints!B:B)"
    ws2["B10"].number_format = "DD/MM/YYYY"
    ws2["A11"] = "Total prints:"
    ws2["B11"] = "=COUNTA(Prints!A:A)-1"
    ws2["A13"] = "Last sync:"
    ws2["B13"] = datetime.now().strftime("%d/%m/%Y %H:%M")

    for row in ws2.iter_rows(min_row=4, max_row=13, min_col=1, max_col=3):
        for cell in row:
            if cell.font.name != "Arial":
                cell.font = Font(name="Arial", bold=cell.font.bold)

    ws2.column_dimensions["A"].width = 22
    ws2.column_dimensions["B"].width = 14
    ws2.column_dimensions["C"].width = 10

    wb.save(xlsx_path)


def _last_data_row(ws) -> int:
    """ws.max_row can overshoot the real data (Excel extends the 'used range'
    just from clicking/selecting cells, even with nothing typed in them), so
    scan for the last row that actually has a value in the File column."""
    for row in range(ws.max_row, 1, -1):
        if ws.cell(row=row, column=4).value not in (None, ""):
            return row
    return 1  # only the header


def append_missing_records(records: list[dict], xlsx_path: Path) -> int:
    """Append only the records not yet present in the sheet, leaving every
    existing row (including anything the user edited by hand) untouched.
    Records must be in the same chronological order they were saved in
    records.json. Returns how many rows were added."""
    records = sorted(records, key=lambda r: r["dt"])

    if not xlsx_path.exists():
        rebuild_excel(records, xlsx_path)
        return len(records)

    wb = load_workbook(xlsx_path)
    ws = wb["Prints"]
    last_row = _last_data_row(ws)
    existing_data_rows = max(last_row - 1, 0)  # exclude header
    missing = records[existing_data_rows:]

    if not missing:
        wb.close()
        return 0

    # Trim any trailing blank rows Excel's "used range" picked up from mere
    # clicks/selections, so we append right after the real last row.
    if ws.max_row > last_row:
        ws.delete_rows(last_row + 1, ws.max_row - last_row)

    thin = Side(style="thin", color="D9D9D9")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    row = last_row + 1
    idx = existing_data_rows + 1
    for r in missing:
        _write_data_row(ws, row, idx, r, border)
        row += 1
        idx += 1

    ws.auto_filter.ref = f"A1:H{ws.max_row}"

    if "Summary" in wb.sheetnames:
        wb["Summary"]["B13"] = datetime.now().strftime("%d/%m/%Y %H:%M")

    wb.save(xlsx_path)
    return len(missing)
