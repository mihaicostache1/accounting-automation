"""Modal dialog shown when a month cell is clicked.

Two color-coded buttons — "Declarație" and "Recipisă" — open the stored PDF
with the system viewer. Each document also has a "…" menu to attach/replace
the PDF or flip the submitted flag. `self.changed` tells the caller whether
the tabs need a refresh.
"""

from __future__ import annotations

import sqlite3

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QLabel,
                               QLineEdit, QMenu, QMessageBox, QPushButton,
                               QToolButton, QVBoxLayout)

import anaf_client
import database
import file_manager
from anaf_service import CellJob, RecipisaWorker
from config import MONTHS_LONG
from theme import GREEN, RED, repolish

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

        # -- ANAF: index de încărcare + verificare recipisă ---------------- #
        anaf_title = QLabel("ANAF — verificare recipisă")
        anaf_title.setProperty("role", "section-title")
        layout.addWidget(anaf_title)

        index_row = QHBoxLayout()
        index_row.setSpacing(6)
        index_row.addWidget(QLabel("Index încărcare:"))
        self.index_edit = QLineEdit()
        self.index_edit.setPlaceholderText("ex. 1179071386")
        self.index_edit.editingFinished.connect(self._save_index)
        index_row.addWidget(self.index_edit, stretch=1)
        layout.addLayout(index_row)

        self.stare_label = QLabel("")
        self.stare_label.setWordWrap(True)
        layout.addWidget(self.stare_label)

        anaf_row = QHBoxLayout()
        anaf_row.setSpacing(6)
        self.check_btn = QPushButton("🔄  Verifică și descarcă recipisa")
        self.check_btn.setProperty("variant", "primary")
        self.check_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.check_btn.clicked.connect(self._check_recipisa)
        anaf_row.addWidget(self.check_btn, stretch=1)

        folder_btn = QPushButton("📁  Deschide folderul")
        folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        folder_btn.clicked.connect(self._open_folder)
        anaf_row.addWidget(folder_btn)
        layout.addLayout(anaf_row)

        close_btn = QPushButton("Închide")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignRight)

        self._worker: RecipisaWorker | None = None
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

        row = database.get_status(self.firma["id"], self.tip, self.an, self.luna)
        index = (row["index_incarcare"] or "") if row else ""
        stare = row["stare_validare"] if row else None
        if not self.index_edit.hasFocus():
            self.index_edit.setText(index)
        if stare:
            label = anaf_client.STARE_LABELS.get(stare, stare)
            color = {anaf_client.STARE_VALID: GREEN,
                     anaf_client.STARE_ERORI: RED,
                     anaf_client.STARE_INVALID: RED}.get(stare, "#8a6d1a")
            self.stare_label.setText(f"Stare validare: {label}")
            self.stare_label.setStyleSheet(f"color: {color}; font-weight: 600;")
        else:
            self.stare_label.setText("Stare validare: neverificată")
            self.stare_label.setStyleSheet("color: #8a93a0;")

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

    # ----------------------------------------------------------------- ANAF

    def _save_index(self) -> None:
        row = database.get_status(self.firma["id"], self.tip, self.an, self.luna)
        stored = (row["index_incarcare"] or "") if row else ""
        typed = self.index_edit.text().strip()
        if typed != stored:
            database.update_status_fields(self.firma["id"], self.tip, self.an,
                                          self.luna, index_incarcare=typed)
            self.changed = True

    def _check_recipisa(self) -> None:
        self._save_index()
        index = self.index_edit.text().strip()
        if not index:
            QMessageBox.information(
                self, "Index lipsă",
                "Introduceți indexul de încărcare primit la depunerea "
                "declarației pe decl.anaf.mfinante.gov.ro.")
            return
        job = CellJob(self.firma["id"], self.firma["cui"], self.firma["nume_firma"],
                      self.tip, self.an, self.luna, index)
        self.check_btn.setEnabled(False)
        self.check_btn.setText("Se verifică la ANAF…")
        self._worker = RecipisaWorker([job], parent=self)
        self._worker.completed.connect(self._on_check_done)
        self._worker.start()

    def _on_check_done(self, outcomes: list) -> None:
        self.check_btn.setEnabled(True)
        self.check_btn.setText("🔄  Verifică și descarcă recipisa")
        self.changed = True
        self._refresh()
        outcome = outcomes[0]
        if outcome.ok:
            QMessageBox.information(self, "Rezultat ANAF", outcome.message)
        else:
            QMessageBox.warning(self, "Verificare eșuată", outcome.message)

    def _open_folder(self) -> None:
        folder = (database.get_base_folder() / file_manager.relative_doc_path(
            self.firma["cui"], self.an, self.luna, self.tip, "recipisa")).parent
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _toggle_status(self, kind: str) -> None:
        submitted, _ = self._current(kind)
        status_col, _ = DB_FIELDS[kind]
        database.update_status_fields(self.firma["id"], self.tip, self.an, self.luna,
                                      **{status_col: 0 if submitted else 1})
        self.changed = True
        self._refresh()
