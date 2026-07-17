"""Dialog for adding or editing a company: name, unique CUI, and the set of
declaration types that apply to it (drives the buttons in Tab 1 and the gray
cells in Tab 2)."""

from __future__ import annotations

import sqlite3

from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFormLayout,
                               QGridLayout, QGroupBox, QLineEdit, QMessageBox)

import database
from config import DECLARATION_TYPES


class CompanyDialog(QDialog):
    def __init__(self, parent=None, firma: sqlite3.Row | None = None):
        super().__init__(parent)
        self.firma = firma
        self.setWindowTitle("Editează firma" if firma else "Adaugă firmă")
        self.setModal(True)
        self.setMinimumWidth(400)

        form = QFormLayout(self)
        form.setContentsMargins(20, 20, 20, 20)
        form.setSpacing(10)

        self.nume_edit = QLineEdit(firma["nume_firma"] if firma else "")
        self.nume_edit.setPlaceholderText("ex: SC Exemplu SRL")
        self.cui_edit = QLineEdit(firma["cui"] if firma else "")
        self.cui_edit.setPlaceholderText("ex: RO12345678")
        form.addRow("Nume firmă:", self.nume_edit)
        form.addRow("CUI:", self.cui_edit)

        # Applicable declaration types: all checked for a new firm, the saved
        # selection when editing.
        selected = (set(database.get_firma_tipuri(firma["id"])) if firma
                    else set(DECLARATION_TYPES))
        types_box = QGroupBox("Declarații aplicabile")
        types_grid = QGridLayout(types_box)
        types_grid.setContentsMargins(14, 18, 14, 12)
        self.type_checks: dict[str, QCheckBox] = {}
        for i, tip in enumerate(DECLARATION_TYPES):
            check = QCheckBox(tip)
            check.setChecked(tip in selected)
            self.type_checks[tip] = check
            types_grid.addWidget(check, i // 3, i % 3)
        form.addRow(types_box)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Salvează")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Renunță")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _save(self) -> None:
        nume = self.nume_edit.text().strip()
        cui = self.cui_edit.text().strip()
        tipuri = [t for t in DECLARATION_TYPES if self.type_checks[t].isChecked()]
        if not nume or not cui:
            QMessageBox.warning(self, "Date incomplete",
                                "Completează atât numele firmei, cât și CUI-ul.")
            return
        if not tipuri:
            QMessageBox.warning(self, "Nicio declarație selectată",
                                "Bifează cel puțin un tip de declarație aplicabil firmei.")
            return
        try:
            if self.firma:
                firma_id = self.firma["id"]
                database.update_firma(firma_id, nume, cui)
            else:
                firma_id = database.add_firma(nume, cui)
        except sqlite3.IntegrityError:
            QMessageBox.warning(self, "CUI duplicat",
                                f"Există deja o firmă cu CUI-ul „{cui}”.")
            return
        database.set_firma_tipuri(firma_id, tipuri)
        self.accept()
