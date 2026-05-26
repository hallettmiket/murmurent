"""
Purpose: ``wigamig common-tool`` — terminal-first CRUD for the centre's
         common-tools catalog.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-23

Examples:

    wigamig common-tool list
    wigamig common-tool list --kind skill --tag qc
    wigamig common-tool show qc_drift_routine

    # Submit (defaults owner_lab to your local lab).
    wigamig common-tool submit \\
      --slug qc_drift_routine --name 'QC drift watcher' \\
      --kind routine \\
      --description 'Posts Slack on MoM QC drift >2σ' \\
      --install 'wigamig routine install qc_drift_routine' \\
      --url https://github.com/hallettmiket/qc_drift_routine \\
      --tag qc --tag monitoring

    wigamig common-tool archive qc_drift_routine

The CLI does not call the HTTP dashboard; it edits ``<lab_info>``
directly via the same ``core.common_tools`` helpers the endpoints
use, so it works offline / before the dashboard is running.
"""

from __future__ import annotations

import click

from ..core import common_tools as _ct
from ..core import lab as _lab


@click.group(name="common-tool",
              help="Centre-wide common-tools catalog (SEAs / skills / routines).")
def common_tool() -> None:
    pass


@common_tool.command("list")
@click.option("--kind", default="",
              help="Filter to one kind: sea|skill|routine|mcp|dataset.")
@click.option("--owner-lab", default="",
              help="Filter to one lab id.")
@click.option("--tag", default="",
              help="Filter to one tag.")
@click.option("--include-deprecated", is_flag=True, default=False,
              help="Include archived/deprecated tools.")
def cmd_list(kind: str, owner_lab: str, tag: str,
              include_deprecated: bool) -> None:
    tools = _ct.iter_tools(
        kind=kind or None, owner_lab=owner_lab or None,
        tag=tag or None, include_deprecated=include_deprecated,
    )
    if not tools:
        click.echo("(no common tools registered)")
        return
    click.echo(f"{'slug':30s} {'kind':9s} {'owner':12s} {'status':10s} name")
    click.echo("-" * 80)
    for t in tools:
        click.echo(
            f"{t.slug:30s} {t.kind:9s} {t.owner_lab:12s} "
            f"{t.status:10s} {t.name}"
        )


@common_tool.command("show")
@click.argument("slug")
def cmd_show(slug: str) -> None:
    t = _ct.get_tool(slug)
    if t is None:
        raise click.ClickException(f"not found: {slug}")
    click.echo(f"slug:        {t.slug}")
    click.echo(f"name:        {t.name}")
    click.echo(f"kind:        {t.kind}")
    click.echo(f"owner_lab:   {t.owner_lab}")
    click.echo(f"status:      {t.status}")
    click.echo(f"tags:        {', '.join(t.tags) or '—'}")
    click.echo(f"description: {t.description}")
    if t.install:
        click.echo(f"install:     {t.install}")
    if t.url:
        click.echo(f"url:         {t.url}")
    click.echo(f"created:     {t.created}")
    click.echo(f"path:        {t.path}")
    if t.notes:
        click.echo("\n" + t.notes)


@common_tool.command("submit")
@click.option("--slug", required=True)
@click.option("--name", required=True)
@click.option("--kind", required=True,
              type=click.Choice(list(_ct.VALID_KINDS)))
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
        p = _ct.create_tool(
            slug=slug, name=name, kind=kind, owner_lab=owner_lab,
            description=description, install=install, url=url,
            tags=list(tags), notes=notes,
        )
    except _ct.CommonToolError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Submitted {slug} ({kind}, lab {owner_lab}): {p}")


@common_tool.command("archive")
@click.argument("slug")
def cmd_archive(slug: str) -> None:
    try:
        _ct.archive_tool(slug=slug)
    except _ct.CommonToolError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Archived {slug} → status=deprecated.")
