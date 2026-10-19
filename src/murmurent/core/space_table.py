"""
Purpose: The space table (issue #151, step 2): one row per suggestion about a
         file or folder, kept where only the person who ran the scan can read
         it, with the decision a person records against each row.
Author:  Mike Hallett (with Claude Code)
Date:    2026-10-16
Input:   Results of :func:`core.space_scan.scan_project`; decisions typed with
         ``murmurent space decide``.
Output:  ``~/.murmurent/space/space.sqlite`` (folder mode 0700, file 0600), and
         the rows, the top three and any emergencies read back from it.

Why a database in the home folder. The PI asked for the table in their own
dashboard, PI only, and warned it may be large. The lab's shared data drive
gives the whole group read and write access whatever permissions are set, so a
table of file names there could not be kept private. The home folder can. A
small database rather than a spreadsheet, so a table of a million rows can be
filtered quickly.

The millwright never decides. ``decision``, ``decided_by`` and ``decided_at``
are written only by :func:`decide`, from a person's command. A rescan keeps
every decision. Nothing here moves or deletes a file; carrying out decisions is
step 6 (:mod:`core.space_actions`), which logs each action in ``actions``.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import project_unit as _pu

TABLE_FILENAME = "space.sqlite"
TABLE_SCHEMA = 1

# The categories of a row. The first six are the plan's; ``listed`` is a file a
# member already put in ``src/ready_to_delete.md``; ``access`` goes to the
# security guard; ``unreadable`` is a folder the scan could not look into.
TEMPORARY = "temporary"
INTERMEDIATE = "intermediate"
COMPRESSIBLE = "compressible"
DUPLICATE = "duplicate"
OUT_OF_PLACE = "out of place"
UNATTRIBUTED = "unattributed"
LISTED = "listed"
ACCESS = "access"
UNREADABLE = "unreadable"
# From the lab-wide scan (step 3): a data folder no project claims, and a
# project unused for long enough to be called dormant.
UNCLAIMED = "unclaimed"
DORMANT = "dormant"
CATEGORIES = (TEMPORARY, INTERMEDIATE, COMPRESSIBLE, DUPLICATE, OUT_OF_PLACE,
              UNATTRIBUTED, LISTED, ACCESS, UNREADABLE, UNCLAIMED, DORMANT)

# What the millwright suggests. A person's decision uses the same words.
DELETE = "delete"
MOTHBALL = "mothball"
COMPRESS = "compress"
MOVE = "move"
KEEP = "keep"
ASK_OWNER = "ask the owner"
REFER_SECURITY = "refer to security guard"
SUGGESTIONS = (DELETE, MOTHBALL, COMPRESS, MOVE, KEEP, ASK_OWNER, REFER_SECURITY)
DECISIONS = (DELETE, MOTHBALL, COMPRESS, MOVE, KEEP)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY,
    project TEXT NOT NULL,
    started_at TEXT, finished_at TEXT, scanned_by TEXT,
    files INTEGER, bytes INTEGER, unreadable INTEGER,
    notes TEXT
);
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY,
    project TEXT NOT NULL,
    path TEXT NOT NULL,
    category TEXT NOT NULL,
    kind TEXT, size INTEGER, n_files INTEGER, owner TEXT, changed_at TEXT,
    suggestion TEXT, reason TEXT, evidence TEXT, cost_cpu_hours REAL,
    peek TEXT, disk TEXT,
    first_seen TEXT, last_seen TEXT, last_scan INTEGER, previous_size INTEGER,
    gone INTEGER NOT NULL DEFAULT 0,
    decision TEXT, decided_by TEXT, decided_at TEXT, decision_note TEXT,
    UNIQUE (project, path, category)
);
CREATE INDEX IF NOT EXISTS items_project ON items (project);
CREATE TABLE IF NOT EXISTS sop_gaps (
    project TEXT NOT NULL, kind TEXT NOT NULL, detail TEXT NOT NULL,
    example TEXT, count INTEGER, size INTEGER,
    first_seen TEXT, last_seen TEXT,
    UNIQUE (project, kind, detail)
);
CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL, project TEXT NOT NULL, action TEXT NOT NULL,
    source TEXT NOT NULL, destination TEXT, status TEXT NOT NULL,
    files INTEGER, bytes INTEGER, detail TEXT, done_by TEXT,
    started_at TEXT, finished_at TEXT
);
CREATE TABLE IF NOT EXISTS disks (
    project TEXT NOT NULL, disk TEXT NOT NULL, label TEXT,
    total INTEGER, free INTEGER, scanned_at TEXT,
    UNIQUE (project, disk)
);
"""


def now_iso() -> str:
    """The current time, local zone, to the second."""
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def table_path() -> Path:
    """Where the table lives: ``<murmurent home>/space/space.sqlite``."""
    return _pu.murmurent_home() / _pu.SPACE_SUBDIR / TABLE_FILENAME


def connect(path: Path | None = None) -> sqlite3.Connection:
    """Open the table, creating it private (folder 0700, file 0600) on first use.

    Parameters
    ----------
    path : Path, optional
        The database file; defaults to :func:`table_path`.

    Returns
    -------
    sqlite3.Connection
        Rows come back as :class:`sqlite3.Row`.
    """
    path = path or table_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not path.exists():
        os.close(os.open(path, os.O_WRONLY | os.O_CREAT, 0o600))
    os.chmod(path, 0o600)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA_SQL)
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('schema', ?)",
                 (str(TABLE_SCHEMA),))
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# What a scan hands over
# ---------------------------------------------------------------------------


@dataclass
class Item:
    """One suggestion about a file, a folder, or a group of files.

    ``path`` is a file or folder. ``kind`` says which: ``file``, ``folder`` (the
    whole folder) or ``files`` (some files inside the folder, described in
    ``evidence``). ``disk`` names the disk the item is on, matching a key in
    :attr:`ScanSummary.disks`.
    """

    path: str
    category: str
    suggestion: str
    reason: str
    kind: str = "file"
    size: int = 0
    n_files: int = 1
    owner: str = ""
    changed_at: str = ""
    evidence: str = ""
    cost_cpu_hours: float | None = None
    peek: str = ""
    disk: str = ""


@dataclass
class SopGap:
    """A case the lab's written procedures do not cover, with one example."""

    kind: str
    detail: str
    example: str = ""
    count: int = 0
    size: int = 0


@dataclass
class Disk:
    """Size and free space of one disk the project's files are on."""

    label: str
    total: int
    free: int

    @property
    def fill(self) -> float:
        """The share of the disk in use, from 0 to 1."""
        return 0.0 if self.total <= 0 else max(0.0, 1 - self.free / self.total)


@dataclass
class ScanSummary:
    """Everything one scan of one project found, ready to be recorded."""

    project: str
    started_at: str
    finished_at: str = ""
    scanned_by: str = ""
    files: int = 0
    bytes: int = 0
    unreadable: int = 0
    items: list[Item] = field(default_factory=list)
    sop_gaps: list[SopGap] = field(default_factory=list)
    disks: dict[str, Disk] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    #: Bytes read in full to confirm duplicates.
    bytes_fingerprinted: int = 0
    #: {top-level data folder: {owner: [bytes, files, newest change]}}; used by
    #: the lab-wide scan, not stored in the table.
    owners_by_folder: dict[str, dict[str, list[float]]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Recording a scan
# ---------------------------------------------------------------------------


def _inside(path: str, roots: list[str]) -> bool:
    return any(path == r or path.startswith(r.rstrip("/") + "/") for r in roots)


def record_scan(conn: sqlite3.Connection, summary: ScanSummary, *,
                roots: list[str] | None = None) -> int:
    """Write one scan's findings into the table, keeping every decision.

    A row seen before keeps its first-seen date and its decision, and its old
    size is kept so the table can show growth. A row not seen this time is
    removed if nobody had decided on it, and marked ``gone`` if someone had,
    so a decision is never lost.

    ``roots`` limits that clean-up to rows inside the folders this scan
    walked. The lab-wide scan walks data folders only, so without it the rows
    an in-session scan found in a project's repositories would be retired.

    Returns
    -------
    int
        The scan's number.
    """
    seen_at = summary.finished_at or now_iso()
    cur = conn.execute(
        "INSERT INTO scans (project, started_at, finished_at, scanned_by, files, bytes, "
        "unreadable, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (summary.project, summary.started_at, seen_at, summary.scanned_by, summary.files,
         summary.bytes, summary.unreadable, json.dumps(summary.notes)))
    scan_id = int(cur.lastrowid or 0)
    for item in summary.items:
        old = conn.execute(
            "SELECT id, size FROM items WHERE project = ? AND path = ? AND category = ?",
            (summary.project, item.path, item.category)).fetchone()
        values = (item.kind, item.size, item.n_files, item.owner, item.changed_at,
                  item.suggestion, item.reason, item.evidence, item.cost_cpu_hours,
                  item.peek, item.disk, seen_at, scan_id)
        if old is None:
            conn.execute(
                "INSERT INTO items (kind, size, n_files, owner, changed_at, suggestion, reason, "
                "evidence, cost_cpu_hours, peek, disk, last_seen, last_scan, project, path, "
                "category, first_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                values + (summary.project, item.path, item.category, seen_at))
        else:
            conn.execute(
                "UPDATE items SET kind = ?, size = ?, n_files = ?, owner = ?, changed_at = ?, "
                "suggestion = ?, reason = ?, evidence = ?, cost_cpu_hours = ?, peek = ?, "
                "disk = ?, last_seen = ?, last_scan = ?, previous_size = ?, gone = 0 "
                "WHERE id = ?", values + (old["size"], old["id"]))
    unseen = conn.execute("SELECT id, path, decision FROM items WHERE project = ? "
                          "AND last_scan IS NOT ?", (summary.project, scan_id)).fetchall()
    for row in unseen:
        if roots is not None and not _inside(row["path"], roots):
            continue
        if row["decision"] is None:
            conn.execute("DELETE FROM items WHERE id = ?", (row["id"],))
        else:
            conn.execute("UPDATE items SET gone = 1 WHERE id = ?", (row["id"],))

    # Gaps are replaced by this scan's, keeping when each was first seen.
    first = {(r["kind"], r["detail"]): r["first_seen"] for r in conn.execute(
        "SELECT kind, detail, first_seen FROM sop_gaps WHERE project = ?", (summary.project,))}
    conn.execute("DELETE FROM sop_gaps WHERE project = ?", (summary.project,))
    for gap in summary.sop_gaps:
        conn.execute(
            "INSERT OR REPLACE INTO sop_gaps (project, kind, detail, example, count, size, "
            "first_seen, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (summary.project, gap.kind, gap.detail, gap.example, gap.count, gap.size,
             first.get((gap.kind, gap.detail), seen_at), seen_at))
    conn.execute("DELETE FROM disks WHERE project = ?", (summary.project,))
    for key, disk in summary.disks.items():
        conn.execute("INSERT INTO disks (project, disk, label, total, free, scanned_at) "
                     "VALUES (?, ?, ?, ?, ?, ?)",
                     (summary.project, key, disk.label, disk.total, disk.free, seen_at))
    conn.commit()
    return scan_id


# ---------------------------------------------------------------------------
# Reading it back
# ---------------------------------------------------------------------------


def last_scan(conn: sqlite3.Connection, project: str) -> sqlite3.Row | None:
    """The most recent scan of ``project``, or None."""
    return conn.execute("SELECT * FROM scans WHERE project = ? ORDER BY id DESC LIMIT 1",
                        (project,)).fetchone()


def disks(conn: sqlite3.Connection, project: str) -> dict[str, Disk]:
    """The disks recorded at the project's last scan, by key."""
    rows = conn.execute("SELECT * FROM disks WHERE project = ?", (project,)).fetchall()
    return {r["disk"]: Disk(label=r["label"], total=int(r["total"] or 0),
                            free=int(r["free"] or 0)) for r in rows}


def sop_gaps(conn: sqlite3.Connection, project: str | None = None) -> list[sqlite3.Row]:
    """Cases the lab's procedures do not cover, largest first."""
    if project:
        return conn.execute("SELECT * FROM sop_gaps WHERE project = ? ORDER BY size DESC",
                            (project,)).fetchall()
    return conn.execute("SELECT * FROM sop_gaps ORDER BY project, size DESC").fetchall()


def rows(conn: sqlite3.Connection, project: str | None = None, *,
         category: str | None = None, owner: str | None = None, min_size: int = 0,
         include_settled: bool = False) -> list[sqlite3.Row]:
    """Rows of the table, largest first.

    Parameters
    ----------
    project, category, owner : str, optional
        Filters; ``None`` means any.
    min_size : int
        Leave out rows smaller than this many bytes.
    include_settled : bool
        Also return rows already decided, rows suggested ``keep``, and rows
        whose file is gone. By default only rows still waiting for a person.
    """
    where, args = ["1 = 1"], []
    if project:
        where.append("project = ?")
        args.append(project)
    if category:
        where.append("category = ?")
        args.append(category)
    if owner:
        where.append("owner = ?")
        args.append(owner)
    if min_size:
        where.append("size >= ?")
        args.append(int(min_size))
    if not include_settled:
        where.append("decision IS NULL AND gone = 0 AND suggestion != ?")
        args.append(KEEP)
    sql = f"SELECT * FROM items WHERE {' AND '.join(where)} ORDER BY size DESC, path"
    return conn.execute(sql, args).fetchall()


#: Most rows one page of :func:`rows_page` returns.
PAGE_LIMIT = 500


def read_page(**filters) -> dict:
    """:func:`rows_page` from the table, or an empty page when there is no table
    yet. Only reads: looking at the list never creates the table (#185 follow-up;
    the dashboard's Space page used to create it by being opened)."""
    path = table_path()
    if not path.is_file():
        limit = filters.get("limit", 200)
        return {"kind": "space_rows", "total": 0, "total_bytes": 0,
                "offset": max(0, int(filters.get("offset", 0))), "limit": limit,
                "rows": [], "facets": {"projects": [], "categories": [],
                                       "suggestions": [], "owners": []},
                "no_table": True}
    return rows_page(connect(path), **filters)


def rows_page(conn: sqlite3.Connection, *, project: str | None = None,
              category: str | None = None, suggestion: str | None = None,
              owner: str | None = None, min_size: int = 0, limit: int = 200,
              offset: int = 0) -> dict:
    """One page of the rows waiting for a decision, largest first, with totals.

    For the dashboard's list of every suggestion. ``total`` and ``total_bytes``
    cover every row the filters match, not just this page; ``facets`` give the
    projects, categories, suggestions and owners there are to filter by.
    Folder-level rows (unclaimed folders, dormant projects) are included: on a
    page of their own category they are what the person is looking for.
    """
    where, args = ["decision IS NULL", "gone = 0", "suggestion != ?"], [KEEP]
    for column, value in (("project", project), ("category", category),
                          ("suggestion", suggestion), ("owner", owner)):
        if value:
            where.append(f"{column} = ?")
            args.append(value)
    if min_size:
        where.append("size >= ?")
        args.append(int(min_size))
    clause = " AND ".join(where)
    total, total_bytes = conn.execute(
        f"SELECT COUNT(*), COALESCE(SUM(size), 0) FROM items WHERE {clause}", args).fetchone()
    limit = max(1, min(int(limit), PAGE_LIMIT))
    found = conn.execute(
        f"SELECT * FROM items WHERE {clause} ORDER BY size DESC, path LIMIT ? OFFSET ?",
        args + [limit, max(0, int(offset))]).fetchall()
    waiting = "decision IS NULL AND gone = 0 AND suggestion != ?"

    def facet(column: str, top: int = 0) -> list[list]:
        sql = (f"SELECT {column}, COUNT(*) FROM items WHERE {waiting} AND {column} != '' "
               f"GROUP BY {column} ORDER BY COUNT(*) DESC")
        return [list(r) for r in conn.execute(sql + (f" LIMIT {top}" if top else ""), [KEEP])]

    return {
        "kind": "space_rows", "total": int(total), "total_bytes": int(total_bytes),
        "offset": max(0, int(offset)), "limit": limit,
        "rows": [{"id": int(r["id"]), "project": r["project"], "path": r["path"],
                  "category": r["category"], "suggestion": r["suggestion"],
                  "reason": r["reason"] or "", "evidence": r["evidence"] or "",
                  "size": int(r["size"] or 0), "files": int(r["n_files"] or 0),
                  "owner": r["owner"] or "", "changed_at": r["changed_at"] or "",
                  "cost_cpu_hours": r["cost_cpu_hours"]} for r in found],
        "facets": {"projects": facet("project"), "categories": facet("category"),
                   "suggestions": facet("suggestion"), "owners": facet("owner", 40)},
    }


def get_row(conn: sqlite3.Connection, item_id: int) -> sqlite3.Row | None:
    """One row by its number."""
    return conn.execute("SELECT * FROM items WHERE id = ?", (int(item_id),)).fetchone()


# ---------------------------------------------------------------------------
# What to look at first
# ---------------------------------------------------------------------------


def _days_since(iso: str | None, now: _dt.datetime) -> float:
    try:
        then = _dt.datetime.fromisoformat(str(iso))
    except (TypeError, ValueError):
        return 0.0
    if then.tzinfo is None:
        then = then.astimezone()
    return max(0.0, (now - then).total_seconds() / 86400)


def score(row: Any, disk: Disk | None, now: _dt.datetime | None = None) -> float:
    """How pressing a row is. Bigger is more pressing.

    The size in gigabytes, multiplied by three weights, each starting at 1:

    - how full its disk is: 1 up to 70% full, rising to 5 when the disk is full;
    - how long it has waited for a decision: up to 3, reached after two months;
    - how fast it grew since the last scan: up to 2, for doubling or more.

    So an 87 TB file always comes first, and between two items of the same size
    the one on a fuller disk, or waiting longer, or growing, comes first.
    """
    now = now or _dt.datetime.now().astimezone()
    size = int(row["size"] or 0)
    fill = disk.fill if disk else 0.0
    fill_weight = 1 + 4 * min(1.0, max(0.0, fill - 0.7) / 0.3)
    wait_weight = 1 + min(_days_since(row["first_seen"], now) / 30, 2.0)
    previous = int(row["previous_size"] or 0)
    growth = (size - previous) / previous if previous > 0 else 0.0
    growth_weight = 1 + min(max(growth, 0.0), 1.0)
    return size / 1e9 * fill_weight * wait_weight * growth_weight


def ranked(conn: sqlite3.Connection, project: str,
           now: _dt.datetime | None = None) -> list[tuple[float, sqlite3.Row]]:
    """Rows waiting for a person, most pressing first, with their scores.

    Rows referred to the security guard are left out: they are the guard's to
    rank, not the millwright's.
    """
    known = disks(conn, project)
    scored = [(score(r, known.get(r["disk"] or ""), now), r)
              for r in rows(conn, project) if r["suggestion"] != REFER_SECURITY]
    return sorted(scored, key=lambda pair: pair[0], reverse=True)


@dataclass(frozen=True)
class Emergency:
    """Something the PI should hear about now rather than when they next look."""

    text: str
    item_id: int | None = None


def emergencies(conn: sqlite3.Connection, project: str, *, disk_fill_limit: float,
                item_share_of_free: float) -> list[Emergency]:
    """Disks past the fill limit, and single items too big for a disk's free space."""
    found: list[Emergency] = []
    known = disks(conn, project)
    for disk in known.values():
        if disk.fill > disk_fill_limit:
            found.append(Emergency(
                text=(f"The disk holding {disk.label} is {disk.fill:.0%} full "
                      f"({_human(disk.free)} free).")))
    for row in rows(conn, project):
        disk = known.get(row["disk"] or "")
        if disk is None or disk.free <= 0 or row["suggestion"] == REFER_SECURITY:
            continue
        if int(row["size"] or 0) > item_share_of_free * disk.free:
            found.append(Emergency(
                item_id=int(row["id"]),
                text=(f"{row['path']} is {_human(int(row['size']))}, more than "
                      f"{item_share_of_free:.0%} of the {_human(disk.free)} free on its disk.")))
    return found


def _human(size: int) -> str:
    from .run_cards import format_size
    return format_size(size)


# ---------------------------------------------------------------------------
# A person's decision
# ---------------------------------------------------------------------------


class DecisionError(ValueError):
    """A decision that cannot be recorded, with the reason in plain words."""


def decide(conn: sqlite3.Connection, item_id: int, decision: str, *, by: str,
           note: str = "") -> sqlite3.Row:
    """Record a person's decision on one row. Nothing is moved or deleted.

    ``decision`` is one of :data:`DECISIONS`, or ``undo`` to clear an earlier
    decision.
    """
    row = get_row(conn, item_id)
    if row is None:
        raise DecisionError(f"there is no row {item_id} in the space table.")
    choice = decision.strip().lower()
    if choice == "undo":
        conn.execute("UPDATE items SET decision = NULL, decided_by = NULL, decided_at = NULL, "
                     "decision_note = NULL WHERE id = ?", (int(item_id),))
    elif choice in DECISIONS:
        conn.execute("UPDATE items SET decision = ?, decided_by = ?, decided_at = ?, "
                     "decision_note = ? WHERE id = ?",
                     (choice, by, now_iso(), note or None, int(item_id)))
    else:
        raise DecisionError(f"{decision!r} is not a decision. Use one of: "
                            f"{', '.join(DECISIONS)}, or undo.")
    conn.commit()
    return get_row(conn, item_id)  # type: ignore[return-value]


def decided(conn: sqlite3.Connection, project: str) -> list[sqlite3.Row]:
    """Rows with a decision, newest decision first."""
    return conn.execute("SELECT * FROM items WHERE project = ? AND decision IS NOT NULL "
                        "ORDER BY decided_at DESC", (project,)).fetchall()


def counts_by_category(conn: sqlite3.Connection, project: str) -> list[tuple[str, int, int]]:
    """(category, rows, bytes) for rows still waiting, largest first."""
    totals: dict[str, list[int]] = {}
    for row in rows(conn, project):
        entry = totals.setdefault(row["category"], [0, 0])
        entry[0] += 1
        entry[1] += int(row["size"] or 0)
    return sorted(((c, n, b) for c, (n, b) in totals.items()), key=lambda t: t[2], reverse=True)


def projects(conn: sqlite3.Connection) -> list[str]:
    """Every project the table holds a scan for."""
    return [r[0] for r in conn.execute("SELECT DISTINCT project FROM scans ORDER BY project")]


__all__ = [
    "TABLE_FILENAME", "TABLE_SCHEMA", "CATEGORIES", "SUGGESTIONS", "DECISIONS",
    "TEMPORARY", "INTERMEDIATE", "COMPRESSIBLE", "DUPLICATE", "OUT_OF_PLACE",
    "UNATTRIBUTED", "LISTED", "ACCESS", "UNREADABLE", "UNCLAIMED", "DORMANT",
    "DELETE", "MOTHBALL", "COMPRESS", "MOVE", "KEEP", "ASK_OWNER", "REFER_SECURITY",
    "Item", "SopGap", "Disk", "ScanSummary", "Emergency", "DecisionError",
    "now_iso", "table_path", "connect", "record_scan", "last_scan", "disks", "sop_gaps",
    "rows", "rows_page", "PAGE_LIMIT", "get_row", "score", "ranked", "emergencies", "decide", "decided",
    "counts_by_category", "projects",
]
