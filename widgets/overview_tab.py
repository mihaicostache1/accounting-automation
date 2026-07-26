"""Tab 2 — global overview for one selected year + month.

One row per company; one column per declaration type. Each cell is a single
green/red indicator: submitted or not for the selected month. Clicking a cell
jumps to Tab 1 with that company and type pre-selected.
"""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QHeaderView, QLabel,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

import database
from config import DECLARATION_TYPES, MONTHS_LONG, YEARS
from theme import GRAY_BG, GRAY_TEXT, GREEN, RED


class OverviewTab(QWidget):
    # Emitted when a status cell is clicked: navigate to Tab 1 (firma_id, tip).
    cell_activated = Signal(int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._firme: list = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(QLabel("Anul:"))
        self.year_combo = QComboBox()
        self.year_combo.setMinimumWidth(100)
        for year in YEARS:
            self.year_combo.addItem(str(year), userData=year)
        self.year_combo.setCurrentIndex(0)  # 2026 by default
        self.year_combo.currentIndexChanged.connect(lambda _idx: self.refresh())
        top.addWidget(self.year_combo)

        top.addWidget(QLabel("Luna:"))
        self.month_combo = QComboBox()
        self.month_combo.setMinimumWidth(140)
        for luna, name in enumerate(MONTHS_LONG, start=1):
            self.month_combo.addItem(name, userData=luna)
        self.month_combo.setCurrentIndex(date.today().month - 1)
        self.month_combo.currentIndexChanged.connect(lambda _idx: self.refresh())
        top.addWidget(self.month_combo)
        top.addStretch()

        hint = QLabel("Click pe o celulă pentru a deschide firma în primul tab")
        hint.setProperty("role", "section-title")
        top.addWidget(hint)
        layout.addLayout(top)

        self.table = QTableWidget()
        self.table.setColumnCount(2 + len(DECLARATION_TYPES))
        self.table.setHorizontalHeaderLabels(["Firmă", "CUI", *DECLARATION_TYPES])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.cellClicked.connect(self._on_cell_clicked)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        for col in range(2, 2 + len(DECLARATION_TYPES)):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

        self.refresh()

    def refresh(self) -> None:
        an = self.year_combo.currentData()
        luna = self.month_combo.currentData()
        self._firme = database.list_firme()
        statuses = database.get_month_overview(an, luna)
        self._tipuri = database.get_all_firma_tipuri()

        self.table.setRowCount(len(self._firme))
        for row, firma in enumerate(self._firme):
            self.table.setRowHeight(row, 42)
            self.table.setItem(row, 0, QTableWidgetItem(firma["nume_firma"]))
            self.table.setItem(row, 1, QTableWidgetItem(firma["cui"]))

            applicable = self._tipuri.get(firma["id"], set())
            for col, tip in enumerate(DECLARATION_TYPES, start=2):
                if tip not in applicable:
                    # Declaration type does not apply to this firm -> gray cell.
                    item = QTableWidgetItem("—")
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    item.setBackground(QBrush(QColor(GRAY_BG)))
                    item.setForeground(QBrush(QColor(GRAY_TEXT)))
                    item.setToolTip(f"{tip} — nu se aplică acestei firme")
                else:
                    decl_ok, rec_ok = statuses.get((firma["id"], tip), (False, False))
                    item = QTableWidgetItem("✓" if decl_ok else "✗")
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    item.setBackground(QBrush(QColor(GREEN if decl_ok else RED)))
                    item.setForeground(QBrush(QColor("#ffffff")))
                    item.setToolTip(
                        f"{tip} — {MONTHS_LONG[luna - 1]} {an}\n"
                        f"Declarație: {'depusă' if decl_ok else 'lipsă'}\n"
                        f"Recipisă: {'depusă' if rec_ok else 'lipsă'}")
                self.table.setItem(row, col, item)

    def _on_cell_clicked(self, row: int, col: int) -> None:
        if col < 2 or row >= len(self._firme):
            return
        firma = self._firme[row]
        tip = DECLARATION_TYPES[col - 2]
        # Gray (non-applicable) cells are not navigable.
        if tip not in self._tipuri.get(firma["id"], set()):
            return
        self.cell_activated.emit(firma["id"], tip)
