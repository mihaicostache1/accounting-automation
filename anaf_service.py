"""Background bridge between the UI and `anaf_client`.

`RecipisaWorker` runs on a QThread: for every requested cell it asks ANAF for
the validation state, stores it in the DB and, when available, downloads the
recipisa PDF into the organized folder structure. One HTTP call per company
(CIF) is enough — ANAF's answer lists every submission of the last 3 months.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QThread, Signal

import anaf_client
import database
import file_manager


@dataclass
class CellJob:
    firma_id: int
    cui: str
    nume_firma: str
    tip: str
    an: int
    luna: int
    index: str


@dataclass
class CellOutcome:
    job: CellJob
    ok: bool
    stare: str | None      # anaf_client.STARE_* or None on failure
    message: str           # human-readable summary line
    recipisa_downloaded: bool = False


# Host the app normally talks to; anything else means it fell back to the
# mirror, which is worth showing so an ANAF outage is visible rather than
# looking like the app being slow.
_MAIN_HOST = "www.anaf.ro"


def _cui_number(cui: str) -> str:
    """ANAF expects the numeric CIF — strip the optional RO prefix."""
    return cui.strip().upper().removeprefix("RO").strip()


def _pick_status(job: CellJob, by_index: dict[str, anaf_client.DocumentStatus]
                 ) -> anaf_client.DocumentStatus | None:
    """The ANAF row that describes this cell's declaration.

    Normally the stored index. But a declaration that was resent (because the
    first upload looked failed) has a valid earlier submission and a newer one
    ANAF rejects as a duplicate — the valid one is the real answer. Walk the
    cell's index history newest first and take the first valid submission,
    unless a newer one is still being processed (it may be a correction that
    will replace the older valid one, so wait for its verdict).
    """
    current = by_index.get(str(job.index).strip())
    history = database.list_index_history(job.firma_id, job.tip, job.an, job.luna)
    for index in history:
        status = by_index.get(index)
        if status is None:
            continue
        if status.stare == anaf_client.STARE_VALID:
            return status
        if status.stare in (anaf_client.STARE_IN_PRELUCRARE,
                            anaf_client.STARE_NECUNOSCUT):
            break
    return current


def _sync_cell(job: CellJob, status: anaf_client.DocumentStatus) -> CellOutcome:
    """Store the validation state and fetch the recipisa for one cell."""
    switched = status.index != str(job.index).strip()
    fields = {"stare_validare": status.stare}
    if switched:
        fields["index_incarcare"] = status.index
    database.update_status_fields(job.firma_id, job.tip, job.an, job.luna, **fields)
    label = anaf_client.STARE_LABELS.get(status.stare, status.stare_text)

    downloaded = False
    if status.recipisa_disponibila:
        rel = file_manager.relative_doc_path(job.cui, job.an, job.luna,
                                             job.tip, "recipisa")
        dest = database.get_base_folder() / rel
        row = database.get_status(job.firma_id, job.tip, job.an, job.luna)
        file_index = row["index_recipisa"] if row else None
        # A file on disk may be the recipisa of another index of this cell
        # (e.g. the rejection of a duplicate) — replace it in that case.
        stale = switched or (file_index is not None and file_index != status.index)
        if stale or not dest.is_file():
            pdf = anaf_client.download_recipisa(status.index)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(pdf)
            downloaded = True
        database.update_status_fields(job.firma_id, job.tip, job.an, job.luna,
                                      status_recipisa=1, path_recipisa=str(rel),
                                      index_recipisa=status.index)

    parts = [label]
    if switched:
        parts.append(f"folosită depunerea validă cu indexul {status.index} "
                     f"(indexul {job.index} a fost respins, probabil ca duplicat)")
    if downloaded:
        parts.append("recipisă descărcată")
    elif status.recipisa_disponibila:
        parts.append("recipisă existentă")
    return CellOutcome(job, True, status.stare, ", ".join(parts), downloaded)


class RecipisaWorker(QThread):
    progress = Signal(str)        # status-bar style updates
    completed = Signal(object)    # list[CellOutcome]

    def __init__(self, jobs: list[CellJob], parent=None):
        super().__init__(parent)
        self._jobs = jobs

    def run(self) -> None:
        outcomes: list[CellOutcome] = []
        by_cui: dict[str, list[CellJob]] = {}
        for job in self._jobs:
            by_cui.setdefault(job.cui, []).append(job)

        for cui, jobs in by_cui.items():
            self.progress.emit(f"Interogare ANAF pentru {jobs[0].nume_firma}…")
            try:
                statuses = anaf_client.check_status(jobs[0].index, _cui_number(cui))
            except anaf_client.AnafError as exc:
                outcomes += [CellOutcome(j, False, None, str(exc)) for j in jobs]
                continue
            # Only meaningful after a successful call: before it, this is the
            # host we intend to try, not the one that answered.
            if anaf_client.current_host() != _MAIN_HOST:
                self.progress.emit(
                    f"ANAF principal indisponibil — se folosește "
                    f"{anaf_client.current_host()}…")

            by_index = {s.index: s for s in statuses}
            for job in jobs:
                status = _pick_status(job, by_index)
                if status is None:
                    # Store it: unlike a network error, an index ANAF does not
                    # know about is a real problem with this declaration, and
                    # the matrices must show it instead of a reassuring green.
                    database.update_status_fields(
                        job.firma_id, job.tip, job.an, job.luna,
                        stare_validare=anaf_client.STARE_NEGASIT)
                    outcomes.append(CellOutcome(
                        job, False, anaf_client.STARE_NEGASIT,
                        "Indexul nu apare în lista ANAF (verificați indexul și "
                        "CIF-ul; serviciul acoperă doar ultimele 3 luni)."))
                    continue
                try:
                    outcomes.append(_sync_cell(job, status))
                except anaf_client.AnafError as exc:
                    outcomes.append(CellOutcome(job, False, status.stare, str(exc)))

        self.completed.emit(outcomes)
