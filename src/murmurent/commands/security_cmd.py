"""
Purpose: ``murmurent security scan`` — run the Tier-1 unprivileged security
         scanner against a registered host and render results.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-19
Input: ``--host``, optional path overrides, output format.
Output: Rich table to stdout (default) or JSON; persists JSONL to
        ``~/.murmurent/security/<host>/<UTC-date>.jsonl``.

Mirrors :mod:`murmurent.commands.reconcile_cmd` — a thin click wrapper
around :mod:`core.security_remote` so the CC ``/routine`` skill can
schedule daily runs without bespoke plumbing.
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from ..core import hosts as _hosts
from ..core import security_remote as _sr
from ..core.security_findings import (
    Finding, SEVERITY_BLOCK, SEVERITY_WARN, SEVERITY_INFO, write_jsonl,
)


PERSIST_ROOT = Path.home() / ".murmurent" / "security"


def _persist(host_name: str, findings: list[Finding]) -> Path:
    """Write the daily JSONL + refresh the ``latest.jsonl`` symlink."""
    host_dir = PERSIST_ROOT / host_name
    host_dir.mkdir(parents=True, exist_ok=True)
    date = _dt.datetime.utcnow().strftime("%Y-%m-%d")
    target = host_dir / f"{date}.jsonl"
    write_jsonl(target, findings)
    # Refresh ``latest.jsonl`` symlink. Recreate to handle existing link.
    latest = host_dir / "latest.jsonl"
    try:
        if latest.is_symlink() or latest.exists():
            latest.unlink()
        latest.symlink_to(target.name)
    except OSError:
        pass  # symlink is convenience, not load-bearing
    return target


def _render_table(findings: list[Finding], progress: list[str], errors: list[str]) -> None:
    console = Console()
    if progress:
        console.print(f"[dim]progress ({len(progress)} steps):[/]")
        for line in progress[-8:]:
            console.print(f"  [dim]{line}[/]")
        console.print()
    if errors:
        console.print(f"[yellow]parse warnings: {len(errors)}[/]")
        for e in errors[:3]:
            console.print(f"  [yellow]· {e}[/]")
        console.print()
    if not findings:
        console.print("[green]No findings — clean scan.[/]\n")
        return
    by_sev = {SEVERITY_BLOCK: 0, SEVERITY_WARN: 0, SEVERITY_INFO: 0}
    for f in findings:
        by_sev[f.severity] = by_sev.get(f.severity, 0) + 1
    console.print(
        f"[bold]Summary[/] · "
        f"[red]{by_sev[SEVERITY_BLOCK]} BLOCK[/] · "
        f"[yellow]{by_sev[SEVERITY_WARN]} WARN[/] · "
        f"[blue]{by_sev[SEVERITY_INFO]} INFO[/]\n"
    )
    table = Table(show_lines=False)
    table.add_column("sev")
    table.add_column("rule", style="cyan")
    table.add_column("path", style="bold")
    table.add_column("current")
    table.add_column("fix", style="dim", overflow="fold")
    color = {SEVERITY_BLOCK: "red", SEVERITY_WARN: "yellow", SEVERITY_INFO: "blue"}
    for f in findings:
        c = color.get(f.severity, "white")
        path_disp = f.path
        if f.is_directory:
            path_disp += f"  (rolled up · {f.aggregate_count} files)"
        table.add_row(
            f"[{c}]{f.severity}[/]",
            f.rule,
            path_disp,
            f.current_state,
            f.suggested_fix,
        )
    console.print(table)
    console.print()


def cmd_scan(host_name: str, *, json_out: bool = False, timeout: int = 600,
             projects_root: str | None = None, lab_vm_root: str | None = None,
             home_warn_gb: int = 100, repo_large_mb: int = 50,
             lab_group: str | None = None) -> int:
    """Run the scanner. Returns 0 on success, 1 if any BLOCK finding."""
    try:
        host_obj = _hosts.resolve(host_name)
    except _hosts.HostNotFound:
        click.echo(f"host not registered: {host_name}", err=True)
        return 2

    opts = _sr.ScanOptions(
        lab_vm_root=lab_vm_root,
        projects_root=projects_root,
        lab_group=lab_group,
        home_warn_gb=home_warn_gb,
        repo_large_mb=repo_large_mb,
    )

    if not json_out:
        click.echo(f"Scanning {host_name} (this may take a few minutes)...", err=True)

    res = _sr.scan(host_obj, opts, timeout=timeout)

    if not res.ssh_ok:
        click.echo(f"ssh failed: {res.ssh_error}", err=True)
        return 3

    persisted = _persist(host_name, res.findings)

    if json_out:
        click.echo(json.dumps({
            "host": host_name,
            "generated_at": _dt.datetime.utcnow().isoformat() + "Z",
            "findings": [f.to_dict() for f in res.findings],
            "progress": res.progress,
            "parse_errors": res.parse_errors,
            "persisted": str(persisted),
        }, indent=2))
    else:
        _render_table(res.findings, res.progress, res.parse_errors)
        click.echo(f"Persisted to: {persisted}", err=True)

    has_block = any(f.severity == SEVERITY_BLOCK for f in res.findings)
    return 1 if has_block else 0


def _render_personal(report) -> None:
    """Render a :class:`PersonalAuditReport` as a headline-first grouped table."""
    from ..core import personal_audit as _pa

    console = Console()
    # Headline-first (rules/headline_first.md): the verdict line comes first.
    counts = report.counts()
    console.print(f"[bold]{report.headline()}[/]\n")
    console.print(
        f"[bold]Summary[/] · "
        f"[red]{counts['block']} BLOCK[/] · "
        f"[yellow]{counts['concern']} CONCERN[/] · "
        f"[green]{counts['ok']} OK[/] · "
        f"[dim]{counts['unverifiable']} could-not-verify[/]\n"
    )
    color = {SEVERITY_BLOCK: "red", SEVERITY_WARN: "yellow", SEVERITY_INFO: "blue"}
    by_area = report.by_area()
    for area in _pa.ALL_AREAS:
        rows = by_area.get(area) or []
        if not rows:
            continue
        console.print(f"[bold cyan]{area}[/]")
        table = Table(show_lines=False)
        table.add_column("sev")
        table.add_column("verify")
        table.add_column("rule", style="cyan")
        table.add_column("finding", overflow="fold")
        table.add_column("fix", style="dim", overflow="fold")
        for f in rows:
            c = color.get(f.severity, "white")
            vs = "[dim]?[/]" if f.verify_state != "verified" else "[green]✓[/]"
            table.add_row(f"[{c}]{f.severity}[/]", vs, f.rule,
                          f.current_state, f.suggested_fix)
        console.print(table)
        console.print()


def cmd_audit_me(*, json_out: bool = False) -> int:
    """Run the LOCAL personal audit (issue #63 Phase 1). Returns 1 if any
    BLOCK finding, else 0."""
    from ..core import personal_audit as _pa

    report, path = _pa.run_and_persist()
    if json_out:
        payload = report.to_dict()
        payload["persisted"] = str(path)
        click.echo(json.dumps(payload, indent=2))
    else:
        _render_personal(report)
        click.echo(f"Persisted to: {path}", err=True)
    return 1 if report.counts()["block"] else 0


def _render_secret_hits(hits, scope_desc: str) -> None:
    """Render redacted secret hits grouped by file, headline-first."""
    from ..core.secret_scan import SEVERITY_BLOCK, SEVERITY_WARN

    console = Console()
    n_block = sum(1 for h in hits if h.severity == SEVERITY_BLOCK)
    n_warn = sum(1 for h in hits if h.severity == SEVERITY_WARN)

    # Headline-first (rules/headline_first.md).
    if n_block:
        console.print(
            f"[bold red]BLOCKED[/] — {n_block} block-severity secret(s) in "
            f"{scope_desc}; do NOT push.\n"
        )
    elif n_warn:
        console.print(
            f"[bold yellow]Warnings[/] — {n_warn} secret-looking value(s) in "
            f"{scope_desc}; review before pushing.\n"
        )
    else:
        console.print(f"[bold green]Clear[/] — no secrets detected in {scope_desc}.\n")
        return

    color = {SEVERITY_BLOCK: "red", SEVERITY_WARN: "yellow"}
    show_commit = any(getattr(h, "commit", "") for h in hits)
    by_file: dict[str, list] = {}
    for h in hits:
        by_file.setdefault(h.path, []).append(h)
    for path in sorted(by_file):
        console.print(f"[bold]{path}[/]")
        table = Table(show_lines=False)
        table.add_column("sev")
        table.add_column("line", justify="right")
        if show_commit:
            table.add_column("commit", style="magenta")
        table.add_column("rule", style="cyan")
        table.add_column("redacted")
        table.add_column("hint", style="dim", overflow="fold")
        for h in sorted(by_file[path], key=lambda x: x.line):
            c = color.get(h.severity, "white")
            row = [f"[{c}]{h.severity}[/]", str(h.line)]
            if show_commit:
                row.append((getattr(h, "commit", "") or "")[:9])
            row += [h.rule, h.redacted, h.hint]
            table.add_row(*row)
        console.print(table)
        console.print()


def cmd_secrets_scan(*, staged: bool = True, tracked: bool = False,
                     paths: tuple[str, ...] = (), history: bool = False,
                     json_out: bool = False,
                     strict: bool = False, repo_root: str | None = None) -> int:
    """Deterministic secret-CONTENT scan.

    Exit-code contract (this is what the ``murmurent-push`` skill gates on):

    - **2** — at least one ``block``-severity hit (high-confidence secret).
      Never push.
    - **1** — only ``warn`` hits AND ``--strict`` was given.
    - **0** — clean, or warn-only without ``--strict``.
    """
    from ..core import secret_scan as _ss

    root = repo_root or "."
    if history:
        hits = _ss.scan_history(root)
        scope = "git history"
    elif paths:
        hits = _ss.scan_paths(list(paths))
        scope = f"{len(paths)} path(s)"
    elif tracked:
        tracked_paths = _ss._git(root, ["ls-files", "-z"]).split("\0")
        tracked_paths = [str(Path(root) / p) for p in tracked_paths if p]
        hits = _ss.scan_paths(tracked_paths)
        scope = "tracked files"
    else:  # default: --staged
        hits = _ss.scan_staged(root)
        scope = "staged changes"

    n_block = sum(1 for h in hits if h.severity == _ss.SEVERITY_BLOCK)
    n_warn = sum(1 for h in hits if h.severity == _ss.SEVERITY_WARN)

    if json_out:
        click.echo(json.dumps({
            "scope": scope,
            "block": n_block,
            "warn": n_warn,
            "hits": [h.to_dict() for h in hits],
        }, indent=2))
    else:
        _render_secret_hits(hits, scope)

    if n_block:
        return 2
    if n_warn and strict:
        return 1
    return 0


def add_to_cli(cli_group: click.Group) -> None:
    """Attach the ``murmurent security`` subcommand group."""

    @cli_group.group("security", help="Per-lab security agent + dashboard.")
    def _security() -> None:
        """Security agent commands."""

    @_security.command("audit-me",
                       help="Run the LOCAL personal security audit (no SSH).")
    @click.option("--json", "json_out", is_flag=True, help="Emit JSON instead of a table.")
    def _audit_me(json_out: bool) -> None:
        sys.exit(cmd_audit_me(json_out=json_out))

    @_security.command("scan", help="Run the Tier-1 scanner on a host (unprivileged).")
    @click.option("--host", required=True, help="Registered host name (see `murmurent host list`).")
    @click.option("--json", "json_out", is_flag=True, help="Emit JSON instead of a Rich table.")
    @click.option("--timeout", default=600, type=int, help="SSH timeout in seconds.")
    @click.option("--projects-root", default=None, help="Override remote ~/repos.")
    @click.option("--lab-vm-root", default=None, help="Override remote /data/lab_vm.")
    @click.option("--lab-group", default=None, help="Lab Unix group (e.g. labgroup).")
    @click.option("--home-warn-gb", default=100, type=int, help="HOME-SIZE-01 threshold.")
    @click.option("--repo-large-mb", default=50, type=int, help="HOME-REPO-LARGE-01 threshold.")
    def _scan(host: str, json_out: bool, timeout: int,
              projects_root: str | None, lab_vm_root: str | None,
              lab_group: str | None, home_warn_gb: int, repo_large_mb: int) -> None:
        rc = cmd_scan(host, json_out=json_out, timeout=timeout,
                      projects_root=projects_root, lab_vm_root=lab_vm_root,
                      lab_group=lab_group, home_warn_gb=home_warn_gb,
                      repo_large_mb=repo_large_mb)
        sys.exit(rc)

    @_security.command(
        "secrets-scan",
        help="Deterministic secret-CONTENT scan of staged/tracked/given paths "
             "(pre-push gate). Exit 2 on a block hit.",
    )
    @click.option("--staged", "mode_staged", is_flag=True, default=False,
                  help="Scan STAGED content (the default when no mode/paths given).")
    @click.option("--tracked", "mode_tracked", is_flag=True, default=False,
                  help="Scan all git-tracked files instead of the staged set.")
    @click.option("--history", "mode_history", is_flag=True, default=False,
                  help="Scan added lines across (bounded) git history — catches "
                       "secrets committed then later deleted.")
    @click.option("--strict", is_flag=True, default=False,
                  help="Exit 1 on warn-only hits (default: warn-only exits 0).")
    @click.option("--json", "json_out", is_flag=True, help="Emit JSON instead of a table.")
    @click.argument("paths", nargs=-1, type=click.Path())
    def _secrets_scan(mode_staged: bool, mode_tracked: bool, mode_history: bool,
                      strict: bool, json_out: bool, paths: tuple[str, ...]) -> None:
        # Default to --staged unless the caller named paths / --tracked / --history.
        use_staged = mode_staged or (not mode_tracked and not mode_history
                                     and not paths)
        rc = cmd_secrets_scan(staged=use_staged, tracked=mode_tracked,
                              history=mode_history, paths=paths,
                              json_out=json_out, strict=strict)
        sys.exit(rc)


__all__ = ["cmd_scan", "cmd_audit_me", "cmd_secrets_scan", "add_to_cli"]
