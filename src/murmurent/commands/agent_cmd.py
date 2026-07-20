"""
Purpose: CLI handlers for ``murmurent agent {list, fork, drift, unfork}``.
Author: Mike Hallett (with Claude Code)
Date: 2026-07-20
Input: Arguments from the click subcommand layer.
Output: Stdout tables/messages + fork side effects (see :mod:`core.agent_forks`).

The ``fork`` family lets a member peel a commons agent off the symlink into a
personal, upgrade-surviving copy, keep it across ``git pull`` / setup.sh
re-runs, and see when the commons version has drifted. The heavy lifting lives
in :mod:`core.agent_forks`; this module is the CLI surface only.
"""

from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

from ..core import agent_forks as _af


def _upstream_label(st: _af.AgentStatus) -> str:
    if not st.in_commons:
        return "[yellow]orphaned[/yellow]"
    return "[yellow]upstream-changed[/yellow]" if st.upstream_changed else "[green]up-to-date[/green]"


def _local_label(st: _af.AgentStatus) -> str:
    return "[cyan]locally-modified[/cyan]" if st.locally_modified else "[green]clean[/green]"


def cmd_list() -> None:
    """Print every installed agent with its linked/forked + drift status."""
    rows = _af.iter_status()
    if not rows:
        click.echo(f"No agents installed in {_af.installed_agents_dir()}.")
        return
    console = Console()
    table = Table(title=f"Installed agents ({_af.installed_agents_dir()})")
    table.add_column("name", style="bold")
    table.add_column("status")
    table.add_column("upstream")
    table.add_column("local")
    for st in rows:
        if st.kind == "forked":
            table.add_row(st.name, "forked", _upstream_label(st), _local_label(st))
        elif st.kind == "linked":
            table.add_row(st.name, "linked", "[dim]—[/dim]", "[dim]—[/dim]")
        else:  # user-file
            table.add_row(st.name, "[magenta]user-file[/magenta]", "[dim]—[/dim]", "[dim]—[/dim]")
    console.print(table)


def cmd_fork(name: str, force: bool) -> None:
    """Fork ``name`` into a personal copy that survives commons upgrades."""
    try:
        res = _af.fork_agent(name, force=force)
    except _af.AgentForkError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Forked {name!r} → personal copy ({res.method}).")
    click.echo(f"  working copy:  {res.working}")
    click.echo(f"  canonical:     {res.canonical}  (git-track {res.canonical.parent})")
    click.echo(f"  source sha:    {res.source_sha[:12]}  · forked {res.forked_at}")
    click.echo("  edits here are preserved across `git pull` + setup.sh re-runs.")


def cmd_drift(name: str | None) -> None:
    """Report which forks have upstream and/or local changes to review."""
    forks = _af.iter_forks()
    if name is not None:
        forks = [st for st in forks if st.name == name]
        if not forks:
            raise click.ClickException(
                f"{name!r} is not a tracked fork — run `murmurent agent fork {name}` first."
            )
    if not forks:
        click.echo("No forked agents. Nothing to compare.")
        return

    console = Console()
    n_review = 0
    for st in forks:
        if not st.in_commons:
            hint = "orphaned: commons no longer ships this agent — keep your copy or delete it"
            tag = "[yellow]ORPHANED[/yellow]"
        elif st.diverged:
            n_review += 1
            hint = "diverged: BOTH commons and your copy changed — review + merge upstream edits"
            tag = "[red]DIVERGED[/red]"
        elif st.upstream_changed:
            n_review += 1
            hint = "upstream-changed: commons advanced — review, then re-fork with --force to adopt"
            tag = "[yellow]UPSTREAM[/yellow]"
        elif st.locally_modified:
            hint = "local edits only — up to date with commons, nothing to merge"
            tag = "[green]LOCAL-ONLY[/green]"
        else:
            hint = "identical to the commons fork point — nothing to do"
            tag = "[green]UP-TO-DATE[/green]"
        console.print(f"{tag}  [bold]{st.name}[/bold] — {hint}")

    if name is None:
        summary = (
            f"{n_review} fork(s) have upstream changes to review."
            if n_review
            else "All forks are up to date with the commons."
        )
        console.print(f"\n{summary}")


def cmd_unfork(name: str, force: bool) -> None:
    """Restore the commons symlink after confirmation (or with ``--force``)."""
    st = _af.status_for(name)
    if st is None:
        raise click.ClickException(f"{name!r} is not installed in {_af.installed_agents_dir()}.")
    if st.kind == "linked":
        raise click.ClickException(f"{name!r} is already linked to the commons — nothing to unfork.")
    if st.locally_modified and not force:
        click.echo(f"Warning: your {name!r} copy has local edits that will be discarded.")
    if not force:
        click.confirm(
            f"Restore {name!r} to the commons symlink and delete your personal copy?",
            abort=True,
        )
    try:
        dest = _af.unfork_agent(name, force=force)
    except _af.AgentForkError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Unforked {name!r} → relinked to the commons ({dest}).")
