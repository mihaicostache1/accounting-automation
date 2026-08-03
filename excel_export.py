"""Build the Excel report of submitted declarations and their ANAF verdicts.

One row per declaration: which firm, which month, which type, the upload index
and what ANAF said about it. The same layout serves a single month and a whole
year — the year report simply spans all twelve.

The verdict column is color-coded with the same meaning the app uses on screen
(green = valid, amber = needs attention, red = missing receipt), so a printed
report reads like the matrices it came from.
"""

from __future__ import annotations

from pathlib import Path

import anaf_client
from config import MONTHS_LONG
from theme import GREEN, RED, YELLOW

HEADERS = ["Firmă", "CUI", "An", "Luna", "Declarație", "Index încărcare",
           "Stare recipisă"]

# Widths in Excel character units, in HEADERS order.
_WIDTHS = [34, 14, 7, 12, 12, 20, 42]

_HEADER_BG = "1F2430"
_HEADER_FG = "FFFFFF"


def _verdict(row) -> tuple[str, str | None]:
    """(text, hex fill) for the state column.

    Falls back to describing what is known when ANAF was never asked, so the
    cell never sits empty and unexplained.
    """
    stare = row["stare_validare"]
    if stare:
        label = anaf_client.STARE_LABELS.get(stare, stare)
        if stare == anaf_client.STARE_VALID:
            return label, GREEN.lstrip("#")
        if anaf_client.are_erori(stare):
            return label, YELLOW.lstrip("#")
        return label, None
    if row["status_recipisa"]:
        return "Recipisă descărcată (neverificată)", None
    if row["index_incarcare"]:
        return "Neverificată", None
    return "Fără index de încărcare", RED.lstrip("#")


def build_report(rows: list, an: int, luna: int | None) -> "Workbook":  # noqa: F821
    """Workbook for the given rows. `luna=None` means the whole year."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = (f"{MONTHS_LONG[luna - 1]} {an}" if luna else f"Anul {an}")[:31]

    ws.append(HEADERS)
    header_font = Font(bold=True, color=_HEADER_FG)
    header_fill = PatternFill("solid", fgColor=_HEADER_BG)
    for col, width in enumerate(_WIDTHS, start=1):
        cell = ws.cell(row=1, column=col)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(vertical="center")
        ws.column_dimensions[get_column_letter(col)].width = width

    for row in rows:
        text, fill = _verdict(row)
        ws.append([row["nume_firma"], row["cui"], row["an"],
                   MONTHS_LONG[row["luna"] - 1], row["tip_declaratie"],
                   # Excel would turn a 10-digit index into a number in
                   # scientific notation; it is an identifier, keep it text.
                   str(row["index_incarcare"] or ""), text])
        if fill:
            ws.cell(row=ws.max_row, column=len(HEADERS)).fill = PatternFill(
                "solid", fgColor=fill)

    for excel_row in range(2, ws.max_row + 1):
        ws.cell(row=excel_row, column=6).alignment = Alignment(horizontal="left")

    # Keep the header visible and let the user filter/sort the report.
    ws.freeze_panes = "A2"
    if ws.max_row > 1:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(HEADERS))}{ws.max_row}"
    return wb


def save_report(path: Path | str, rows: list, an: int, luna: int | None) -> Path:
    path = Path(path)
    if path.suffix.lower() != ".xlsx":
        path = path.with_suffix(".xlsx")
    build_report(rows, an, luna).save(path)
    return path


def default_filename(an: int, luna: int | None) -> str:
    if luna:
        return f"Raport_declaratii_{an}_{luna:02d}.xlsx"
    return f"Raport_declaratii_{an}.xlsx"
