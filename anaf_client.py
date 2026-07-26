"""HTTP client for ANAF's public StareD112 service (no authentication).

Given an "index de încărcare" (returned by the WAS6DUS upload page) and the
company's CIF, `check_status` returns the validation state of every document
submitted for that CIF in the last 3 months, and `download_recipisa` fetches
the signed receipt PDF (available only 60 days after submission).

Uses only the standard library so the PyInstaller build needs no new deps.
"""

from __future__ import annotations

import re
import urllib.parse
import urllib.request
from dataclasses import dataclass

BASE_URL = "https://www.anaf.ro/StareD112"
_USER_AGENT = "Mozilla/5.0 (compatible; DeclaratiiFirme)"
_TIMEOUT = 30  # seconds

# Normalized validation states (stare_validare in the DB).
STARE_VALID = "valid"
STARE_ERORI = "erori"
STARE_IN_PRELUCRARE = "in_prelucrare"
STARE_INVALID = "invalid"
STARE_NECUNOSCUT = "necunoscut"

STARE_LABELS = {
    STARE_VALID: "Documentul este valid",
    STARE_ERORI: "Documentul are erori de validare",
    STARE_IN_PRELUCRARE: "În prelucrare",
    STARE_INVALID: "Fișierul depus nu este un document valid",
    STARE_NECUNOSCUT: "Stare necunoscută",
}


class AnafError(Exception):
    """Network failure or unusable response from the ANAF service."""


@dataclass
class DocumentStatus:
    index: str            # index de încărcare (or nr. de înregistrare la ghișeu)
    tip_document: str     # e.g. "D100"
    stare: str            # one of the STARE_* constants
    stare_text: str       # raw text shown by ANAF
    data_inregistrare: str
    recipisa_disponibila: bool


def _normalize_stare(text: str) -> str:
    low = text.lower()
    if "este valid" in low:
        return STARE_VALID
    if "erori de validare" in low:
        return STARE_ERORI
    if "prelucrare" in low:
        return STARE_IN_PRELUCRARE
    if "nu este un document valid" in low:
        return STARE_INVALID
    return STARE_NECUNOSCUT


def _strip_tags(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def _fetch(url: str, data: dict | None = None) -> bytes:
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return resp.read()
    except OSError as exc:  # URLError, timeout, connection reset…
        raise AnafError(f"Conexiunea la ANAF a eșuat: {exc}") from exc


def check_status(index: str, cif: str, ghiseu: bool = False) -> list[DocumentStatus]:
    """All documents submitted for `cif` in the last 3 months.

    ANAF requires one valid (index, cif) pair to answer; the response then
    covers every recent submission for that CIF, so one call can refresh many
    stored declarations at once. Returns [] when the pair is not recognized.
    """
    html = _fetch(f"{BASE_URL}/vizualizareStare.do",
                  {"ghiseu": "Y" if ghiseu else "N",
                   "id": str(index).strip(), "cui": str(cif).strip()}).decode(
                       "utf-8", "replace")

    results = []
    for row_html in re.findall(r'<tr align="left">(.*?)</tr>', html, re.DOTALL):
        cells = [_strip_tags(c) for c in
                 re.findall(r"<td>(.*?)</td>", row_html, re.DOTALL)]
        if len(cells) < 4:
            continue
        results.append(DocumentStatus(
            index=cells[0],
            tip_document=cells[1],
            stare=_normalize_stare(cells[2]),
            stare_text=cells[2],
            data_inregistrare=cells[3],
            recipisa_disponibila="ObtineRecipisa" in row_html,
        ))
    return results


def download_recipisa(index: str) -> bytes:
    """The signed receipt PDF for one submission index.

    Raises AnafError if ANAF answers with something that is not a PDF
    (typically the recipisa is not ready yet or the 60-day window passed).
    """
    data = _fetch(f"{BASE_URL}/ObtineRecipisa?numefisier={str(index).strip()}.pdf")
    if not data.startswith(b"%PDF"):
        raise AnafError(
            "ANAF nu a returnat un PDF — recipisa nu este încă disponibilă "
            "sau perioada de 60 de zile a expirat.")
    return data
