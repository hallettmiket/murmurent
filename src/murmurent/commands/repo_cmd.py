"""
Purpose: CLI handlers for ``murmurent repo {list, status, adopt}``.
Author: Mike Hallett (with Claude Code)
Date: 2026-07-14
Input: Arguments from the click subcommand layer.
Output: Stdout tables/ladders + (for adopt) the same side effects as the
        dashboard's Repos-panel "↑ adopt" button.

The ``repo`` command tree is the terminal twin of the dashboard's Repos
panel: see every clone on every registered machine (local included),
ask whether any one repo has been adopted (made murmurent-ready), and
adopt a plain clone without opening the dashboard. All three lean on
the same core modules the panel uses (:mod:`core.repo_inventory`,
:mod:`core.adopt`), so the two surfaces can't drift.
"""

from __future__ import annotations

import os
from pathlib import Path

import click

from ..core import adopt as _adopt
from ..core import hosts as _hosts
from ..core import repo_inventory as _inv

# Verdict → glyph, matching the Repos panel's cell vocabulary.
_GLYPH = {
    "adopted": "✓ adopted",
    "partial": "± partial",
    "plain clone": "• clone",
    "not a git repo": "✗ not a git repo",
    "missing": "✗ missing",
}


def _looks_like_path(target: str) -> bool:
    return target.startswith(("/", "~", ".")) or "/" in target


def _clone_verdict(clone: _inv.RepoOnHost) -> str:
    if clone.has_charter and clone.has_claude_dir:
        return "adopted"
    if clone.has_charter or clone.has_claude_dir:
        return "partial"
    return "plain clone"


def cmd_list(host_filter: str | None) -> int:
    """Print every clone on every registered machine (local included),
    grouped by host, with its adoption verdict."""
    registry = _hosts.read()
    if host_filter:
        if host_filter not in registry:
            raise click.ClickException(
                f"unknown host {host_filter!r} — see `murmurent host list`"
            )
        registry = {host_filter: registry[host_filter]}

    for name, host in registry.items():
        target = host.ssh_host if host.is_remote() else "(this machine)"
        click.echo(f"{name}  {target}")
        clones, err = _inv.list_machine_repos(name)
        if err:
            click.echo(f"  ! scan failed: {err}")
            continue
        if not clones:
            dirs = ", ".join(_inv._effective_scan_dirs(host))
            click.echo(f"  (no git repos under {dirs})")
            continue
        name_w = max(len(Path(c.path).name) for c in clones) + 1
        for c in sorted(clones, key=lambda c: Path(c.path).name.lower()):
            verdict = _GLYPH[_clone_verdict(c)]
            click.echo(f"  {Path(c.path).name:<{name_w}} {verdict:<14} {c.path}")
    return 0


def _print_status(st: _adopt.AdoptionStatus) -> None:
    mark = lambda b: "✓" if b else "—"  # noqa: E731
    click.echo(f"{st.host}:{st.path}")
    click.echo(f"  verdict:         {_GLYPH.get(st.verdict, st.verdict)}")
    click.echo(f"  git working tree {mark(st.is_git)}")
    click.echo(f"  CHARTER.md       {mark(st.has_charter)}")
    click.echo(f"  .claude/agents/  {mark(st.has_claude_agents)}")
    click.echo(f"  manifest         {st.manifest_path or '—'}")


def cmd_status(target: str, host_name: str | None) -> int:
    """Report whether a repo has been adopted.

    ``target`` is either a path (checked directly, on ``--host`` or
    local) or a bare repo name (searched across every registered
    machine's scan dirs). Exit code: 0 = every clone found is adopted,
    1 = found but not (fully) adopted, 2 = not found.
    """
    statuses: list[_adopt.AdoptionStatus] = []

    if _looks_like_path(target):
        try:
            statuses.append(
                _adopt.adoption_status(target, host=host_name or "local")
            )
        except _adopt.AdoptError as exc:
            raise click.ClickException(str(exc)) from exc
    else:
        registry = _hosts.read()
        if host_name:
            if host_name not in registry:
                raise click.ClickException(
                    f"unknown host {host_name!r} — see `murmurent host list`"
                )
            registry = {host_name: registry[host_name]}
        for name in registry:
            clones, err = _inv.list_machine_repos(name)
            if err:
                click.echo(f"! {name}: scan failed: {err}", err=True)
                continue
            for c in clones:
                if Path(c.path).name != target:
                    continue
                statuses.append(_adopt.AdoptionStatus(
                    host=name, path=c.path, exists=True, is_git=True,
                    has_charter=c.has_charter,
                    has_claude_agents=c.has_claude_dir,
                    manifest_path=(
                        str(mf) if (mf := _adopt.find_manifest_for(
                            c.path, host=name)) else None
                    ),
                ))

    found = [s for s in statuses if s.exists]
    if not found:
        click.echo(f"{target}: not found on any registered machine")
        return 2
    for st in found:
        _print_status(st)
    return 0 if all(s.adopted for s in found) else 1


def cmd_adopt(
    *,
    path: str,
    project: str | None,
    lead: str | None,
    members_csv: str | None,
    sensitivity: str,
    description: str,
    choreography: str | None,
    agents_csv: str | None,
    host_name: str,
    reb_number: str | None,
    reb_expires: str | None,
    data_residency: str | None,
) -> int:
    """Adopt an existing clone as a murmurent project (CLI twin of the
    Repos panel's ↑ adopt button)."""
    project = project or Path(path).name
    lead = lead or (
        "@" + os.environ.get("MURMURENT_USER", "").strip().lstrip("@")
        if os.environ.get("MURMURENT_USER", "").strip() else None
    )
    if not lead:
        raise click.ClickException(
            "no --lead given and $MURMURENT_USER is unset — pass --lead @handle"
        )
    members = (
        [m.strip() for m in members_csv.split(",") if m.strip()]
        if members_csv else [lead]
    )
    agents = (
        [a.strip() for a in agents_csv.split(",") if a.strip()]
        if agents_csv else []
    )

    try:
        outcome = _adopt.adopt_clone(
            clone_path=path,
            project=project,
            lead=lead,
            members=members,
            sensitivity=sensitivity,
            description=description,
            choreography=choreography,
            agents=agents,
            host=host_name,
            reb_number=reb_number,
            reb_expires=reb_expires,
            data_residency=data_residency,
        )
    except _adopt.AdoptError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"Adopted {project} on {outcome.host} ({outcome.clone_path}).")
    icon = {"ok": "✓", "warn": "!", "fail": "✗"}
    for p in outcome.result.probes:
        click.echo(f"  {icon.get(p.status, '?')} {p.name}: {p.detail}")
    click.echo("Next: `murmurent repo status "
               f"{project}` or check the dashboard's Repos panel.")
    return 0
