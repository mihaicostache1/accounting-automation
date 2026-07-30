"""SQLite layer: schema, queries and first-run seeding with mock data.

All paths stored in `declaratii_status` are RELATIVE to the configurable base
folder (see `get_base_folder`), so the whole archive can be moved or synced
without breaking the database.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from config import (DB_PATH, DECLARATION_TYPES, DEFAULT_BASE_FOLDER,
                    DEFAULT_SOURCE_FOLDER, type_folder_name)

SCHEMA = """
CREATE TABLE IF NOT EXISTS firme (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    nume_firma  TEXT NOT NULL,
    cui         TEXT NOT NULL UNIQUE,
    folder_sursa TEXT
);

CREATE TABLE IF NOT EXISTS declaratii_status (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    firma_id          INTEGER NOT NULL REFERENCES firme(id) ON DELETE CASCADE,
    tip_declaratie    TEXT NOT NULL,
    an                INTEGER NOT NULL,
    luna              INTEGER NOT NULL CHECK (luna BETWEEN 1 AND 12),
    status_declaratie INTEGER NOT NULL DEFAULT 0,
    path_declaratie   TEXT,
    status_recipisa   INTEGER NOT NULL DEFAULT 0,
    path_recipisa     TEXT,
    index_incarcare   TEXT,
    stare_validare    TEXT,
    UNIQUE (firma_id, tip_declaratie, an, luna)
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS firme_tipuri (
    firma_id       INTEGER NOT NULL REFERENCES firme(id) ON DELETE CASCADE,
    tip_declaratie TEXT NOT NULL,
    PRIMARY KEY (firma_id, tip_declaratie)
);
"""


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Create the schema, migrate older DBs and seed mock data on first run."""
    with get_connection() as conn:
        conn.executescript(SCHEMA)
        _migrate_anaf_columns(conn)
        _migrate_firma_folder(conn)
        empty = conn.execute("SELECT COUNT(*) FROM firme").fetchone()[0] == 0
        if not empty:
            _migrate_firma_tipuri(conn)
    if empty:
        seed_mock_data()


def _migrate_anaf_columns(conn: sqlite3.Connection) -> None:
    """Add the ANAF tracking columns to DBs created before they existed."""
    existing = {r["name"] for r in
                conn.execute("PRAGMA table_info(declaratii_status)").fetchall()}
    for column in ("index_incarcare", "stare_validare"):
        if column not in existing:
            conn.execute(f"ALTER TABLE declaratii_status ADD COLUMN {column} TEXT")


def _migrate_firma_folder(conn: sqlite3.Connection) -> None:
    """Add the per-firm source-folder override to DBs created before it existed."""
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(firme)").fetchall()}
    if "folder_sursa" not in existing:
        conn.execute("ALTER TABLE firme ADD COLUMN folder_sursa TEXT")


def _migrate_firma_tipuri(conn: sqlite3.Connection) -> None:
    """Backfill `firme_tipuri` for firms created before the table existed:
    assign the types they already have data for, or all types otherwise."""
    orphans = conn.execute(
        "SELECT id FROM firme WHERE id NOT IN (SELECT firma_id FROM firme_tipuri)"
    ).fetchall()
    for (firma_id,) in orphans:
        used = [r[0] for r in conn.execute(
            "SELECT DISTINCT tip_declaratie FROM declaratii_status WHERE firma_id = ?",
            (firma_id,)).fetchall()]
        for tip in (used or DECLARATION_TYPES):
            conn.execute(
                "INSERT OR IGNORE INTO firme_tipuri (firma_id, tip_declaratie) VALUES (?, ?)",
                (firma_id, tip))


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #

def get_setting(key: str, default: str | None = None) -> str | None:
    with get_connection() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def get_base_folder() -> Path:
    return Path(get_setting("base_folder", str(DEFAULT_BASE_FOLDER)))


def set_base_folder(path: Path | str) -> None:
    set_setting("base_folder", str(path))


def get_source_folder() -> Path:
    """Folder the app reads declarations from for uploading (see upload_scanner)."""
    return Path(get_setting("source_folder", str(DEFAULT_SOURCE_FOLDER)))


def set_source_folder(path: Path | str) -> None:
    set_setting("source_folder", str(path))


# --------------------------------------------------------------------------- #
# Firme
# --------------------------------------------------------------------------- #

def list_firme() -> list[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            "SELECT id, nume_firma, cui, folder_sursa FROM firme "
            "ORDER BY nume_firma COLLATE NOCASE"
        ).fetchall()


def add_firma(nume: str, cui: str) -> int:
    """Insert a company; raises sqlite3.IntegrityError on duplicate CUI."""
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO firme (nume_firma, cui) VALUES (?, ?)", (nume.strip(), cui.strip())
        )
        return cur.lastrowid


def update_firma(firma_id: int, nume: str, cui: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE firme SET nume_firma = ?, cui = ? WHERE id = ?",
            (nume.strip(), cui.strip(), firma_id),
        )


def delete_firma(firma_id: int) -> None:
    """Delete a firm and everything derived from it (statuses, applicable
    types) via the ON DELETE CASCADE foreign keys. Does not touch archived
    PDFs on disk."""
    with get_connection() as conn:
        conn.execute("DELETE FROM firme WHERE id = ?", (firma_id,))


def get_firma_source_folder(firma_id: int) -> Path | None:
    """Per-firm override of the source folder, or None to use the global one
    (see database.get_source_folder)."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT folder_sursa FROM firme WHERE id = ?", (firma_id,)
        ).fetchone()
    return Path(row["folder_sursa"]) if row and row["folder_sursa"] else None


def set_firma_source_folder(firma_id: int, path: Path | str | None) -> None:
    """Set or clear (path=None) the per-firm source-folder override."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE firme SET folder_sursa = ? WHERE id = ?",
            (str(path) if path else None, firma_id),
        )


def get_firma_tipuri(firma_id: int) -> list[str]:
    """Declaration types applicable to one firm, in DECLARATION_TYPES order."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT tip_declaratie FROM firme_tipuri WHERE firma_id = ?", (firma_id,)
        ).fetchall()
    tipuri = {r["tip_declaratie"] for r in rows}
    return [t for t in DECLARATION_TYPES if t in tipuri]


def get_all_firma_tipuri() -> dict[int, set[str]]:
    """{firma_id: applicable declaration types} for every firm."""
    with get_connection() as conn:
        rows = conn.execute("SELECT firma_id, tip_declaratie FROM firme_tipuri").fetchall()
    result: dict[int, set[str]] = {}
    for r in rows:
        result.setdefault(r["firma_id"], set()).add(r["tip_declaratie"])
    return result


def set_firma_tipuri(firma_id: int, tipuri: list[str]) -> None:
    """Replace the set of declaration types applicable to one firm."""
    with get_connection() as conn:
        conn.execute("DELETE FROM firme_tipuri WHERE firma_id = ?", (firma_id,))
        conn.executemany(
            "INSERT INTO firme_tipuri (firma_id, tip_declaratie) VALUES (?, ?)",
            [(firma_id, tip) for tip in tipuri],
        )


# --------------------------------------------------------------------------- #
# Declaration statuses
# --------------------------------------------------------------------------- #

def get_status(firma_id: int, tip: str, an: int, luna: int) -> sqlite3.Row | None:
    """Full status row for one cell, or None if nothing was recorded yet."""
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM declaratii_status "
            "WHERE firma_id = ? AND tip_declaratie = ? AND an = ? AND luna = ?",
            (firma_id, tip, an, luna),
        ).fetchone()


def get_type_matrix(firma_id: int, tip: str) -> dict[tuple[int, int], tuple[bool, str | None]]:
    """{(an, luna): (declaration_submitted, stare_validare)} for every recorded
    cell of one type — the ANAF state drives the yellow 'validation errors'
    color in the matrices."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT an, luna, status_declaratie, stare_validare "
            "FROM declaratii_status WHERE firma_id = ? AND tip_declaratie = ?",
            (firma_id, tip),
        ).fetchall()
    return {(r["an"], r["luna"]): (bool(r["status_declaratie"]), r["stare_validare"])
            for r in rows}


def get_month_overview(an: int, luna: int) -> dict[tuple[int, str], tuple[bool, bool, str | None]]:
    """{(firma_id, tip): (declaration_submitted, receipt_submitted,
    stare_validare)} for one month."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT firma_id, tip_declaratie, status_declaratie, status_recipisa, "
            "stare_validare FROM declaratii_status WHERE an = ? AND luna = ?",
            (an, luna),
        ).fetchall()
    return {(r["firma_id"], r["tip_declaratie"]):
            (bool(r["status_declaratie"]), bool(r["status_recipisa"]),
             r["stare_validare"])
            for r in rows}


def update_status_fields(firma_id: int, tip: str, an: int, luna: int, **fields) -> None:
    """Upsert one cell, setting any of: status_declaratie, path_declaratie,
    status_recipisa, path_recipisa, index_incarcare, stare_validare."""
    allowed = {"status_declaratie", "path_declaratie", "status_recipisa",
               "path_recipisa", "index_incarcare", "stare_validare"}
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"Unknown status fields: {bad}")
    columns = ", ".join(fields)
    placeholders = ", ".join("?" for _ in fields)
    updates = ", ".join(f"{col} = excluded.{col}" for col in fields)
    with get_connection() as conn:
        conn.execute(
            f"INSERT INTO declaratii_status (firma_id, tip_declaratie, an, luna, {columns}) "
            f"VALUES (?, ?, ?, ?, {placeholders}) "
            f"ON CONFLICT(firma_id, tip_declaratie, an, luna) DO UPDATE SET {updates}",
            (firma_id, tip, an, luna, *fields.values()),
        )


def list_pending_recipise() -> list[sqlite3.Row]:
    """Cells that have an ANAF index but no downloaded recipisa yet, or whose
    last known state is still 'in prelucrare' — the bulk-check work list."""
    with get_connection() as conn:
        return conn.execute(
            "SELECT ds.*, f.cui, f.nume_firma FROM declaratii_status ds "
            "JOIN firme f ON f.id = ds.firma_id "
            "WHERE ds.index_incarcare IS NOT NULL AND ds.index_incarcare != '' "
            "AND (ds.status_recipisa = 0 OR ds.path_recipisa IS NULL "
            "     OR ds.stare_validare IS NULL OR ds.stare_validare = 'in_prelucrare') "
            "ORDER BY f.nume_firma COLLATE NOCASE, ds.an, ds.luna",
        ).fetchall()


# --------------------------------------------------------------------------- #
# Mock data (first run only)
# --------------------------------------------------------------------------- #

def _write_placeholder_pdf(path: Path, title: str) -> None:
    """Write a tiny but valid single-page PDF showing `title`, so the green
    buttons open a real document in the system viewer."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = title.encode("latin-1", "replace").decode("latin-1")
    stream = f"BT /F1 16 Tf 60 780 Td ({text}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (i, body)
    xref_pos = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += (
        b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
        % (len(objects) + 1, xref_pos)
    )
    path.write_bytes(bytes(out))


def seed_mock_data() -> None:
    """Insert 3 demo companies with a realistic mix of submitted / missing
    declarations for 2026, including placeholder PDFs on disk."""
    base = get_base_folder()

    firme = [
        ("SC Alfa Consulting SRL", "RO12345678"),
        ("SC Beta Impex SRL", "RO87654321"),
        ("SC Gama Cont SRL", "RO11223344"),
    ]
    # Applicable declaration types differ per demo firm (drives Tab 1 buttons
    # and the gray "not applicable" cells in Tab 2).
    tipuri_firma = {
        "RO12345678": ["100", "112", "300", "390"],
        "RO87654321": ["100", "300", "406", "Case de marcat"],
        "RO11223344": ["100", "112", "390"],
    }
    ids = {}
    for nume, cui in firme:
        ids[cui] = add_firma(nume, cui)
        set_firma_tipuri(ids[cui], tipuri_firma[cui])

    # (cui, tip, months with declaration, months that ALSO have the receipt)
    seed = [
        ("RO12345678", "100", range(1, 7), range(1, 6)),
        ("RO12345678", "112", range(1, 7), range(1, 7)),
        ("RO12345678", "300", range(1, 5), range(1, 4)),
        ("RO12345678", "390", [1, 2, 3, 5], [1, 2, 3]),
        ("RO87654321", "100", range(1, 4), range(1, 3)),
        ("RO87654321", "300", range(1, 7), range(1, 7)),
        ("RO87654321", "406", [1, 3, 5], [1, 3]),
        ("RO87654321", "Case de marcat", range(1, 6), range(1, 5)),
        ("RO11223344", "100", range(1, 7), range(1, 7)),
        ("RO11223344", "112", [1, 2, 4, 5, 6], [1, 2, 4]),
        ("RO11223344", "390", range(1, 3), range(1, 3)),
    ]
    an = 2026
    for cui, tip, decl_months, rec_months in seed:
        firma_id = ids[cui]
        rec_set = set(rec_months)
        for luna in decl_months:
            folder = Path(cui) / str(an) / f"{luna:02d}" / type_folder_name(tip)
            fields = {}

            rel_decl = folder / "declaratie.pdf"
            _write_placeholder_pdf(base / rel_decl,
                                   f"Declaratie {tip} - {cui} - {luna:02d}/{an}")
            fields["status_declaratie"] = 1
            fields["path_declaratie"] = str(rel_decl)

            if luna in rec_set:
                rel_rec = folder / "recipisa.pdf"
                _write_placeholder_pdf(base / rel_rec,
                                       f"Recipisa {tip} - {cui} - {luna:02d}/{an}")
                fields["status_recipisa"] = 1
                fields["path_recipisa"] = str(rel_rec)

            update_status_fields(firma_id, tip, an, luna, **fields)
