"""
Purpose: ``murmurent paper`` and ``murmurent thesis``: scaffold, check and
         build queryable paper packages and the theses composed from them
         (issue #284), draft the defence talk, and write the Western (SGPS)
         submission checklist. Thin click wrappers over
         :mod:`murmurent.core.paper_package`.
Author: Mike Hallett (with Claude Code)
Date: 2026-11-06
Input: A package directory (default: the nearest paper.yaml or thesis.yaml
       above the current directory).
Output: Reports on stdout; files under ``<package>/build/``. ``check`` exits
        1 on any error (or on a warning with ``--strict``) so a script or an
        agent can stop on it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from ..core import paper_package as pp


def _locate(path: str | None, kind: str) -> Path:
    if path:
        return Path(path).resolve()
    found = pp.find_package()
    if found is None or found[1] != kind:
        manifest = pp.PAPER_MANIFEST if kind == "paper" else pp.THESIS_MANIFEST
        click.echo(f"No {manifest} here or above. Pass the package directory, or run "
                   f"`murmurent {kind} init <dir>` to start one.", err=True)
        sys.exit(2)
    return found[0]


def _report(rep: pp.CheckReport, *, strict: bool) -> None:
    click.echo(rep.format())
    if not rep.ok(strict=strict):
        sys.exit(1)


def _echo_done(done: list[str]) -> None:
    for line in done:
        click.echo(line)
    if any(line.startswith("PDF failed") for line in done):
        sys.exit(1)


# --------------------------------------------------------------------------- #
# murmurent paper
# --------------------------------------------------------------------------- #


@click.group("paper", help="A paper as a queryable package: manuscript, claims, code and data.")
def paper_group() -> None:
    pass


@paper_group.command("init", help="Scaffold a paper package in DIR (never overwrites a file).")
@click.argument("directory", type=click.Path(file_okay=False))
@click.option("--title", required=True, help="The paper's title.")
@click.option("--author", default="", help="First author, as written on the paper.")
@click.option("--lab", default=None, help="Lab name for the .murmurent.yaml marker.")
def paper_init(directory: str, title: str, author: str, lab: str | None) -> None:
    written = pp.init_paper(Path(directory), title=title, author=author, lab=lab)
    for p in written:
        click.echo(f"wrote {p}")
    click.echo(f"Next: fill in {pp.PAPER_MANIFEST}, then `murmurent paper check {directory}`.")


@paper_group.command("check", help="Check the manifest: every claim has its code, data and figure.")
@click.argument("directory", required=False, type=click.Path(exists=True, file_okay=False))
@click.option("--strict", is_flag=True, help="Treat warnings as errors.")
def paper_check(directory: str | None, strict: bool) -> None:
    _report(pp.check_paper(_locate(directory, "paper")), strict=strict)


@paper_group.command("build", help="Write build/claim_map.md (and the PDF with --pdf).")
@click.argument("directory", required=False, type=click.Path(exists=True, file_okay=False))
@click.option("--pdf", is_flag=True, help="Run latexmk on the source as well.")
def paper_build(directory: str | None, pdf: bool) -> None:
    _echo_done(pp.build_paper(_locate(directory, "paper"), pdf=pdf))


# --------------------------------------------------------------------------- #
# murmurent thesis
# --------------------------------------------------------------------------- #


@click.group("thesis", help="A thesis composed of paper packages: check, build, talk, paperwork.")
def thesis_group() -> None:
    pass


@thesis_group.command("init", help="Scaffold a thesis package in DIR (never overwrites a file).")
@click.argument("directory", type=click.Path(file_okay=False))
@click.option("--title", required=True, help="The thesis title.")
@click.option("--candidate", default="", help="The candidate's name as it will appear.")
@click.option("--lab", default=None, help="Lab name for the .murmurent.yaml marker.")
def thesis_init(directory: str, title: str, candidate: str, lab: str | None) -> None:
    written = pp.init_thesis(Path(directory), title=title, candidate=candidate, lab=lab)
    for p in written:
        click.echo(f"wrote {p}")
    click.echo(f"Next: list the chapters in {pp.THESIS_MANIFEST}, then `murmurent thesis check {directory}`.")


@thesis_group.command("adopt", help="Turn one monolithic thesis .tex into a package in DIR: preamble kept, "
                                     "front matter and chapters split, a draft claim per figure.")
@click.argument("tex", type=click.Path(exists=True, dir_okay=False))
@click.argument("directory", type=click.Path(file_okay=False))
@click.option("--title", default="", help="Override the title found in the source.")
@click.option("--candidate", default="", help="Override the author found in the source.")
@click.option("--lab", default=None, help="Lab name for the .murmurent.yaml marker.")
def thesis_adopt(tex: str, directory: str, title: str, candidate: str, lab: str | None) -> None:
    try:
        done = pp.adopt_thesis(Path(tex), Path(directory), title=title, candidate=candidate, lab=lab)
    except pp.PackageError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)
    _echo_done(done)
    click.echo(f"Next: `murmurent thesis check {directory}`; the source folder was not changed.")


@thesis_group.command("check", help="Check the thesis and every paper package in it.")
@click.argument("directory", required=False, type=click.Path(exists=True, file_okay=False))
@click.option("--strict", is_flag=True, help="Treat warnings as errors.")
def thesis_check(directory: str | None, strict: bool) -> None:
    _report(pp.check_thesis(_locate(directory, "thesis")), strict=strict)


@thesis_group.command("build", help="Assemble build/main.tex and build/claim_map.md (PDF with --pdf).")
@click.argument("directory", required=False, type=click.Path(exists=True, file_okay=False))
@click.option("--pdf", is_flag=True, help="Run latexmk on the assembled thesis as well.")
def thesis_build(directory: str | None, pdf: bool) -> None:
    _echo_done(pp.build_thesis(_locate(directory, "thesis"), pdf=pdf))


@thesis_group.command("talk", help="Draft the defence talk: one timed slide per claim.")
@click.argument("directory", required=False, type=click.Path(exists=True, file_okay=False))
@click.option("--minutes", default=20, show_default=True, type=int, help="Length of the talk.")
@click.option("--pdf", is_flag=True, help="Run latexmk on build/talk.tex as well.")
def thesis_talk(directory: str | None, minutes: int, pdf: bool) -> None:
    _echo_done(pp.build_talk(_locate(directory, "thesis"), minutes=minutes, pdf=pdf))


@thesis_group.command("paperwork", help="Write build/paperwork.md: the Western (SGPS) submission checklist.")
@click.argument("directory", required=False, type=click.Path(exists=True, file_okay=False))
def thesis_paperwork(directory: str | None) -> None:
    _echo_done(pp.build_paperwork(_locate(directory, "thesis")))
