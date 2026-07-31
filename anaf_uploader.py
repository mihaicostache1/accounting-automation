"""Drive an authenticated ANAF upload session in the user's own browser.

ANAF's upload page authenticates with a hardware certificate/token, which
cannot be done headlessly. So the app never handles credentials: it starts
Chrome with a remote-debugging port, the user signs in there by hand, and the
app then attaches over CDP and drives that already-authenticated tab.

Playwright is used only as a CDP *client* (`connect_over_cdp`) — it never
downloads or launches its own Chromium, so `playwright install` is not needed
and the PyInstaller bundle stays free of browser binaries.

A dedicated Chrome profile (not the default one) is used because recent Chrome
refuses remote debugging on the default profile. Certificates are unaffected:
on Windows the token is reached through the system certificate store, which is
per-machine, and the profile persists so the session survives a restart.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QThread, Signal

import database
import file_manager
from config import ANAF_UPLOAD_URL, CHROME_DEBUG_PORT

# "Indexul de încărcare este 123456789" on the WAS6DUS success page.
_INDEX_RE = re.compile(r"index(?:ul)?[^0-9]{0,40}?(\d{6,})", re.IGNORECASE)

_PROFILE_DIR = Path(
    os.environ.get("LOCALAPPDATA", str(Path.home() / ".local" / "share"))
) / "DeclaratiiFirme" / "chrome-profile"

_CHROME_CANDIDATES = {
    "Windows": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ],
    "Darwin": [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ],
    "Linux": ["google-chrome", "chromium", "chromium-browser", "microsoft-edge"],
}


class UploadError(RuntimeError):
    """Anything that stops a declaration from being submitted."""


@dataclass
class UploadJob:
    """One declaration to submit. Mirrors a resolved `upload_scanner.Candidate`."""
    path: Path
    firma_id: int
    cui: str
    nume_firma: str
    tip: str
    an: int
    luna: int


@dataclass
class UploadOutcome:
    job: UploadJob
    ok: bool
    index: str | None
    message: str


# --------------------------------------------------------------------------- #
# Browser plumbing
# --------------------------------------------------------------------------- #

def find_browser() -> str | None:
    """Path to an installed Chrome/Edge, or None if nothing was found."""
    for candidate in _CHROME_CANDIDATES.get(platform.system(), []):
        if Path(candidate).is_file():
            return candidate
        if found := shutil.which(candidate):
            return found
    return None


def debugger_ready(port: int = CHROME_DEBUG_PORT) -> bool:
    """True when a Chrome with an open debugging port is already listening."""
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/json/version", timeout=2) as resp:
            json.load(resp)
        return True
    except (urllib.error.URLError, OSError, ValueError):
        return False


def launch_browser(port: int = CHROME_DEBUG_PORT) -> None:
    """Start Chrome on the ANAF upload page with debugging enabled.

    Returns as soon as the process is spawned — the caller waits for the user to
    finish signing in. Does nothing if a debuggable Chrome is already running.
    """
    if debugger_ready(port):
        return
    browser = find_browser()
    if browser is None:
        raise UploadError(
            "Nu am găsit Google Chrome sau Microsoft Edge. Instalați Chrome "
            "pentru a putea trimite declarațiile.")
    _PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(
        [browser, f"--remote-debugging-port={port}",
         f"--user-data-dir={_PROFILE_DIR}", "--no-first-run",
         "--no-default-browser-check", ANAF_UPLOAD_URL],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def close_browser(port: int = CHROME_DEBUG_PORT) -> None:
    """Close the debugging Chrome started by `launch_browser`.

    Only the app's own instance is targeted (matched on its dedicated profile
    directory), so the user's everyday Chrome windows are left alone.
    """
    if platform.system() == "Windows":
        # PowerShell rather than wmic, which no longer ships on current Windows.
        cmd = ["powershell", "-NoProfile", "-Command",
               "Get-CimInstance Win32_Process -Filter \"Name like '%chrome%'\" | "
               f"Where-Object {{ $_.CommandLine -like '*{_PROFILE_DIR.name}*' }} | "
               "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"]
    else:
        cmd = ["pkill", "-f", f"remote-debugging-port={port}"]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   check=False)


def _connect(pw):
    """Attach to the user's Chrome, translating the one failure mode that has a
    known remedy into an instruction the user can act on.

    Playwright's disconnect leaves Chrome's browser-level CDP target unusable by
    a *later* process, so an app restart against a still-running Chrome fails
    here even though the port is open. Restarting Chrome clears it; the login
    usually survives because the profile is persistent.
    """
    try:
        return pw.chromium.connect_over_cdp(f"http://127.0.0.1:{CHROME_DEBUG_PORT}")
    except Exception as exc:
        if "context management" in str(exc).lower():
            raise UploadError(
                "Sesiunea Chrome a rămas într-o stare inutilizabilă după o "
                "rulare anterioară a aplicației.\n\n"
                "Apăsați „♻ Repornește Chrome”, autentificați-vă din nou, apoi "
                "reluați trimiterea.") from exc
        raise UploadError(f"Nu m-am putut conecta la Chrome: {exc}") from exc


def _require_playwright():
    """Import Playwright with an actionable message when it is missing."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise UploadError(
            "Modulul Playwright lipsește. Instalați-l cu:\n"
            "    pip install playwright") from exc
    return sync_playwright


# --------------------------------------------------------------------------- #
# The upload itself
# --------------------------------------------------------------------------- #

def _submit_one(page, job: UploadJob) -> str:
    """Upload one PDF on the current page and return the ANAF index.

    Raises UploadError with a snippet of the page when the expected form or the
    index cannot be found, so a page-layout change is diagnosable from the log.
    """
    page.goto(ANAF_UPLOAD_URL, wait_until="domcontentloaded")

    file_input = page.locator("input[type=file]").first
    if file_input.count() == 0:
        raise UploadError(
            "Pagina ANAF nu conține un câmp de încărcare fișier. "
            "Probabil sesiunea nu este autentificată — reautentificați-vă în "
            "Chrome și încercați din nou.")
    file_input.set_input_files(str(job.path))

    # The submit control is labelled differently across ANAF's forms.
    for selector in ("input[type=submit]", "button[type=submit]",
                     "text=/Trimite|Transmite|Incarca|Încarcă/i"):
        button = page.locator(selector).first
        if button.count():
            button.click()
            break
    else:
        raise UploadError("Nu am găsit butonul de trimitere pe pagina ANAF.")

    page.wait_for_load_state("domcontentloaded")
    body = page.inner_text("body")
    if m := _INDEX_RE.search(body):
        return m.group(1)
    raise UploadError(
        "Fișierul a fost trimis dar nu am putut citi indexul de încărcare. "
        f"Verificați manual în Chrome. Text pagină: {body[:300].strip()!r}")


def _archive_and_record(job: UploadJob, index: str) -> None:
    """Copy the sent PDF into the organized archive and store the index, so the
    existing recipisa poller (anaf_service) can pick the cell up from here."""
    rel = file_manager.import_pdf(job.path, job.cui, job.an, job.luna,
                                  job.tip, "declaratie")
    database.update_status_fields(
        job.firma_id, job.tip, job.an, job.luna,
        status_declaratie=1, path_declaratie=str(rel), index_incarcare=index)


class UploadWorker(QThread):
    """Uploads a list of declarations through an already-authenticated Chrome."""

    progress = Signal(str)
    completed = Signal(object)   # list[UploadOutcome]

    def __init__(self, jobs: list[UploadJob], parent=None):
        super().__init__(parent)
        self._jobs = jobs

    def run(self) -> None:
        outcomes: list[UploadOutcome] = []
        try:
            sync_playwright = _require_playwright()
        except UploadError as exc:
            self.completed.emit(
                [UploadOutcome(j, False, None, str(exc)) for j in self._jobs])
            return

        try:
            with sync_playwright() as pw:
                browser = _connect(pw)
                context = browser.contexts[0] if browser.contexts else browser.new_context()
                page = context.pages[0] if context.pages else context.new_page()

                for n, job in enumerate(self._jobs, start=1):
                    self.progress.emit(
                        f"({n}/{len(self._jobs)}) {job.nume_firma} — "
                        f"{job.tip} {job.luna:02d}/{job.an}…")
                    try:
                        index = _submit_one(page, job)
                        _archive_and_record(job, index)
                        outcomes.append(UploadOutcome(
                            job, True, index, f"trimis, index {index}"))
                    except Exception as exc:            # one bad file must not
                        outcomes.append(UploadOutcome(  # abort the whole batch
                            job, False, None, str(exc)))
        except Exception as exc:
            done = {id(o.job) for o in outcomes}
            outcomes += [UploadOutcome(j, False, None, f"sesiune întreruptă: {exc}")
                         for j in self._jobs if id(j) not in done]

        self.completed.emit(outcomes)
