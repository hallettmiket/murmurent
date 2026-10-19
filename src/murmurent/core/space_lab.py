"""
Purpose: The lab-wide space scan (issue #151, step 3). Scans the data folders of
         every project in the lab, and the folders no project claims, so that
         projects nobody opens any more are looked at too; writes one report
         for the PI.
Author:  Mike Hallett (with Claude Code)
Date:    2026-10-17
Input:   The lab's project records; the lab's data folder (immutable/,
         append_only/ and anything else at the top of the data root); the
         lab's policy file.
Output:  Rows in the space table (core.space_table), one scan per project plus
         one for unclaimed folders; ``~/.murmurent/space/lab_report.json``; and
         lines of text for the terminal, a Slack direct message and the
         dashboard.

Runs on a timer under the PI's account, on the conditions agreed on #151: it
only reads, never uses administrator rights, posts with the lab's bot rather
than a personal token, and its timer entry is written down in the lab records
repository. When a lab service account exists, the timer moves to it and
nothing here changes.

Only this lab's folders are scanned: other labs on a shared server keep their
own procedures.
"""

from __future__ import annotations

import datetime as _dt
import fcntl
import json
import os
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Callable, Iterator

from . import cert_projects as _cp
from . import lab_vm as _lab_vm
from . import project_unit as _pu
from . import sensitivity as _sens
from . import space_scan as _ss
from . import space_table as _st
from .millwright_policy import Policy, load_policy

REPORT_FILENAME = "lab_report.json"
REPORT_SCHEMA = 1
LOCK_FILENAME = "lab_scan.lock"

#: The table's name for folders no project claims.
UNCLAIMED_PROJECT = "(unclaimed)"
#: Cottages and shared folders (tools/, db/): the lab's or a person's, not a project's.
LAB_WIDE_PROJECT = "(cottages and shared)"

#: Rows in the report's lab-wide "look at these first".
TOP = 3

#: Rows that describe a whole folder (no project claims it; its project is
#: dormant). The files inside have rows of their own, so these are left out of
#: "waiting" totals, the most-pressing list and emergencies, and listed apart.
CONTAINERS = (_st.UNCLAIMED, _st.DORMANT)

#: Unclaimed folders listed one by one in the report, largest first.
UNCLAIMED_LISTED = 25


class LabScanBusy(RuntimeError):
    """Another lab scan is still running."""


def report_path() -> Path:
    """Where the last lab scan's report is kept."""
    return _pu.murmurent_home() / _pu.SPACE_SUBDIR / REPORT_FILENAME


@contextmanager
def _lock() -> Iterator[None]:
    """Hold the lab-scan lock, or raise :class:`LabScanBusy`."""
    path = _pu.murmurent_home() / _pu.SPACE_SUBDIR / LOCK_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(path, "w", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise LabScanBusy("a lab space scan is already running") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


# ---------------------------------------------------------------------------
# What belongs to whom
# ---------------------------------------------------------------------------


def lab_projects(lab: str = "", env: dict | None = None) -> list[_cp.CertProject]:
    """Every project record of ``lab`` (this machine's lab when blank), any status.

    An archived project still owns its data, so it is scanned too.
    """
    lab = lab or _pu.this_machine_lab()
    projects = _cp.iter_projects(env)
    if not lab:
        return list(projects)
    return [p for p in projects if (p.lab or "").casefold() == lab.casefold()]


def _protocol_parents(env: dict | None = None) -> tuple[Path, list[Path], list[Path], list[Path]]:
    """``(root, per_project, per_person, shared)`` folders at the top of the
    data root, following the lab folder protocol (:mod:`lab_layout`)."""
    from . import lab_layout as _layout
    root = Path(os.path.normpath(_lab_vm.data_root(env)))
    known, _ = _layout.folders(env)
    groups: dict[str, list[Path]] = {_layout.PER_PROJECT: [], _layout.PER_PERSON: [],
                                     _layout.SHARED: []}
    for name, folder in known.items():
        path = root / name
        if _ss._is_dir(path) and not path.is_symlink():
            groups[folder.kind].append(path)
    return (root, groups[_layout.PER_PROJECT], groups[_layout.PER_PERSON],
            groups[_layout.SHARED])


def _children(parent: Path) -> list[Path]:
    try:
        return sorted(p for p in parent.iterdir()
                      if not p.name.startswith(".") and not p.is_symlink() and _ss._is_dir(p))
    except OSError:
        return []


def top_level_folders(env: dict | None = None) -> list[Path]:
    """The folders under the data root that a project could own.

    Each folder inside a per-project folder of the lab folder protocol
    (``immutable/``, ``append_only/``, ``modifiable/``, ``release/``,
    ``mothballed/``, and the older ``raw/`` and ``refined/``), and each folder
    at the top of the data root that is not in the protocol. Cottages and the
    shared folders are lab-wide (:func:`lab_wide_folders`), not listed here.
    Hidden folders and links are left out.
    """
    root, per_project, per_person, shared = _protocol_parents(env)
    found: list[Path] = []
    for parent in per_project:
        found += _children(parent)
    skip = set(per_project) | set(per_person) | set(shared)
    found += [c for c in _children(root) if c not in skip]
    return found


def lab_wide_folders(env: dict | None = None) -> list[Path]:
    """Space that belongs to the lab or to one person rather than a project:
    each person's ``cottage/<login>`` and each shared folder (``tools/``,
    ``db/``)."""
    _root, _proj, per_person, shared = _protocol_parents(env)
    out: list[Path] = []
    for parent in per_person:
        out += _children(parent)
    return out + shared


def _overlaps(a: Path, b: Path) -> bool:
    return a == b or _ss._within(a, b) or _ss._within(b, a)


def unclaimed_folders(projects: list[_cp.CertProject], env: dict | None = None) -> list[Path]:
    """Top-level data folders that no project's data folders touch.

    A folder holding a project's data folder, or inside one, counts as claimed.
    Folders a project only reads (``reads_from``) do not claim anything.
    ``projects`` should be every project murmurent knows, of any lab: another
    lab's folder is theirs, not unclaimed, and is never scanned.
    """
    claimed: list[Path] = []
    for cp in projects:
        for f in _pu.effective_data_folders(cp, env):
            claimed += [f, _pu._resolved(f)]
    out: list[Path] = []
    for folder in top_level_folders(env):
        resolved = _pu._resolved(folder)
        if not any(_overlaps(folder, c) or _overlaps(resolved, c) for c in claimed):
            out.append(folder)
    return out


def layout_findings(env: dict | None = None) -> list[dict]:
    """What does not follow the lab folder protocol, for the PI. Reads folder
    names only; never moves anything."""
    from . import lab_layout as _layout
    try:
        projects, logins = _layout.lab_projects_and_logins()
        found = _layout.check(_lab_vm.data_root(env), projects=projects, logins=logins, env=env)
    except Exception:  # noqa: BLE001
        return []
    return [f.to_dict() for f in found]


# ---------------------------------------------------------------------------
# The scan
# ---------------------------------------------------------------------------


def _human(size: float) -> str:
    from .run_cards import format_size
    return format_size(int(size))


def _folder_bytes(summary: _st.ScanSummary, folder: Path) -> tuple[int, int]:
    """Bytes and files under ``folder``, from the scan's per-owner tallies."""
    size = files = 0
    for key, owners in summary.owners_by_folder.items():
        p = Path(key)
        if p == folder or _ss._within(p, folder):
            for tally in owners.values():
                size += int(tally[0])
                files += int(tally[1])
    return size, files


def _dormant_items(cp: _cp.CertProject, summary: _st.ScanSummary, activity: str,
                   last: _pu.UsageEvidence | None, policy: Policy,
                   roots: list[_ss.Root]) -> list[_st.Item]:
    """A ``dormant`` row per data folder of a project unused for long enough."""
    if activity != _pu.DORMANT or _pu.retention_blocks_deletion(cp):
        return []
    items: list[_st.Item] = []
    since = last.when.date().isoformat() if last else "unknown"
    for root in roots:
        if root.kind == _ss.ROOT_MOTHBALLED:
            continue        # already on its way to long-term storage
        size, files = _folder_bytes(summary, root.path)
        if not size:
            continue
        in_immutable = root.kind == _ss.ROOT_IMMUTABLE
        items.append(_st.Item(
            path=str(root.path), category=_st.DORMANT, suggestion=_st.MOTHBALL, kind="folder",
            reason=(f"Project {cp.name} has not been used since {since}, more than "
                    f"{policy.project_dormant_months} months. Its data could be backed up "
                    "and removed from the server." + (" This is raw data in immutable/; "
                                                      "only the PI decides." if in_immutable
                                                      else "")),
            size=size, n_files=files, disk=root.disk,
            evidence=f"last used {since} ({last.detail if last else 'no sign of use'})"))
    return items


def _unclaimed_items(summary: _st.ScanSummary, folders: list[Path],
                     roots: list[_ss.Root]) -> list[_st.Item]:
    """One ``unclaimed`` row per folder, naming who owns how much of it."""
    items: list[_st.Item] = []
    for folder in folders:
        owners: dict[str, list[float]] = {}
        for key, tallies in summary.owners_by_folder.items():
            p = Path(key)
            if p == folder or _ss._within(p, folder):
                for owner, (size, files, newest) in tallies.items():
                    t = owners.setdefault(owner, [0, 0, 0.0])
                    t[0] += size
                    t[1] += files
                    t[2] = max(t[2], newest)
        if not owners:
            continue
        ranked = sorted(owners.items(), key=lambda kv: kv[1][0], reverse=True)
        total = sum(t[0] for t in owners.values())
        files = sum(int(t[1]) for t in owners.values())
        newest = max(t[2] for t in owners.values())
        shares = "; ".join(f"{o}: {_human(t[0])} in {int(t[1]):,} files"
                           for o, t in ranked[:5])
        disk = next((r.disk for r in roots if folder == r.path or _ss._within(folder, r.path)), "")
        items.append(_st.Item(
            path=str(folder), category=_st.UNCLAIMED, suggestion=_st.ASK_OWNER, kind="folder",
            reason=("No project claims this folder. Add it to a project's data folders, or "
                    f"ask {ranked[0][0]}, who owns most of it."),
            size=int(total), n_files=files, owner=ranked[0][0],
            changed_at=_ss._iso(newest), disk=disk, evidence=f"owners: {shares}"))
    return items


def scan_lab(*, env: dict | None = None, policy: Policy | None = None,
             checksums: bool = True, lab: str = "",
             progress: Callable[[str], None] | None = None,
             now: _dt.datetime | None = None) -> dict:
    """Scan every project's data folders and the unclaimed folders; write the report.

    Never walks repositories (they live in members' home folders) and never
    looks outside this lab's data root, except where a project's own record
    names a data folder elsewhere.

    Returns
    -------
    dict
        The report, as written to :func:`report_path`.
    """
    policy = policy or load_policy(env)
    say = progress or (lambda _msg: None)
    with _lock():
        started = _st.now_iso()
        conn = _st.connect()
        budget = policy.duplicate_max_read_gb * 1024**3 if checksums else 0
        projects = lab_projects(lab, env)
        report: dict = {"schema": REPORT_SCHEMA, "lab": lab or _pu.this_machine_lab(),
                        "started_at": started, "data_root": str(_lab_vm.data_root(env)),
                        "projects": [], "notes": []}
        disks: dict[str, _st.Disk] = {}
        def files_seen(n: int, size: int) -> None:
            say(f"  ... {n:,} files so far ({_human(size)})")

        for cp in projects:
            roots = _ss.project_roots(cp, env, include_repos=False)
            if not roots:
                # Still reported: a project whose data cannot be found is a
                # finding, most often a record that names the wrong folders.
                report["projects"].append(_no_data_entry(cp, env))
                continue
            say(f"Scanning {cp.name}")
            options = _ss.ScanOptions(checksums=checksums, include_repos=False,
                                      max_read_bytes=budget, now=now,
                                      progress=files_seen, progress_every=500_000)
            summary = _ss.scan_project(cp, env=env, policy=policy, options=options)
            budget = max(0, budget - summary.bytes_fingerprinted)
            last = _pu.last_used(cp, env)
            activity = _pu.activity_for(last, now=now, policy=_pu.ActivityPolicy(
                policy.project_quiet_months, policy.project_dormant_months))
            scanned_roots = _ss.project_roots(cp, env, include_repos=False)
            keyed = [replace(r, disk=_ss._disk_key(r.path)) for r in scanned_roots]
            summary.items += _dormant_items(cp, summary, activity, last, policy, keyed)
            _st.record_scan(conn, summary, roots=[str(r.path) for r in scanned_roots])
            disks.update(summary.disks)
            report["projects"].append(_project_entry(conn, cp, summary, activity, last))

        unclaimed = unclaimed_folders(list(_cp.iter_projects(env)), env)
        if unclaimed:
            say(f"Scanning {len(unclaimed)} folders no project claims")
            ghost = _cp.CertProject(name=UNCLAIMED_PROJECT, lab=report["lab"],
                                    sensitivity=_sens.PROTECTED,
                                    data_folders=tuple(str(f) for f in unclaimed))
            options = _ss.ScanOptions(checksums=checksums, include_repos=False,
                                      max_read_bytes=budget, now=now,
                                      progress=files_seen, progress_every=500_000)
            summary = _ss.scan_project(ghost, env=env, policy=policy, options=options)
            roots = [replace(r, disk=_ss._disk_key(r.path))
                     for r in _ss.project_roots(ghost, env, include_repos=False)]
            summary.items += _unclaimed_items(summary, unclaimed, roots)
            _st.record_scan(conn, summary, roots=[str(f) for f in unclaimed])
            disks.update(summary.disks)
            report["unclaimed"] = _project_entry(conn, ghost, summary, _pu.UNKNOWN, None)

        lab_wide = lab_wide_folders(env)
        if lab_wide:
            say(f"Scanning {len(lab_wide)} cottages and shared folders")
            ghost = _cp.CertProject(name=LAB_WIDE_PROJECT, lab=report["lab"],
                                    sensitivity=_sens.PROTECTED,
                                    data_folders=tuple(str(f) for f in lab_wide))
            options = _ss.ScanOptions(checksums=checksums, include_repos=False,
                                      max_read_bytes=budget, now=now,
                                      progress=files_seen, progress_every=500_000)
            summary = _ss.scan_project(ghost, env=env, policy=policy, options=options)
            _st.record_scan(conn, summary, roots=[str(f) for f in lab_wide])
            disks.update(summary.disks)
            entry = _project_entry(conn, ghost, summary, _pu.UNKNOWN, None)
            entry["folders"] = sorted(
                ({"path": str(f), "size": _folder_bytes(summary, f)[0]} for f in lab_wide),
                key=lambda f: f["size"], reverse=True)
            report["lab_wide"] = entry

        report["layout"] = layout_findings(env)

        report["finished_at"] = _st.now_iso()
        report["disks"] = [{"label": d.label, "total": d.total, "free": d.free,
                            "fill": round(d.fill, 4)} for d in disks.values()]
        derive(conn, report, projects, policy)
        _write_report(report)
        return report


def _no_data_entry(cp: _cp.CertProject, env: dict | None) -> dict:
    looked = [str(f) for f in _pu.effective_data_folders(cp, env)]
    return {"name": cp.name, "sensitivity": cp.sensitivity, "activity": _pu.UNKNOWN,
            "last_used": "", "files": 0, "bytes": 0, "unreadable": 0, "waiting_rows": 0,
            "waiting_bytes": 0, "by_category": {}, "gaps": [], "no_data": True,
            "looked_in": looked}


def mount_point(path: str) -> str:
    """The mount point holding ``path``: the disk's own name, not a folder on it."""
    p = Path(path)
    try:
        while not os.path.ismount(p) and p != p.parent:
            p = p.parent
    except OSError:
        return path
    return str(p)


def derive(conn, report: dict, projects: list[_cp.CertProject], policy: Policy) -> dict:
    """Fill in every part of the report that comes from the table.

    Used at the end of each lab scan, and by :func:`rebuild_report` to redo a
    report from a scan already recorded, without walking the drive again.
    """
    for entry in (report.get("projects", []) + [report[k] for k in ("unclaimed", "lab_wide")
                                                 if report.get(k)]):
        if entry.get("no_data"):
            continue
        waiting = [r for r in _st.rows(conn, entry["name"]) if r["category"] not in CONTAINERS]
        by_category: dict[str, list[int]] = {}
        for row in waiting:
            tally = by_category.setdefault(row["category"], [0, 0])
            tally[0] += 1
            tally[1] += int(row["size"] or 0)
        entry["by_category"] = by_category
        entry["waiting_rows"] = len(waiting)
        entry["waiting_bytes"] = sum(int(r["size"] or 0) for r in waiting)
    for disk in report.get("disks", []):
        disk["label"] = mount_point(disk["label"])
    names = [p["name"] for p in report.get("projects", []) if not p.get("no_data")] + (
        [UNCLAIMED_PROJECT] if report.get("unclaimed") else []) + (
        [LAB_WIDE_PROJECT] if report.get("lab_wide") else [])
    report["emergencies"] = _emergencies(conn, names, policy)
    report["unreadable"] = _unreadable(conn, names, projects)
    report["top"] = _lab_top(conn, names, projects)
    report["unclaimed_folders"] = _unclaimed_list(conn)
    report["dormant"] = _dormant_list(conn, names)
    return report


def rebuild_report(*, env: dict | None = None, policy: Policy | None = None,
                   lab: str = "") -> dict | None:
    """Redo the last report's summaries from the table; None when there is no report."""
    report = read_report()
    if report is None:
        return None
    policy = policy or load_policy(env)
    conn = _st.connect()
    derive(conn, report, lab_projects(lab or report.get("lab", ""), env), policy)
    report["rebuilt_at"] = _st.now_iso()
    _write_report(report)
    return report


def _unclaimed_list(conn) -> list[dict]:
    """Folders no project claims, largest first, with who owns most of each."""
    rows = sorted(_st.rows(conn, UNCLAIMED_PROJECT, category=_st.UNCLAIMED),
                  key=lambda r: int(r["size"] or 0), reverse=True)
    return [{"row": int(r["id"]), "path": r["path"], "size": int(r["size"] or 0),
             "files": int(r["n_files"] or 0), "owner": r["owner"] or "",
             "owners": str(r["evidence"] or "").removeprefix("owners: "),
             "changed_at": r["changed_at"] or ""} for r in rows[:UNCLAIMED_LISTED]]


def _dormant_list(conn, names: list[str]) -> list[dict]:
    out: list[dict] = []
    for name in names:
        rows = _st.rows(conn, name, category=_st.DORMANT)
        if rows:
            out.append({"project": name, "size": sum(int(r["size"] or 0) for r in rows),
                        "folders": len(rows)})
    return sorted(out, key=lambda d: d["size"], reverse=True)


def _project_entry(conn, cp: _cp.CertProject, summary: _st.ScanSummary, activity: str,
                   last: _pu.UsageEvidence | None) -> dict:
    waiting = [r for r in _st.rows(conn, cp.name) if r["category"] not in CONTAINERS]
    by_category: dict[str, list[int]] = {}
    for row in waiting:
        entry = by_category.setdefault(row["category"], [0, 0])
        entry[0] += 1
        entry[1] += int(row["size"] or 0)
    return {
        "name": cp.name, "sensitivity": cp.sensitivity, "activity": activity,
        "last_used": last.when.date().isoformat() if last else "",
        "files": summary.files, "bytes": summary.bytes, "unreadable": summary.unreadable,
        "waiting_rows": len(waiting), "waiting_bytes": sum(int(r["size"] or 0) for r in waiting),
        "by_category": by_category,
        "gaps": [g.detail for g in summary.sop_gaps],
    }


def _emergencies(conn, names: list[str], policy: Policy) -> list[dict]:
    """Each emergency in full (``text``) and without any file name (``short``)."""
    seen: list[dict] = []
    for name in names:
        for e in _st.emergencies(conn, name, disk_fill_limit=policy.disk_emergency_fill_fraction,
                                 item_share_of_free=policy.emergency_item_share_of_free):
            if e.item_id is None:
                entry = {"text": e.text, "short": e.text}
            else:
                row = _st.get_row(conn, e.item_id)
                if row is not None and row["category"] in CONTAINERS:
                    continue   # a whole folder that has stood for years is not news
                size = _human(int(row["size"] or 0)) if row else "one item"
                entry = {"text": f"{name}: {e.text}",
                         "short": (f"{name}: one {row['category'] if row else ''} item of "
                                   f"{size} is too big for its disk's free space "
                                   f"(row {e.item_id})")}
            if entry not in seen:
                seen.append(entry)
    return seen


def _unreadable(conn, names: list[str], projects: list[_cp.CertProject]) -> dict:
    """Everything the scan could not read, by owner. None of it is in any total.

    These are folders, and the PI needs their names to get them fixed, so they
    are named even for unclaimed folders; only protected projects' are left out.
    (The Slack summary never names any.)
    """
    protected = {p.name for p in projects if _sens.is_protected(p.sensitivity)}
    by_owner: dict[str, int] = {}
    places: list[dict] = []
    items = 0
    for name in names:
        for row in _st.rows(conn, name, category=_st.UNREADABLE):
            count = max(1, int(row["n_files"] or 0))
            items += count
            owner = row["owner"] or "unknown"
            by_owner[owner] = by_owner.get(owner, 0) + count
            places.append({"project": name, "owner": owner, "items": count, "row": int(row["id"]),
                           "path": row["path"] if name not in protected else "",
                           "fix": (f"chmod -R g+rX {row['path']}" if name not in protected else "")})
    return {"items": items, "places": len(places),
            "by_owner": dict(sorted(by_owner.items(), key=lambda kv: kv[1], reverse=True)),
            "list": places[:50]}


def _lab_top(conn, names: list[str], projects: list[_cp.CertProject]) -> list[dict]:
    """The most pressing rows across the lab. Paths are left out for protected data."""
    protected = {p.name for p in projects if _sens.is_protected(p.sensitivity)} | {UNCLAIMED_PROJECT}
    scored = [(score, name, row) for name in names for score, row in _st.ranked(conn, name)
              if row["category"] not in CONTAINERS]
    scored.sort(key=lambda t: t[0], reverse=True)
    return [{"project": name, "row": int(row["id"]), "category": row["category"],
             "suggestion": row["suggestion"], "size": int(row["size"] or 0),
             "files": int(row["n_files"] or 0),
             "path": "" if name in protected else row["path"],
             "reason": "" if name in protected else row["reason"]}
            for _score, name, row in scored[:TOP]]


def _write_report(report: dict) -> Path:
    path = report_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    os.replace(tmp, path)
    return path


def read_report(path: Path | None = None) -> dict | None:
    """The last lab scan's report, or None when there is none."""
    try:
        data = json.loads((path or report_path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("schema") == REPORT_SCHEMA else None


# ---------------------------------------------------------------------------
# Saying it in words
# ---------------------------------------------------------------------------


def _when(iso: str) -> str:
    return str(iso)[:16].replace("T", " ") if iso else "unknown"


def describe(report: dict) -> list[str]:
    """The report as lines for the terminal (also what the dashboard shows)."""
    projects = report.get("projects") or []
    unclaimed = report.get("unclaimed")
    extra = [e for e in (unclaimed, report.get("lab_wide")) if e]
    total = sum(p["bytes"] for p in projects) + sum(e["bytes"] for e in extra)
    waiting = sum(p["waiting_bytes"] for p in projects) + sum(
        e.get("waiting_bytes", 0) for e in extra)
    lines = [f"Lab {report.get('lab') or '?'} space report, scanned "
             f"{_when(report.get('finished_at', ''))}",
             f"  {len(projects)} projects, {_human(total)} in all; "
             f"{_human(waiting)} waiting for a decision."]
    for d in report.get("disks") or []:
        lines.append(f"  Disk holding {d['label']}: {d['fill']:.0%} full, "
                     f"{_human(d['free'])} free.")
    if report.get("emergencies"):
        lines.append("")
        lines.append("Emergencies")
        lines += [f"  ! {e['text']}" for e in report["emergencies"]]
    if report.get("top"):
        lines.append("")
        lines.append("Look at these first")
        for i, t in enumerate(report["top"], start=1):
            what = f"{t['category']}, suggest {t['suggestion']}"
            lines.append(f"  {i}. {_human(t['size']):>9}  {t['project']}: {what}  [row {t['row']}]")
            if t.get("path"):
                lines.append(f"       {t['path']}")
    blind = report.get("unreadable") or {}
    if blind.get("items"):
        lines.append("")
        lines.append(f"Not readable: {blind['items']:,} items in {blind['places']} places are in "
                     "no total, so the figures above are low by an unknown amount")
        lines.append("  By owner: " + ", ".join(f"{o} {n:,}" for o, n in blind["by_owner"].items()))
        for place in blind.get("list", [])[:10]:
            where = place["path"] or f"a folder of {place['project']}"
            lines.append(f"  {where} (owner {place['owner']}) [row {place['row']}]")
        lines.append("  Each owner can fix theirs with: chmod -R g+rX <folder>")
    lines.append("")
    lines.append("Projects")
    for p in sorted(projects, key=lambda p: p["waiting_bytes"], reverse=True):
        if p.get("no_data"):
            lines.append(f"  {p['name']:<28} no data folder found; the record points to "
                         + ", ".join(p.get("looked_in") or []) + ". Set data_folders in its record.")
            continue
        used = f"last used {p['last_used']}" if p["last_used"] else "no sign of use"
        lines.append(f"  {p['name']:<28} {_human(p['bytes']):>9}  {p['activity']:<8} {used:<22}"
                     f" waiting: {p['waiting_rows']} rows, {_human(p['waiting_bytes'])}")
    if unclaimed:
        lines.append(f"  {'(no project claims these)':<28} {_human(unclaimed['bytes']):>9}"
                     f"  waiting: {unclaimed['waiting_rows']} rows, "
                     f"{_human(unclaimed['waiting_bytes'])}")
    lab_wide = report.get("lab_wide")
    if lab_wide:
        lines.append(f"  {'(cottages and shared)':<28} {_human(lab_wide['bytes']):>9}"
                     f"  waiting: {lab_wide.get('waiting_rows', 0)} rows, "
                     f"{_human(lab_wide.get('waiting_bytes', 0))}")
    folders = report.get("unclaimed_folders") or []
    if folders:
        lines.append("")
        lines.append(f"Folders no project claims (largest {len(folders)}); add each to a "
                     "project's data_folders, or ask its owner")
        for f in folders:
            lines.append(f"  {_human(f['size']):>9}  {f['path']}  ({f['owners']})")
    if lab_wide and lab_wide.get("folders"):
        lines.append("")
        lines.append("Cottages and shared folders, largest first")
        for f in lab_wide["folders"][:15]:
            lines.append(f"  {_human(f['size']):>9}  {f['path']}")
    layout = report.get("layout") or []
    if layout:
        from . import lab_layout as _layout
        lines.append("")
        lines += _layout.describe([_layout.LayoutFinding(**f) for f in layout])
        lines.append("  murmurent moves nothing to fix these; the PI decides.")
    dormant = report.get("dormant") or []
    if dormant:
        lines.append("")
        lines.append("Dormant projects: mothballing suggested")
        lines += [f"  {_human(d['size']):>9}  {d['project']}" for d in dormant]
    lines.append("")
    lines.append("Details for one project: murmurent space show <project>")
    return lines


def slack_summary(report: dict) -> str:
    """The weekly direct message to the PI: totals and names of projects, no file names."""
    projects = report.get("projects") or []
    unclaimed = report.get("unclaimed")
    extra = [e for e in (unclaimed, report.get("lab_wide")) if e]
    total = sum(p["bytes"] for p in projects) + sum(e["bytes"] for e in extra)
    waiting = sum(p["waiting_bytes"] for p in projects) + sum(
        e.get("waiting_bytes", 0) for e in extra)
    parts = [f"*Weekly space report, lab {report.get('lab') or '?'}*: "
             f"{len(projects)} projects, {_human(total)}; "
             f"{_human(waiting)} suggested for a decision."]
    for e in report.get("emergencies") or []:
        parts.append(f":warning: {e['short']}")
    for i, t in enumerate(report.get("top") or [], start=1):
        parts.append(f"{i}. {t['project']}: {_human(t['size'])}, {t['category']}, "
                     f"suggest {t['suggestion']} (row {t['row']})")
    blind = report.get("unreadable") or {}
    if blind.get("items"):
        owners = ", ".join(f"{n:,} owned by {o}" for o, n in list(blind["by_owner"].items())[:5])
        parts.append(f"{blind['items']:,} items could not be read, so the totals miss them: "
                     f"{owners}. Each owner can fix it by letting the lab group read them.")
    dormant = [d["project"] for d in report.get("dormant") or []] or \
        [p["name"] for p in projects if p["activity"] == _pu.DORMANT]
    if dormant:
        parts.append("Dormant, mothballing suggested: " + ", ".join(dormant))
    if unclaimed and unclaimed["bytes"]:
        parts.append(f"No project claims {_human(unclaimed['bytes'])}, in "
                     f"{len(report.get('unclaimed_folders') or [])} or more folders.")
    lab_wide = report.get("lab_wide")
    if lab_wide and lab_wide["bytes"]:
        parts.append(f"Cottages and shared folders hold {_human(lab_wide['bytes'])}.")
    layout = report.get("layout") or []
    if layout:
        parts.append(f"{len(layout)} folder(s) or file(s) do not follow the lab's folder "
                     "protocol. Nothing was moved; see the Space page to decide.")
    missing = [p["name"] for p in projects if p.get("no_data")]
    if missing:
        parts.append("Projects whose data folders were not found: " + ", ".join(missing))
    parts.append("Details: `murmurent space lab` on the server, or the Space page of your "
                 "dashboard.")
    return "\n".join(parts)


class FetchError(RuntimeError):
    """The report could not be fetched from another machine."""


def audit_setting(env: dict[str, str] | None = None) -> str:
    """The lab's choice for the space audit, from ``space_audit:`` in lab.md:
    ``on``, ``off``, or ``""`` when the PI has not chosen. Never raises."""
    try:
        from .frontmatter import parse_file
        from .repo import lab_mgmt_repo_root
        meta = parse_file(lab_mgmt_repo_root(env) / "lab.md").meta or {}
    except Exception:  # noqa: BLE001
        return ""
    value = meta.get("space_audit")
    if value is True:
        return "on"
    if value is False:
        return "off"
    value = str(value or "").strip().lower()
    return value if value in ("on", "off") else ""


#: Said wherever the audit is refused because the PI turned it off.
TURNED_OFF = ("The space audit is turned off for this lab. The PI can turn it on "
              "in the dashboard under Lab settings.")


def _plain_fetch_error(host_name: str, text: str, what: str) -> str:
    """Turn the last line of a failed remote command into advice a person can act on."""
    low = text.lower()
    last = text.splitlines()[-1] if text else ""
    if "command not found" in low or "murmurent: not found" in low:
        return (f"murmurent is not installed on {host_name} (or not on its PATH), so "
                f"it cannot send the {what}. Choose the machine where the weekly scan "
                "runs, or install murmurent there.")
    if "no such command" in low:
        return (f"murmurent on {host_name} is too old to send the {what}. Update it "
                f"there, then try again.")
    if any(k in low for k in ("permission denied (publickey", "could not resolve hostname",
                              "connection refused", "connection timed out",
                              "no route to host", "host key verification failed")):
        return (f"could not connect to {host_name} ({last}). Check that `ssh "
                f"{host_name}` works from this computer.")
    if "timed out" in low or "timeout" in low:
        return f"{host_name} took too long to answer. Try again in a minute."
    return f"could not fetch the {what} from {host_name}: {last}"


def fetch_report(host_name: str = "") -> dict | None:
    """The last lab report: this computer's, or a registered host's over SSH.

    The report stays on the machine that made it, readable only by its owner;
    another machine fetches it when asked, through murmurent's own SSH
    connection (``murmurent host list``), and keeps no copy. None when there is
    no report there yet.
    """
    if not host_name:
        return read_report()
    from . import hosts as _hosts
    from .remote import Remote, RemoteError
    try:
        host = _hosts.resolve(host_name)
    except Exception as exc:  # noqa: BLE001 - an unknown name is a person's typo
        raise FetchError(f"no host named {host_name!r}. List them with: "
                         "murmurent host list") from exc
    if not host.is_remote():
        return read_report()
    try:
        out = Remote(host).run("murmurent space lab --json", timeout=60)
    except RemoteError as exc:
        text = (exc.stderr or exc.stdout or str(exc)).strip()
        if "no lab space report" in text:
            return None
        raise FetchError(_plain_fetch_error(host_name, text or str(exc), "report")) from exc
    data = _report_from_output(out.stdout)
    if data is None:
        raise FetchError(f"{host_name} did not send a report murmurent can read; is "
                         "murmurent up to date there?")
    return data


def _report_from_output(text: str) -> dict | None:
    """The report in a remote command's output, skipping anything printed before it."""
    return _json_from_output(text, lambda d: d.get("schema") == REPORT_SCHEMA)


def fetch_rows(host_name: str = "", **filters) -> dict:
    """One page of the space table, from this computer or a registered host over SSH.

    ``filters`` are :func:`core.space_table.rows_page`'s (project, category,
    suggestion, owner, min_size, limit, offset).
    """
    if not host_name:
        return _local_rows(**filters)
    import shlex
    from . import hosts as _hosts
    from .remote import Remote, RemoteError
    try:
        host = _hosts.resolve(host_name)
    except Exception as exc:  # noqa: BLE001
        raise FetchError(f"no host named {host_name!r}. List them with: "
                         "murmurent host list") from exc
    if not host.is_remote():
        return _local_rows(**filters)
    parts = ["murmurent", "space", "rows", "--json"]
    for key, value in filters.items():
        if value not in (None, "", 0):
            parts += [f"--{key.replace('_', '-')}", str(value)]
    try:
        out = Remote(host).run(" ".join(shlex.quote(p) for p in parts), timeout=60)
    except RemoteError as exc:
        text = (exc.stderr or exc.stdout or str(exc)).strip()
        raise FetchError(_plain_fetch_error(host_name, text or str(exc), "list")) from exc
    data = _json_from_output(out.stdout, lambda d: d.get("kind") == "space_rows")
    if data is None:
        raise FetchError(f"{host_name} did not send a list murmurent can read; is "
                         "murmurent up to date there?")
    return data


def decide_row(host_name: str, row: int, decision: str, *, note: str = "",
               by: str = "") -> str:
    """Record a decision on one row of the space table, here or on a registered
    host over SSH (where ``murmurent space decide`` records it). Returns one
    plain sentence. Nothing is carried out."""
    import shlex
    choice = decision.strip().lower()
    if choice not in _st.DECISIONS and choice != "undo":
        raise FetchError(f"{decision!r} is not a decision. Use one of: "
                         f"{', '.join(_st.DECISIONS)}, or undo.")
    host = None
    if host_name:
        from . import hosts as _hosts
        try:
            host = _hosts.resolve(host_name)
        except Exception as exc:  # noqa: BLE001
            raise FetchError(f"no host named {host_name!r}. List them with: "
                             "murmurent host list") from exc
    if host is None or not host.is_remote():
        try:
            _st.decide(_st.connect(), int(row), choice,
                       by=by or _pu.local_handle() or "unknown", note=note)
        except _st.DecisionError as exc:
            raise FetchError(str(exc)) from exc
        return f"Row {row}: recorded '{choice}'."
    from .remote import Remote, RemoteError
    parts = ["murmurent", "space", "decide", str(int(row)), choice]
    if note:
        parts += ["--note", note]
    try:
        out = Remote(host).run(" ".join(shlex.quote(p) for p in parts), timeout=60)
    except RemoteError as exc:
        text = (exc.stderr or exc.stdout or str(exc)).strip()
        raise FetchError(_plain_fetch_error(host_name, text or str(exc), "decision")) from exc
    line = next((ln for ln in out.stdout.splitlines() if ln.startswith(f"Row {row}:")), "")
    return line or f"Row {row}: recorded '{choice}' on {host_name}."


def _local_rows(**filters) -> dict:
    """This computer's space table, read without creating it."""
    try:
        return _st.read_page(**filters)
    except Exception as exc:  # noqa: BLE001 - a broken table is reported, not a 500
        raise FetchError(f"could not read this computer's space table: {exc}") from exc


def _json_from_output(text: str, accept: Callable[[dict], bool]) -> dict | None:
    """The first JSON object in a remote command's output that ``accept`` approves.

    A server's login scripts may print a notice first (the lab's server reminds
    everyone to use nice 19), and the remote command runs in a login shell. The
    object starts at the beginning of a line and runs to its end.
    """
    decoder = json.JSONDecoder()
    start = 0
    while True:
        at = text.find("{", start)
        if at < 0:
            return None
        if at == 0 or text[at - 1] == "\n":
            try:
                data, _end = decoder.raw_decode(text, at)
            except ValueError:
                data = None
            if isinstance(data, dict) and accept(data):
                return data
        start = at + 1


def notify_pi(report: dict, *, lab: str = "",
              send: Callable[..., tuple[bool, str]] | None = None) -> tuple[bool, str]:
    """Send the PI the weekly summary as a Slack direct message.

    Uses the lab's own Slack bot, never a personal token, and finds the PI's
    Slack account from their member file. Never raises: a Slack outage must
    not fail the scan, whose report is already written.
    """
    lab = lab or report.get("lab") or _pu.this_machine_lab()
    try:
        from . import membership as _members
        from .group_reconcile import send_group_dm
        from .lab import pi_handle
        rec = _members.get(pi_handle())
        send = send or send_group_dm
        return send(lab, text=slack_summary(report), slack=rec.slack, email=rec.email)
    except Exception as exc:  # noqa: BLE001 - the report stands without the message
        return False, f"could not send the summary: {exc}"


__all__ = [
    "notify_pi", "fetch_rows", "derive", "rebuild_report", "mount_point", "CONTAINERS", "FetchError", "fetch_report", "REPORT_FILENAME", "REPORT_SCHEMA", "UNCLAIMED_PROJECT", "LabScanBusy",
    "report_path", "lab_projects", "top_level_folders", "unclaimed_folders",
    "lab_wide_folders", "layout_findings", "LAB_WIDE_PROJECT",
    "scan_lab", "read_report", "describe", "slack_summary",
]
