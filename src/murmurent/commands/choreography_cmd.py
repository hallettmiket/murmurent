"""
Purpose: Implementation of the ``murmurent choreography ...`` subcommands —
         pose a compositional choreography (a posed question + candidate-identity
         space + judging criteria), attach contributed phrases to it, validate
         the whole thing (including the candidate-key joinability check across
         all phrases), and show it.
Author: Mike Hallett (with Claude Code)
Date: 2026-07-21
Input: CLI arguments forwarded from :mod:`murmurent.cli`.
Output: ``new`` writes a choreography markdown file (or stdout with no vault +
        no ``--out``); ``offer`` re-writes the file with a phrase attached;
        ``validate`` reports problems + exit code; ``show`` prints the posed
        question, poser, candidate key, criteria, and each phrase's metric.

Boundary: authoring + validation only — no execution, no judge. See
``docs/choreography.md`` / ``docs/phrases.md``.
"""

from __future__ import annotations

from pathlib import Path

import click

from ..core import choreography as _ch
from ..core import phrase_run as _run
from ..core import phrase_spec as _ps


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
    # A freshly-posed choreography has no phrases yet, so validation only checks
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


def cmd_offer(*, choreography_path: str, phrase: str) -> int:
    """Attach a phrase contribution to a choreography and re-write the file."""
    p = Path(choreography_path).expanduser()
    if not p.is_file():
        raise click.ClickException(f"no such file: {p}")
    try:
        obj = _ch.Choreography.from_file(p)
    except _ch.ChoreographyError as exc:
        raise click.ClickException(str(exc)) from exc

    added = obj.attach_phrase(phrase)
    if not added:
        click.echo(f"Phrase {phrase!r} is already attached; nothing to do.")
        return 0

    p.write_text(obj.to_markdown(), encoding="utf-8")
    click.echo(f"Attached phrase {phrase!r} → {p} ({len(obj.phrases)} total).")
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
            f"({len(obj.phrases)} phrase(s), all joinable on "
            f"{obj.candidate_key!r})."
        )
        return 0
    click.echo(f"INVALID — {p} has {len(problems)} problem(s):")
    for prob in problems:
        click.echo(f"  - {prob}")
    raise click.ClickException("choreography failed validation.")


def cmd_show(choreography_path: str) -> int:
    """Print the posed question, poser, candidate key, criteria, and phrases."""
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
    click.echo(f"Phrases ({len(obj.phrases)}):")
    if not obj.phrases:
        click.echo("  (none attached yet)")
        return 0

    base = p.parent
    for ref in obj.phrases:
        spec_path = _ps.resolve_spec_reference(ref, base)
        if spec_path is None:
            click.echo(f"  - {ref}: [spec unresolved]")
            continue
        try:
            spec = _ps.PhraseSpec.from_file(spec_path)
        except _ps.PhraseSpecError:
            click.echo(f"  - {ref}: [spec unparseable]")
            continue
        contract = spec.resolved_contract()
        if contract is None:
            click.echo(f"  - {spec.phrase} by {spec.author}: [contract unresolved]")
            continue
        join = "joins" if contract.candidate_key == obj.candidate_key else "DIFFERS"
        click.echo(
            f"  - {spec.phrase} by {spec.author}: "
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
    click.echo("Hand this package to the judge agent to combine + present the phrases.")
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
