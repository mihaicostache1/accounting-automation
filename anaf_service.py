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


def _cui_number(cui: str) -> str:
    """ANAF expects the numeric CIF — strip the optional RO prefix."""
    return cui.strip().upper().removeprefix("RO").strip()


def _sync_cell(job: CellJob, status: anaf_client.DocumentStatus) -> CellOutcome:
    """Store the validation state and fetch the recipisa for one cell."""
    database.update_status_fields(job.firma_id, job.tip, job.an, job.luna,
                                  stare_validare=status.stare)
    label = anaf_client.STARE_LABELS.get(status.stare, status.stare_text)

    downloaded = False
    if status.recipisa_disponibila:
        rel = file_manager.relative_doc_path(job.cui, job.an, job.luna,
                                             job.tip, "recipisa")
        dest = database.get_base_folder() / rel
        if not dest.is_file():
            pdf = anaf_client.download_recipisa(job.index)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(pdf)
            downloaded = True
        database.update_status_fields(job.firma_id, job.tip, job.an, job.luna,
                                      status_recipisa=1, path_recipisa=str(rel))

    parts = [label]
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

            by_index = {s.index: s for s in statuses}
            for job in jobs:
                status = by_index.get(str(job.index).strip())
                if status is None:
                    outcomes.append(CellOutcome(
                        job, False, None,
                        "Indexul nu apare în lista ANAF (verificați indexul și "
                        "CIF-ul; serviciul acoperă doar ultimele 3 luni)."))
                    continue
                try:
                    outcomes.append(_sync_cell(job, status))
                except anaf_client.AnafError as exc:
                    outcomes.append(CellOutcome(job, False, status.stare, str(exc)))

        self.completed.emit(outcomes)
