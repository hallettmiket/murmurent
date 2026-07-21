"""
Purpose: Implementation of the ``murmurent phrase contract ...`` subcommands —
         author and validate a phrase output-contract (the typed data contract
         that lets heterogeneous phrase outputs be aligned + judged).
Author: Mike Hallett (with Claude Code)
Date: 2026-07-21
Input: CLI arguments forwarded from :mod:`murmurent.cli`.
Output: ``contract new`` writes a schema-valid contract markdown file (or prints
        it to stdout when no vault + no ``--out``); ``contract validate`` parses
        a file and reports problems, exiting non-zero when it is invalid.
"""

from __future__ import annotations

from pathlib import Path

import click

from ..core import phrase_contract as _pc


def cmd_contract_new(
    *,
    phrase: str,
    author: str,
    question: str,
    candidate_key: str,
    metric: str,
    units: str,
    direction: str,
    uncertainty: str,
    out: str | None,
) -> int:
    """Build + validate a contract, then write it (vault → --out → stdout)."""
    contract = _pc.PhraseContract(
        phrase=phrase,
        author=author,
        question=question,
        candidate_key=candidate_key,
        metric=metric,
        units=units,
        direction=direction,
        uncertainty=uncertainty,
    )
    problems = contract.validate()
    if problems:
        for p in problems:
            click.echo(f"  - {p}")
        raise click.ClickException(
            f"refusing to write an invalid contract ({len(problems)} problem(s))."
        )

    markdown = contract.to_markdown()

    # Resolve the destination: explicit --out wins; else the vault phrases/
    # dir; else print to stdout so the command is still useful without a vault.
    if out is not None:
        dest = Path(out).expanduser()
        if dest.is_dir():
            dest = dest / _pc.default_contract_filename(phrase)
    else:
        base = _pc.default_contract_dir()
        if base is None:
            click.echo(markdown, nl=False)
            return 0
        dest = base / _pc.default_contract_filename(phrase)

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(markdown, encoding="utf-8")
    click.echo(f"Wrote phrase contract → {dest}")
    return 0


def cmd_contract_validate(path: str) -> int:
    """Parse + validate a contract file. Exit 0 if valid, non-zero if not."""
    p = Path(path).expanduser()
    if not p.is_file():
        raise click.ClickException(f"no such file: {p}")
    try:
        contract = _pc.PhraseContract.from_file(p)
    except _pc.PhraseContractError as exc:
        raise click.ClickException(str(exc)) from exc

    problems = contract.validate()
    if not problems:
        click.echo(f"OK — {p} is a valid phrase contract.")
        return 0
    click.echo(f"INVALID — {p} has {len(problems)} problem(s):")
    for prob in problems:
        click.echo(f"  - {prob}")
    raise click.ClickException("contract failed validation.")
