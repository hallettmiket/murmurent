"""
Purpose: Implementations of ``murmurent sea ...`` subcommands.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-07
Input: CLI arguments forwarded from :mod:`murmurent.cli`.
Output: Side effects on ``<project>/seas/<id>.md``; messages to stdout.
"""

from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

from ..core import deliberation, sea
from ..core.identity import resolve as resolve_identity
from ..core.projects import find_project, iter_local_projects
from ..core.repo import ProjectRepo

VALID_DIRECTIONS: tuple[str, ...] = ("mine", "incoming", "outgoing")


def _at(handle: str) -> str:
    handle = handle.strip()
    return handle if handle.startswith("@") else f"@{handle}"


def _resolve_project_repo(project_name: str | None) -> ProjectRepo:
    """Resolve the project repo to operate on. Phase 3 keeps it explicit."""
    if project_name:
        repo = find_project(project_name)
        if repo is None:
            raise click.ClickException(f"Project not found locally: {project_name}")
        return repo
    raise click.ClickException(
        "No --project given. Pass --project <name> for sea commands until "
        "context-aware project resolution lands."
    )


def _resolve_sea_globally(sea_id: int) -> tuple[ProjectRepo, sea.Sea]:
    """Find a SEA by global id across all local projects.

    SEAs are filed inside individual project repos but their integer IDs are
    monotonically increasing across the whole tutorial; this helper lets the
    CLI accept a bare ``<id>`` without forcing the user to pass --project.
    """
    matches: list[tuple[ProjectRepo, sea.Sea]] = []
    for repo in iter_local_projects():
        for s in sea.iter_seas(repo):
            if s.id == sea_id:
                matches.append((repo, s))
    if not matches:
        raise click.ClickException(f"SEA {sea_id} not found in any local project.")
    if len(matches) > 1:
        names = ", ".join(repo.path.name for repo, _ in matches)
        raise click.ClickException(
            f"SEA id {sea_id} is ambiguous (found in: {names}); pass --project."
        )
    return matches[0]


def cmd_request(
    *,
    project_name: str | None,
    to_target: str,
    kind: str,
    description: str,
    from_handle: str | None = None,
) -> sea.Sea:
    """``murmurent sea request`` — file a new SEA inside a project."""
    if kind not in sea.VALID_KINDS:
        raise click.ClickException(f"--kind must be one of {sea.VALID_KINDS!r}; got {kind!r}")
    repo = _resolve_project_repo(project_name)
    if from_handle is None:
        identity = resolve_identity(allow_unknown=True)
        from_handle = identity.at_handle
    new_id = sea.next_sea_id(repo)
    new = sea.Sea(
        id=new_id,
        from_handle=_at(from_handle),
        to_handle=_at(to_target),
        kind=kind,
        description=description,
    )
    sea.write_sea(repo, new)
    click.echo(f"Filed SEA {new.id} in {repo.path.name}: {new.from_handle} -> {new.to_handle}")
    return new


def cmd_list(
    *,
    project_name: str | None,
    mine: bool,
    incoming: bool,
    outgoing: bool,
) -> int:
    """``murmurent sea list`` — print SEAs filtered by direction."""
    if sum(1 for f in (mine, incoming, outgoing) if f) > 1:
        raise click.ClickException("Pass at most one of --mine / --incoming / --outgoing.")
    repos = [_resolve_project_repo(project_name)] if project_name else iter_local_projects()
    direction: str | None = None
    if mine:
        direction = "mine"
    elif incoming:
        direction = "incoming"
    elif outgoing:
        direction = "outgoing"

    identity = resolve_identity(allow_unknown=True)
    console = Console()
    table = Table(title="SEAs")
    table.add_column("project")
    table.add_column("id", style="bold")
    table.add_column("from")
    table.add_column("to")
    table.add_column("kind")
    table.add_column("state")
    table.add_column("description", overflow="fold")

    found = False
    for repo in repos:
        seas = sea.iter_seas(repo)
        if direction is not None:
            seas = sea.filter_for_member(seas, identity.handle, direction=direction)
        for s in seas:
            table.add_row(
                repo.path.name,
                str(s.id),
                s.from_handle,
                s.to_handle,
                s.kind,
                s.state,
                s.description,
            )
            found = True
    if not found:
        click.echo("No SEAs match.")
        return 0
    console.print(table)
    return 0


def cmd_claim(sea_id: int, *, project_name: str | None = None) -> int:
    """``murmurent sea claim <id>``."""
    repo, s = _load(sea_id, project_name)
    try:
        sea.claim(s)
    except sea.SeaTransitionError as exc:
        raise click.ClickException(str(exc)) from exc
    sea.write_sea(repo, s)
    click.echo(f"Claimed SEA {s.id} ({s.state}).")
    return 0


def cmd_complete(sea_id: int, *, delivery: str, project_name: str | None = None) -> int:
    """``murmurent sea complete <id> --delivery <path>``."""
    repo, s = _load(sea_id, project_name)
    try:
        sea.complete(s, delivery=delivery)
    except sea.SeaTransitionError as exc:
        raise click.ClickException(str(exc)) from exc
    sea.write_sea(repo, s)
    click.echo(f"Completed SEA {s.id} (delivery: {delivery}).")
    return 0


def cmd_decline(sea_id: int, *, reason: str, project_name: str | None = None) -> int:
    """``murmurent sea decline <id> --reason <r>``."""
    repo, s = _load(sea_id, project_name)
    try:
        sea.decline(s, reason=reason)
    except sea.SeaTransitionError as exc:
        raise click.ClickException(str(exc)) from exc
    sea.write_sea(repo, s)
    click.echo(f"Declined SEA {s.id}: {reason}")
    return 0


def cmd_examine(sea_id: int, *, project_name: str | None = None) -> int:
    """``murmurent sea examine <id>`` — scaffold the deliberation document."""
    repo, s = _load(sea_id, project_name)
    if s.state not in {"complete", "examined"}:
        raise click.ClickException(
            f"SEA {s.id} is in state {s.state!r}; only 'complete' SEAs can be examined."
        )
    delib_path = deliberation.deliberation_path(repo, "sea", str(s.id))
    if not delib_path.exists():
        delib_path.parent.mkdir(parents=True, exist_ok=True)
        delib_path.write_text(
            deliberation.render_deliberation(
                scope="sea",
                target=str(s.id),
                operational_status=s.state if s.state != "examined" else "complete",
                analysis_status="examined",
                examined_at=deliberation._today(),
            ),
            encoding="utf-8",
        )
        click.echo(f"Scaffolded deliberation: {delib_path}")
    else:
        deliberation.update_status(delib_path, analysis_status="examined")
        click.echo(f"Updated deliberation status: {delib_path}")

    if s.state == "complete":
        try:
            sea.mark_examined(s)
        except sea.SeaTransitionError as exc:
            raise click.ClickException(str(exc)) from exc
        sea.write_sea(repo, s)
    click.echo(
        "Now invoke each agent in your CC session and paste its contribution into "
        "the relevant section. Run `murmurent sea conclude` when ready."
    )
    return 0


def cmd_conclude(
    sea_id: int,
    *,
    statement: str | None = None,
    project_name: str | None = None,
) -> int:
    """``murmurent sea conclude <id>`` — validate sections, mark concluded."""
    repo, s = _load(sea_id, project_name)
    delib_path = deliberation.deliberation_path(repo, "sea", str(s.id))
    if not delib_path.exists():
        raise click.ClickException(
            f"No deliberation at {delib_path}; run `murmurent sea examine {s.id}` first."
        )
    text = delib_path.read_text(encoding="utf-8")
    try:
        deliberation.assert_sections_present(text, context=str(delib_path))
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    if statement is not None:
        statement_path = repo.path / statement if not str(statement).startswith("/") else statement
        from pathlib import Path as _P

        statement_text = _P(statement).read_text(encoding="utf-8")
        text = text.replace(
            "_(filled in during conclude — claim, partial findings, explicit non-consensus, artefact reference, or next steps)_",
            statement_text.strip(),
            1,
        )
        delib_path.write_text(text, encoding="utf-8")

    deliberation.update_status(delib_path, analysis_status="concluded")
    try:
        sea.mark_concluded(s)
    except sea.SeaTransitionError as exc:
        raise click.ClickException(str(exc)) from exc
    sea.write_sea(repo, s)
    click.echo(f"Concluded SEA {s.id}; deliberation at {delib_path}.")
    click.echo("Run `murmurent push <project> --finalize` to open a PR for squad approvals.")
    return 0


def cmd_reopen(sea_id: int, *, project_name: str | None = None) -> int:
    """``murmurent sea reopen <id>`` — re-open a concluded deliberation."""
    repo, s = _load(sea_id, project_name)
    try:
        sea.reopen(s)
    except sea.SeaTransitionError as exc:
        raise click.ClickException(str(exc)) from exc
    sea.write_sea(repo, s)
    delib_path = deliberation.deliberation_path(repo, "sea", str(s.id))
    if delib_path.exists():
        deliberation.update_status(delib_path, analysis_status="examined")
    click.echo(f"Reopened SEA {s.id}.")
    return 0


def cmd_finalize(scope: str, target_id: str, *, project_name: str | None = None) -> int:
    """``murmurent finalize <scope> <id>`` — examine then conclude."""
    if scope == "sea":
        sea_id = int(target_id)
        cmd_examine(sea_id, project_name=project_name)
        cmd_conclude(sea_id, project_name=project_name)
        return 0
    if scope in {"experiment", "project"}:
        # v1 stub: only the SEA scope ships in phase 3.
        click.echo(
            f"finalize {scope} is scaffolded but the full multi-actor flow lands in phase 5."
        )
        return 0
    raise click.ClickException(f"unknown scope: {scope!r}")


def _load(sea_id: int, project_name: str | None) -> tuple[ProjectRepo, sea.Sea]:
    """Load a SEA by id, optionally constrained to ``project_name``."""
    if project_name:
        repo = _resolve_project_repo(project_name)
        path = sea.sea_path(repo, sea_id)
        if not path.is_file():
            raise click.ClickException(f"SEA {sea_id} not found in {repo.path.name}.")
        return repo, sea.parse_sea(path)
    return _resolve_sea_globally(sea_id)
