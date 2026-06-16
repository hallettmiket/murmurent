"""
Purpose: ``wigamig centre-init`` / ``wigamig centre-status`` — the
         mayor's front door for first-time centre setup.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-26

Examples:

    # Interactive (laptop). Prompts for every field.
    wigamig centre-init

    # Scripted (server / CI).
    wigamig centre-init --no-prompt \\
      --name "Western Bioconvergence Centre" \\
      --institution "Western University" \\
      --slack-workspace T0WESTERN \\
      --github-org centre-westernu \\
      --data-server biodatsci.uwo.ca \\
      --raw-root /data/lab_vm/raw \\
      --refined-root /data/lab_vm/refined

    # After bootstrap.
    wigamig centre-status

``centre-init`` resolves the founding mayor from ``$WIGAMIG_USER``
falling back to the OS user (``getpass.getuser()``) if unset. Pass
``--mayor @handle`` to override.
"""

from __future__ import annotations

import getpass
import os

import click

from ..core import centre_init as _ci


def _default_mayor() -> str:
    """Best-effort handle resolution for the bootstrap user."""
    raw = os.environ.get("WIGAMIG_USER") or ""
    raw = raw.strip()
    if not raw:
        try:
            raw = getpass.getuser()
        except Exception:
            raw = ""
    return raw.lstrip("@").lower()


@click.command(
    "centre-init",
    help="Bootstrap a brand-new wigamig centre. Idempotent; refuses if a centre already exists.",
)
@click.option("--name", default="",
              help="Display name of the centre.")
@click.option("--institution", default="",
              help="Hosting institution (e.g. 'Western University').")
@click.option("--mayor", default="",
              help="@handle of the bootstrapping user. "
                   "Defaults to $WIGAMIG_USER then the OS user.")
@click.option("--slack-workspace", default="",
              help="Slack team/workspace id (e.g. T0WESTERN). Optional.")
@click.option("--github-org", default="",
              help="Canonical centre github org. Optional.")
@click.option("--data-server", default="",
              help="Primary lab server hostname. Optional.")
@click.option("--raw-root", default="",
              help="Path to centre raw/ root on the data server. Optional.")
@click.option("--refined-root", default="",
              help="Path to centre refined/ root on the data server. Optional.")
@click.option("--no-prompt", is_flag=True, default=False,
              help="Skip all interactive prompts (for scripted / server use).")
@click.option("--no-sentinel", is_flag=True, default=False,
              help="Do not write the per-machine registrar sentinel "
                   "(useful when running under sudo or in CI).")
def centre_init(
    name: str, institution: str, mayor: str,
    slack_workspace: str, github_org: str,
    data_server: str, raw_root: str, refined_root: str,
    no_prompt: bool, no_sentinel: bool,
) -> None:
    """Run the mayor wizard / scripted bootstrap."""

    def _prompt(label: str, current: str, default: str = "",
                 required: bool = False) -> str:
        if current:
            return current
        if no_prompt:
            if required and not default:
                raise click.ClickException(
                    f"--{label.replace(' ', '-')} required in --no-prompt mode"
                )
            return default
        return click.prompt(label, default=default or "",
                             show_default=bool(default))

    mayor = mayor or _default_mayor()
    if not mayor and not no_prompt:
        mayor = click.prompt("Founding mayor @handle",
                              default=getpass.getuser())
    if not mayor:
        raise click.ClickException(
            "could not resolve founding mayor (set $WIGAMIG_USER or pass --mayor)"
        )

    name = _prompt("Centre name", name, required=True)
    institution = _prompt("Institution", institution, required=True)
    slack_workspace = _prompt("Slack workspace id", slack_workspace)
    github_org = _prompt("Centre GitHub org", github_org)
    data_server = _prompt("Primary lab server hostname", data_server)
    raw_root = _prompt("Centre raw/ root path", raw_root,
                        default="/data/lab_vm/raw")
    refined_root = _prompt("Centre refined/ root path", refined_root,
                            default="/data/lab_vm/refined")

    # Default to writing the per-machine sentinel — for the mayor on
    # their laptop that's the right behavior (so future `git -C
    # lab_info commit` runs use their identity). On servers and in
    # tests, callers pass --no-sentinel.
    write_sent = not no_sentinel
    try:
        profile = _ci.init_centre(
            name=name, institution=institution,
            founding_mayor=mayor,
            slack_workspace=slack_workspace,
            github_org=github_org,
            data_server=data_server,
            raw_root=raw_root, refined_root=refined_root,
            write_sentinel=write_sent,
        )
    except _ci.CentreAlreadyInitialised as exc:
        # Exit 9 is non-standard but easy to remember; 0/1/2 are taken.
        click.echo(str(exc), err=True)
        raise click.exceptions.Exit(9)
    except _ci.CentreInitError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo("Centre initialised ✓")
    click.echo(f"  name:         {profile.name}")
    click.echo(f"  institution:  {profile.institution}")
    click.echo(f"  mayor:        @{profile.founding_mayor}")
    if profile.slack_workspace:
        click.echo(f"  slack:        {profile.slack_workspace}")
    if profile.github_org:
        click.echo(f"  github:       {profile.github_org}")
    if profile.data_server:
        click.echo(f"  data_server:  {profile.data_server}")
    click.echo(f"  centre.md:    {profile.path}")
    click.echo()
    click.echo("Next: open the registrar dashboard at "
                "http://localhost:8771/registrar and approve incoming "
                "lab/core join requests.")


@click.group(name="join-request",
              help="Submit / list / approve / decline lab/core/admin/pi join requests.")
def join_request_group() -> None:
    pass


@join_request_group.command("submit")
@click.option("--kind", required=True,
              type=click.Choice(["lab", "core", "admin", "pi"]))
@click.option("--name", "proposed_name", required=True,
              help="Proposed lab/core slug.")
@click.option("--pi", "proposed_pi", default="",
              help="@handle of the proposed PI. Required for lab/core.")
@click.option("--email", "email", required=True,
              help="Requester's email (so the registrar can reach back).")
@click.option("--institution", "institution",
              default="", help="Institution affiliation.")
@click.option("--justification", default="")
@click.option("--member", "members", multiple=True,
              help="Repeatable. @handles of proposed members.")
def cmd_submit(kind: str, proposed_name: str, proposed_pi: str,
                email: str, institution: str, justification: str,
                members: tuple[str, ...]) -> None:
    from ..core import join_requests as _jr
    try:
        req = _jr.file_request(
            kind=kind, requester_email=email,
            proposed_name=proposed_name, proposed_pi=proposed_pi,
            institution_affiliation=institution,
            justification=justification,
            proposed_members=list(members),
        )
    except _jr.JoinRequestError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Filed join request #{req.id:04d} ({kind} {proposed_name}).")
    click.echo(f"Path: {req.path}")


@join_request_group.command("list")
@click.option("--state", default="",
              help="Filter by state: pending|approved|declined|provisioned|failed")
def cmd_list(state: str) -> None:
    from ..core import join_requests as _jr
    rows = _jr.iter_requests(state=state or None)
    if not rows:
        click.echo("(no join requests)")
        return
    click.echo(f"{'id':>4s}  {'kind':6s} {'state':12s} {'name':22s} {'pi':12s} email")
    click.echo("-" * 90)
    for r in rows:
        click.echo(
            f"{r.id:04d}  {r.kind:6s} {r.state:12s} {r.proposed_name:22s} "
            f"{r.proposed_pi:12s} {r.requester_email}"
        )


@join_request_group.command("show")
@click.argument("req_id", type=int)
def cmd_show(req_id: int) -> None:
    from ..core import join_requests as _jr
    try:
        r = _jr.get_request(req_id)
    except _jr.JoinRequestNotFound as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"id:                     {r.id:04d}")
    click.echo(f"kind:                   {r.kind}")
    click.echo(f"state:                  {r.state}")
    click.echo(f"requester_email:        {r.requester_email}")
    click.echo(f"proposed_name:          {r.proposed_name}")
    click.echo(f"proposed_pi:            {r.proposed_pi}")
    click.echo(f"institution_affiliation: {r.institution_affiliation}")
    click.echo(f"created_at:             {r.created_at}")
    if r.resolved_at:
        click.echo(f"resolved_at:            {r.resolved_at}")
        click.echo(f"resolved_by:            @{r.resolved_by}")
    if r.decline_reason:
        click.echo(f"decline_reason:         {r.decline_reason}")
    if r.justification:
        click.echo("\nJustification:")
        click.echo(r.justification)
    if r.probes:
        click.echo("\nProbes:")
        for p in r.probes:
            click.echo(f"  [{p.get('severity'):5s}] {p.get('kind')}: {p.get('summary')}")


@join_request_group.command("approve")
@click.argument("req_id", type=int)
@click.option("--actor", default="",
              help="Registrar handle. Defaults to $WIGAMIG_USER.")
@click.option("--no-provision", is_flag=True, default=False,
              help="Approve the record only; skip the Slack/GitHub/FS provisioning step.")
def cmd_approve(req_id: int, actor: str, no_provision: bool) -> None:
    from ..core import join_requests as _jr
    if not actor:
        actor = os.environ.get("WIGAMIG_USER", "")
    if not actor:
        raise click.ClickException("--actor required (or set $WIGAMIG_USER)")
    try:
        r = _jr.approve(req_id=req_id, actor=actor,
                          provision=not no_provision)
    except _jr.JoinRequestError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Request #{r.id:04d} → {r.state} (by @{actor})")
    for p in r.probes:
        click.echo(f"  [{p.get('severity'):5s}] {p.get('kind')}: {p.get('summary')}")


@join_request_group.command("decline")
@click.argument("req_id", type=int)
@click.option("--actor", default="")
@click.option("--reason", required=True)
def cmd_decline(req_id: int, actor: str, reason: str) -> None:
    from ..core import join_requests as _jr
    if not actor:
        actor = os.environ.get("WIGAMIG_USER", "")
    if not actor:
        raise click.ClickException("--actor required (or set $WIGAMIG_USER)")
    try:
        r = _jr.decline(req_id=req_id, actor=actor, reason=reason)
    except _jr.JoinRequestError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Request #{r.id:04d} → declined (by @{actor}). Reason: {r.decline_reason}")


@click.command("centre-status",
                help="Print the centre profile + counts of labs/cores/joins.")
def centre_status() -> None:
    profile = _ci.read_centre()
    if profile is None:
        click.echo("(no centre initialised — run `wigamig centre-init`)")
        raise click.exceptions.Exit(2)
    from ..core import registrar as _R
    reg = _R.read_registry()
    click.echo(f"Centre:           {profile.name}")
    click.echo(f"Institution:      {profile.institution}")
    click.echo(f"Founding mayor:   @{profile.founding_mayor}")
    click.echo(f"Created:          {profile.created}")
    if profile.slack_workspace:
        click.echo(f"Slack workspace:  {profile.slack_workspace}")
    if profile.github_org:
        click.echo(f"GitHub org:       {profile.github_org}")
    if profile.data_server:
        click.echo(f"Data server:      {profile.data_server}")
    click.echo()
    click.echo(f"Registrars:       {len(reg.registrars)}  "
                f"({', '.join('@'+h for h in reg.registrars)})")
    click.echo(f"Labs:             {len(reg.labs)}")
    click.echo(f"Cores:            {len(reg.cores)}")
    click.echo(f"Collaborations:   {len(reg.collaborations)}")
