"""Fiscal Declarations Tracker — entry point.

Run with:  python main.py
On first run the SQLite DB is created and seeded with 3 demo companies plus
placeholder PDFs under the base folder (default: ~/Declaratii_Firme).
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog, QMainWindow,
                               QMessageBox, QTabWidget, QToolBar)

import database
from anaf_service import CellJob, RecipisaWorker
from config import (APP_ICON_PATH, APP_NAME, AUTO_RECIPISA_INTERVAL_MIN,
                    AUTO_RECIPISA_STARTUP_DELAY_S, MONTHS_SHORT)
from theme import LIGHT_QSS
from widgets.company_dialog import CompanyDialog
from widgets.company_tab import CompanyTab
from widgets.import_dialog import ImportDialog
from widgets.overview_tab import OverviewTab
from widgets.report_dialog import ReportDialog
from widgets.upload_dialog import UploadDialog


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1150, 640)

        toolbar = QToolBar("Acțiuni")
        toolbar.setMovable(False)
        toolbar.addAction("➕  Adaugă firmă", self._add_company)
        toolbar.addAction("📥  Importă din Excel", self._import_from_excel)
        toolbar.addAction("📁  Setări folder", self._choose_base_folder)
        toolbar.addAction("⬆  Trimite la ANAF", self._upload_declarations)
        toolbar.addAction("📊  Raport Excel", self._export_report)
        self._check_action = toolbar.addAction("🔄  Verifică recipise ANAF",
                                               self._check_all_recipise)
        self._auto_action = toolbar.addAction("⏱  Verificare automată")
        self._auto_action.setCheckable(True)
        self._auto_action.setToolTip(
            f"Verifică singură la fiecare {AUTO_RECIPISA_INTERVAL_MIN} de minute "
            "și descarcă recipisele disponibile, cât timp aplicația este deschisă.")
        self.addToolBar(toolbar)
        self._recipisa_worker: RecipisaWorker | None = None
        self._silent_check = False

        # Background polling: one timer while the app is open, plus a delayed
        # first run so startup stays instant.
        self._auto_timer = QTimer(self)
        self._auto_timer.setInterval(AUTO_RECIPISA_INTERVAL_MIN * 60 * 1000)
        self._auto_timer.timeout.connect(self._auto_check_recipise)

        self.tabs = QTabWidget()
        self.company_tab = CompanyTab()
        self.overview_tab = OverviewTab()
        self.tabs.addTab(self.company_tab, "Vizualizare firmă")
        self.tabs.addTab(self.overview_tab, "Situație globală")
        self.setCentralWidget(self.tabs)

        # Cross-tab wiring: edits refresh the overview; overview cells navigate.
        self.company_tab.data_changed.connect(self.overview_tab.refresh)
        self.overview_tab.cell_activated.connect(self._goto_company)

        # Restore the saved preference; setChecked fires toggled, which starts
        # the timer and schedules the first check.
        self._auto_action.toggled.connect(self._set_auto_check)
        self._auto_action.setChecked(database.get_auto_recipise())
        self._update_status_bar()

    def _update_status_bar(self) -> None:
        auto = ("verificare automată pornită" if self._auto_action.isChecked()
                else "verificare automată oprită")
        self.statusBar().showMessage(
            f"Folder documente: {database.get_base_folder()}  ·  {auto}")

    def _add_company(self) -> None:
        dialog = CompanyDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.company_tab.reload_companies()
            self.overview_tab.refresh()

    def _export_report(self) -> None:
        ReportDialog(self).exec()

    def _import_from_excel(self) -> None:
        dialog = ImportDialog(self)
        dialog.exec()
        if dialog.imported:
            self.company_tab.reload_companies()
            self.overview_tab.refresh()

    def _choose_base_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Alege folderul de bază pentru documente",
            str(database.get_base_folder()))
        if folder:
            database.set_base_folder(folder)
            self._update_status_bar()

    def _upload_declarations(self) -> None:
        """Review the source folder and send the chosen declarations to ANAF.

        Successful uploads archive the PDF and store the index, so the tabs and
        the recipisa poller both pick the new cells up afterwards.
        """
        dialog = UploadDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.company_tab.refresh_matrix()
            self.overview_tab.refresh()

    def _start_recipisa_check(self, *, silent: bool) -> bool:
        """Kick off a check for every declaration that has an index but no
        recipisa yet. Returns False when there is nothing pending.

        `silent` runs it as background polling: the outcome goes to the status
        bar instead of a dialog, so a timed check never interrupts what the
        user is doing.
        """
        pending = database.list_pending_recipise()
        if not pending:
            return False
        jobs = [CellJob(r["firma_id"], r["cui"], r["nume_firma"],
                        r["tip_declaratie"], r["an"], r["luna"],
                        r["index_incarcare"]) for r in pending]
        self._silent_check = silent
        self._check_action.setEnabled(False)
        self._recipisa_worker = RecipisaWorker(jobs, parent=self)
        self._recipisa_worker.progress.connect(self.statusBar().showMessage)
        self._recipisa_worker.completed.connect(self._on_recipise_checked)
        self._recipisa_worker.start()
        return True

    def _check_all_recipise(self) -> None:
        """Toolbar action: same check, but reports back with a dialog."""
        if self._recipisa_worker is not None:
            QMessageBox.information(
                self, "Verificare în curs",
                "O verificare rulează deja. Așteptați să se termine.")
            return
        if not self._start_recipisa_check(silent=False):
            QMessageBox.information(
                self, "Nimic de verificat",
                "Nicio declarație cu index de încărcare nu așteaptă recipisă.\n"
                "Introduceți indexul în dialogul lunii (click pe o celulă).")

    def _auto_check_recipise(self) -> None:
        """Timer tick. Skips silently when a check is already running or there
        is nothing pending — an idle app must not talk to ANAF for no reason."""
        if self._recipisa_worker is not None:
            return
        self._start_recipisa_check(silent=True)

    def _set_auto_check(self, enabled: bool) -> None:
        database.set_auto_recipise(enabled)
        if enabled:
            self._auto_timer.start()
            QTimer.singleShot(AUTO_RECIPISA_STARTUP_DELAY_S * 1000,
                              self._auto_check_recipise)
        else:
            self._auto_timer.stop()
        self._update_status_bar()

    def _on_recipise_checked(self, outcomes: list) -> None:
        self._recipisa_worker = None
        self._check_action.setEnabled(True)
        self.company_tab.refresh_matrix()
        self.overview_tab.refresh()

        downloaded = sum(1 for o in outcomes if o.recipisa_downloaded)
        failed = sum(1 for o in outcomes if not o.ok)

        if self._silent_check:
            if downloaded:
                self.statusBar().showMessage(
                    f"✅  {downloaded} recipise descărcate automat "
                    f"({len(outcomes)} verificate).", 15000)
            else:
                self._update_status_bar()
            return

        lines = [
            f"{o.job.nume_firma} — {o.job.tip} "
            f"{MONTHS_SHORT[o.job.luna - 1]} {o.job.an}: {o.message}"
            for o in outcomes]
        self._update_status_bar()
        box = QMessageBox(self)
        box.setWindowTitle("Verificare recipise ANAF")
        box.setIcon(QMessageBox.Icon.Warning if failed else QMessageBox.Icon.Information)
        box.setText(f"Verificate: {len(outcomes)}  ·  "
                    f"Recipise descărcate: {downloaded}  ·  Eșuate: {failed}")
        box.setDetailedText("\n".join(lines))
        box.exec()

    def closeEvent(self, event) -> None:
        """Stop polling and let a running check finish, so Qt does not tear the
        worker thread down mid-request."""
        self._auto_timer.stop()
        if self._recipisa_worker is not None:
            self._recipisa_worker.wait(3000)
        super().closeEvent(event)

    def _goto_company(self, firma_id: int, tip: str) -> None:
        self.company_tab.select_company_and_type(firma_id, tip)
        self.tabs.setCurrentWidget(self.company_tab)


def _qt_listing_broken(path: Path) -> bool:
    """True when the OS sees files in `path` but Qt's own directory listing
    comes back empty — the failure mode behind 'Could not find the Qt
    platform plugin'."""
    from PySide6.QtCore import QDir
    real = [n for n in os.listdir(path) if not n.startswith(".")]
    seen = [n for n in QDir(str(path)).entryList() if n not in (".", "..")]
    return bool(real) and not seen


def _ensure_qt_plugins() -> None:
    """Self-heal Qt plugin discovery on macOS.

    macOS can stamp the venv's Qt files with a `com.apple.provenance`
    attribute that makes Qt's directory scan return nothing, so QApplication
    aborts with 'Could not find the Qt platform plugin "cocoa"'. A plain copy
    of the plugins does not carry the attribute, so when the original folder
    is broken we keep a clean cached copy and point Qt at it instead.
    Must run BEFORE QApplication is created.
    """
    import PySide6
    plugins = Path(PySide6.__file__).resolve().parent / "Qt" / "plugins"
    platforms = plugins / "platforms"
    if not platforms.is_dir() or not _qt_listing_broken(platforms):
        return

    cache = (Path.home() / ".cache" / "declaratii_firme"
             / f"qtplugins-{PySide6.__version__}")
    if not (cache / "platforms").is_dir() or _qt_listing_broken(cache / "platforms"):
        shutil.rmtree(cache, ignore_errors=True)
        cache.parent.mkdir(parents=True, exist_ok=True)
        if sys.platform == "darwin":
            # `cp` clones stay free of the provenance attribute; files written
            # by Python itself can get re-stamped and stay broken.
            import subprocess
            subprocess.run(["cp", "-R", str(plugins), str(cache)], check=True)
        else:
            shutil.copytree(plugins, cache)

    from PySide6.QtCore import QCoreApplication
    QCoreApplication.setLibraryPaths(
        [str(cache)] + [p for p in QCoreApplication.libraryPaths() if p != str(plugins)])
    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(cache / "platforms")


def main() -> int:
    _ensure_qt_plugins()
    database.init_db()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    if APP_ICON_PATH.is_file():
        app.setWindowIcon(QIcon(str(APP_ICON_PATH)))
    app.setStyleSheet(LIGHT_QSS)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
