"""Excel-import dialog: pick a file, review what was recognized, import.

Every parsed row is shown with a verdict before anything touches the database
— rows with problems (missing name, bad CUI, duplicates) and firms that
already exist are visible but cannot be ticked, so the import button only ever
inserts valid new firms.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QHeaderView,
                               QLabel, QMessageBox, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

import excel_import

COL_IMPORT, COL_NUME, COL_CUI, COL_TIPURI, COL_PERIOD, COL_STATUS = range(6)
HEADERS = ["Importă", "Nume firmă", "CUI", "Declarații", "Periodicitate", "Status"]


class ImportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Importă firme din Excel")
        self.setModal(True)
        self.resize(900, 520)
        self.imported = 0    # caller refreshes tabs when > 0

        self._firms: list[excel_import.ParsedFirm] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        title = QLabel("Firme găsite în fișier")
        title.setProperty("role", "section-title")
        layout.addWidget(title)

        self.info_label = QLabel(
            "Alegeți un fișier .xlsx cu firmele: o coloană cu numele, una cu "
            "CUI-ul și, opțional, câte o coloană pe tip de declarație "
            "(100, 112, 300…) bifată cu „x”/„da”. Pentru 300/394/406, o valoare "
            "„lunar”/„trimestrial” în celulă setează și periodicitatea.")
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)

        pick_row = QHBoxLayout()
        pick_row.setSpacing(6)
        pick_btn = QPushButton("📄  Alege fișierul Excel…")
        pick_btn.clicked.connect(self._pick_file)
        pick_row.addWidget(pick_btn)
        pick_row.addStretch(1)
        layout.addLayout(pick_row)

        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_NUME, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_STATUS, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, stretch=1)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close_btn = QPushButton("Închide")
        close_btn.clicked.connect(self.reject)
        buttons.addWidget(close_btn)
        self.import_btn = QPushButton("⬇  Importă firmele selectate")
        self.import_btn.setProperty("variant", "primary")
        self.import_btn.setEnabled(False)
        self.import_btn.clicked.connect(self._do_import)
        buttons.addWidget(self.import_btn)
        layout.addLayout(buttons)

        self.table.itemChanged.connect(lambda _item: self._refresh_import_button())

    # ------------------------------------------------------------------ parse

    def _pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Alege fișierul cu firme", "",
            "Fișiere Excel (*.xlsx *.xlsm)")
        if not path:
            return
        try:
            result = excel_import.parse_excel(path)
        except ValueError as exc:
            QMessageBox.warning(self, "Fișier nerecunoscut", str(exc))
            return
        except Exception as exc:
            QMessageBox.warning(self, "Eroare la citire",
                                f"Nu am putut citi fișierul:\n{exc}")
            return

        self._firms = result.firms
        remarks = " ".join(result.notes)
        if result.type_columns:
            remarks = (f"Coloane de declarații găsite: "
                       f"{', '.join(result.type_columns)}. " + remarks)
        self.info_label.setText(remarks or "Fișier citit.")
        self._populate()

    def _populate(self) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(len(self._firms))
        for row, firm in enumerate(self._firms):
            importable = firm.error is None and not firm.existing

            tick = QTableWidgetItem()
            if importable:
                tick.setFlags(Qt.ItemFlag.ItemIsUserCheckable
                              | Qt.ItemFlag.ItemIsEnabled)
                tick.setCheckState(Qt.CheckState.Checked)
            else:
                tick.setFlags(Qt.ItemFlag.NoItemFlags)
            self.table.setItem(row, COL_IMPORT, tick)

            if firm.error:
                status = f"⚠  {firm.error} (rând {firm.row_number})"
            elif firm.existing:
                status = "există deja — ignorat"
            else:
                status = "nou"
            for col, text in ((COL_NUME, firm.nume or "—"),
                              (COL_CUI, firm.cui or "—"),
                              (COL_TIPURI, ", ".join(firm.tipuri)),
                              (COL_PERIOD, firm.periodicitate),
                              (COL_STATUS, status)):
                item = QTableWidgetItem(text)
                if not importable:
                    item.setForeground(Qt.GlobalColor.gray)
                self.table.setItem(row, col, item)
        self.table.blockSignals(False)

        new = sum(1 for f in self._firms if f.error is None and not f.existing)
        existing = sum(1 for f in self._firms if f.existing)
        errors = sum(1 for f in self._firms if f.error)
        self.status.setText(f"{len(self._firms)} rânduri: {new} noi, "
                            f"{existing} existente, {errors} cu probleme.")
        self._refresh_import_button()

    # ----------------------------------------------------------------- import

    def _checked_firms(self) -> list[excel_import.ParsedFirm]:
        out = []
        for row, firm in enumerate(self._firms):
            item = self.table.item(row, COL_IMPORT)
            if (item and item.checkState() == Qt.CheckState.Checked
                    and firm.error is None and not firm.existing):
                out.append(firm)
        return out

    def _refresh_import_button(self) -> None:
        count = len(self._checked_firms())
        self.import_btn.setEnabled(count > 0)
        self.import_btn.setText(f"⬇  Importă {count} firme" if count
                                else "⬇  Importă firmele selectate")

    def _do_import(self) -> None:
        firms = self._checked_firms()
        if not firms:
            return
        self.imported = excel_import.import_firms(firms)
        QMessageBox.information(
            self, "Import finalizat",
            f"{self.imported} firme au fost importate.")
        self.accept()
