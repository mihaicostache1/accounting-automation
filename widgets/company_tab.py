"""Tab 1 — per-company view.

Company selector + CUI badge + edit button on top, then toggle buttons for
ONLY the declaration types applicable to the selected firm (configured in the
add/edit dialog), and the years × months green/red matrix. Clicking a cell
opens `MonthDialog`.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QDialog, QGridLayout,
                               QGroupBox, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

import anaf_client
import database
from config import MONTHS_LONG, MONTHS_SHORT, YEARS
from theme import repolish
from widgets.company_dialog import CompanyDialog
from widgets.month_dialog import MonthDialog


class CompanyTab(QWidget):
    # Emitted after data changed (statuses, files, firm edits), so other tabs refresh.
    data_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._firme: list = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # -- Top: company selector + CUI badge + edit ---------------------- #
        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(QLabel("Firma:"))

        self.company_combo = QComboBox()
        self.company_combo.currentIndexChanged.connect(self._on_company_changed)
        top.addWidget(self.company_combo, stretch=1)

        top.addWidget(QLabel("CUI:"))
        self.cui_label = QLabel("—")
        self.cui_label.setProperty("role", "cui-badge")
        top.addWidget(self.cui_label)

        edit_btn = QPushButton("✏️  Editează firma")
        edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        edit_btn.clicked.connect(self._edit_company)
        top.addWidget(edit_btn)
        layout.addLayout(top)

        # -- Middle: per-firm declaration-type toggles --------------------- #
        types_box = QGroupBox("Tip declarație")
        self.types_layout = QHBoxLayout(types_box)
        self.types_layout.setSpacing(8)
        self.type_group = QButtonGroup(self)
        self.type_group.setExclusive(True)
        self.type_group.buttonClicked.connect(lambda _btn: self.refresh_matrix())
        layout.addWidget(types_box)

        # -- Bottom: years × months matrix -------------------------------- #
        matrix_box = QGroupBox("Situație lunară")
        grid = QGridLayout(matrix_box)
        grid.setSpacing(6)
        grid.setContentsMargins(14, 20, 14, 14)

        for col, month in enumerate(MONTHS_SHORT, start=1):
            header = QLabel(month)
            header.setAlignment(Qt.AlignmentFlag.AlignCenter)
            header.setProperty("role", "section-title")
            grid.addWidget(header, 0, col)

        self._cells: dict[tuple[int, int], QPushButton] = {}
        for row, year in enumerate(YEARS, start=1):
            year_label = QLabel(str(year))
            year_label.setProperty("role", "year-label")
            grid.addWidget(year_label, row, 0)
            for col, luna in enumerate(range(1, 13), start=1):
                cell = QPushButton()
                cell.setMinimumSize(52, 40)
                cell.setCursor(Qt.CursorShape.PointingHandCursor)
                cell.setToolTip(f"{MONTHS_LONG[luna - 1]} {year}")
                cell.clicked.connect(
                    lambda _=False, y=year, m=luna: self._open_month_dialog(y, m))
                grid.addWidget(cell, row, col)
                self._cells[(year, luna)] = cell
        for col in range(1, 13):
            grid.setColumnStretch(col, 1)

        layout.addWidget(matrix_box)
        layout.addStretch()

        self.reload_companies()

    # ------------------------------------------------------------- selection

    def current_firma(self):
        idx = self.company_combo.currentIndex()
        return self._firme[idx] if 0 <= idx < len(self._firme) else None

    def current_type(self) -> str | None:
        btn = self.type_group.checkedButton()
        return btn.text() if btn else None

    def select_company_and_type(self, firma_id: int, tip: str) -> None:
        """Programmatic navigation used by the overview tab."""
        for idx, firma in enumerate(self._firme):
            if firma["id"] == firma_id:
                self.company_combo.setCurrentIndex(idx)  # rebuilds type buttons
                break
        for btn in self.type_group.buttons():
            if btn.text() == tip:
                btn.setChecked(True)
                break
        self.refresh_matrix()

    # --------------------------------------------------------------- refresh

    def reload_companies(self) -> None:
        """Re-read companies from the DB, keeping the current selection."""
        selected_id = self.current_firma()["id"] if self.current_firma() else None
        self._firme = database.list_firme()
        self.company_combo.blockSignals(True)
        self.company_combo.clear()
        for firma in self._firme:
            self.company_combo.addItem(f"{firma['nume_firma']} — {firma['cui']}")
        if selected_id is not None:
            for idx, firma in enumerate(self._firme):
                if firma["id"] == selected_id:
                    self.company_combo.setCurrentIndex(idx)
                    break
        self.company_combo.blockSignals(False)
        self._on_company_changed()

    def _on_company_changed(self) -> None:
        firma = self.current_firma()
        self.cui_label.setText(firma["cui"] if firma else "—")
        self._rebuild_type_buttons()
        self.refresh_matrix()

    def _rebuild_type_buttons(self) -> None:
        """Show toggle buttons only for the selected firm's declaration types,
        keeping the previously active type when it still applies."""
        previous = self.current_type()

        for btn in self.type_group.buttons():
            self.type_group.removeButton(btn)
        while self.types_layout.count():
            item = self.types_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        firma = self.current_firma()
        tipuri = database.get_firma_tipuri(firma["id"]) if firma else []
        for tip in tipuri:
            btn = QPushButton(tip)
            btn.setCheckable(True)
            btn.setProperty("role", "type-toggle")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.type_group.addButton(btn)
            self.types_layout.addWidget(btn)
        self.types_layout.addStretch()

        buttons = self.type_group.buttons()
        if buttons:
            wanted = next((b for b in buttons if b.text() == previous), buttons[0])
            wanted.setChecked(True)

    def refresh_matrix(self) -> None:
        firma = self.current_firma()
        tip = self.current_type()
        if firma is None or tip is None:
            for cell in self._cells.values():
                cell.setEnabled(False)
                cell.setProperty("status", "na")
                repolish(cell)
            return
        matrix = database.get_type_matrix(firma["id"], tip)
        for (year, luna), cell in self._cells.items():
            submitted, stare = matrix.get((year, luna), (False, None))
            cell.setEnabled(True)
            if submitted and anaf_client.are_erori(stare):
                cell.setProperty("status", "warn")
            else:
                cell.setProperty("status", "ok" if submitted else "missing")
            repolish(cell)

    # ---------------------------------------------------------------- dialogs

    def _edit_company(self) -> None:
        firma = self.current_firma()
        if firma is None:
            return
        dialog = CompanyDialog(self, firma=firma)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.reload_companies()
            self.data_changed.emit()

    def _open_month_dialog(self, year: int, luna: int) -> None:
        firma = self.current_firma()
        tip = self.current_type()
        if firma is None or tip is None:
            return
        dialog = MonthDialog(firma, tip, year, luna, parent=self)
        dialog.exec()
        if dialog.changed:
            self.refresh_matrix()
            self.data_changed.emit()
