"""Review-and-send dialog for uploading declarations to ANAF.

Three stages in one window, because the middle one needs the user to act:

  1. Scan   — list every PDF in the source folder with the app's guesses.
  2. Log in — open Chrome on the ANAF page so the user authenticates by hand.
  3. Send   — upload only the rows that are ticked and fully resolved.

Nothing is submitted until the user presses the send button: an upload to ANAF
cannot be withdrawn, so a wrong guess must be correctable first. Rows the
scanner could not resolve are shown but cannot be ticked.
"""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QCompleter, QDialog, QDialogButtonBox,
                               QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                               QListWidget, QMessageBox, QProgressBar,
                               QPushButton, QSpinBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

import anaf_uploader
import database
import upload_scanner
from anaf_uploader import UploadJob, UploadWorker
from config import DECLARATION_TYPES, MONTHS_LONG, YEARS

# Table columns.
COL_SEND, COL_FILE, COL_FIRMA, COL_TIP, COL_AN, COL_LUNA, COL_NOTE = range(7)
HEADERS = ["Trimite", "Fișier", "Firmă", "Tip", "An", "Lună", "Observații"]


class ConfirmSendDialog(QDialog):
    """Last look before an irreversible upload.

    A plain message box truncates once the list grows past a dozen, which is
    exactly when reviewing it matters most — so the list lives in its own
    scrollable widget and every entry stays readable.
    """

    def __init__(self, parent, lines: list[str]):
        super().__init__(parent)
        self.setWindowTitle("Confirmare trimitere")
        self.setModal(True)
        self.resize(520, 420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        head = QLabel(f"Se vor trimite {len(lines)} declarații la ANAF:")
        head.setProperty("role", "section-title")
        layout.addWidget(head)

        listing = QListWidget()
        listing.addItems(lines)
        listing.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        layout.addWidget(listing, stretch=1)

        warning = QLabel("⚠  Trimiterea nu poate fi anulată.")
        warning.setWordWrap(True)
        layout.addWidget(warning)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Yes
                                   | QDialogButtonBox.StandardButton.No)
        buttons.button(QDialogButtonBox.StandardButton.Yes).setText("Trimite")
        buttons.button(QDialogButtonBox.StandardButton.No).setText("Renunță")
        buttons.button(QDialogButtonBox.StandardButton.No).setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class UploadDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Trimite declarații la ANAF")
        self.setModal(True)
        self.resize(1000, 560)

        self._worker: UploadWorker | None = None
        self._candidates: list[upload_scanner.Candidate] = []
        self._firme = database.list_firme()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        title = QLabel("Declarații găsite în folderul sursă")
        title.setProperty("role", "section-title")
        layout.addWidget(title)

        self.folder_label = QLabel()
        self.folder_label.setWordWrap(True)
        layout.addWidget(self.folder_label)

        folder_row = QHBoxLayout()
        folder_row.setSpacing(6)
        change_btn = QPushButton("📁  Schimbă folderul sursă")
        change_btn.clicked.connect(self._choose_folder)
        rescan_btn = QPushButton("🔄  Rescanează")
        rescan_btn.clicked.connect(self._rescan)
        folder_row.addWidget(change_btn)
        folder_row.addWidget(rescan_btn)
        folder_row.addStretch(1)
        layout.addLayout(folder_row)

        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        header = self.table.horizontalHeader()
        # Only the free-text columns absorb slack; the editors stay just wide
        # enough for their content.
        for col in (COL_SEND, COL_TIP, COL_AN, COL_LUNA):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_FILE, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_FIRMA, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_NOTE, QHeaderView.ResizeMode.Stretch)
        # Without this, ticking a row changes nothing the send button can see.
        self.table.itemChanged.connect(lambda _item: self._refresh_send_button())
        layout.addWidget(self.table, stretch=1)

        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        self.login_btn = QPushButton("🌐  Deschide Chrome și autentifică-te")
        self.login_btn.clicked.connect(self._open_browser)
        self.restart_btn = QPushButton("♻  Repornește Chrome")
        self.restart_btn.setToolTip(
            "Închide și redeschide sesiunea Chrome a aplicației. Folosiți acest "
            "buton dacă primiți eroarea „sesiune inutilizabilă”.")
        self.restart_btn.clicked.connect(self._restart_browser)
        self.send_btn = QPushButton("⬆  Trimite selecția la ANAF")
        self.send_btn.setDefault(True)
        self.send_btn.clicked.connect(self._send)
        close_btn = QPushButton("Închide")
        close_btn.clicked.connect(self.reject)
        buttons.addWidget(self.login_btn)
        buttons.addWidget(self.restart_btn)
        buttons.addStretch(1)
        buttons.addWidget(close_btn)
        buttons.addWidget(self.send_btn)
        layout.addLayout(buttons)

        self._rescan()

    # ---------------------------------------------------------------- scanning

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Alege folderul cu declarațiile de trimis",
            str(database.get_source_folder()))
        if folder:
            database.set_source_folder(folder)
            self._rescan()

    def _rescan(self) -> None:
        source = database.get_source_folder()
        self.folder_label.setText(
            f"Folder sursă implicit:  {source}\n"
            "(firmele cu folder dedicat, setat în „Editează firma”, sunt "
            "incluse automat)")
        try:
            # No explicit path: combines every firm's dedicated folder with
            # the shared one above, so per-firm overrides are picked up too.
            self._candidates = upload_scanner.scan()
        except FileNotFoundError:
            self._candidates = []
            self.status.setText(
                "⚠  Niciun folder sursă nu există — nici cel implicit, nici "
                "vreun folder dedicat unei firme. Alegeți folderul implicit "
                "sau setați unul per firmă din „Editează firma”.")
            self.table.setRowCount(0)
            self._refresh_send_button()
            return
        self._populate()

    def _populate(self) -> None:
        # Filling the rows sets check states programmatically; block signals so
        # that does not re-enter through itemChanged for every single cell.
        self.table.blockSignals(True)
        self.table.setRowCount(len(self._candidates))
        for row, cand in enumerate(self._candidates):
            self._fill_row(row, cand)
        self.table.blockSignals(False)
        self._update_status()
        self._refresh_send_button()

    def _update_status(self) -> None:
        """Counters under the table. Recomputed after manual corrections too,
        otherwise the line keeps claiming a row still needs attention."""
        total = len(self._candidates)
        if not total:
            self.status.setText("Nu am găsit fișiere PDF în folderul sursă.")
            return
        skipped = sum(1 for c in self._candidates if c.skip_reason)
        ready = sum(1 for c in self._candidates if c.sendable)
        parts = [f"{total} fișiere PDF găsite", f"{ready} recunoscute complet"]
        incomplete = total - ready - skipped
        if incomplete:
            parts.append(f"{incomplete} necesită completare "
                         "(alegeți firma/perioada în tabel)")
        if skipped:
            parts.append(f"{skipped} nesemnate, ignorate (există varianta semnată)")
        self.status.setText(" · ".join(parts) + ".")

    def _fill_row(self, row: int, cand: upload_scanner.Candidate) -> None:
        """One table row: a tick box plus editors that write back into `cand`."""
        tick = QTableWidgetItem()
        if cand.skip_reason:
            # Not tickable: filing this copy is a mistake, not a choice.
            tick.setFlags(Qt.ItemFlag.NoItemFlags)
        else:
            tick.setFlags(Qt.ItemFlag.ItemIsUserCheckable
                          | Qt.ItemFlag.ItemIsEnabled)
        tick.setCheckState(Qt.CheckState.Checked if cand.sendable
                           else Qt.CheckState.Unchecked)
        self.table.setItem(row, COL_SEND, tick)

        try:
            shown = str(cand.path.relative_to(database.get_source_folder()))
        except ValueError:
            shown = cand.path.name
        name_item = QTableWidgetItem(shown)
        name_item.setToolTip(str(cand.path))
        name_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.table.setItem(row, COL_FILE, name_item)

        # Typing filters the list: with dozens of firms, scrolling to one is
        # slower than typing three letters of its name or CUI.
        firma_box = QComboBox()
        firma_box.setProperty("role", "compact")
        firma_box.setEditable(True)
        firma_box.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        firma_box.addItem("— alege firma —", None)
        for f in self._firme:
            firma_box.addItem(f"{f['nume_firma']} ({f['cui']})", f["id"])
        completer = firma_box.completer()
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        if cand.firma_id is not None:
            firma_box.setCurrentIndex(firma_box.findData(cand.firma_id))
        firma_box.currentIndexChanged.connect(
            lambda _, c=cand, b=firma_box: self._set_firma(c, b))
        firma_box.lineEdit().editingFinished.connect(
            lambda b=firma_box: self._restore_firma_text(b))
        self.table.setCellWidget(row, COL_FIRMA, firma_box)

        tip_box = QComboBox()
        tip_box.setProperty("role", "compact")
        tip_box.addItem("— tip —", None)
        for tip in DECLARATION_TYPES:
            tip_box.addItem(tip, tip)
        if cand.tip:
            tip_box.setCurrentIndex(tip_box.findData(cand.tip))
        tip_box.currentIndexChanged.connect(
            lambda _, c=cand, b=tip_box: self._set_field(c, "tip", b.currentData()))
        self.table.setCellWidget(row, COL_TIP, tip_box)

        an_spin = QSpinBox()
        an_spin.setProperty("role", "compact")
        an_spin.setRange(min(YEARS) - 5, max(YEARS) + 5)
        an_spin.setValue(cand.an or date.today().year)
        # A spin box cannot show "empty", so adopt the displayed year as the
        # candidate's value — otherwise a row looks complete while `an` is still
        # None and silently refuses to send.
        cand.an = an_spin.value()
        an_spin.valueChanged.connect(
            lambda v, c=cand: self._set_field(c, "an", v))
        self.table.setCellWidget(row, COL_AN, an_spin)

        luna_box = QComboBox()
        luna_box.setProperty("role", "compact")
        luna_box.addItem("— luna —", None)
        for idx, name in enumerate(MONTHS_LONG, start=1):
            luna_box.addItem(name, idx)
        if cand.luna:
            luna_box.setCurrentIndex(luna_box.findData(cand.luna))
        luna_box.currentIndexChanged.connect(
            lambda _, c=cand, b=luna_box: self._set_field(c, "luna", b.currentData()))
        self.table.setCellWidget(row, COL_LUNA, luna_box)

        # The exclusion reason leads: it explains why the row cannot be ticked.
        notes = ([f"⊘  {cand.skip_reason}"] if cand.skip_reason else []) + cand.notes
        note = QTableWidgetItem(" · ".join(notes))
        note.setFlags(Qt.ItemFlag.ItemIsEnabled)
        note.setToolTip("\n".join(notes))
        self.table.setItem(row, COL_NOTE, note)

    @staticmethod
    def _restore_firma_text(box: QComboBox) -> None:
        """Put the selected firm's text back after a search that matched
        nothing, so the cell never shows a name that is not the selection."""
        box.lineEdit().setText(box.itemText(box.currentIndex()))

    def _set_firma(self, cand: upload_scanner.Candidate, box: QComboBox) -> None:
        firma_id = box.currentData()
        cand.firma_id = firma_id
        match = next((f for f in self._firme if f["id"] == firma_id), None)
        cand.nume_firma = match["nume_firma"] if match else None
        cand.cui = match["cui"] if match else None
        self._after_edit(cand)

    def _set_field(self, cand: upload_scanner.Candidate, name: str, value) -> None:
        setattr(cand, name, value)
        self._after_edit(cand)

    def _after_edit(self, cand: upload_scanner.Candidate) -> None:
        """Tick a row as soon as manual corrections make it complete.

        Rows the scanner could not place start unticked, and their tick box is
        the only thing standing between a fully filled-in row and the send
        button. Filling one in *is* the intent to send it, so ticking it by
        hand afterwards is a step with no decision in it.
        """
        for row, other in enumerate(self._candidates):
            if other is not cand:
                continue
            item = self.table.item(row, COL_SEND)
            if (item is not None and cand.sendable
                    and item.checkState() != Qt.CheckState.Checked):
                self.table.blockSignals(True)
                item.setCheckState(Qt.CheckState.Checked)
                self.table.blockSignals(False)
            break
        self._update_status()
        self._refresh_send_button()

    # ---------------------------------------------------------------- sending

    def _checked(self) -> list[upload_scanner.Candidate]:
        """Ticked rows that are also allowed to be filed — the upload set."""
        out = []
        for row, cand in enumerate(self._candidates):
            item = self.table.item(row, COL_SEND)
            if item and item.checkState() == Qt.CheckState.Checked and cand.sendable:
                out.append(cand)
        return out

    def _refresh_send_button(self) -> None:
        count = len(self._checked())
        self.send_btn.setEnabled(count > 0 and self._worker is None)
        self.send_btn.setText(
            f"⬆  Trimite {count} la ANAF" if count else "⬆  Trimite selecția la ANAF")

    def _restart_browser(self) -> None:
        """Close and relaunch the app's Chrome — the remedy when a previous run
        of the app left its debugging session unusable."""
        anaf_uploader.close_browser()
        self._open_browser()

    def _open_browser(self) -> None:
        try:
            anaf_uploader.launch_browser()
        except anaf_uploader.UploadError as exc:
            QMessageBox.warning(self, "Chrome", str(exc))
            return
        QMessageBox.information(
            self, "Autentificare ANAF",
            "Chrome s-a deschis pe pagina ANAF.\n\n"
            "Autentificați-vă cu certificatul/tokenul, apoi reveniți aici și "
            "apăsați „Trimite la ANAF”.\n\n"
            "Lăsați Chrome deschis în timpul trimiterii.")

    def _send(self) -> None:
        jobs_src = self._checked()
        if not jobs_src:
            return
        if not anaf_uploader.debugger_ready():
            QMessageBox.warning(
                self, "Nu există sesiune ANAF",
                "Chrome nu este pornit în modul necesar.\n\n"
                "Apăsați „Deschide Chrome și autentifică-te”, autentificați-vă, "
                "apoi încercați din nou.")
            return

        lines = [f"{c.nume_firma} — {c.tip} — {MONTHS_LONG[c.luna - 1]} {c.an}"
                 for c in jobs_src]
        if ConfirmSendDialog(self, lines).exec() != QDialog.DialogCode.Accepted:
            return

        jobs = [UploadJob(path=c.path, firma_id=c.firma_id, cui=c.cui,
                          nume_firma=c.nume_firma, tip=c.tip, an=c.an, luna=c.luna)
                for c in jobs_src]

        self.progress.setRange(0, 0)
        self.progress.setVisible(True)
        self._worker = UploadWorker(jobs, self)
        self._worker.progress.connect(self.status.setText)
        self._worker.completed.connect(self._finished)
        self._refresh_send_button()
        self._worker.start()

    def _finished(self, outcomes) -> None:
        self._worker = None
        self.progress.setVisible(False)
        sent = [o for o in outcomes if o.ok]
        failed = [o for o in outcomes if not o.ok]

        lines = [f"✅  {o.job.nume_firma} — {o.job.tip} — index {o.index}" for o in sent]
        lines += [f"❌  {o.job.nume_firma} — {o.job.tip} — {o.message}" for o in failed]
        self.status.setText(f"{len(sent)} trimise, {len(failed)} eșuate.")
        QMessageBox.information(
            self, "Rezultat trimitere",
            f"{len(sent)} declarații trimise, {len(failed)} eșuate.\n\n"
            + "\n".join(lines[:20])
            + ("\n…" if len(lines) > 20 else ""))

        # Uploaded files are now archived and carry an index; drop them from the
        # list so a second press cannot resubmit the same declaration.
        sent_paths = {o.job.path for o in sent}
        self._candidates = [c for c in self._candidates if c.path not in sent_paths]
        self._populate()
        if sent:
            self.accept()
