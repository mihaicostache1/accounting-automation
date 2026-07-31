"""Dialog for adding or editing a company: name, unique CUI, and the set of
declaration types that apply to it (drives the buttons in Tab 1 and the gray
cells in Tab 2)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
                               QLineEdit, QMessageBox, QPushButton, QWidget)

import database
from config import DECLARATION_TYPES, PERIODIC_TYPES


class PeriodicityDialog(QDialog):
    """Lunar sau trimestrial pentru grupul 300/394/406.

    One click chooses and closes — no OK step, per the requested flow. Closing
    the window instead leaves `choice` as None (caller keeps the old value).
    """

    def __init__(self, parent, current: str):
        super().__init__(parent)
        self.choice: str | None = None
        self.setWindowTitle("Periodicitate 300 / 394 / 406")
        self.setModal(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        for value, label in (("lunar", "Lunar"), ("trimestrial", "Trimestrial")):
            btn = QPushButton(label)
            btn.setMinimumSize(140, 48)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            if value == current:
                btn.setProperty("variant", "primary")
            btn.clicked.connect(lambda _=False, v=value: self._pick(v))
            layout.addWidget(btn)

    def _pick(self, value: str) -> None:
        self.choice = value
        self.accept()


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

        # Optional per-firm override of the shared upload source folder (see
        # database.get_firma_source_folder / upload_scanner).
        self._source_folder: Path | None = (
            database.get_firma_source_folder(firma["id"]) if firma else None)
        folder_row = QWidget()
        folder_layout = QHBoxLayout(folder_row)
        folder_layout.setContentsMargins(0, 0, 0, 0)
        folder_layout.setSpacing(6)
        self.folder_edit = QLineEdit()
        self.folder_edit.setReadOnly(True)
        self.folder_edit.setPlaceholderText("(folosește folderul sursă implicit)")
        if self._source_folder:
            self.folder_edit.setText(str(self._source_folder))
        folder_layout.addWidget(self.folder_edit, stretch=1)
        choose_folder_btn = QPushButton("Alege…")
        choose_folder_btn.clicked.connect(self._choose_source_folder)
        folder_layout.addWidget(choose_folder_btn)
        reset_folder_btn = QPushButton("Resetează")
        reset_folder_btn.clicked.connect(self._reset_source_folder)
        folder_layout.addWidget(reset_folder_btn)
        form.addRow("Folder sursă declarații:", folder_row)

        # Applicable declaration types: all checked for a new firm, the saved
        # selection when editing.
        selected = (set(database.get_firma_tipuri(firma["id"])) if firma
                    else set(DECLARATION_TYPES))
        self._periodicitate: str = firma["periodicitate"] if firma else "lunar"
        types_box = QGroupBox("Declarații aplicabile")
        types_grid = QGridLayout(types_box)
        types_grid.setContentsMargins(14, 18, 14, 12)
        self.type_checks: dict[str, QCheckBox] = {}
        for i, tip in enumerate(DECLARATION_TYPES):
            check = QCheckBox(tip)
            check.setChecked(tip in selected)
            self.type_checks[tip] = check
            types_grid.addWidget(check, i // 3, i % 3)
        # Ticking 300 asks lunar/trimestrial; the answer is copied to 394/406.
        self.type_checks["300"].clicked.connect(self._on_300_clicked)
        self._refresh_periodic_labels()
        form.addRow(types_box)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Salvează")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Renunță")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        # `deleted` tells the caller (CompanyTab) the firm is gone rather than
        # saved — it still just needs to reload the company list either way.
        self.deleted = False
        if firma:
            bottom_row = QWidget()
            bottom_layout = QHBoxLayout(bottom_row)
            bottom_layout.setContentsMargins(0, 0, 0, 0)
            delete_btn = QPushButton("🗑️  Șterge firma")
            delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            delete_btn.clicked.connect(self._delete)
            bottom_layout.addWidget(delete_btn)
            bottom_layout.addStretch(1)
            bottom_layout.addWidget(buttons)
            form.addRow(bottom_row)
        else:
            form.addRow(buttons)

    def _on_300_clicked(self, checked: bool) -> None:
        if not checked:
            return
        dialog = PeriodicityDialog(self, self._periodicitate)
        dialog.exec()
        if dialog.choice:
            self._periodicitate = dialog.choice
            self._refresh_periodic_labels()

    def _refresh_periodic_labels(self) -> None:
        """Show the shared periodicity on 300, 394 and 406 alike, so it is
        visible that one choice drives all three."""
        for tip in PERIODIC_TYPES:
            self.type_checks[tip].setText(f"{tip} · {self._periodicitate}")

    def _choose_source_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Alege folderul dedicat acestei firme",
            str(self._source_folder or database.get_source_folder()))
        if folder:
            self._source_folder = Path(folder)
            self.folder_edit.setText(folder)

    def _reset_source_folder(self) -> None:
        self._source_folder = None
        self.folder_edit.clear()

    def _delete(self) -> None:
        confirmed = QMessageBox.question(
            self, "Șterge firma",
            f"Ștergeți „{self.firma['nume_firma']}” ({self.firma['cui']})?\n\n"
            "Toate declarațiile și recipisele înregistrate pentru această firmă "
            "vor fi șterse din bază de date (PDF-urile arhivate pe disc rămân "
            "neatinse). Acțiunea nu poate fi anulată.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if confirmed != QMessageBox.StandardButton.Yes:
            return
        database.delete_firma(self.firma["id"])
        self.deleted = True
        self.accept()

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
        database.set_firma_source_folder(firma_id, self._source_folder)
        database.set_firma_periodicitate(firma_id, self._periodicitate)
        self.accept()
