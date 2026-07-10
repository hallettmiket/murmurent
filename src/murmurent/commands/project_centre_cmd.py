"""
Purpose: ``murmurent project`` — centre_cable_guy's CLI front door for
         project declarations + reconcile.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-26

Distinct from any per-lab project tools — these commands edit the
centre's ``<lab_info>/projects/`` tree (the desired-state declarations
the reconcile loop reads).

Examples:

    # Declare or update a project.
    murmurent project declare --name dcis_imaging --primary-lab hallett \\
      --member @allie --member @didi --member @cara \\
      --machine biodatsci \\
      --github-org hallettmiket --github-repo dcis_imaging

    # List declared projects.
    murmurent project list

    # Show one project.
    murmurent project show dcis_imaging

    # Reconcile (dry-run by default).
    murmurent project reconcile dcis_imaging
    murmurent project reconcile dcis_imaging --apply

    # Append an audit-log entry by hand.
    murmurent project log dcis_imaging --action "manual fs ACL fix" \\
      --detail "added @newpostdoc to wgm_dcis_imaging on biodatsci"
"""

from __future__ import annotations

import click

from ..core import centre_provision as _cp


@click.group(name="centre-project",
              help="Centre project declarations + reconcile (centre_cable_guy front door).")
def centre_project() -> None:
    pass


# Back-compat alias for the click decorator group below — the actual
# group object is ``centre_project``; old usages still see ``project``.
project = centre_project


@project.command("declare")
@click.option("--name", required=True)
@click.option("--primary-lab", required=True,
              help="Lab id whose workspace owns the Slack channel.")
@click.option("--member", "members", multiple=True,
              help="Repeatable; @handle per flag.")
@click.option("--machine", "machines", multiple=True,
              help="Repeatable; lab server id per flag.")
@click.option("--github-org", default="")
@click.option("--github-repo", default="",
              help="Defaults to <name>.")
@click.option("--description", default="")
def cmd_declare(name: str, primary_lab: str,
                 members: tuple[str, ...], machines: tuple[str, ...],
                 github_org: str, github_repo: str,
                 description: str) -> None:
    try:
        p = _cp.upsert_project(
            name=name, primary_lab=primary_lab,
            members=list(members), machines=list(machines),
            github_org=github_org, github_repo=github_repo,
            description=description,
        )
    except _cp.CentreProvisionError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Declared {name}: {p}")


@project.command("list")
def cmd_list() -> None:
    rows = _cp.iter_projects()
    if not rows:
        click.echo("(no projects declared)")
        return
    click.echo(f"{'name':30s} {'primary_lab':14s} {'members':8s} {'machines'}")
    click.echo("-" * 80)
    for r in rows:
        click.echo(
            f"{r.name:30s} {r.primary_lab:14s} "
            f"{len(r.members):>8d}  {','.join(r.machines) or '—'}"
        )


@project.command("show")
@click.argument("name")
def cmd_show(name: str) -> None:
    r = _cp.get_project(name)
    if r is None:
        raise click.ClickException(f"not found: {name}")
    click.echo(f"name:        {r.name}")
    click.echo(f"primary_lab: {r.primary_lab}")
    click.echo(f"members:     {', '.join('@'+m for m in r.members) or '—'}")
    click.echo(f"machines:    {', '.join(r.machines) or '—'}")
    click.echo(f"github:      {r.github_org}/{r.github_repo}")
    click.echo(f"slack:       {r.slack_channel_id or '—'}")
    click.echo(f"created:     {r.created}")
    click.echo(f"path:        {r.path}")


@project.command("reconcile",
                  help="Diff desired state vs actual; --apply runs the deltas.")
@click.argument("name")
@click.option("--apply", is_flag=True, default=False,
              help="Without this flag: dry-run printout only.")
def cmd_reconcile(name: str, apply: bool) -> None:
    """v1 reconcile is pure-Python diff against passed-in actual state.

    For a real-world reconcile we'd shell out to Slack/GitHub/ssh here
    to gather actuals. v1 keeps that gathering on the operator side
    (or in the dashboard) and exposes the pure-diff via the API.
    The CLI just prints the project's declared state + reminds the
    operator how to invoke the actual-state-gathering reconcile.
    """
    r = _cp.get_project(name)
    if r is None:
        raise click.ClickException(f"not found: {name}")
    click.echo(f"Project {name}:")
    click.echo(f"  primary_lab: {r.primary_lab}")
    click.echo(f"  members:     {', '.join('@'+m for m in r.members) or '—'}")
    click.echo(f"  machines:    {', '.join(r.machines) or '—'}")
    click.echo()
    if not apply:
        click.echo("(dry-run) Reconcile needs Slack/GitHub/FS actuals.")
        click.echo("From the dashboard: POST /api/projects/<name>/reconcile")
        click.echo("Or manually: gather actuals + call "
                   "core.centre_provision.reconcile_project(…).")
    else:
        click.echo("Apply mode: not yet wired in the CLI (use the dashboard).")


@project.command("log")
@click.argument("name")
@click.option("--actor", default="",
              help="Defaults to $WIGAMIG_USER.")
@click.option("--action", required=True)
@click.option("--detail", default="")
def cmd_log(name: str, actor: str, action: str, detail: str) -> None:
    import os
    if not actor:
        actor = os.environ.get("WIGAMIG_USER", "")
    if not actor:
        raise click.ClickException("--actor not set and $WIGAMIG_USER is empty")
    p = _cp.append_log(project=name, actor=actor, action=action, detail=detail)
    click.echo(f"Logged to {p}")
