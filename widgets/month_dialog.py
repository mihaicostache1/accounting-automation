"""Modal dialog shown when a month cell is clicked.

Two color-coded buttons — "Declarație" and "Recipisă" — open the stored PDF
with the system viewer. Each document also has a "…" menu to attach/replace
the PDF or flip the submitted flag. `self.changed` tells the caller whether
the tabs need a refresh.
"""

from __future__ import annotations

import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QLabel, QMenu,
                               QMessageBox, QPushButton, QToolButton, QVBoxLayout)

import database
import file_manager
from config import MONTHS_LONG
from theme import repolish

# (attribute prefix in the DB row, user-facing label)
DOC_KINDS = [("declaratie", "Declarație"), ("recipisa", "Recipisă")]
DB_FIELDS = {"declaratie": ("status_declaratie", "path_declaratie"),
             "recipisa": ("status_recipisa", "path_recipisa")}


class MonthDialog(QDialog):
    def __init__(self, firma: sqlite3.Row, tip: str, an: int, luna: int, parent=None):
        super().__init__(parent)
        self.firma = firma
        self.tip = tip
        self.an = an
        self.luna = luna
        self.changed = False  # caller refreshes the matrices when True

        self.setWindowTitle(f"{firma['nume_firma']} — {tip} — {MONTHS_LONG[luna - 1]} {an}")
        self.setModal(True)
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        header = QLabel(f"{tip}  ·  {MONTHS_LONG[luna - 1]} {an}")
        header.setProperty("role", "section-title")
        layout.addWidget(header)

        self.doc_buttons: dict[str, QPushButton] = {}
        for kind, label in DOC_KINDS:
            row = QHBoxLayout()
            row.setSpacing(6)

            btn = QPushButton(label)
            btn.setMinimumHeight(48)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, k=kind: self._open_document(k))
            self.doc_buttons[kind] = btn
            row.addWidget(btn, stretch=1)

            more = QToolButton()
            more.setText("…")
            more.setFixedSize(48, 48)
            more.setCursor(Qt.CursorShape.PointingHandCursor)
            more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            more.setMenu(self._build_menu(kind, label))
            row.addWidget(more)

            layout.addLayout(row)

        close_btn = QPushButton("Închide")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignRight)

        self._refresh()

    # ------------------------------------------------------------------ state

    def _current(self, kind: str) -> tuple[bool, str | None]:
        """(submitted, stored_path) for one document kind, from the DB."""
        row = database.get_status(self.firma["id"], self.tip, self.an, self.luna)
        status_col, path_col = DB_FIELDS[kind]
        if row is None:
            return False, None
        return bool(row[status_col]), row[path_col]

    def _refresh(self) -> None:
        for kind, label in DOC_KINDS:
            submitted, _ = self._current(kind)
            btn = self.doc_buttons[kind]
            btn.setText(f"{label}  —  {'Depusă' if submitted else 'Lipsă'}")
            btn.setProperty("status", "ok" if submitted else "missing")
            repolish(btn)

    # ---------------------------------------------------------------- actions

    def _build_menu(self, kind: str, label: str) -> QMenu:
        menu = QMenu(self)
        menu.addAction(f"Atașează / înlocuiește PDF ({label})",
                       lambda: self._attach_pdf(kind))
        menu.addAction("Comută status depus / nedepus",
                       lambda: self._toggle_status(kind))
        return menu

    def _open_document(self, kind: str) -> None:
        submitted, path = self._current(kind)
        if path and file_manager.open_pdf(path):
            return
        if submitted and path:
            msg = "Fișierul PDF nu a fost găsit pe disc. Atașezi altul?"
        else:
            msg = "Nu există un PDF atașat. Atașezi unul acum?"
        answer = QMessageBox.question(self, "Fișier indisponibil", msg)
        if answer == QMessageBox.StandardButton.Yes:
            self._attach_pdf(kind)

    def _attach_pdf(self, kind: str) -> None:
        source, _ = QFileDialog.getOpenFileName(
            self, "Alege fișierul PDF", "", "Fișiere PDF (*.pdf)")
        if not source:
            return
        rel = file_manager.import_pdf(source, self.firma["cui"], self.an,
                                      self.luna, self.tip, kind)
        status_col, path_col = DB_FIELDS[kind]
        database.update_status_fields(self.firma["id"], self.tip, self.an, self.luna,
                                      **{status_col: 1, path_col: str(rel)})
        self.changed = True
        self._refresh()

    def _toggle_status(self, kind: str) -> None:
        submitted, _ = self._current(kind)
        status_col, _ = DB_FIELDS[kind]
        database.update_status_fields(self.firma["id"], self.tip, self.an, self.luna,
                                      **{status_col: 0 if submitted else 1})
        self.changed = True
        self._refresh()
