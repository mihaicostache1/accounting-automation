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

from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog, QMainWindow,
                               QTabWidget, QToolBar)

import database
from config import APP_NAME
from theme import LIGHT_QSS
from widgets.company_dialog import CompanyDialog
from widgets.company_tab import CompanyTab
from widgets.overview_tab import OverviewTab


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1150, 640)

        toolbar = QToolBar("Acțiuni")
        toolbar.setMovable(False)
        toolbar.addAction("➕  Adaugă firmă", self._add_company)
        toolbar.addAction("📁  Setări folder", self._choose_base_folder)
        self.addToolBar(toolbar)

        self.tabs = QTabWidget()
        self.company_tab = CompanyTab()
        self.overview_tab = OverviewTab()
        self.tabs.addTab(self.company_tab, "Vizualizare firmă")
        self.tabs.addTab(self.overview_tab, "Situație globală")
        self.setCentralWidget(self.tabs)

        # Cross-tab wiring: edits refresh the overview; overview cells navigate.
        self.company_tab.data_changed.connect(self.overview_tab.refresh)
        self.overview_tab.cell_activated.connect(self._goto_company)

        self._update_status_bar()

    def _update_status_bar(self) -> None:
        self.statusBar().showMessage(f"Folder documente: {database.get_base_folder()}")

    def _add_company(self) -> None:
        dialog = CompanyDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.company_tab.reload_companies()
            self.overview_tab.refresh()

    def _choose_base_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Alege folderul de bază pentru documente",
            str(database.get_base_folder()))
        if folder:
            database.set_base_folder(folder)
            self._update_status_bar()

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
    app.setStyleSheet(LIGHT_QSS)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
