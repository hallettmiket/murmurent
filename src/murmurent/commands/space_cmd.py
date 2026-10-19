"""
Purpose: ``murmurent space``: scan one project for files that could be deleted,
         compressed, moved or asked about; show the table, most pressing
         first; and record a person's decision on each row.
Author:  Mike Hallett (with Claude Code)
Date:    2026-10-16
Input:   The command line; a project record; the space table in
         ``~/.murmurent/space/space.sqlite``.
Output:  Text in the terminal, and the table. No file in the project is
         changed, moved or deleted.

Issue #151, step 2. The logic lives in ``core/space_scan.py`` and
``core/space_table.py``; this file reads options and prints.
"""

from __future__ import annotations

import os
from pathlib import Path

import click

from ..core import cert_projects as _cp
from ..core import lab_vm as _lv
from ..core import project_unit as _pu
from ..core import space_scan as _ss
from ..core import space_table as _st
from ..core.millwright_policy import load_policy
from ..core.run_cards import format_size

TOP = 3


def _project(name: str | None) -> _cp.CertProject:
    """The named project, or the project of the repository you are in."""
    if not name:
        name = _cp.project_name_for_cwd()
        if not name:
            raise click.ClickException(
                "this folder is not inside a repository murmurent knows. "
                "Name the project: murmurent space scan <name>")
    cp = _cp.get(name) or _pu.owning_project(name)
    if cp is None:
        raise click.ClickException(
            f"no project named {name!r}. To list repositories that are in no project, "
            "run: murmurent project migrate")
    return cp


def _short(path: str) -> str:
    """A path relative to the data root, or with ``~`` for the home folder."""
    p = Path(path)
    for base, prefix in ((_lv.data_root(), ""), (Path.home(), "~/")):
        try:
            return prefix + str(p.relative_to(base))
        except ValueError:
            continue
    return path


def _lower_priority() -> None:
    """Run the scan at the lowest priority, like every job on the server."""
    try:
        os.setpriority(os.PRIO_PROCESS, 0, 19)
    except (AttributeError, OSError):
        pass


def _row_lines(number: str, row) -> list[str]:
    files = int(row["n_files"] or 0)
    count = f", {files:,} files" if row["kind"] != "file" and files > 1 else ""
    head = (f"{number}{format_size(int(row['size'] or 0)):>9}  {row['category']}, "
            f"suggest {row['suggestion']}{count}  [row {row['id']}]")
    lines = [head, f"      {_short(row['path'])}", f"      {row['reason']}"]
    if row["evidence"]:
        lines.append(f"      Evidence: {row['evidence']}.")
    if row["owner"]:
        changed = f", last changed {str(row['changed_at'])[:10]}" if row["changed_at"] else ""
        lines.append(f"      Owner {row['owner']}{changed}.")
    if row["cost_cpu_hours"] is not None:
        lines.append(f"      Cost to make again: about {row['cost_cpu_hours']:g} CPU hours.")
    if row["peek"]:
        lines.append("      Starts with:")
        lines += [f"        | {line}" for line in str(row["peek"]).splitlines()]
    if row["decision"]:
        lines.append(f"      Decided: {row['decision']} by {row['decided_by']} on "
                     f"{str(row['decided_at'])[:10]}"
                     + (f" ({row['decision_note']})" if row["decision_note"] else ""))
    return lines


def _echo_pressing(conn, project: str) -> None:
    """Emergencies, then the top three."""
    policy = load_policy()
    found = _st.emergencies(conn, project, disk_fill_limit=policy.disk_emergency_fill_fraction,
                            item_share_of_free=policy.emergency_item_share_of_free)
    if found:
        click.echo("\nEmergencies")
        for e in found:
            click.echo(f"  ! {e.text}" + (f" [row {e.item_id}]" if e.item_id else ""))
    ranked = _st.ranked(conn, project)
    if not ranked:
        click.echo("\nNothing is waiting for a decision.")
        return
    click.echo(f"\nLook at these first (of {len(ranked)} waiting for a decision)")
    for i, (_score, row) in enumerate(ranked[:TOP], start=1):
        for line in _row_lines(f"  {i}.", row):
            click.echo(line)


def _echo_next_steps(project: str) -> None:
    click.echo("\nNothing was changed, moved or deleted.")
    click.echo(f"  The whole table:     murmurent space show {project}")
    click.echo("  Record a decision:   murmurent space decide <row> "
               "keep|delete|mothball|compress|move")


@click.group("space", help="Find files in a project that could be deleted, compressed, "
                           "moved or asked about, and record what you decide. Only "
                           "suggests: nothing is ever changed by these commands.")
def space_group() -> None:
    pass


@space_group.command(
    "scan",
    help="Scan one project's repositories and data folders, and list what could be "
         "deleted, compressed, moved or asked about, most pressing first. Reads sizes, "
         "dates, owners and names. PROJECT defaults to the project of the repository "
         "you are in.")
@click.argument("project", required=False)
@click.option("--no-checksums", is_flag=True, default=False,
              help="Do not look for duplicates. Finding them means reading large files of "
                   "the same size to fingerprint them, which takes a while.")
def space_scan(project: str | None, no_checksums: bool) -> None:
    cp = _project(project)
    _lower_priority()
    roots = _ss.project_roots(cp)
    click.echo(f"Scanning project {cp.name}: "
               + (", ".join(_short(str(r.path)) for r in roots) or "nothing on this computer"))

    def progress(files: int, size: int) -> None:
        click.echo(f"  ... {files:,} files so far ({format_size(size)})", err=True)

    summary = _ss.scan_project(cp, options=_ss.ScanOptions(checksums=not no_checksums,
                                                           progress=progress))
    conn = _st.connect()
    _st.record_scan(conn, summary)
    click.echo(f"Scanned {summary.files:,} files, {format_size(summary.bytes)}.")
    for note in summary.notes:
        click.echo(f"  Note: {note}")
    _echo_pressing(conn, cp.name)
    counts = _st.counts_by_category(conn, cp.name)
    if counts:
        click.echo("\nWaiting for a decision, by category")
        for category, n, size in counts:
            click.echo(f"  {category:<14}{n:>6} rows  {format_size(size):>9}")
    gaps = _st.sop_gaps(conn, cp.name)
    if gaps:
        click.echo(f"\nCases the lab's procedures do not cover: {len(gaps)}. "
                   f"See: murmurent space gaps {cp.name}")
    _echo_next_steps(cp.name)


@space_group.command(
    "show",
    help="Show the space table for a project from its last scan: emergencies, the top "
         "three, then every row still waiting for a decision, largest first.")
@click.argument("project", required=False)
@click.option("--category", type=click.Choice(_st.CATEGORIES), default=None,
              help="Only this category.")
@click.option("--owner", default=None, help="Only files owned by this login.")
@click.option("--min-size", default="", help="Only rows at least this big, such as 1G.")
@click.option("--all", "show_all", is_flag=True, default=False,
              help="Also show rows already decided, suggested keep, or gone.")
@click.option("--limit", type=int, default=50, show_default=True,
              help="The most rows to print. 0 for all.")
def space_show(project: str | None, category: str | None, owner: str | None, min_size: str,
               show_all: bool, limit: int) -> None:
    cp = _project(project)
    conn = _st.connect()
    last = _st.last_scan(conn, cp.name)
    if last is None:
        raise click.ClickException(f"project {cp.name} has not been scanned on this computer. "
                                   f"Run: murmurent space scan {cp.name}")
    from ..core.run_launcher import LaunchError, parse_size
    try:
        smallest = parse_size(min_size) if min_size else 0
    except LaunchError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Project {cp.name}, scanned {str(last['finished_at'])[:16].replace('T', ' ')}: "
               f"{int(last['files'] or 0):,} files, {format_size(int(last['bytes'] or 0))}.")
    filtered = bool(category or owner or smallest or show_all)
    if not filtered:
        _echo_pressing(conn, cp.name)
    found = _st.rows(conn, cp.name, category=category, owner=owner, min_size=smallest,
                     include_settled=show_all)
    click.echo(f"\nRows ({len(found)})" if filtered else f"\nEvery row waiting ({len(found)})")
    shown = found if limit == 0 else found[:limit]
    for row in shown:
        for line in _row_lines("  ", row):
            click.echo(line)
    if len(shown) < len(found):
        click.echo(f"  ... and {len(found) - len(shown)} more. Add --limit 0 to see them all.")
    _echo_next_steps(cp.name)


@space_group.command(
    "decide",
    help="Record your decision on one row of the space table: keep, delete, mothball, "
         "compress or move; or undo. Only records it. Nothing is carried out.")
@click.argument("row", type=int)
@click.argument("decision", type=click.Choice(list(_st.DECISIONS) + ["undo"],
                                              case_sensitive=False))
@click.option("--note", default="", help="Why, in a few words, for whoever carries it out.")
def space_decide(row: int, decision: str, note: str) -> None:
    conn = _st.connect()
    by = _pu.local_handle() or os.environ.get("USER", "") or "unknown"
    try:
        updated = _st.decide(conn, row, decision, by=by, note=note)
    except _st.DecisionError as exc:
        raise click.ClickException(str(exc)) from exc
    if decision.lower() == "undo":
        click.echo(f"Row {row}: decision cleared.")
    else:
        click.echo(f"Row {row}: recorded '{updated['decision']}' for {_short(updated['path'])}.")
        click.echo("Nothing was changed. To carry out mothball, compress or move: "
                   "murmurent space carry-out")


@space_group.command(
    "carry-out",
    help="Carry out the mothball, compress and move decisions in the space table. Each "
         "makes a copy, checks it against fingerprints of the original, and logs it. "
         "Originals are never removed; `murmurent space removable` lists those a person "
         "may now remove. Shows the plan only, unless --apply is given.")
@click.argument("project", required=False)
@click.option("--row", "rows", type=int, multiple=True,
              help="Only this row (repeat for several).")
@click.option("--to", "move_to", default="",
              help="Where a 'move' goes: a folder, or a new name.")
@click.option("--apply", "apply_it", is_flag=True, help="Do it. Without this, only the plan.")
def space_carry_out(project: str | None, rows: tuple[int, ...], move_to: str,
                    apply_it: bool) -> None:
    from ..core import space_actions as _sa
    _lower_priority()
    conn = _st.connect()
    try:
        planned = _sa.plan(conn, project=project, rows=list(rows) or None, move_to=move_to)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    if not planned:
        click.echo("No mothball, compress or move decisions to carry out. Record one with "
                   "murmurent space decide <row> <decision>.")
        return
    todo = [p for p in planned if not p.blocked]
    for p in planned:
        click.echo("  " + p.describe())
    if not apply_it:
        click.echo(f"\n{len(todo)} of {len(planned)} can be carried out. Nothing was changed; "
                   "add --apply to do it. Originals are never removed.")
        return
    by = _pu.local_handle() or os.environ.get("USER", "") or "unknown"
    ok = 0
    for p in todo:
        result = _sa.carry_out(conn, p, by=by)
        ok += result.status == _sa.VERIFIED
        click.echo(f"row {p.row}: {result.status}. {result.detail}")
        for m in result.mismatches[:10]:
            click.echo(f"    {m}")
    click.echo(f"\n{ok} of {len(todo)} copied and checked; each is logged. The originals are "
               "still in place. See which may now be removed: murmurent space removable")


@space_group.command(
    "removable",
    help="List originals a person may now remove: those whose copy was checked by "
         "`carry-out`, and rows decided 'delete'. Projects with a keep-until date in the "
         "future are listed separately. murmurent removes nothing.")
@click.argument("project", required=False)
def space_removable(project: str | None) -> None:
    from ..core import space_actions as _sa
    may, held = _sa.removable(_st.connect(), project=project)
    if not may and not held:
        click.echo("Nothing is waiting to be removed.")
        return
    if may:
        total = sum(r.size for r in may)
        click.echo(f"May be removed by a person ({len(may)}, {_short_size(total)} in all):")
        for r in may:
            click.echo(f"  row {r.row}  {r.path}\n      {r.reason}")
    if held:
        click.echo(f"\nHeld by a keep-until date ({len(held)}):")
        for r in held:
            click.echo(f"  row {r.row}  {r.path}\n      {r.reason}")
    click.echo("\nmurmurent does not remove files. Check each, then remove it yourself.")


def _short_size(n: int) -> str:
    from ..core.run_cards import format_size
    return format_size(int(n))


@space_group.command(
    "gaps",
    help="List the cases the scan found that the lab's written procedures do not cover, "
         "with an example of each, for the PI to write a rule.")
@click.argument("project", required=False)
def space_gaps(project: str | None) -> None:
    cp = _project(project)
    conn = _st.connect()
    gaps = _st.sop_gaps(conn, cp.name)
    if not gaps:
        click.echo(f"No gaps recorded for {cp.name}. (Has it been scanned? "
                   f"murmurent space scan {cp.name})")
        return
    click.echo(f"Cases the lab's procedures do not cover, in {cp.name}")
    for gap in gaps:
        extra = []
        if gap["count"]:
            extra.append(f"{int(gap['count']):,}")
        if gap["size"]:
            extra.append(format_size(int(gap["size"])))
        click.echo(f"  - {gap['detail']}" + (f" ({', '.join(extra)})" if extra else ""))
        if gap["example"]:
            click.echo(f"      for example {_short(gap['example'])}")


# ---------------------------------------------------------------------------
# The whole lab (step 3)
# ---------------------------------------------------------------------------


@space_group.command(
    "scan-lab",
    help="Scan the data folders of every project in this lab, and the folders no "
         "project claims, and write the lab's space report. This is what the weekly "
         "timer runs. Reads only; changes nothing.")
@click.option("--no-checksums", is_flag=True, default=False,
              help="Do not look for duplicates.")
@click.option("--notify", is_flag=True, default=False,
              help="Send the PI a Slack direct message with the summary (no file names).")
def space_scan_lab(no_checksums: bool, notify: bool) -> None:
    from ..core import space_lab as _sl
    if _sl.audit_setting() == "off":
        # Exit quietly and successfully, so a weekly timer left behind after
        # the PI turned the audit off does nothing and reports no failure.
        click.echo(_sl.TURNED_OFF + " Nothing was scanned.")
        return
    _lower_priority()
    try:
        report = _sl.scan_lab(checksums=not no_checksums,
                              progress=lambda msg: click.echo(f"  {msg}"))
    except _sl.LabScanBusy as exc:
        raise click.ClickException(f"{exc}; try again when it has finished.") from exc
    for line in _sl.describe(report):
        click.echo(line)
    if notify:
        ok, detail = _sl.notify_pi(report)
        click.echo("Summary sent to the PI on Slack." if ok
                   else f"Summary not sent to the PI: {detail}")


@space_group.command(
    "lab",
    help="Show the lab's last space report: emergencies, what to look at first, and "
         "every project with how much is waiting for a decision. With --host, fetch it "
         "from that machine (for example from your laptop, from the server the scan "
         "runs on).")
@click.option("--host", "host_name", default="",
              help="A machine from `murmurent host list` to fetch the report from.")
@click.option("--json", "as_json", is_flag=True, default=False,
              help="Print the report as JSON, for other programs.")
@click.option("--rebuild", is_flag=True, default=False,
              help="Redo the report's summaries from the last scan's table, without "
                   "scanning again (on the machine the scan ran on).")
def space_lab_report(host_name: str, as_json: bool, rebuild: bool) -> None:
    import json as _json

    from ..core import space_lab as _sl
    if rebuild and host_name:
        raise click.UsageError("--rebuild runs on the machine the scan ran on; leave out --host")
    report = _sl.rebuild_report() if rebuild else fetch_lab_report(host_name)
    if report is None:
        where = f"on {host_name}" if host_name else "on this computer"
        raise click.ClickException(
            f"no lab space report {where} yet. It is written by "
            "`murmurent space scan-lab`, which the weekly timer runs.")
    if as_json:
        click.echo(_json.dumps(report, indent=2))
        return
    for line in _sl.describe(report):
        click.echo(line)


def fetch_lab_report(host_name: str = "") -> dict | None:
    """The lab report from this computer, or from a registered host over SSH."""
    from ..core import space_lab as _sl
    try:
        return _sl.fetch_report(host_name)
    except _sl.FetchError as exc:
        raise click.ClickException(str(exc)) from exc


@space_group.command(
    "rows",
    help="List rows of the space table waiting for a decision, largest first, with "
         "filters. With --json, one page for other programs (the dashboard's Space page "
         "fetches it this way).")
@click.option("--project", default="", help="Only this project; \"(unclaimed)\" for folders no project claims.")
@click.option("--category", type=click.Choice(_st.CATEGORIES), default=None, help="Only this category.")
@click.option("--suggestion", type=click.Choice(_st.SUGGESTIONS), default=None,
              help="Only this suggestion.")
@click.option("--owner", default="", help="Only files owned by this login.")
@click.option("--min-size", default="", help="Only rows at least this big, such as 10G.")
@click.option("--limit", type=int, default=50, show_default=True, help="Rows per page.")
@click.option("--offset", type=int, default=0, help="Rows to skip, for the next page.")
@click.option("--json", "as_json", is_flag=True, default=False, help="Print JSON.")
def space_rows(project: str, category: str | None, suggestion: str | None, owner: str,
               min_size: str, limit: int, offset: int, as_json: bool) -> None:
    import json as _json

    from ..core.run_launcher import LaunchError, parse_size
    try:
        smallest = parse_size(min_size) if min_size else 0
    except LaunchError as exc:
        raise click.ClickException(str(exc)) from exc
    page = _st.read_page(project=project or None, category=category,
                         suggestion=suggestion, owner=owner or None, min_size=smallest,
                         limit=limit, offset=offset)
    if as_json:
        click.echo(_json.dumps(page))
        return
    click.echo(f"{page['total']:,} rows, {format_size(page['total_bytes'])}; "
               f"showing {page['offset'] + 1} to {page['offset'] + len(page['rows'])}.")
    for r in page["rows"]:
        click.echo(f"  {format_size(r['size']):>9}  {r['project']}: {r['category']}, suggest "
                   f"{r['suggestion']}  [row {r['id']}]")
        click.echo(f"      {r['path']}")


@space_group.command(
    "layout",
    help="Check the lab folder against the lab's folder protocol: each top-level "
         "folder's purpose, subfolders named after projects (or logins in cottage/), "
         "no loose files, and folders being phased out. Reads names only; changes "
         "nothing. Report to the PI; never fix by hand-moving files.")
@click.option("--json", "as_json", is_flag=True, help="Print the findings as JSON.")
def space_layout(as_json: bool) -> None:
    import json as _json

    from ..core import lab_layout as _ll
    projects, logins = _ll.lab_projects_and_logins()
    findings = _ll.check(_lv.data_root(), projects=projects, logins=logins)
    if as_json:
        click.echo(_json.dumps([f.to_dict() for f in findings], indent=2))
        return
    click.echo(f"Lab folder: {_lv.data_root()}")
    for line in _ll.describe(findings):
        click.echo(line)


@space_group.command(
    "schedule",
    help="Show, set up or remove the weekly lab space scan. It runs under your "
         "account at the lowest priority, reads only, and sends you a Slack summary.")
@click.option("--install", is_flag=True, default=False, help="Set up the weekly scan.")
@click.option("--remove", "remove_it", is_flag=True, default=False, help="Remove it.")
@click.option("--day", default="sun", show_default=True, help="Day of the week.")
@click.option("--at", "at", default="02:00", show_default=True, help="Time of day.")
def space_schedule(install: bool, remove_it: bool, day: str, at: str) -> None:
    from ..core import space_lab as _sl
    from ..core import space_schedule as _sch
    try:
        if install and remove_it:
            raise click.UsageError("choose --install or --remove, not both")
        if install and _sl.audit_setting() == "off":
            raise click.ClickException(_sl.TURNED_OFF + " The weekly scan was not set up.")
        if install:
            result = _sch.install(day, at)
        elif remove_it:
            result = _sch.remove()
        else:
            result = _sch.status()
    except (ValueError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc
    except FileNotFoundError as exc:
        # No systemctl: not a Linux server with systemd (a Mac, for example).
        raise click.ClickException(
            "This computer has no systemd, so the weekly scan cannot be scheduled "
            "here. Set it up on the lab's Linux data server instead.") from exc
    for line in result.lines():
        click.echo(line)
    if result.record:
        click.echo("  Commit and push the lab records repository so the lab can see it.")


__all__ = ["space_group", "fetch_lab_report"]
