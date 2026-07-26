"""Work out what each PDF in the source folder is, before anything is uploaded.

The source folder is the accountant's own tree, not the app's organized archive,
so the layout is whatever it happens to be. Observed shape:

    E:\\1. Declaratii 100\\<CUI NAME>\\...\\d100_iunie.pdf

Nothing here is authoritative: every field is a *guess* with a reason attached,
and `scan()` deliberately returns rows it could not resolve (company/period
missing) rather than dropping them. The review dialog shows the guesses and the
user corrects them — uploads to ANAF cannot be undone, so no file is ever sent
on the strength of a filename match alone.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import database
from config import DECLARATION_TYPES, MONTHS_LONG, MONTHS_SHORT

# Declaration types that appear as bare numbers in paths ("Declaratii 100").
_NUMERIC_TYPES = [t for t in DECLARATION_TYPES if t.isdigit()]

# Company-name noise that must not take part in matching.
_LEGAL_FORMS = {"SC", "SRL", "SA", "PFA", "II", "SNC", "SCS", "SRLD"}


def _fold(text: str) -> str:
    """Uppercase, strip diacritics and collapse to single spaces.

    'Societate Comercială Alfa-Consulting S.R.L.' -> 'SOCIETATE COMERCIALA ALFA CONSULTING S R L'
    """
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^0-9A-Za-z]+", " ", ascii_only).upper().split())


def _name_tokens(nume: str) -> set[str]:
    """Significant words of a company name (legal forms and initials dropped)."""
    return {w for w in _fold(nume).split() if len(w) > 1 and w not in _LEGAL_FORMS}


def _cui_digits(cui: str) -> str:
    return re.sub(r"\D", "", cui)


@dataclass
class Candidate:
    """One PDF found in the source folder, with the app's best guess at what it is.

    `firma_id is None` or `an`/`luna is None` means "could not tell" — the row is
    still returned so the user can resolve it in the dialog.
    """
    path: Path
    firma_id: int | None = None
    nume_firma: str | None = None
    cui: str | None = None
    tip: str | None = None
    an: int | None = None
    luna: int | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def resolved(self) -> bool:
        """True when there is enough information to attempt an upload."""
        return None not in (self.firma_id, self.tip, self.an, self.luna)


def _match_firma(haystack: str, firme: list) -> tuple[object | None, str]:
    """Identify the company from a folded path string.

    CUI wins over name: an 8-9 digit fiscal code is unambiguous, whereas name
    matching can tie between similarly-named firms. Returns (row, reason).
    """
    digits = re.sub(r"\D", " ", haystack)
    for row in firme:
        cui = _cui_digits(row["cui"])
        if cui and re.search(rf"\b{cui}\b", digits):
            return row, f"CUI {cui} găsit în cale"

    words = set(haystack.split())
    best, best_score = None, 0
    for row in firme:
        tokens = _name_tokens(row["nume_firma"])
        if not tokens:
            continue
        score = len(tokens & words)
        # Require every significant word of the name to appear, so 'Alfa Cont'
        # does not swallow a file that belongs to 'Alfa Consulting'.
        if score == len(tokens) and score > best_score:
            best, best_score = row, score
    if best is not None:
        return best, f"nume „{best['nume_firma']}” găsit în cale"
    return None, "firma nu a putut fi identificată"


def _match_tip(haystack: str) -> tuple[str | None, str]:
    """Identify the declaration type. Later path segments win, since the file
    name is more specific than an ancestor folder like 'Declaratii 100'."""
    if "CASE DE MARCAT" in haystack:
        return "Case de marcat", "„case de marcat” găsit în cale"

    # Bounded by non-digits rather than \b: filenames commonly glue a letter
    # prefix straight onto the code ('d100.pdf' has no word boundary between
    # 'D' and '100'), but a real match must still be the FULL numeric code,
    # not a substring of a longer number.
    found = [(m.start(), m.group()) for m in
             re.finditer(rf"(?<!\d)(?:{'|'.join(_NUMERIC_TYPES)})(?!\d)", haystack)]
    if found:
        _, tip = max(found)
        return tip, f"tip {tip} găsit în cale"
    return None, "tipul declarației nu a putut fi identificat"


def _match_period(haystack: str) -> tuple[int | None, int | None, str]:
    """Identify year and month from the path.

    Tries explicit numeric pairs first (2026-06, 06.2026), then a Romanian month
    name combined with any 4-digit year present.
    """
    if m := re.search(r"\b(20\d{2})\D{0,3}(0[1-9]|1[0-2])\b", haystack):
        return int(m.group(1)), int(m.group(2)), "an/lună din cale"
    if m := re.search(r"\b(0[1-9]|1[0-2])\D{0,3}(20\d{2})\b", haystack):
        return int(m.group(2)), int(m.group(1)), "lună/an din cale"

    year = None
    if m := re.search(r"\b(20\d{2})\b", haystack):
        year = int(m.group(1))

    words = haystack.split()
    for idx, (long_name, short_name) in enumerate(zip(MONTHS_LONG, MONTHS_SHORT), start=1):
        folded_long, folded_short = _fold(long_name), _fold(short_name)
        if folded_long in words or folded_short in words:
            if year is not None:
                return year, idx, f"luna „{long_name}” din cale"
            return None, idx, f"luna „{long_name}” găsită, anul lipsește"

    if year is not None:
        return year, None, "anul găsit, luna lipsește"
    return None, None, "perioada nu a putut fi identificată"


def _scan_folder(root: Path, firme: list, preset_firma=None) -> list[Candidate]:
    """Find every PDF under `root` and guess type / period for it.

    When `preset_firma` is given (a firm's dedicated folder), the company is
    already known and is never guessed; otherwise it is matched against
    `firme` the same way as the shared source folder.
    """
    candidates: list[Candidate] = []
    for pdf in sorted(root.rglob("*.pdf")):
        # Match against the path *relative* to the root: absolute paths carry
        # noise ('1. Declaratii 100' is useful, 'C:\\Users\\...' is not).
        relative = pdf.relative_to(root)
        haystack = _fold(str(relative))

        cand = Candidate(path=pdf)
        if preset_firma is not None:
            cand.firma_id = preset_firma["id"]
            cand.nume_firma = preset_firma["nume_firma"]
            cand.cui = preset_firma["cui"]
            why_firma = f"folder dedicat firmei „{preset_firma['nume_firma']}”"
        else:
            firma, why_firma = _match_firma(haystack, firme)
            if firma is not None:
                cand.firma_id = firma["id"]
                cand.nume_firma = firma["nume_firma"]
                cand.cui = firma["cui"]
        cand.tip, why_tip = _match_tip(haystack)
        cand.an, cand.luna, why_period = _match_period(haystack)
        cand.notes = [why_firma, why_tip, why_period]
        candidates.append(cand)
    return candidates


def scan(folder: Path | str | None = None) -> list[Candidate]:
    """Find every declaration PDF and guess company / type / period for it.

    With an explicit `folder`, scans only that folder and guesses the company
    among every firm (used to preview a single folder in isolation). With no
    argument (the normal case), combines every firm's dedicated folder — where
    the company is already known, not guessed — with the shared source folder
    for firms that have no override.

    Returns rows sorted so the ones needing attention surface first. Raises
    FileNotFoundError if the (combined-mode) shared folder does not exist, so
    the caller can point the user at the folder setting; a missing per-firm
    folder is skipped rather than raised, since most firms won't have one.
    """
    firme = database.list_firme()

    if folder is not None:
        root = Path(folder)
        if not root.is_dir():
            raise FileNotFoundError(root)
        candidates = _scan_folder(root, firme)
        candidates.sort(key=lambda c: (c.resolved, str(c.path)))
        return candidates

    seen: set[Path] = set()
    candidates: list[Candidate] = []
    any_dedicated = False
    for firma in firme:
        if not firma["folder_sursa"]:
            continue
        dedicated = Path(firma["folder_sursa"])
        if not dedicated.is_dir():
            continue
        any_dedicated = True
        for cand in _scan_folder(dedicated, firme, preset_firma=firma):
            if cand.path.resolve() not in seen:
                seen.add(cand.path.resolve())
                candidates.append(cand)

    # The shared folder still matches against EVERY firm — having a dedicated
    # folder must not make a firm unrecognizable in the shared one.
    shared = database.get_source_folder()
    if shared.is_dir():
        for cand in _scan_folder(shared, firme):
            if cand.path.resolve() not in seen:
                seen.add(cand.path.resolve())
                candidates.append(cand)
    elif not any_dedicated:
        raise FileNotFoundError(shared)

    candidates.sort(key=lambda c: (c.resolved, str(c.path)))
    return candidates
