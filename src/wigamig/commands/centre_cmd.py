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
      --data-server lab-server.example.edu \\
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
@click.option("--unique-name", default="",
              help="Non-institution-specific install id (drives repo/Slack/"
                   "group names, e.g. 'western'). Optional.")
@click.option("--slack-workspace", default="",
              help="Slack team/workspace id (e.g. T0WESTERN). Optional.")
@click.option("--github-org", default="",
              help="Canonical centre github org / dedicated account. Optional.")
@click.option("--public-hub", default="",
              help="Global wigamig_public onboarding hub + this centre's label. "
                   "Optional.")
@click.option("--server-host", default="",
              help="The 'wigamig server' hostname/IP (always-online, ssh-gated). "
                   "Optional.")
@click.option("--server-account", default="",
              help="SSH login account on the wigamig server. Optional.")
@click.option("--cc-install-path", default="",
              help="Where Claude Code is installed on the server. Optional.")
@click.option("--obsidian-vault", default="",
              help="Centre-level Obsidian/markdown pool path. Optional.")
@click.option("--mayor-root", default="",
              help="High-level mayor dir (e.g. /mayor/wigamig; mirrorable). "
                   "Optional.")
@click.option("--data-server", default="",
              help="Legacy alias of --server-host. Optional.")
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
    unique_name: str, slack_workspace: str, github_org: str, public_hub: str,
    server_host: str, server_account: str, cc_install_path: str,
    obsidian_vault: str, mayor_root: str,
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
    unique_name = _prompt("Unique install name (repo/Slack id)", unique_name)
    slack_workspace = _prompt("Slack workspace id", slack_workspace)
    github_org = _prompt("Centre GitHub org / account", github_org)
    public_hub = _prompt("Public onboarding hub", public_hub)
    server_host = _prompt("Wigamig server host/IP", server_host)
    server_account = _prompt("Server SSH account", server_account)
    cc_install_path = _prompt("Claude Code install path on server",
                              cc_install_path)
    obsidian_vault = _prompt("Centre Obsidian vault path", obsidian_vault)
    mayor_root = _prompt("Mayor root dir", mayor_root)
    data_server = _prompt("Data server hostname (legacy alias)", data_server)
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
            unique_name=unique_name,
            slack_workspace=slack_workspace,
            github_org=github_org,
            public_hub=public_hub,
            server_host=server_host,
            server_account=server_account,
            cc_install_path=cc_install_path,
            obsidian_vault=obsidian_vault,
            mayor_root=mayor_root,
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
    if profile.unique_name:
        click.echo(f"  install id:   {profile.unique_name}")
    click.echo(f"  mayor:        @{profile.founding_mayor}")
    if profile.slack_workspace:
        click.echo(f"  slack:        {profile.slack_workspace}")
    if profile.github_org:
        click.echo(f"  github:       {profile.github_org}")
    if profile.server:
        click.echo(f"  server:       {profile.server}"
                   + (f" ({profile.server_account})" if profile.server_account else ""))
    if profile.mayor_root:
        click.echo(f"  mayor_root:   {profile.mayor_root}")
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


@join_request_group.command("ingest")
def cmd_ingest() -> None:
    """Poll the wigamig_public hub once and file new join requests.

    Reads the hub repo from `public_hub` in centre.md, ingests open
    `join-request` issues addressed to this centre, comments on each with
    the routed request id, and skips anything already ingested. Safe to
    run repeatedly (schedule it from a routine/cron)."""
    from ..core import join_ingest as _ji
    try:
        created = _ji.ingest()
    except _ji.JoinIngestError as exc:
        raise click.ClickException(str(exc)) from exc
    if not created:
        click.echo("No new hub requests to ingest.")
        return
    click.echo(f"Ingested {len(created)} request(s) from the hub:")
    for r in created:
        click.echo(f"  #{r.id:04d}  {r.kind:5s} {r.proposed_name:20s} "
                   f"← {r.source_issue}")


@click.command(
    "centre-slack-smoke",
    help="Verify the Slack bot token can create a private channel. "
          "Run this BEFORE approving real lab/core join requests so the "
          "auto-provisioning path doesn't fail mid-flight.",
)
@click.option("--channel", default="",
              help="Channel name to attempt to create. "
                   "Defaults to a timestamped probe name so the smoke "
                   "doesn't collide with real channels.")
@click.option("--public", is_flag=True, default=False,
              help="Create a public channel. Default is private (matches "
                   "the join-approve flow).")
@click.option("--keep", is_flag=True, default=False,
              help="Leave the probe channel behind. Default: archive it "
                   "via conversations.archive after a successful create.")
def centre_slack_smoke(channel: str, public: bool, keep: bool) -> None:
    """End-to-end smoke for the Slack channel-create path.

    Prints (a) the resolved channel name, (b) the result of the
    conversations.create call, (c) the actionable hint when Slack
    returns an error code. Cleans up the probe channel unless --keep.
    """
    import datetime as _dt
    import os
    from ..core import centre_provision as _cp

    if not os.environ.get("SLACK_BOT_TOKEN"):
        raise click.ClickException(
            "$SLACK_BOT_TOKEN is not set. Get a bot token with "
            "'groups:write' (private) or 'channels:manage' (public) "
            "scope from your Slack app's OAuth settings and export it."
        )

    if not channel:
        # Use UTC + seconds so re-runs don't collide.
        stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
        channel = f"wigamig-smoke-{stamp}"

    click.echo(f"channel name:  {channel}")
    click.echo(f"private:       {not public}")
    click.echo(f"keep:          {keep}")
    click.echo()

    res = _cp.slack_create_channel(channel, private=not public)
    if res.ok:
        click.echo(f"✓ created channel {res.channel_id} ({res.channel_name})")
        click.echo(f"  detail: {res.detail}")
        if not keep:
            archived = _archive_probe_channel(res.channel_id)
            if archived:
                click.echo("✓ probe channel archived")
            else:
                click.echo(
                    "⚠ created but could not archive — go clean up "
                    f"{res.channel_id} by hand."
                )
        click.echo()
        click.echo("Bot token is healthy. Real join-approve "
                    "provisioning will work.")
        return

    click.echo(f"✗ failed: error={res.error}")
    click.echo(f"  detail: {res.detail}")
    click.echo()
    click.echo("Fix the issue above and re-run before approving "
                "real lab/core join requests.")
    raise click.exceptions.Exit(1)


def _archive_probe_channel(channel_id: str) -> bool:
    """Archive a channel via Slack's conversations.archive. Returns
    True on success; best-effort (no exceptions). Used by the smoke
    CLI to clean up after itself."""
    import os
    try:
        import httpx
        tok = os.environ.get("SLACK_BOT_TOKEN", "")
        if not tok:
            return False
        r = httpx.post(
            "https://slack.com/api/conversations.archive",
            headers={"Authorization": f"Bearer {tok}"},
            json={"channel": channel_id},
            timeout=10,
        )
        return bool(r.json().get("ok"))
    except Exception:  # noqa: BLE001
        return False


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


@click.command("centre-slack-setup",
                help="Provision the centre's Slack fabric: the private mayor↔CC "
                     "channel (#wigamig-ops) + the #general broadcast wiring. "
                     "Needs a bot token ($WIGAMIG_SLACK_TOKEN) + slack_workspace "
                     "set on the centre.")
def centre_slack_setup() -> None:
    from ..core import centre_provision as _cp
    probes = _cp.provision_centre_slack()
    any_block = False
    for p in probes:
        mark = {"ok": "✓", "warn": "!", "block": "✗"}.get(p.status, "-")
        click.echo(f"  {mark} {p.name}: {p.detail}")
        any_block = any_block or p.status == "block"
    if any_block:
        raise click.exceptions.Exit(1)
    prof = _ci.read_centre()
    if prof and prof.mayor_channel_id:
        click.echo(f"\nmayor↔CC channel: {prof.mayor_channel_id}  "
                   f"(events + `admin` broadcasts route here)")
