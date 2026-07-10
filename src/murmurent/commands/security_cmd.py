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


def add_to_cli(cli_group: click.Group) -> None:
    """Attach the ``murmurent security`` subcommand group."""

    @cli_group.group("security", help="Per-lab security agent + dashboard.")
    def _security() -> None:
        """Security agent commands."""

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


__all__ = ["cmd_scan", "add_to_cli"]
