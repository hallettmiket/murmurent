"""
Purpose: obtain a choreography from a git URL (or the public index) and make it
         murmurent-ready; list what is available.
Author: Mike Hallett (with Claude Code)
Date: 2026-09-02
Input: a git URL or an index name; the public choreography index
Output: a cloned, adopted repo; a rendered listing

Issue #136. ``install`` is deliberately thin: clone, then hand the clone to the
existing ``core.adopt.adopt_clone`` path rather than re-implementing readiness.

Everything shown to the user comes from the choreography's own
``.murmurent.yaml``, never from the index, so a description cannot drift away
from the repo it describes.

The index is now published, so ``install`` also accepts a bare name and looks
the location up. A git URL still works and still needs no index: the index is a
convenience for finding a published choreography, never a gatekeeper standing
between someone and a repository they can already name.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import click

from ..core import adopt as _adopt
from ..core.choreography_registry import (
    ChoreographyError,
    ChoreographyInfo,
    clone_choreography,
    missing_agents,
    read_marker,
)

#: Where the public index lives. URLs only; see choreography_registry's header.
INDEX_URL = (
    "https://raw.githubusercontent.com/hallettmiket/murmurent_public/main/"
    "choreographies.tsv"
)


#: Appended to every index failure: the index is a convenience, and the route
#: that does not need it is always available.
_URL_ROUTE = (
    "\nYou can install from a repository URL instead, which needs no index:\n"
    "  murmurent choreography install https://github.com/<owner>/<repo>.git"
)


class IndexUnavailable(RuntimeError):
    """The index could not be read. The message is meant for a person."""


def _fetch_index(index_url: str, timeout: float) -> list[tuple[str, str]]:
    """Return the index's ``(name, url)`` rows.

    Locations only, by design: see this module's header. A row with no URL is
    dropped rather than reported, so a half-filled row cannot be installed.
    """
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(index_url, timeout=timeout) as fh:  # noqa: S310
            text = fh.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise IndexUnavailable(
                f"there is no choreography index at\n  {index_url}{_URL_ROUTE}"
            ) from exc
        raise IndexUnavailable(f"could not read the index ({exc}).{_URL_ROUTE}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        # Offline, or the hub is down. Either way the URL route still works and
        # needs nothing from the network but the repository itself, so say so
        # rather than leaving someone stuck behind a directory they do not need.
        raise IndexUnavailable(f"could not reach the index ({exc}).{_URL_ROUTE}") from exc

    rows: list[tuple[str, str]] = []
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split("\t")
        name = parts[0].strip()
        url = parts[1].strip() if len(parts) > 1 else ""
        if name and url:
            rows.append((name, url))
    return rows


def _resolve_name(name: str, *, index_url: str, timeout: float) -> str:
    """Turn a published choreography's name into its git URL.

    A name that is not in the index is refused with the names that are, rather
    than guessed at: installing the wrong repository because its name was close
    is worse than being told to look at the list.
    """
    rows = _fetch_index(index_url, timeout)
    for known, url in rows:
        if known == name:
            return url
    if not rows:
        raise IndexUnavailable(
            f"the index at {index_url} lists no choreographies, so '{name}' "
            f"cannot be resolved.{_URL_ROUTE}"
        )
    names = " ".join(n for n, _ in rows)
    raise IndexUnavailable(
        f"'{name}' is not in the public index. Published: {names}\n"
        "Or pass the repository URL directly."
    )


def _render(info: ChoreographyInfo, *, indent: str = "  ") -> None:
    click.echo(f"{indent}{info.name}  {info.title}".rstrip())
    if info.summary:
        click.echo(f"{indent}  {info.summary}")
    if info.target:
        click.echo(f"{indent}  target: {info.target}")
    if info.approaches:
        click.echo(f"{indent}  approaches: {' '.join(info.approaches)}")
    if info.agents:
        click.echo(f"{indent}  agents: {' '.join(info.agents)}")
    needs = []
    if info.requires_murmurent:
        needs.append(f"murmurent {info.requires_murmurent}")
    if info.requires_gpu:
        needs.append("a GPU")
    if needs:
        click.echo(f"{indent}  needs: {', '.join(needs)}")
    if info.data_scale or info.data_subdir:
        where = info.data_subdir or "the centre's governed data root"
        scale = f"{info.data_scale}, " if info.data_scale else ""
        click.echo(f"{indent}  data: not included ({scale}kept under {where})")
    if info.citation:
        click.echo(f"{indent}  cite: {info.citation}")


def cmd_install(*, source: str, dest: str | None, branch: str,
                lab: str, adopt: bool, index_url: str = INDEX_URL,
                timeout: float = 10.0) -> int:
    """Clone a choreography and make it murmurent-ready.

    ``source`` is either a git URL or the name of a published choreography,
    which is looked up in the public index.
    """
    if "/" not in source and ":" not in source:
        try:
            url = _resolve_name(source, index_url=index_url, timeout=timeout)
        except IndexUnavailable as exc:
            click.echo(f"x {exc}", err=True)
            return 2
        click.echo(f"+ {source} -> {url} (from the public index)")
        source = url

    try:
        clone = clone_choreography(source, dest=Path(dest) if dest else None,
                                  branch=branch)
    except ChoreographyError as exc:
        click.echo(f"x {exc}", err=True)
        return 1

    click.echo(f"+ cloned to {clone}")

    try:
        info = read_marker(clone)
    except ChoreographyError as exc:
        # Leave the clone in place: it is a perfectly good repo, it simply does
        # not declare itself a choreography. Deleting someone's fresh clone to
        # punish a missing metadata file would be worse than the problem.
        click.echo(f"\n! {exc}", err=True)
        click.echo(f"\nThe clone is at {clone} and has been left alone.", err=True)
        return 1

    click.echo()
    _render(info, indent="")
    click.echo()

    absent = missing_agents(info)
    if absent:
        click.echo(
            f"! this choreography asks for agents this machine does not have: "
            f"{' '.join(absent)}"
        )

    if not adopt:
        click.echo(f"Skipped adoption (--no-adopt). Run:\n  murmurent repo adopt {clone}")
        return 0

    try:
        outcome = _adopt.adopt_clone(clone_path=str(clone), lab=lab,
                                     agents=info.agents or None)
    except _adopt.AdoptError as exc:
        click.echo(f"\n! cloned, but adoption failed: {exc}", err=True)
        click.echo(f"  Fix the cause and run: murmurent repo adopt {clone}", err=True)
        return 1

    click.echo(f"+ murmurent-ready ({getattr(outcome, 'summary', 'adopted')})")
    click.echo(
        f"\nNext: read {clone.name}/README.md, then its decisions/ if it has one.\n"
        "Data is not included; a choreography repo carries code, decisions and "
        "documentation only."
    )
    return 0


def cmd_list(*, index_url: str = INDEX_URL, timeout: float = 10.0) -> int:
    """List choreographies from the public index.

    Names and locations only. The description of each one is read from its own
    repository at install time, so nothing printed here can contradict it.
    """
    try:
        rows = _fetch_index(index_url, timeout)
    except IndexUnavailable as exc:
        click.echo(f"x {exc}", err=True)
        return 1

    if not rows:
        click.echo("The index is empty.")
        return 0

    click.echo(f"{len(rows)} choreograph{'y' if len(rows) == 1 else 'ies'}:\n")
    for name, url in rows:
        click.echo(f"  {name}\n    {url}")
    click.echo(
        "\nDescriptions come from each repository's own .murmurent.yaml, read "
        "when you install.\nInstall one with:  murmurent choreography install "
        f"{rows[0][0]}"
    )
    return 0
