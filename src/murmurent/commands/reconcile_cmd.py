"""
Purpose: ``murmurent reconcile`` — compare murmurent's recorded state to
         on-disk reality across every host, report drift, optionally
         repair the actionable subset.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-17
Input: ``--apply`` flag (default: dry run); ``--no-slack`` to suppress
       the Slack notification (default: post a summary).
Output: Rich-rendered drift table to stdout; optional Slack post to
        ``#claude-test``; non-zero exit when ``--apply`` was needed
        but skipped (so CI/cron picks up dirty state).

Pairs with :mod:`core.reconcile` for the detection + repair logic.
"""

from __future__ import annotations

import os
import sys

import click
from rich.console import Console
from rich.table import Table

from ..core import reconcile as _rec


SLACK_CHANNEL_ID = "C0B3D9DS6SE"  # #claude-test (per rules/slack.md)


def cmd_reconcile(*, apply: bool, slack_body: bool) -> int:
    """Run reconciliation and render the report.

    The actual Slack post is left to the caller (typically the CC
    routine that wraps this CLI) — murmurent doesn't ship a non-MCP
    Slack client, and the CC session that schedules this command
    has the slack MCP tool available anyway. With ``--slack-body``
    the function prints the formatted message to stdout after the
    table so the routine can copy it verbatim.

    Returns an exit code:
      - 0 when nothing was drift OR everything actionable was applied.
      - 1 when actionable drift was detected and ``apply`` was False
        (so cron / CI can branch on it).
    """
    report = _rec.reconcile(apply=apply)
    _render_table(report)
    if slack_body:
        click.echo("\n--- slack body (copy into #claude-test) ---")
        click.echo(_build_slack_body(report, applied=apply))
    actionable = [f for f in report.findings if f.severity == "actionable"]
    if actionable and not apply:
        return 1
    return 0


def _render_table(report: _rec.ReconcileReport) -> None:
    """Pretty-print the report to stdout."""
    console = Console()
    console.print(f"\n[bold]Murmurent reconcile[/] — {report.generated_at}")
    console.print(f"[dim]{report.summary_line()}[/]\n")
    if not report.findings:
        console.print("[green]Nothing to do.[/]\n")
        return
    table = Table(show_lines=False)
    table.add_column("kind", style="cyan")
    table.add_column("sev")
    table.add_column("host")
    table.add_column("target", style="bold")
    table.add_column("detail")
    table.add_column("action", style="dim")
    for f in report.findings:
        sev_color = {"info": "blue", "warn": "yellow", "actionable": "red"}[f.severity]
        table.add_row(
            f.kind, f"[{sev_color}]{f.severity}[/]",
            f.host, f.target, f.detail, f.suggested_action,
        )
    console.print(table)
    if report.applied:
        console.print(f"\n[green]Applied {len(report.applied)} fix(es):[/]")
        for f in report.applied:
            console.print(f"  ✓ {f.kind} {f.host}:{f.target}")
    if report.errors:
        console.print(f"\n[red]Errors ({len(report.errors)}):[/]")
        for e in report.errors:
            console.print(f"  ✗ {e}")
    console.print()


def _build_slack_body(report: _rec.ReconcileReport, *, applied: bool) -> str:
    """Compose the Slack message. Trailing 'All worship me…' is added
    per rules/slack.md."""
    head = f"*murmurent reconcile* — {report.generated_at}\n{report.summary_line()}"
    by_kind = report.by_kind()
    lines = [head]
    if report.findings:
        for kind, items in sorted(by_kind.items()):
            lines.append(f"\n*{kind}* ({len(items)}):")
            for f in items[:5]:  # cap per-section so the message stays scannable
                lines.append(f"  • `{f.host}:{f.target}` — {f.detail}")
            if len(items) > 5:
                lines.append(f"  • _… and {len(items) - 5} more_")
    if applied:
        lines.append(f"\n*Applied:* {len(report.applied)} fix(es).")
    elif any(f.severity == "actionable" for f in report.findings):
        lines.append(
            "\n_Dry-run only. Run `murmurent reconcile --apply` "
            "to archive orphan manifests + flip registry status._"
        )
    if report.errors:
        lines.append(f"\n*Errors:* {len(report.errors)} (see stdout).")
    lines.append("\nAll worship me and I will let you serve me.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Click wiring (called from src/murmurent/cli.py)
# ---------------------------------------------------------------------------


def add_to_cli(cli_group: click.Group) -> None:
    """Attach the ``murmurent reconcile`` subcommand to the CLI group."""

    @cli_group.command("reconcile", help="Detect drift between murmurent's state and on-disk reality.")
    @click.option("--apply", is_flag=True,
                  help="Repair actionable findings (archive manifests, flip registry status). "
                       "Default: dry-run.")
    @click.option("--slack-body", is_flag=True,
                  help="After the table, print a formatted summary suitable for "
                       "pasting into #claude-test (the CC routine posts it via MCP).")
    def _reconcile_cmd(apply: bool, slack_body: bool) -> None:
        rc = cmd_reconcile(apply=apply, slack_body=slack_body)
        sys.exit(rc)


__all__ = ["cmd_reconcile", "add_to_cli"]
