"""Application-wide constants for the Fiscal Declarations Tracker."""

import os
import sys
from pathlib import Path

APP_NAME = "Evidență Declarații Fiscale"


def _data_dir() -> Path:
    """Writable data dir: next to the code in development, the per-user
    app-data folder when running as a frozen (PyInstaller) executable."""
    if getattr(sys, "frozen", False):
        if sys.platform == "darwin":
            base = Path.home() / "Library" / "Application Support" / "DeclaratiiFirme"
        elif sys.platform == "win32":
            base = Path(os.environ.get("APPDATA", str(Path.home()))) / "DeclaratiiFirme"
        else:
            base = Path.home() / ".local" / "share" / "declaratii_firme"
        base.mkdir(parents=True, exist_ok=True)
        return base
    return Path(__file__).resolve().parent


# Read-only bundled resources (icons): next to the code in development, the
# PyInstaller extraction dir (_MEIPASS -> _internal in onedir mode) when frozen.
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))

APP_ICON_PATH = RESOURCE_DIR / "assets" / "icon.png"

# SQLite database location (see _data_dir).
DB_PATH = _data_dir() / "declaratii.db"

# Default base folder for organized PDF storage. The effective value is stored
# in the DB `settings` table and can be changed from the app (Setări folder).
DEFAULT_BASE_FOLDER = Path.home() / "Declaratii_Firme"

# Folder the app READS signed declarations from before uploading them to ANAF.
# Distinct from DEFAULT_BASE_FOLDER, which is where the organized archive of
# declarations and recipise is written. Also overridable from the app.
DEFAULT_SOURCE_FOLDER = Path.home() / "Declaratii_de_trimis"

# Chrome/Edge debugging port used to attach to the user's already-authenticated
# ANAF session (see anaf_uploader). Fixed so a relaunch reuses the same channel.
CHROME_DEBUG_PORT = 9222

# ANAF's certificate-authenticated upload page for D112-family declarations.
ANAF_UPLOAD_URL = "https://decl.anaf.mfinante.gov.ro/WAS6DUS"

# Declaration types shown as toggle buttons (Tab 1) and columns (Tab 2).
DECLARATION_TYPES = ["100", "112", "300", "390", "394", "406", "Case de marcat"]

# Types that follow the firm's VAT periodicity: choosing lunar/trimestrial for
# 300 in the firm dialog applies the same to 394 and 406.
PERIODIC_TYPES = ("300", "394", "406")

# A quarterly declaration is recorded under the last month of its quarter.
QUARTER_MONTHS = (3, 6, 9, 12)

# Years shown as rows in the Tab 1 matrix.
YEARS = [2026, 2027, 2028]

MONTHS_SHORT = ["Ian", "Feb", "Mar", "Apr", "Mai", "Iun",
                "Iul", "Aug", "Sep", "Oct", "Nov", "Dec"]

MONTHS_LONG = ["Ianuarie", "Februarie", "Martie", "Aprilie", "Mai", "Iunie",
               "Iulie", "August", "Septembrie", "Octombrie", "Noiembrie", "Decembrie"]


def type_folder_name(tip: str) -> str:
    """Folder-safe name for a declaration type ('Case de marcat' -> 'Case_de_marcat')."""
    return tip.replace(" ", "_")
