"""
Purpose: ``wigamig common-sea`` — terminal-first CRUD for the centre's
         common-SEAs catalog.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-26

Examples:

    wigamig common-sea list
    wigamig common-sea list --kind skill --tag qc
    wigamig common-sea show qc_drift_routine

    # Submit (defaults owner_lab to your local lab).
    wigamig common-sea submit \\
      --slug qc_drift_routine --name 'QC drift watcher' \\
      --kind routine \\
      --description 'Posts Slack on MoM QC drift >2σ' \\
      --install 'wigamig routine install qc_drift_routine' \\
      --url https://github.com/hallettmiket/qc_drift_routine \\
      --tag qc --tag monitoring

    wigamig common-sea archive qc_drift_routine

The CLI does not call the HTTP dashboard; it edits ``<lab_info>``
directly via the same ``core.common_seas`` helpers the endpoints
use, so it works offline / before the dashboard is running.
"""

from __future__ import annotations

import click

from ..core import common_seas as _cs
from ..core import lab as _lab


@click.group(name="common-sea",
              help="Centre-wide common-SEAs catalog.")
def common_sea() -> None:
    pass


@common_sea.command("list")
@click.option("--kind", default="",
              help="Filter to one kind: service|skill|routine|mcp|dataset.")
@click.option("--owner-lab", default="",
              help="Filter to one lab id.")
@click.option("--tag", default="",
              help="Filter to one tag.")
@click.option("--include-deprecated", is_flag=True, default=False,
              help="Include archived/deprecated SEAs.")
def cmd_list(kind: str, owner_lab: str, tag: str,
              include_deprecated: bool) -> None:
    seas = _cs.iter_seas(
        kind=kind or None, owner_lab=owner_lab or None,
        tag=tag or None, include_deprecated=include_deprecated,
    )
    if not seas:
        click.echo("(no common SEAs registered)")
        return
    click.echo(f"{'slug':30s} {'kind':9s} {'owner':12s} {'status':10s} name")
    click.echo("-" * 80)
    for s in seas:
        click.echo(
            f"{s.slug:30s} {s.kind:9s} {s.owner_lab:12s} "
            f"{s.status:10s} {s.name}"
        )


@common_sea.command("show")
@click.argument("slug")
def cmd_show(slug: str) -> None:
    s = _cs.get_sea(slug)
    if s is None:
        raise click.ClickException(f"not found: {slug}")
    click.echo(f"slug:        {s.slug}")
    click.echo(f"name:        {s.name}")
    click.echo(f"kind:        {s.kind}")
    click.echo(f"owner_lab:   {s.owner_lab}")
    click.echo(f"status:      {s.status}")
    click.echo(f"tags:        {', '.join(s.tags) or '—'}")
    click.echo(f"description: {s.description}")
    if s.install:
        click.echo(f"install:     {s.install}")
    if s.url:
        click.echo(f"url:         {s.url}")
    click.echo(f"created:     {s.created}")
    click.echo(f"path:        {s.path}")
    if s.notes:
        click.echo("\n" + s.notes)


@common_sea.command("submit")
@click.option("--slug", required=True)
@click.option("--name", required=True)
@click.option("--kind", required=True,
              type=click.Choice(list(_cs.VALID_KINDS)))
@click.option("--owner-lab", default="",
              help="Defaults to local lab.md's lab id.")
@click.option("--description", default="")
@click.option("--install", default="",
              help="Copy-paste install command.")
@click.option("--url", default="")
@click.option("--tag", "tags", multiple=True,
              help="Repeatable; one tag per flag.")
@click.option("--notes", default="",
              help="Long-form markdown body.")
def cmd_submit(slug: str, name: str, kind: str, owner_lab: str,
                description: str, install: str, url: str,
                tags: tuple[str, ...], notes: str) -> None:
    if not owner_lab:
        try:
            owner_lab = _lab.load_lab_config().lab
        except Exception as exc:
            raise click.ClickException(
                f"--owner-lab not provided and lab.md couldn't be read: {exc}"
            ) from exc
    try:
        p = _cs.create_sea(
            slug=slug, name=name, kind=kind, owner_lab=owner_lab,
            description=description, install=install, url=url,
            tags=list(tags), notes=notes,
        )
    except _cs.CommonSeaError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Submitted {slug} ({kind}, lab {owner_lab}): {p}")


@common_sea.command("archive")
@click.argument("slug")
def cmd_archive(slug: str) -> None:
    try:
        _cs.archive_sea(slug=slug)
    except _cs.CommonSeaError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Archived {slug} → status=deprecated.")
