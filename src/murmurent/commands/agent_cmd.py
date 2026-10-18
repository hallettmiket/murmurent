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

from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from ..core import agent_forks as _af


def cmd_new(name: str, *, description: str = "", model: str | None = None,
            tools: list[str] | None = None) -> None:
    """Create a net-new personal agent in the member's vault + install it."""
    from ..core import personal_agents as _pa

    try:
        path = _pa.create_personal_agent(name, description, model=model, tools=tools)
    except _pa.PersonalAgentError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Created personal agent {name!r}.")
    click.echo(f"  vault file:  {path}   (backed up on `murmurent vault sync`)")
    click.echo(f"  loaded by CC via a symlink in {_af.installed_agents_dir()}")
    click.echo("  edit the vault file to shape how it works; it is yours alone.")


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


def cmd_which(repo: str | None) -> None:
    """Print which definition of each agent Claude Code will use, and where it
    comes from (#186 step 1). With ``repo``, for a session in that repo."""
    from ..core import agent_in_use as _aiu

    root = Path(repo).expanduser().resolve() if repo else None
    rows = _aiu.which_all(repo=root)
    if not rows:
        click.echo("No agents found.")
        return
    tone = {"centre": "", "yours": "magenta", "project": "green",
            "local-file": "yellow", "broken-link": "red", "missing": "red"}
    where = f"a session in {root}" if root else "a session outside any repo"
    table = Table(title=f"Agents Claude Code will use in {where}")
    table.add_column("agent", style="bold")
    table.add_column("in use")
    table.add_column("why")
    for r in rows:
        style = tone.get(r.level, "")
        label = f"[{style}]{r.label}[/{style}]" if style else r.label
        table.add_row(r.name, label, r.detail)
    Console().print(table)


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


def cmd_relink() -> None:
    """Re-link every vault agent + fork into ``~/.claude/agents/`` (issue #80).

    Run after a vault pull on a second machine (setup.sh also runs it), so
    agents created or forked elsewhere are loaded by Claude Code here.
    """
    from ..core import personal_agents as _pa

    res = _pa.relink_vault_agents()
    mig = res.get("migrated") or {}
    if mig.get("migrated"):
        click.echo(f"Migrated legacy fork home: {mig.get('detail', '')}")
        if mig.get("backup"):
            click.echo(f"  backup kept at {mig['backup']}")
    for row in res["personal"]:
        click.echo(f"  personal  {row['name']:<20} {row['method']}")
    for row in res["forks"]:
        click.echo(f"  fork      {row['name']:<20} {row['method']}")
    for row in res["skipped"]:
        click.echo(f"  skipped   {row['name']:<20} {row['reason']}")
    n = len(res["personal"]) + len(res["forks"])
    if n == 0 and not res["skipped"]:
        if res.get("vault_agents") is None:
            click.echo("No personal vault registered on this machine — nothing "
                       "to re-link (run `murmurent vault init` first).")
        else:
            click.echo("No vault agents or forks to re-link.")
    else:
        click.echo(f"Re-linked {n} agent(s) into {_af.installed_agents_dir()}.")
    # The lab's versions, where you have none of your own (#186).
    from ..core import agent_levels as _lv
    _print_sync("lab versions", _lv.sync_user_level())


# ---------------------------------------------------------------------------
# Levels: lab, project, and your own version for one project (#186)
# ---------------------------------------------------------------------------


def _print_sync(where: str, rep) -> None:
    if rep.linked:
        click.echo(f"{where}: " + ", ".join(rep.linked))
    if rep.off:
        click.echo(f"{where}: switched off: " + ", ".join(rep.off))
    for note in rep.notes:
        click.echo(f"{where}: {note}")


def cmd_sync(repo: str | None, all_repos: bool) -> None:
    """Install the winning version of each agent: the lab's into your agents
    folder, and the project's or your per-project versions into each repo."""
    from ..core import agent_levels as _lv
    _print_sync("your agents folder", _lv.sync_user_level())
    targets: list[tuple[str | None, Path]] = []
    if repo:
        targets.append((None, Path(repo).expanduser().resolve()))
    elif all_repos:
        targets = list(_lv.local_project_repos())
    else:
        here = Path.cwd()
        if (here / ".git").exists():
            targets.append((None, here))
    for project, path in targets:
        _print_sync(str(path), _lv.sync_repo(path, project))
    click.echo("Done. Open a new Claude Code session for the changes to apply.")


def cmd_fork_for_project(name: str, project: str) -> None:
    """Copy the version you use now into your vault as your version for one
    project, then install it in that project's repos."""
    from ..core import agent_levels as _lv
    try:
        dest, created = _lv.fork_for_project(name, project)
    except _lv.LevelError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo((f"Copied {name} to {dest}." if created
                else f"You already have your own {name} for {project}: {dest}"))
    click.echo(f"Edit it, then run `murmurent vault sync` to keep it on your other "
               "machines. Open a new Claude Code session for it to apply.")


def cmd_switch(name: str, project: str, off: bool) -> None:
    """Switch an agent off (or back on) for you in one project."""
    from ..core import agent_levels as _lv
    try:
        _lv.switch(name, project, off)
    except _lv.LevelError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"{name} is {'switched off' if off else 'back on'} for you in {project}. "
               "Open a new Claude Code session for it to apply.")


def cmd_share(name: str, to_lab: bool, repo: str | None) -> None:
    """Share the version you use now: with the whole lab (PI only), or with a
    project team by putting it in the repo for you to commit."""
    import shutil
    from ..core import agent_levels as _lv
    if _lv.is_locked(name):
        raise click.ClickException(f"{name} is centre-controlled and cannot be replaced.")
    win = _lv.resolve(name, user_level_only=True)
    if win is None:
        raise click.ClickException(f"no agent named {name!r}.")
    if to_lab:
        try:
            dest, probes = _lv.share_with_lab(name)
        except _lv.LevelError as exc:
            raise click.ClickException(str(exc)) from exc
        click.echo(f"The lab's {name} is now {dest}.")
        for pr in probes:
            click.echo(f"  {pr.name}: {pr.detail}")
        click.echo("Members get it when their dashboard next updates the lab repo, or with "
                   "`murmurent agent sync`. A member's own version still wins.")
    elif repo:
        root = Path(repo).expanduser().resolve()
        dest = _lv.project_agents_dir(root) / f"{name}.md"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(win.path, dest)
        _print_sync(str(root), _lv.sync_repo(root))
        click.echo(f"Copied to {dest}. Commit and push it so the whole project uses it:\n"
                   f"  git -C {root} add .murmurent/agents/{name}.md && git -C {root} commit "
                   f"-m 'project version of {name}' && git -C {root} push")
    else:
        raise click.ClickException("say who to share with: --lab, or --repo <folder>.")


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
