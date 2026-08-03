"""Modern light theme (QSS) and status colors.

Status-colored widgets use the dynamic property `status` = "ok" | "missing"
| "warn" | "na"; call `repolish()` after changing it so Qt re-applies the
stylesheet.
"""

from PySide6.QtWidgets import QWidget

GREEN = "#2e9e5b"
GREEN_HOVER = "#27884e"
RED = "#d64545"
RED_HOVER = "#bf3a3a"
YELLOW = "#f0b429"       # recipisa with validation errors
YELLOW_HOVER = "#dda20f"
YELLOW_TEXT = "#5b4708"  # dark text — white is unreadable on amber
GRAY_BG = "#e3e6eb"      # "not applicable" cells
GRAY_TEXT = "#8a93a0"
ACCENT = "#2563eb"
CANVAS = "#f7f8fb"       # page background behind the cards

LIGHT_QSS = f"""
* {{
    font-family: "Segoe UI", "SF Pro Text", "Helvetica Neue", Arial, sans-serif;
    font-size: 13px;
    color: #1f2430;
}}

QMainWindow, QDialog {{
    background-color: {CANVAS};
}}
QWidget[role="content"] {{
    background-color: {CANVAS};
}}

/* Left navigation panel (replaces the old top toolbar) */
QFrame[role="sidebar"] {{
    background-color: #ffffff;
    border-right: 1px solid #e6e9ee;
}}
QLabel[role="brand"] {{
    color: #1f2430;
    font-size: 17px;
    font-weight: 800;
    letter-spacing: 2px;
    padding: 0 6px;
}}
QLabel[role="brand-sub"] {{
    color: #9aa3b0;
    font-size: 11px;
    padding: 2px 6px 0 6px;
}}
QLabel[role="nav-section"] {{
    color: #aab2bd;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1px;
    padding: 0 6px 6px 6px;
}}
QLabel[role="page-title"] {{
    color: #1f2430;
    font-size: 19px;
    font-weight: 700;
}}

QPushButton[role="nav"] {{
    background-color: transparent;
    border: none;
    border-radius: 8px;
    padding: 10px 12px;
    text-align: left;
    color: #5b6472;
    font-size: 13px;
    min-height: 20px;
}}
QPushButton[role="nav"]:hover {{
    background-color: #f2f5fa;
    border: none;
    color: #1f2430;
}}
QPushButton[role="nav"]:pressed {{
    background-color: #e8eef8;
}}
QPushButton[role="nav"]:checked {{
    background-color: {ACCENT};
    color: #ffffff;
    font-weight: 600;
}}
QPushButton[role="nav"]:disabled {{
    color: #c2c8d0;
    background-color: transparent;
}}

QToolButton {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 5px 10px;
}}
QToolButton:hover {{
    background-color: #eef2f8;
    border-color: #d5dbe3;
}}

QTabWidget::pane {{
    border: 1px solid #e6e9ee;
    border-radius: 12px;
    background-color: #ffffff;
    top: -1px;
}}
QTabBar::tab {{
    background-color: transparent;
    padding: 8px 18px;
    margin-right: 4px;
    border: 1px solid transparent;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    color: #5b6472;
}}
QTabBar::tab:selected {{
    background-color: #ffffff;
    border-color: #dde1e6;
    border-bottom-color: #ffffff;
    color: {ACCENT};
    font-weight: 600;
}}
QTabBar::tab:hover:!selected {{
    color: #1f2430;
}}

QGroupBox {{
    border: 1px solid #e6e9ee;
    border-radius: 12px;
    margin-top: 12px;
    background-color: #ffffff;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 4px;
    color: #5b6472;
}}

QComboBox {{
    background-color: #ffffff;
    border: 1px solid #ccd3dc;
    border-radius: 6px;
    padding: 6px 10px;
    min-width: 220px;
}}
QComboBox:hover {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}

/* Editors sitting inside table cells: the 220px minimum above is meant for
   standalone selectors and makes table columns absurdly wide. */
QComboBox[role="compact"] {{
    min-width: 0;
    padding: 2px 6px;
}}
QComboBox[role="compact"]::drop-down {{ width: 16px; }}
QSpinBox[role="compact"] {{
    background-color: #ffffff;
    border: 1px solid #ccd3dc;
    border-radius: 6px;
    padding: 2px 4px;
    min-width: 0;
}}
QSpinBox[role="compact"]:focus {{ border-color: {ACCENT}; }}
QSpinBox[role="compact"]::up-button, QSpinBox[role="compact"]::down-button {{
    width: 14px;
}}
QComboBox QAbstractItemView {{
    background-color: #ffffff;
    border: 1px solid #ccd3dc;
    border-radius: 6px;
    selection-background-color: #e8effd;
    selection-color: #1f2430;
    outline: none;
}}

QLineEdit {{
    background-color: #ffffff;
    border: 1px solid #ccd3dc;
    border-radius: 6px;
    padding: 6px 10px;
}}
QLineEdit:focus {{ border-color: {ACCENT}; }}

QPushButton {{
    background-color: #ffffff;
    border: 1px solid #ccd3dc;
    border-radius: 6px;
    padding: 6px 14px;
}}
QPushButton:hover {{ background-color: #f0f4fa; border-color: {ACCENT}; }}
QPushButton:pressed {{ background-color: #e4ebf5; }}

/* Primary action buttons */
QPushButton[variant="primary"] {{
    background-color: {ACCENT};
    border-color: {ACCENT};
    color: #ffffff;
    font-weight: 600;
}}
QPushButton[variant="primary"]:hover {{ background-color: #1d4fd7; }}

/* Declaration-type toggle buttons (Tab 1) */
QPushButton[role="type-toggle"] {{
    padding: 8px 18px;
    font-weight: 600;
    color: #5b6472;
    background-color: #f5f7fa;
}}
QPushButton[role="type-toggle"]:checked {{
    background-color: {ACCENT};
    border-color: {ACCENT};
    color: #ffffff;
}}

/* Month matrix cells and dialog document buttons:
   green = ok, red = missing, yellow = ANAF validation errors */
QPushButton[status="ok"] {{
    background-color: {GREEN};
    border: 1px solid {GREEN};
    color: #ffffff;
    font-weight: 600;
}}
QPushButton[status="ok"]:hover {{ background-color: {GREEN_HOVER}; }}
QPushButton[status="missing"] {{
    background-color: {RED};
    border: 1px solid {RED};
    color: #ffffff;
    font-weight: 600;
}}
QPushButton[status="missing"]:hover {{ background-color: {RED_HOVER}; }}
QPushButton[status="warn"] {{
    background-color: {YELLOW};
    border: 1px solid {YELLOW};
    color: {YELLOW_TEXT};
    font-weight: 600;
}}
QPushButton[status="warn"]:hover {{ background-color: {YELLOW_HOVER}; }}
QPushButton[status="na"] {{
    background-color: {GRAY_BG};
    border: 1px solid {GRAY_BG};
    color: {GRAY_TEXT};
}}

QLabel[role="cui-badge"] {{
    background-color: #e8effd;
    color: {ACCENT};
    border-radius: 6px;
    padding: 6px 12px;
    font-weight: 700;
    font-size: 14px;
}}
QLabel[role="section-title"] {{
    color: #5b6472;
    font-weight: 600;
}}
QLabel[role="year-label"] {{
    font-weight: 700;
    font-size: 14px;
    color: #1f2430;
}}

QTableWidget {{
    background-color: #ffffff;
    border: 1px solid #e6e9ee;
    border-radius: 12px;
    gridline-color: #eceff3;
    selection-background-color: #e8effd;
    selection-color: #1f2430;
}}
QHeaderView::section {{
    background-color: #f5f7fa;
    border: none;
    border-bottom: 1px solid #dde1e6;
    border-right: 1px solid #eceff3;
    padding: 8px;
    font-weight: 600;
    color: #5b6472;
}}
QTableCornerButton::section {{
    background-color: #f5f7fa;
    border: none;
    border-bottom: 1px solid #dde1e6;
}}

QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: #c6cdd6; border-radius: 5px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: #aab3bf; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{
    background: transparent; height: 10px; margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: #c6cdd6; border-radius: 5px; min-width: 30px;
}}

QStatusBar {{
    background-color: #ffffff;
    border-top: 1px solid #dde1e6;
    color: #5b6472;
}}

QToolTip {{
    background-color: #1f2430;
    color: #ffffff;
    border: none;
    padding: 5px 8px;
    border-radius: 4px;
}}
"""


def repolish(widget: QWidget) -> None:
    """Re-apply the stylesheet after a dynamic property change."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
