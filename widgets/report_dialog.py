"""Pick a period and write the Excel report for it.

One month or a whole year — the same choice the overview tab offers, plus a
live count so the user sees whether the period actually holds anything before
producing an empty file.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QHBoxLayout,
                               QLabel, QMessageBox, QPushButton, QVBoxLayout)

import database
import excel_export
from config import MONTHS_LONG, YEARS


class ReportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Raport Excel")
        self.setModal(True)
        self.setMinimumWidth(430)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        title = QLabel("Generează raport declarații")
        title.setProperty("role", "section-title")
        layout.addWidget(title)

        info = QLabel("Raportul conține, pentru fiecare declarație depusă: "
                      "firma, luna, tipul declarației, indexul de încărcare și "
                      "starea recipisei primite de la ANAF.")
        info.setWordWrap(True)
        layout.addWidget(info)

        period = QHBoxLayout()
        period.setSpacing(8)
        period.addWidget(QLabel("Anul:"))
        self.year_combo = QComboBox()
        years = sorted({*YEARS, date.today().year})
        for year in years:
            self.year_combo.addItem(str(year), year)
        self.year_combo.setCurrentIndex(
            max(0, self.year_combo.findData(date.today().year)))
        self.year_combo.currentIndexChanged.connect(self._refresh_count)
        period.addWidget(self.year_combo)

        period.addWidget(QLabel("Perioada:"))
        self.month_combo = QComboBox()
        self.month_combo.addItem("Tot anul", None)
        for idx, name in enumerate(MONTHS_LONG, start=1):
            self.month_combo.addItem(name, idx)
        self.month_combo.currentIndexChanged.connect(self._refresh_count)
        period.addWidget(self.month_combo, stretch=1)
        layout.addLayout(period)

        self.count_label = QLabel("")
        self.count_label.setWordWrap(True)
        layout.addWidget(self.count_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close_btn = QPushButton("Închide")
        close_btn.clicked.connect(self.reject)
        buttons.addWidget(close_btn)
        self.save_btn = QPushButton("📊  Salvează raportul")
        self.save_btn.setProperty("variant", "primary")
        self.save_btn.clicked.connect(self._save)
        buttons.addWidget(self.save_btn)
        layout.addLayout(buttons)

        self._refresh_count()

    def _selection(self) -> tuple[int, int | None]:
        return self.year_combo.currentData(), self.month_combo.currentData()

    def _rows(self) -> list:
        an, luna = self._selection()
        return database.list_report_rows(an, luna)

    def _refresh_count(self) -> None:
        rows = self._rows()
        firms = len({r["nume_firma"] for r in rows})
        self.count_label.setText(
            f"{len(rows)} declarații, {firms} firme în perioada aleasă."
            if rows else
            "Nicio declarație depusă în perioada aleasă.")
        self.save_btn.setEnabled(bool(rows))

    def _save(self) -> None:
        an, luna = self._selection()
        rows = self._rows()
        if not rows:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Salvează raportul",
            str(Path.home() / excel_export.default_filename(an, luna)),
            "Fișiere Excel (*.xlsx)")
        if not path:
            return
        try:
            saved = excel_export.save_report(path, rows, an, luna)
        except OSError as exc:
            QMessageBox.warning(
                self, "Salvare eșuată",
                f"Nu am putut scrie fișierul:\n{exc}\n\n"
                "Dacă raportul este deschis în Excel, închideți-l și încercați "
                "din nou.")
            return

        answer = QMessageBox.question(
            self, "Raport salvat",
            f"{len(rows)} declarații salvate în:\n{saved}\n\nDeschideți fișierul?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        if answer == QMessageBox.StandardButton.Yes:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(saved)))
        self.accept()
