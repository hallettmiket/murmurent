"""
Purpose: Implementation of the ``murmurent choreography ...`` subcommands —
         pose a compositional choreography (a posed question + candidate-identity
         space + judging criteria), attach contributed contributions to it, validate
         the whole thing (including the candidate-key joinability check across
         all contributions), and show it.
Author: Mike Hallett (with Claude Code)
Date: 2026-07-21
Input: CLI arguments forwarded from :mod:`murmurent.cli`.
Output: ``new`` writes a choreography markdown file (or stdout with no vault +
        no ``--out``); ``offer`` re-writes the file with a contribution attached;
        ``validate`` reports problems + exit code; ``show`` prints the posed
        question, poser, candidate key, criteria, and each contribution's metric.

Boundary: authoring + validation only — no execution, no judge. See
``docs/choreography.md`` / ``docs/contributions.md``.
"""

from __future__ import annotations

from pathlib import Path

import click

from ..core import choreography as _ch
from ..core import contribution_run as _run
from ..core import contribution_spec as _ps


def _load_criteria(raw: str) -> str:
    """Resolve a ``--criteria`` value: ``@file`` reads the file, else literal."""
    if raw.startswith("@"):
        path = Path(raw[1:]).expanduser()
        if not path.is_file():
            raise click.ClickException(f"no such criteria file: {path}")
        return path.read_text(encoding="utf-8").strip()
    return raw


def cmd_new(
    *,
    question: str,
    poser: str,
    title: str,
    candidate_key: str,
    criteria: str,
    out: str | None,
) -> int:
    """Pose + validate a choreography, then write it (vault → --out → stdout)."""
    obj = _ch.pose(
        question=question,
        poser=poser,
        title=title,
        candidate_key=candidate_key,
        criteria=_load_criteria(criteria),
    )
    # A freshly-posed choreography has no contributions yet, so validation only checks
    # the poser-supplied fields (the joinability check is a no-op here).
    problems = obj.validate()
    if problems:
        for prob in problems:
            click.echo(f"  - {prob}")
        raise click.ClickException(
            f"refusing to write an invalid choreography ({len(problems)} problem(s))."
        )

    markdown = obj.to_markdown()

    if out is not None:
        dest = Path(out).expanduser()
        if dest.is_dir():
            dest = dest / _ch.default_choreography_filename(question)
    else:
        base = _ch.default_choreography_dir()
        if base is None:
            click.echo(markdown, nl=False)
            return 0
        dest = base / _ch.default_choreography_filename(question)

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(markdown, encoding="utf-8")
    click.echo(f"Posed choreography → {dest}")
    return 0


def cmd_offer(*, choreography_path: str, contribution: str) -> int:
    """Attach a contribution contribution to a choreography and re-write the file."""
    p = Path(choreography_path).expanduser()
    if not p.is_file():
        raise click.ClickException(f"no such file: {p}")
    try:
        obj = _ch.Choreography.from_file(p)
    except _ch.ChoreographyError as exc:
        raise click.ClickException(str(exc)) from exc

    added = obj.attach_contribution(contribution)
    if not added:
        click.echo(f"Contribution {contribution!r} is already attached; nothing to do.")
        return 0

    p.write_text(obj.to_markdown(), encoding="utf-8")
    click.echo(f"Attached contribution {contribution!r} → {p} ({len(obj.contributions)} total).")
    return 0


def cmd_validate(choreography_path: str) -> int:
    """Validate the whole choreography incl. the candidate-key joinability check."""
    p = Path(choreography_path).expanduser()
    if not p.is_file():
        raise click.ClickException(f"no such file: {p}")
    try:
        obj = _ch.Choreography.from_file(p)
    except _ch.ChoreographyError as exc:
        raise click.ClickException(str(exc)) from exc

    problems = obj.validate()
    if not problems:
        click.echo(
            f"OK — {p} is a valid choreography "
            f"({len(obj.contributions)} contribution(s), all joinable on "
            f"{obj.candidate_key!r})."
        )
        return 0
    click.echo(f"INVALID — {p} has {len(problems)} problem(s):")
    for prob in problems:
        click.echo(f"  - {prob}")
    raise click.ClickException("choreography failed validation.")


def cmd_show(choreography_path: str) -> int:
    """Print the posed question, poser, candidate key, criteria, and contributions."""
    p = Path(choreography_path).expanduser()
    if not p.is_file():
        raise click.ClickException(f"no such file: {p}")
    try:
        obj = _ch.Choreography.from_file(p)
    except _ch.ChoreographyError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"Question:      {obj.question}")
    click.echo(f"Title:         {obj.title}")
    click.echo(f"Poser:         {obj.poser}")
    click.echo(f"Candidate key: {obj.candidate_key}")
    click.echo("Criteria:")
    for line in (obj.criteria or "(none)").splitlines() or ["(none)"]:
        click.echo(f"  {line}")
    click.echo(f"Contributions ({len(obj.contributions)}):")
    if not obj.contributions:
        click.echo("  (none attached yet)")
        return 0

    base = p.parent
    for ref in obj.contributions:
        spec_path = _ps.resolve_spec_reference(ref, base)
        if spec_path is None:
            click.echo(f"  - {ref}: [spec unresolved]")
            continue
        try:
            spec = _ps.ContributionSpec.from_file(spec_path)
        except _ps.ContributionSpecError:
            click.echo(f"  - {ref}: [spec unparseable]")
            continue
        contract = spec.resolved_contract()
        if contract is None:
            click.echo(f"  - {spec.contribution} by {spec.author}: [contract unresolved]")
            continue
        join = "joins" if contract.candidate_key == obj.candidate_key else "DIFFERS"
        click.echo(
            f"  - {spec.contribution} by {spec.author}: "
            f"{contract.metric} [{contract.units}], {contract.direction} "
            f"(key {contract.candidate_key} — {join})"
        )
    return 0


def cmd_prepare_run(*, choreography_path: str, out: str | None) -> int:
    """Assemble a run package (choreography + contracts + outputs + judge version)."""
    try:
        dest = _run.prepare_run(choreography_path, out_dir=out)
    except _run.RunError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Prepared run package → {dest}")
    click.echo(f"  manifest: {dest / _run.MANIFEST_NAME}")
    click.echo("Hand this package to the judge agent to combine + present the contributions.")
    return 0


def cmd_freeze_run(
    *, choreography_path: str, result: str, run: str | None, out: str | None
) -> int:
    """Freeze the run (package + judge result) into an append-only run record."""
    try:
        dest = _run.freeze_run(
            choreography_path, result_path=result, run_package=run, out_dir=out
        )
    except _run.RunError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Froze run record → {dest}")
    click.echo(f"  record: {dest / _run.RECORD_MANIFEST_NAME}")
    return 0


# ---------------------------------------------------------------------------
# init: start a choreography from nothing
# ---------------------------------------------------------------------------

_MARK = {"ok": "✓", "warn": "!", "fail": "✗"}


def _csv(raw: str | None) -> list[str]:
    return [x.strip() for x in (raw or "").split(",") if x.strip()]


def cmd_init(
    *,
    name: str,
    title: str | None,
    summary: str | None,
    mode: str | None,
    approaches: str | None,
    agents: str | None,
    question: str | None,
    candidate_key: str | None,
    criteria: str | None,
    members: str | None,
    sensitivity: str,
    lab: str,
    request_project: bool,
    assume_yes: bool,
) -> int:
    """Create a choreography repository, declare it, pose its question and
    file the project request. Asks for anything missing when run in a terminal.
    """
    from ..core import choreography_init as _ci
    from ..core.identity import resolve as resolve_identity

    ask = _interactive() and not assume_yes
    identity = resolve_identity(allow_unknown=True)
    actor = identity.handle if identity.source != "unknown" else ""

    if ask:
        click.echo(f"Starting the choreography '{name}'. "
                   "Press Enter to accept a default in [brackets].\n")
    if title is None and ask:
        title = click.prompt("Title, in one line")
    if summary is None and ask:
        summary = click.prompt("Summary: what the approaches are and how they are combined")
    if mode is None:
        mode = (click.prompt("Mode", type=click.Choice(list(_ci.MODES)),
                             default="compositional") if ask else "compositional")
    if approaches is None and ask:
        approaches = click.prompt(
            "Approaches, comma-separated (blank to add later)", default="",
            show_default=False)
    if mode == "compositional" and candidate_key is None and ask:
        if click.confirm("Pose the question now? It is what contributors answer",
                         default=True):
            candidate_key = click.prompt(
                "Candidate key: what every approach reports on, so results line up "
                f"({', '.join(sorted(_ch_vocab()))}, or other:<description>)")
            if criteria is None:
                criteria = click.prompt(
                    "Criteria: how the judge should rank results (text, or @file)")
    if request_project and members is None and ask:
        members = click.prompt(
            "Project members besides you, comma-separated handles (blank for none)",
            default="", show_default=False)

    plan = _ci.ChoreographyPlan(
        name=name, title=title or "", summary=summary or "", mode=mode,
        approaches=_csv(approaches),
        agents=_csv(agents) or list(_ci.DEFAULT_AGENTS),
        lab=lab, question=question or "",
        candidate_key=candidate_key or "",
        criteria=_load_criteria(criteria) if criteria else "",
        request_project=request_project, members=_csv(members),
        sensitivity=sensitivity,
    )
    problems = plan.problems()
    if problems:
        for prob in problems:
            click.echo(f"  - {prob}")
        hint = "" if ask else " Run it in a terminal to be asked, or pass the flags."
        raise click.ClickException(f"cannot start this choreography.{hint}")

    if ask:
        _show_plan(plan, actor)
        if not click.confirm("Create it?", default=True):
            click.echo("Nothing was created.")
            return 0

    try:
        result = _ci.init_choreography(plan, actor=actor)
    except _ci.InitError as exc:
        for prob in exc.problems:
            click.echo(f"  - {prob}")
        raise click.ClickException("cannot start this choreography.") from exc

    click.echo("")
    for p in result.probes:
        click.echo(f"  {_MARK.get(p.status, '?')} {p.name}: {p.detail}")
    if not result.ok:
        raise click.ClickException("stopped at the step marked ✗; nothing after it ran.")
    click.echo(f"\nThe choreography is in {result.repo_path}.\n\nWhat is left:")
    for i, step in enumerate(result.next_steps, 1):
        click.echo(f"  {i}. {step}")
    return 0


def _interactive() -> bool:
    """True when a person is at the keyboard to answer questions."""
    import sys

    return sys.stdin.isatty()


def _ch_vocab() -> set[str]:
    from ..core import contribution_contract as _pc
    return set(_pc.CANDIDATE_KEY_VOCAB)


def _show_plan(plan, actor: str) -> None:
    from ..core import repo as _repo

    click.echo("\nThis will:")
    click.echo(f"  - create {_repo.repos_root() / plan.name} with exp, src, obsolete, "
               "data and decisions folders, tracked by git")
    click.echo("  - make it murmurent-ready and declare it a choreography "
               f"({plan.mode})")
    if plan.poses_question:
        click.echo(f"  - pose the question '{plan.question_slug}', joining on "
                   f"{plan.candidate_key}")
    click.echo("  - make the first commit")
    if plan.request_project:
        who = ", ".join(([f"@{actor}"] if actor else []) + plan.members) or "you"
        click.echo(f"  - ask your PI to make it a project, with {who}")
    click.echo("")
