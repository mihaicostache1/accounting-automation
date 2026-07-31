"""HTTP client for ANAF's public StareD112 service (no authentication).

Given an "index de încărcare" (returned by the WAS6DUS upload page) and the
company's CIF, `check_status` returns the validation state of every document
submitted for that CIF in the last 3 months, and `download_recipisa` fetches
the signed receipt PDF (available only 60 days after submission).

Uses only the standard library so the PyInstaller build needs no new deps.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

# The same StareD112 application is served by two hosts. The main one goes
# down periodically, so every request falls back to the mirror instead of
# failing the whole check.
BASE_URLS = (
    "https://www.anaf.ro/StareD112",
    "https://stare.anaf.ro/StareD112",
)
_USER_AGENT = "Mozilla/5.0 (compatible; DeclaratiiFirme)"
_TIMEOUT = 30  # seconds

# Normalized validation states (stare_validare in the DB).
STARE_VALID = "valid"
STARE_ERORI = "erori"
STARE_IN_PRELUCRARE = "in_prelucrare"
STARE_INVALID = "invalid"
STARE_NECUNOSCUT = "necunoscut"
# Not an ANAF state: recorded by the app when the stored index is absent from
# ANAF's answer for that CIF (wrong index, wrong CIF, or older than 3 months).
STARE_NEGASIT = "negasit"

STARE_LABELS = {
    STARE_VALID: "Documentul este valid",
    STARE_ERORI: "Documentul are erori de validare",
    STARE_IN_PRELUCRARE: "În prelucrare",
    STARE_INVALID: "Fișierul depus nu este un document valid",
    STARE_NECUNOSCUT: "Stare necunoscută",
    STARE_NEGASIT: "Indexul nu apare în lista ANAF",
}

# Short forms for buttons and cells, where the full sentence does not fit.
STARE_SCURT = {
    STARE_VALID: "Validă",
    STARE_ERORI: "Erori de validare",
    STARE_IN_PRELUCRARE: "În prelucrare",
    STARE_INVALID: "Fișier invalid",
    STARE_NEGASIT: "Index negăsit",
    STARE_NECUNOSCUT: "Stare necunoscută",
}


def are_erori(stare: str | None) -> bool:
    """True when the submission needs attention — failed ANAF validation, or
    an index ANAF does not recognize. Drives the yellow color in the UI.

    Deliberately excludes transient trouble (network errors): those say
    nothing about the declaration itself and must not repaint the table.
    """
    return stare in (STARE_ERORI, STARE_INVALID, STARE_NEGASIT)


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


# Index into BASE_URLS of the host that answered last. Tried first next time,
# so one outage costs a single timeout for the whole run instead of one per
# request — with dozens of companies to check, that is the difference between
# a slow refresh and an unusable one.
_preferred_base = 0


def reset_preferred_host() -> None:
    """Go back to trying the main host first (used by the tests)."""
    global _preferred_base
    _preferred_base = 0


def current_host() -> str:
    """Host that served the last successful request — shown to the user when
    the app had to fall back. Clamped so it stays safe if the mirror list is
    ever shortened while an index into the old one is still remembered."""
    index = min(_preferred_base, len(BASE_URLS) - 1)
    return urllib.parse.urlsplit(BASE_URLS[index]).netloc


def _fetch(path: str, data: dict | None = None) -> bytes:
    """Request `path` from the first mirror that answers.

    Only transport-level trouble (unreachable host, timeout, 5xx) moves on to
    the next mirror: a real answer, even an unwelcome one, is returned as-is.
    """
    global _preferred_base
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    order = (list(range(_preferred_base, len(BASE_URLS)))
             + list(range(_preferred_base)))

    errors = []
    for i in order:
        base = BASE_URLS[i]
        req = urllib.request.Request(f"{base}{path}", data=body,
                                     headers={"User-Agent": _USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                _preferred_base = i
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code < 500:
                # The host is up and gave a verdict; a mirror would repeat it.
                raise AnafError(
                    f"ANAF a răspuns cu eroarea {exc.code} ({exc.reason}).") from exc
            errors.append(f"{urllib.parse.urlsplit(base).netloc}: {exc}")
        except OSError as exc:  # URLError, timeout, connection reset…
            errors.append(f"{urllib.parse.urlsplit(base).netloc}: {exc}")

    raise AnafError("Conexiunea la ANAF a eșuat pe toate adresele — "
                    + "; ".join(errors))


def check_status(index: str, cif: str, ghiseu: bool = False) -> list[DocumentStatus]:
    """All documents submitted for `cif` in the last 3 months.

    ANAF requires one valid (index, cif) pair to answer; the response then
    covers every recent submission for that CIF, so one call can refresh many
    stored declarations at once. Returns [] when the pair is not recognized.
    """
    html = _fetch("/vizualizareStare.do",
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
    data = _fetch(f"/ObtineRecipisa?numefisier={str(index).strip()}.pdf")
    if not data.startswith(b"%PDF"):
        raise AnafError(
            "ANAF nu a returnat un PDF — recipisa nu este încă disponibilă "
            "sau perioada de 60 de zile a expirat.")
    return data
