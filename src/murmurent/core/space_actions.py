"""
Purpose: Carry out the decisions people recorded in the space table (issue
         #151, step 6): mothball, compress and move. Each makes a copy, checks
         the copy against fingerprints of the original taken before it was
         made, and logs who did what and when. Originals are never removed.
Author:  Mike Hallett (with Claude Code)
Date:    2026-10-19
Input:   Rows of the space table with a decision (``murmurent space decide``);
         the lab policy's ``mothball_target`` and ``mothball_target_fill_limit``.
Output:  Copies (on the backup drive, beside the original compressed, or at a
         new place); an ``actions`` table in the space table; a log of every
         action, ``~/.murmurent/space/actions.log``, one JSON line each.

Why originals stay. The plan for #151 keeps automation where it is safe
(copying and checking) and a person where it is not (deleting): "nothing is
deleted by the millwright". It also keeps the lab folder rules, since nothing
in ``append_only/`` may be overwritten or deleted by an agent. After an action
is checked, ``murmurent space removable`` lists the originals a person may now
remove, and a person removes them.

What each action does:

- **mothball**: copies the file or folder to ``<mothball_target>/<project>/``,
  keeping its path below the data root, after checking the backup drive has
  room. Refused when no ``mothball_target`` is set.
- **compress**: writes ``<file>.gz`` beside a text file (bgzip for formats
  that tabix indexes, when bgzip is installed; gzip otherwise), then
  decompresses it and compares fingerprints. Lossless only. Never in
  ``immutable/`` or ``mothballed/``, since it writes a new file there.
- **move**: copies to a destination the person names with ``--to``.

A fingerprint mismatch stops that action and marks it failed; the copy is left
for a person to inspect, and the original is not listed as removable.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import lab_vm as _lab_vm
from . import project_unit as _pu
from . import space_table as _st

MOTHBALL = _st.MOTHBALL
COMPRESS = _st.COMPRESS
MOVE = _st.MOVE
CARRIED_OUT = (MOTHBALL, COMPRESS, MOVE)

#: An action's outcome.
VERIFIED = "copied and checked"
FAILED = "failed"

ACTIONS_LOG = "actions.log"

#: Text formats murmurent compresses, and with what. bgzip output is ordinary
#: gzip that tabix and samtools can also index.
GZIP_FORMATS = {".fastq", ".fq", ".fasta", ".fa", ".csv", ".tsv", ".txt"}
BGZIP_FORMATS = {".vcf", ".bed", ".gff", ".gff3", ".gtf"}

_CHUNK = 4 * 1024 * 1024


@dataclass
class Planned:
    """One decision and what carrying it out would do."""

    row: int
    project: str
    action: str
    source: Path
    destination: Path | None = None
    size: int = 0
    blocked: str = ""          # why it will not be done, in plain words

    def describe(self) -> str:
        if self.blocked:
            return f"row {self.row}: {self.action} {self.source}: not done. {self.blocked}"
        return f"row {self.row}: {self.action} {self.source} -> {self.destination}"


@dataclass
class Result:
    planned: Planned
    status: str
    files: int = 0
    bytes: int = 0
    detail: str = ""
    mismatches: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Fingerprints
# ---------------------------------------------------------------------------


def fingerprint(path: Path) -> str:
    """SHA-256 of a file's contents."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest(root: Path) -> dict[str, tuple[int, str]]:
    """``{path relative to root: (size, fingerprint)}`` for a file or a folder.
    Links are recorded by their target's contents only when they point to a
    file; links to folders are not followed."""
    root = Path(root)
    if root.is_file():
        return {root.name: (root.stat().st_size, fingerprint(root))}
    out: dict[str, tuple[int, str]] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not Path(dirpath, d).is_symlink()]
        for name in filenames:
            p = Path(dirpath, name)
            if p.is_file():
                out[str(p.relative_to(root))] = (p.stat().st_size, fingerprint(p))
    return out


def _compare(before: dict[str, tuple[int, str]],
             after: dict[str, tuple[int, str]]) -> list[str]:
    """Paths whose copy is missing or differs, in plain words."""
    problems = []
    for rel, (size, digest) in sorted(before.items()):
        got = after.get(rel)
        if got is None:
            problems.append(f"{rel}: missing from the copy")
        elif got != (size, digest):
            problems.append(f"{rel}: the copy differs from the original")
    return problems


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


def _hands_off(path: Path, env: dict | None) -> str:
    """The folder kind a path sits in when only people may change it there."""
    root = Path(os.path.normpath(_lab_vm.data_root(env)))
    for name, base in (("immutable", _lab_vm.immutable_root(env)),
                       ("mothballed", root / "mothballed")):
        base = Path(os.path.normpath(base))
        if path == base or base in path.parents:
            return name
    return ""


def _below_data_root(path: Path, env: dict | None) -> Path:
    root = Path(os.path.normpath(_lab_vm.data_root(env)))
    try:
        return path.relative_to(root)
    except ValueError:
        return Path(*path.parts[1:]) if path.is_absolute() else path


def _done(conn, row_id: int) -> bool:
    return conn.execute("SELECT 1 FROM actions WHERE item_id = ? AND status = ?",
                        (row_id, VERIFIED)).fetchone() is not None


def plan(conn, *, project: str | None = None, rows: list[int] | None = None,
         move_to: str = "", policy=None, env: dict | None = None) -> list[Planned]:
    """What carrying out the recorded decisions would do. Changes nothing."""
    from .millwright_policy import load_policy
    policy = policy or load_policy(env)
    if rows:
        found = [_st.get_row(conn, r) for r in rows]
        missing = [r for r, row in zip(rows, found) if row is None]
        if missing:
            raise ValueError(f"there is no row {missing[0]} in the space table.")
        chosen = found
    else:
        names = [project] if project else _st.projects(conn)
        chosen = [r for n in names for r in _st.decided(conn, n)]
    target = Path(policy.mothball_target).expanduser() if policy.mothball_target else None
    out: list[Planned] = []
    for row in chosen:
        decision = (row["decision"] or "").lower()
        if decision not in CARRIED_OUT:
            continue
        source = Path(row["path"])
        p = Planned(row=int(row["id"]), project=row["project"], action=decision,
                    source=source, size=int(row["size"] or 0))
        out.append(p)
        if _done(conn, p.row):
            p.blocked = "Already copied and checked."
        elif not source.exists():
            p.blocked = "It no longer exists."
        elif decision == MOTHBALL:
            if target is None:
                p.blocked = ("No backup drive is set. The PI sets mothball_target in the "
                             "lab policy file.")
            else:
                p.destination = target / p.project / _below_data_root(source, env)
        elif decision == COMPRESS:
            kind = _hands_off(source, env)
            ext = source.suffix.lower()
            if kind:
                p.blocked = f"It is in {kind}/, where only people change files."
            elif not source.is_file():
                p.blocked = "Only single files are compressed. Decide on each file instead."
            elif ext not in GZIP_FORMATS | BGZIP_FORMATS:
                p.blocked = (f"murmurent does not compress {ext or 'files with no ending'} "
                             "files. Do it by hand with the method in the row's reason.")
            else:
                p.destination = source.with_name(source.name + ".gz")
        elif decision == MOVE:
            if not move_to:
                p.blocked = "Say where with --to."
            else:
                dest = Path(move_to).expanduser()
                p.destination = dest / source.name if dest.is_dir() else dest
        if not p.blocked and p.destination is not None and p.destination.exists():
            p.blocked = f"{p.destination} already exists; nothing is overwritten."
    return out


# ---------------------------------------------------------------------------
# Carrying out
# ---------------------------------------------------------------------------


def _room(target: Path, size: int, limit: float) -> str:
    probe = target
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        usage = shutil.disk_usage(probe)
    except OSError as exc:
        return f"the backup drive could not be read ({exc.strerror or exc})."
    if (usage.used + size) / usage.total > limit:
        return (f"the copy would fill the backup drive past {limit:.0%}; free some room "
                "there or raise mothball_target_fill_limit.")
    return ""


def _copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if shutil.which("rsync"):
        src = str(source) + ("/" if source.is_dir() else "")
        subprocess.run(["nice", "-n", "19", "rsync", "-a", src, str(destination)],
                       check=True, capture_output=True)
    elif source.is_dir():
        shutil.copytree(source, destination, symlinks=True)
    else:
        shutil.copy2(source, destination)


def _compress(source: Path, destination: Path) -> str:
    """Write ``destination`` and return the method used."""
    if source.suffix.lower() in BGZIP_FORMATS and shutil.which("bgzip"):
        with open(destination, "wb") as out:
            subprocess.run(["nice", "-n", "19", "bgzip", "-c", str(source)],
                           stdout=out, check=True)
        return "bgzip"
    with open(source, "rb") as fin, gzip.open(destination, "wb", compresslevel=6) as fout:
        shutil.copyfileobj(fin, fout, _CHUNK)
    return "gzip"


def _gunzipped_fingerprint(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with gzip.open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def _record(conn, result: Result, by: str, started: str) -> None:
    p = result.planned
    conn.execute(
        "INSERT INTO actions (item_id, project, action, source, destination, status, "
        "files, bytes, detail, done_by, started_at, finished_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (p.row, p.project, p.action, str(p.source), str(p.destination or ""), result.status,
         result.files, result.bytes, result.detail, by, started, _st.now_iso()))
    conn.commit()
    log = _st.table_path().parent / ACTIONS_LOG
    entry = {"at": _st.now_iso(), "by": by, "row": p.row, "project": p.project,
             "action": p.action, "source": str(p.source),
             "destination": str(p.destination or ""), "status": result.status,
             "files": result.files, "bytes": result.bytes, "detail": result.detail,
             "mismatches": result.mismatches[:20]}
    fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def carry_out(conn, planned: Planned, *, by: str, policy=None,
              env: dict | None = None) -> Result:
    """Do one planned action: copy, check, log. Never removes the original."""
    from .millwright_policy import load_policy
    policy = policy or load_policy(env)
    started = _st.now_iso()
    if planned.blocked or planned.destination is None:
        return Result(planned, "skipped", detail=planned.blocked)
    src, dst = planned.source, planned.destination
    try:
        before = manifest(src)
        total = sum(size for size, _ in before.values())
        if planned.action == MOTHBALL:
            problem = _room(dst, total, policy.mothball_target_fill_limit)
            if problem:
                result = Result(planned, FAILED, detail="Not copied: " + problem)
                _record(conn, result, by, started)
                return result
        if planned.action == COMPRESS:
            method = _compress(src, dst)
            after = {src.name: _gunzipped_fingerprint(dst)}
            note = (f"{method}: {total:,} bytes became {dst.stat().st_size:,}; "
                    "decompressed and compared with the original.")
        else:
            _copy(src, dst)
            after = manifest(dst)
            note = f"{len(before):,} file(s) copied and compared with the original."
        mismatches = _compare(before, after)
    except (OSError, subprocess.CalledProcessError) as exc:
        result = Result(planned, FAILED, detail=f"Stopped: {exc}")
        _record(conn, result, by, started)
        return result
    if mismatches:
        result = Result(planned, FAILED, files=len(before), bytes=total, mismatches=mismatches,
                        detail=(f"{len(mismatches)} file(s) did not match. The copy is left at "
                                f"{dst} for a person to look at; the original stays."))
    else:
        result = Result(planned, VERIFIED, files=len(before), bytes=total, detail=note)
    _record(conn, result, by, started)
    return result


# ---------------------------------------------------------------------------
# What a person may now remove
# ---------------------------------------------------------------------------


@dataclass
class Removable:
    row: int
    project: str
    path: str
    reason: str
    size: int = 0


def removable(conn, *, project: str | None = None, env: dict | None = None,
              today: str = "") -> tuple[list[Removable], list[Removable]]:
    """``(may_remove, held)``. ``may_remove``: originals whose copy was checked,
    and rows a person decided to delete, that still exist. ``held``: the same
    for projects whose keep-until date has not passed. Reads only."""
    from . import cert_projects as _cp
    import datetime as _dt
    today = today or _dt.date.today().isoformat()
    keep: dict[str, str] = {}
    for cp in _cp.iter_projects(env):
        if str(cp.retain_until or "").strip():
            keep[cp.name] = str(cp.retain_until).strip()
    sql = ("SELECT a.item_id, a.project, a.source, a.action, a.destination, a.bytes "
           "FROM actions a WHERE a.status = ?")
    args: list = [VERIFIED]
    if project:
        sql += " AND a.project = ?"
        args.append(project)
    candidates: list[Removable] = []
    for r in conn.execute(sql, args).fetchall():
        candidates.append(Removable(int(r["item_id"]), r["project"], r["source"],
                                    f"{r['action']}: copy checked at {r['destination']}",
                                    int(r["bytes"] or 0)))
    names = [project] if project else _st.projects(conn)
    for n in names:
        for row in _st.decided(conn, n):
            if (row["decision"] or "").lower() == _st.DELETE:
                candidates.append(Removable(int(row["id"]), row["project"], row["path"],
                                            f"decided delete by {row['decided_by']}",
                                            int(row["size"] or 0)))
    may, held = [], []
    for c in candidates:
        if not Path(c.path).exists():
            continue
        until = keep.get(c.project, "")
        if until and until >= today:
            c.reason += f"; the project keeps everything until {until}"
            held.append(c)
        else:
            may.append(c)
    return may, held


__all__ = ["Planned", "Result", "Removable", "plan", "carry_out", "removable",
           "manifest", "fingerprint", "VERIFIED", "FAILED", "CARRIED_OUT"]
