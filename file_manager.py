"""File-system helpers: organized folder layout, importing PDFs, opening PDFs.

Layout on disk (relative to the configurable base folder):
    [Base]/[CUI]/[An]/[Luna 2-digit]/[Tip_Declaratie]/declaratie.pdf
    [Base]/[CUI]/[An]/[Luna 2-digit]/[Tip_Declaratie]/recipisa.pdf
"""

from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

import database
from config import type_folder_name

# Canonical file names inside each month/type folder.
DOC_FILENAMES = {"declaratie": "declaratie.pdf", "recipisa": "recipisa.pdf"}


def relative_doc_path(cui: str, an: int, luna: int, tip: str, doc_kind: str) -> Path:
    """Relative path (from the base folder) for a declaration or receipt PDF."""
    return (Path(cui) / str(an) / f"{luna:02d}" / type_folder_name(tip)
            / DOC_FILENAMES[doc_kind])


def to_absolute(stored_path: str) -> Path:
    """Resolve a DB path (relative to base folder, or already absolute)."""
    p = Path(stored_path)
    return p if p.is_absolute() else database.get_base_folder() / p


def import_pdf(source: str | Path, cui: str, an: int, luna: int, tip: str,
               doc_kind: str) -> Path:
    """Copy a user-picked PDF into the organized structure.

    Returns the RELATIVE path to store in the database.
    """
    rel = relative_doc_path(cui, an, luna, tip, doc_kind)
    dest = database.get_base_folder() / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)
    return rel


def open_pdf(stored_path: str) -> bool:
    """Open a stored PDF with the system's default viewer.

    Returns False if the file is missing on disk (caller shows the message).
    """
    abs_path = to_absolute(stored_path)
    if not abs_path.is_file():
        return False
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(abs_path)))
