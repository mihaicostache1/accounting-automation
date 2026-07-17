"""Application-wide constants for the Fiscal Declarations Tracker."""

from pathlib import Path

APP_NAME = "Evidență Declarații Fiscale"

# SQLite database lives next to the application code.
DB_PATH = Path(__file__).resolve().parent / "declaratii.db"

# Default base folder for organized PDF storage. The effective value is stored
# in the DB `settings` table and can be changed from the app (Setări folder).
DEFAULT_BASE_FOLDER = Path.home() / "Declaratii_Firme"

# Declaration types shown as toggle buttons (Tab 1) and columns (Tab 2).
DECLARATION_TYPES = ["100", "112", "300", "390", "406", "Case de marcat"]

# Years shown as rows in the Tab 1 matrix.
YEARS = [2026, 2027, 2028]

MONTHS_SHORT = ["Ian", "Feb", "Mar", "Apr", "Mai", "Iun",
                "Iul", "Aug", "Sep", "Oct", "Nov", "Dec"]

MONTHS_LONG = ["Ianuarie", "Februarie", "Martie", "Aprilie", "Mai", "Iunie",
               "Iulie", "August", "Septembrie", "Octombrie", "Noiembrie", "Decembrie"]


def type_folder_name(tip: str) -> str:
    """Folder-safe name for a declaration type ('Case de marcat' -> 'Case_de_marcat')."""
    return tip.replace(" ", "_")
