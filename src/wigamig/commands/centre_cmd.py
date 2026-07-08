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
@click.option("--unique-name", default="",
              help="Non-institution-specific install id (drives repo/Slack/"
                   "group names, e.g. 'western'). Optional.")
@click.option("--join-email", default="",
              help="Public contact address for join requests (listed in the "
                   "wigamig_public directory). Optional.")
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
    unique_name: str, join_email: str, slack_workspace: str, github_org: str,
    public_hub: str,
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
    join_email = _prompt("Public join-request email", join_email)
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
            join_email=join_email,
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
    from ..core import centre_provision as _cp
    if not actor:
        actor = os.environ.get("WIGAMIG_USER", "")
    if not actor:
        raise click.ClickException("--actor required (or set $WIGAMIG_USER)")
    # Approving is a deliberate mayor action → resolve the Slack token from env
    # OR the mode-0600 ~/.config/wigamig/slack-token file, so lab/core
    # provisioning actually creates the channel + invites members without
    # requiring the mayor to export a token first.
    tok = _cp.resolve_slack_token(allow_file=True)
    try:
        r = _jr.approve(req_id=req_id, actor=actor,
                          provision=not no_provision, token=tok or None)
    except _jr.JoinRequestError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Request #{r.id:04d} → {r.state} (by @{actor})")
    for p in r.probes:
        click.echo(f"  [{p.get('severity'):5s}] {p.get('kind')}: {p.get('summary')}")

    # Workspace invite + next steps. On free/Pro Slack the bot can't add someone
    # to the workspace by API — so the new PI (lab/core) or member gets the
    # invite LINK by email, joins the workspace, and is then added to their
    # channel on the next reconcile. The mayor/registrar MUST send that email;
    # for a lab/core the PI also needs the steps to set up their group. Surface
    # both here (and open a pre-filled email so the approver just presses Send).
    if r.kind in ("lab", "core", "member") and r.state != "failed":
        from ..core import join_notify as _jn
        prof = _ci.read_centre()
        link = (getattr(prof, "slack_invite_url", "") or "").strip() if prof else ""
        who = (r.requester_email or "").strip()
        is_group = r.kind in ("lab", "core")
        role = "PI" if is_group else "member"
        steps = _jn.group_onboarding_steps(r.proposed_name, invite_url=link) if is_group else []

        click.echo("\n─── NEXT STEPS ───")
        # 1. The registrar's action: email the invite link.
        if who and link:
            click.echo(f"1. Send the workspace invite to the {role} ({who}):")
            click.echo(f"     {link}")
        elif who and not link:
            click.echo(f"1. No workspace invite link is set yet — set one, then email it to {who}:")
            click.echo("     wigamig centre-set slack_invite_url=<your western-serenity join link>")
        # 2. What the new PI then does (lab/core only).
        if is_group:
            click.echo(f"\n2. Once joined, the {role} sets up their group (send them these):")
            for i, s in enumerate(steps[1:], start=1):   # skip step 1 (join link, shown above)
                click.echo(f"     {i}. {s}")

        # Open a pre-filled email containing the link + the setup steps.
        if who and link:
            import shutil as _sh, subprocess as _sp, urllib.parse as _url
            body_lines = [
                f"Welcome! You've been added as the {role} of {r.proposed_name}.",
                "",
                "To get set up, do these in order:",
                "",
            ]
            body_lines += [f"{i}. {s}" for i, s in enumerate(steps, start=1)] if is_group \
                else [f"Join the Slack workspace:\n{link}",
                      "Once you've joined, you'll be added to your group's channel automatically."]
            subject = _url.quote(f"You're in — setting up {r.proposed_name} on wigamig")
            body = _url.quote("\n".join(body_lines))
            mailto = f"mailto:{who}?subject={subject}&body={body}"
            opener = _sh.which("open") or _sh.which("xdg-open")
            if opener:
                _sp.run([opener, mailto], check=False,
                        stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
                click.echo("\n  ✉️  Opened your email app pre-filled with the link + steps — press Send.")


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

    # For a declined MEMBER request the applicant isn't in Slack, so notify them
    # by plain email — open the mayor/PI's mail client pre-filled (no encryption
    # needed for a decline). Best-effort.
    if r.kind == "member" and (r.requester_email or "").strip():
        import shutil as _sh, subprocess as _sp, urllib.parse as _url
        subject = _url.quote(f"Your wigamig join request for {r.proposed_name}")
        body = _url.quote(
            f"Hello,\n\nYour request to join {r.proposed_name} was not approved."
            f"{(' Reason: ' + r.decline_reason) if r.decline_reason else ''}\n\n"
            f"Regards,\n@{actor.lstrip('@')}")
        mailto = f"mailto:{r.requester_email}?subject={subject}&body={body}"
        opener = _sh.which("open") or _sh.which("xdg-open")
        if opener:
            _sp.run([opener, mailto], check=False,
                    stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
            click.echo(f"\nOpened your email app to let {r.requester_email} know "
                       "(plain email — just press Send).")
        else:
            click.echo(f"\nEmail {r.requester_email} to let them know:\n  {mailto}")


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
    from ..core import centre_provision as _cp

    tok = _cp.resolve_slack_token(allow_file=True)
    if not tok:
        raise click.ClickException(
            "no Slack token found. Set $WIGAMIG_SLACK_TOKEN (legacy $SLACK_BOT_TOKEN "
            "also works) or put it in ~/.config/wigamig/slack-token (mode 0600). "
            "The bot needs 'groups:write' (private) or 'channels:manage' (public):\n"
            "    export WIGAMIG_SLACK_TOKEN=xoxb-..."
        )

    if not channel:
        # Use UTC + seconds so re-runs don't collide.
        stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
        channel = f"wigamig-smoke-{stamp}"

    click.echo(f"channel name:  {channel}")
    click.echo(f"private:       {not public}")
    click.echo(f"keep:          {keep}")
    click.echo()

    res = _cp.slack_create_channel(channel, private=not public, token=tok)
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
    try:
        import httpx
        from ..core import centre_provision as _cp
        tok = _cp.resolve_slack_token(allow_file=True)
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
@click.option("--mayor-email", default="",
              help="The email on YOUR Slack account (used to add you to "
                   "#wigamig-ops). Defaults to your registrar profile email, then "
                   "the centre join_email — override here if those don't match "
                   "your Slack login.")
def centre_slack_setup(mayor_email: str) -> None:
    from ..core import centre_provision as _cp
    # Explicit mayor command → resolve the token from env OR the mode-0600
    # ~/.config/wigamig/slack-token file, so it works in any terminal.
    tok = _cp.resolve_slack_token(allow_file=True)
    probes = _cp.provision_centre_slack(token=tok or None, mayor_email=mayor_email)
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


@click.command("centre-age-keygen",
                help="Generate the centre's age key pair for the encrypted-email "
                     "join flow. Writes the private key to ~/.wigamig/age/mayor.key "
                     "and stores the public recipient on the centre (publish it in "
                     "the wigamig_public directory).")
def centre_age_keygen() -> None:
    from ..core import age_crypto as _age
    if not _age.age_available():
        raise click.ClickException(
            "age is not installed. Install it from https://age-encryption.org "
            "(e.g. `brew install age`), then re-run.")
    if _ci.read_centre() is None:
        raise click.ClickException("no centre initialised; run `wigamig centre-init` first.")
    try:
        recipient = _age.keygen()
    except _age.AgeError as exc:
        raise click.ClickException(str(exc)) from exc
    _ci.update_centre({"age_recipient": recipient})
    click.echo(f"✓ private key: {_age.default_key_path()}  (mode 0600, keep it secret)")
    click.echo(f"✓ public recipient (publish this in the directory):\n    {recipient}")


@click.command("centre-root-keygen",
                help="Generate the centre's ROOT signing key — the certificate "
                     "authority that signs PI identity cards. Writes the private "
                     "key to ~/.wigamig/keys/, pins its fingerprint as this "
                     "machine's trust anchor, and stores the public signing "
                     "recipient on the centre. --rotate replaces an existing root "
                     "(all cards must then be re-issued).")
@click.option("--rotate", is_flag=True,
              help="Replace an existing root key (rotation — invalidates all cards).")
def centre_root_keygen(rotate: bool) -> None:
    from ..core import centre_root as _cr
    prof = _ci.read_centre()
    if prof is None:
        raise click.ClickException("no centre initialised; run `wigamig centre-init` first.")
    if _cr.have_root_key() and not rotate:
        fp = _cr.root_fingerprint()
        click.echo(f"✓ centre root key already present — fingerprint:\n    {fp}")
        click.echo(f"  public signing recipient:\n    {_cr.root_public()}")
        click.echo("  (use --rotate to replace it — this invalidates every issued card)")
        return
    existed = _cr.have_root_key()
    fp = _cr.generate_root_key(overwrite=rotate)
    pub = _cr.root_public()
    _cr.bootstrap_root(prof.unique_name or prof.install_id)  # pin anchor
    _ci.update_centre({"signing_recipient": pub})
    verb = "rotated" if (existed and rotate) else "generated"
    click.echo(f"✓ centre root key {verb} — fingerprint:\n    {fp}")
    click.echo(f"✓ private key: {_cr.root_key_path()}  (mode 0600 — the whole centre "
               "depends on this staying secret)")
    click.echo(f"✓ public signing recipient (publish in the directory):\n    {pub}")
    click.echo("\n⚠ BACK IT UP NOW — offline, encrypted, OFF this laptop. If you lose "
               "this key you lose the centre; if it leaks, someone can impersonate "
               "the whole centre. See docs/centre_root_key.md (rotation runbook).")
    if existed and rotate:
        click.echo("⚠ ROTATION: every PI/member card signed by the old key is now "
                   "stale. Re-issue them and publish the new CRL.")


@click.command("identity-card",
                help="MAYOR: generate a scoped identity card for a member — their "
                     "netname + only their own group's role — to hand them so their "
                     "OWN machine knows their role. Decentralized: no shared server "
                     "needed. Prints the card (YAML); --out writes it to a file.")
@click.argument("handle")
@click.option("--out", "out_file", type=click.Path(dir_okay=False), default=None,
              help="Write the card to a file (default: print to stdout).")
@click.option("--actor", default="", help="Issuing mayor handle (for the audit line).")
def identity_card(handle: str, out_file: str | None, actor: str) -> None:
    from ..core import identity_card as _ic
    if _ci.read_centre() is None:
        raise click.ClickException("no centre initialised; run `wigamig centre-init` first.")
    if not actor:
        actor = os.environ.get("WIGAMIG_USER", "")
    try:
        card = _ic.build_card(handle, issued_by=actor)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    text = _ic.card_yaml(card)
    if out_file:
        from pathlib import Path as _P
        _P(out_file).write_text(text, encoding="utf-8")
        click.echo(f"✓ wrote identity card for @{card['netname']} to {out_file}")
        click.echo("  Send it to them; they run `wigamig identity-import <file>` on "
                   "their machine.")
    else:
        click.echo(text.rstrip())


@click.command("identity-import",
                help="MEMBER: import an identity card the mayor gave you, so THIS "
                     "machine knows your role (your dashboard login then resolves "
                     "correctly). Reads a file, or stdin with '-'. Sets your netname "
                     "and materializes a scoped local registry.")
@click.argument("card_file")
def identity_import(card_file: str) -> None:
    from ..core import identity_card as _ic
    import sys as _sys
    text = _sys.stdin.read() if card_file == "-" else \
        __import__("pathlib").Path(card_file).expanduser().read_text(encoding="utf-8")
    try:
        card = _ic.parse_card(text)
        actions = _ic.import_card(card)
    except (ValueError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"✓ imported identity card for @{card['netname']}"
               + (f" — centre: {card.get('centre')}" if card.get("centre") else ""))
    for a in actions:
        click.echo(f"  • {a}")
    click.echo("\nRestart your wigamig dashboard; the login will now show your role.")


@click.command("enroll",
                help="Produce a proof-of-possession enrollment request (proves "
                     "you hold your key) to send to the mayor/PI so they can issue "
                     "you a signed identity card. Requires a local keypair "
                     "(`wigamig identity-init`).")
@click.option("--nonce", default="", help="Challenge nonce (default: random).")
@click.option("--group", default="", help="Group you're enrolling into (optional).")
@click.option("--out", "out_file", type=click.Path(dir_okay=False), default=None,
              help="Write the request to a file (default: print).")
def enroll(nonce: str, group: str, out_file: str | None) -> None:
    from ..core import issuance as _iss
    from ..core import identity as _id
    ident = _id.resolve(allow_unknown=True)
    try:
        req = _iss.make_enrollment(ident.at_handle, nonce=nonce or None, group=group)
    except _iss.IssuanceError as exc:
        raise click.ClickException(str(exc)) from exc
    text = __import__("json").dumps(req, indent=2)
    if out_file:
        from pathlib import Path as _P
        _P(out_file).write_text(text, encoding="utf-8")
        click.echo(f"✓ wrote enrollment request for {ident.at_handle} to {out_file}")
        click.echo("  Send it to your mayor; they run `wigamig issue-pi-card <file>`.")
    else:
        click.echo(text)


@click.command("issue-pi-card",
                help="MAYOR: issue a centre-root-signed PI card from a PI's "
                     "enrollment request. Verifies proof-of-possession, confirms "
                     "the handle is a registered PI/leader, and signs with the "
                     "centre root key. Output is the signed card — send it to the "
                     "PI to `wigamig import-card`.")
@click.argument("enrollment_file")
@click.option("--handle", default="", help="PI handle (default: from the enrollment).")
@click.option("--actor", default="", help="Issuing mayor handle (audit).")
@click.option("--out", "out_file", type=click.Path(dir_okay=False), default=None,
              help="Write the signed card to a file (default: print).")
def issue_pi_card_cmd(enrollment_file: str, handle: str, actor: str,
                      out_file: str | None) -> None:
    from ..core import issuance as _iss
    import json as _json
    from pathlib import Path as _P
    if not actor:
        actor = os.environ.get("WIGAMIG_USER", "")
    try:
        enrollment = _json.loads(_P(enrollment_file).expanduser().read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise click.ClickException(f"cannot read enrollment: {exc}") from exc
    if not handle:
        handle = (enrollment.get("payload") or {}).get("handle", "")
    try:
        card = _iss.issue_pi_card(handle, enrollment=enrollment, actor=actor)
    except _iss.IssuanceError as exc:
        raise click.ClickException(str(exc)) from exc
    from ..core import idcert as _cert
    text = _cert.dumps(card)
    subj = card["payload"]["subject"]["handle"]
    if out_file:
        _P(out_file).write_text(text, encoding="utf-8")
        click.echo(f"✓ signed PI card for {subj} → {out_file}")
        click.echo("  Send it to them (with the centre's signing recipient so they "
                   "can pin it); they run `wigamig import-card <file> --trust-root <pubkey>`.")
    else:
        click.echo(text)


@click.command("issue-member-card",
                help="PI / group-registrar: sign a member card for a member's "
                     "enrollment request, chaining it to the centre via your own "
                     "PI card. Verifies proof-of-possession. Output is a BUNDLE "
                     "(member card + your PI card) — send it to the member to "
                     "`wigamig import-card`.")
@click.argument("enrollment_file")
@click.option("--group", required=True, help="The group you lead to add them to.")
@click.option("--handle", default="", help="Member handle (default: from the enrollment).")
@click.option("--out", "out_file", type=click.Path(dir_okay=False), default=None,
              help="Write the bundle to a file (default: print).")
def issue_member_card_cmd(enrollment_file: str, group: str, handle: str,
                          out_file: str | None) -> None:
    from ..core import issuance as _iss
    import json as _json
    from pathlib import Path as _P
    try:
        enrollment = _json.loads(_P(enrollment_file).expanduser().read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise click.ClickException(f"cannot read enrollment: {exc}") from exc
    if not handle:
        handle = (enrollment.get("payload") or {}).get("handle", "")
    try:
        bundle = _iss.issue_member_card(handle, enrollment=enrollment, group=group)
    except _iss.IssuanceError as exc:
        raise click.ClickException(str(exc)) from exc
    text = _json.dumps(bundle, indent=2)
    subj = bundle["member_card"]["payload"]["subject"]["handle"]
    if out_file:
        _P(out_file).write_text(text, encoding="utf-8")
        click.echo(f"✓ signed member card for {subj} (group {group}) → {out_file}")
        click.echo("  Send it to them (with the centre's signing recipient to pin); "
                   "they run `wigamig import-card <file> --trust-root <pubkey>`.")
    else:
        click.echo(text)


@click.command("import-card",
                help="Import a SIGNED identity card you were issued (a PI card, or "
                     "a member-card bundle). Verifies it chains to the centre root "
                     "(pin it with --trust-root the first time — use the centre's "
                     "published signing recipient, fingerprint confirmed "
                     "out-of-band) and materializes your role locally.")
@click.argument("card_file")
@click.option("--trust-root", "trust_root", default="",
              help="Centre signing recipient (ed25519:...) to pin on first import.")
def import_signed_card_cmd(card_file: str, trust_root: str) -> None:
    from ..core import issuance as _iss
    import json as _json
    import sys as _sys
    text = _sys.stdin.read() if card_file == "-" else \
        __import__("pathlib").Path(card_file).expanduser().read_text(encoding="utf-8")
    try:
        obj = _json.loads(text)
    except ValueError as exc:
        raise click.ClickException(f"not valid card JSON: {exc}") from exc
    try:
        if isinstance(obj, dict) and "member_card" in obj:
            verdict, actions = _iss.verify_and_import_member_card(
                obj, trust_root=trust_root or None)
        else:
            verdict, actions = _iss.verify_and_import_pi_card(
                obj, trust_root=trust_root or None)
    except _iss.IssuanceError as exc:
        raise click.ClickException(str(exc)) from exc
    grp = f", group: {verdict.group}" if verdict.group else ""
    click.echo(f"✓ card verified ({verdict.handle}, role: {verdict.kind}{grp}) and imported")
    for a in actions:
        click.echo(f"  • {a}")
    click.echo("\nRestart your wigamig dashboard; the login will now show your role.")


@click.command("revoke",
                help="MAYOR: revoke an identity card — adds it to the centre CRL "
                     "and republishes. Identify the card by --handle (looked up in "
                     "this machine's issuance ledger), --card-id, or --fingerprint. "
                     "Needs the centre root key.")
@click.option("--handle", default="", help="Revoke the card issued to this handle.")
@click.option("--card-id", "card_id", default="", help="Revoke by card id.")
@click.option("--fingerprint", default="", help="Revoke by key fingerprint.")
def revoke_cmd(handle: str, card_id: str, fingerprint: str) -> None:
    from ..core import revocation as _rev
    prof = _ci.read_centre()
    if prof is None:
        raise click.ClickException("no centre initialised; run `wigamig centre-init` first.")
    centre = prof.unique_name or prof.install_id
    try:
        if handle:
            crl = _rev.revoke_member(centre, handle)
        elif card_id or fingerprint:
            crl = _rev.revoke(centre, card_id=card_id or None,
                              fingerprint=fingerprint or None)
        else:
            raise click.ClickException("specify --handle, --card-id, or --fingerprint.")
    except _rev.RevocationError as exc:
        raise click.ClickException(str(exc)) from exc
    n = len(crl["payload"]["revoked"])
    click.echo(f"✓ revoked. CRL serial {crl['payload']['serial']}, "
               f"{n} entr{'y' if n == 1 else 'ies'}.")
    click.echo("  Publish it to members so verifiers see the revocation: "
               "`wigamig crl --out crl.json`.")


@click.command("crl",
                help="Show or export the centre's current root-signed revocation "
                     "list (CRL). On the mayor's machine it is freshly re-signed; "
                     "elsewhere it prints the last imported CRL.")
@click.option("--out", "out_file", type=click.Path(dir_okay=False), default=None,
              help="Write the signed CRL to a file (default: print).")
def crl_cmd(out_file: str | None) -> None:
    from ..core import revocation as _rev
    import json as _json
    prof = _ci.read_centre()
    if prof is None:
        raise click.ClickException("no centre initialised; run `wigamig centre-init` first.")
    centre = prof.unique_name or prof.install_id
    crl = _rev.current_crl(centre)
    if crl is None:
        raise click.ClickException(
            "no CRL available (need the centre root key, or an imported CRL).")
    text = _json.dumps(crl, indent=2)
    if out_file:
        from pathlib import Path as _P
        _P(out_file).write_text(text, encoding="utf-8")
        click.echo(f"✓ wrote CRL (serial {crl['payload']['serial']}, "
                   f"{len(crl['payload']['revoked'])} revoked) → {out_file}")
    else:
        click.echo(text)


@click.command("identity-init",
                help="Create THIS machine's ed25519 signing keypair — your unique "
                     "wigamig ID (a fingerprint your PI/mayor binds an identity "
                     "card to). Idempotent; normally minted automatically on your "
                     "first wigamig command after cloning. --rotate replaces an "
                     "existing key (you then need a re-issued card).")
@click.option("--rotate", is_flag=True,
              help="Replace an existing keypair with a fresh one.")
def identity_init(rotate: bool) -> None:
    from ..core import idkeys as _k
    existed = _k.have_keys()
    if existed and not rotate:
        click.echo(f"✓ keypair already present — your wigamig ID:\n    {_k.local_fingerprint()}")
        click.echo(f"  private key: {_k.private_key_path()} (mode 0600 — never share it)")
        click.echo("  (use --rotate to replace it)")
        return
    fp = _k.generate_keypair(overwrite=rotate)
    verb = "rotated" if (existed and rotate) else "created"
    click.echo(f"✓ keypair {verb} — your wigamig ID (fingerprint):\n    {fp}")
    click.echo(f"  private key: {_k.private_key_path()} (mode 0600 — never share it)")
    if existed and rotate:
        click.echo("  NOTE: your old identity card is now stale — ask your PI/mayor "
                   "to re-issue one bound to this new key.")


@click.command("whoami",
                help="Show who THIS machine is: your wigamig handle, your unique "
                     "key ID (fingerprint), and whether an identity card has been "
                     "imported.")
def whoami() -> None:
    from ..core import idkeys as _k
    from ..core import identity as _id
    from ..core import identity_card as _ic
    ident = _id.resolve(allow_unknown=True)
    fp = _k.local_fingerprint()
    click.echo(f"handle:   {ident.at_handle}  (via {ident.source})")
    click.echo(f"key ID:   {fp or '— none yet (run `wigamig identity-init`)'}")
    card = _ic.local_card()
    if card:
        centre = card.get("centre") or "?"
        roles = ", ".join(sorted({r.get("kind", "?") for r in card.get("roles", [])})) or "—"
        click.echo(f"card:     centre '{centre}'; roles: {roles}")
    else:
        click.echo("card:     none imported yet")


@click.command("onboard-check",
                help="Check whether newly-approved PIs have joined the Slack "
                     "workspace yet; for any who have, add them to their group "
                     "channel and DM them the step-by-step onboarding "
                     "(registrar -> cable_guy -> security_guard -> dashboard). "
                     "Run this after approving a lab/core (or on a schedule); "
                     "it converges and never double-reports.")
@click.argument("group", required=False, default="")
def onboard_check(group: str) -> None:
    from ..core import onboarding as _ob
    from ..core import centre_provision as _cp
    if _ci.read_centre() is None:
        raise click.ClickException("no centre initialised; run `wigamig centre-init` first.")
    tok = _cp.resolve_slack_token(allow_file=True)
    results = _ob.run_onboard_check(group or None, token=tok or None)
    if not results:
        click.echo("No active labs/cores to check.")
        return
    for r in results:
        icon = "✓" if r.joined and r.dmed else ("…" if not r.joined else "•")
        who = f" ({r.email})" if r.email else ""
        click.echo(f"  [{icon}] {r.group} · PI {r.pi}{who}: {r.note}")
    waiting = [r for r in results if not r.joined and "waiting" in r.note]
    if waiting:
        click.echo(f"\n{len(waiting)} PI(s) haven't accepted the workspace invite yet — "
                   "re-run onboard-check after they do (or leave it to the schedule).")


# Centre profile fields a mayor may set/change after init. Excludes identity +
# audit fields that must not drift once the centre exists (name, institution,
# founding_mayor, created, unique_name).
_CENTRE_SETTABLE = (
    "join_email", "slack_workspace", "slack_invite_url", "github_org",
    "data_server", "server_host", "server_account", "cc_install_path",
    "obsidian_vault", "mayor_root", "public_hub", "raw_root", "refined_root",
)


@click.command("centre-set",
                help="Set one or more centre-profile fields after init "
                     "(e.g. the Slack workspace join link). "
                     "Usage: wigamig centre-set slack_invite_url=https://join.slack.com/…")
@click.argument("pairs", nargs=-1, metavar="KEY=VALUE...")
def centre_set(pairs: tuple[str, ...]) -> None:
    if _ci.read_centre() is None:
        raise click.ClickException("no centre initialised; run `wigamig centre-init` first.")
    if not pairs:
        click.echo("Settable fields:")
        for k in _CENTRE_SETTABLE:
            click.echo(f"  {k}")
        click.echo("\nUsage: wigamig centre-set KEY=VALUE [KEY=VALUE ...]")
        return
    updates: dict[str, str] = {}
    for p in pairs:
        if "=" not in p:
            raise click.ClickException(f"expected KEY=VALUE, got {p!r}")
        key, _, val = p.partition("=")
        key = key.strip()
        if key not in _CENTRE_SETTABLE:
            raise click.ClickException(
                f"{key!r} is not a settable centre field. One of: "
                + ", ".join(_CENTRE_SETTABLE))
        updates[key] = val.strip()
    _ci.update_centre(updates)
    for k, v in updates.items():
        click.echo(f"✓ {k} = {v or '(cleared)'}")


@click.command("centre-hub-publish",
                help="List this centre in the public wigamig_public hub. Clones "
                     "the hub if needed and writes your row into "
                     "join/directory.tsv + the README table. With --submit it "
                     "also publishes: a direct push if you have write access, "
                     "otherwise it forks the hub and opens a pull request for you.")
@click.option("--hub-dir", type=click.Path(file_okay=False), default=None,
              help="Where to clone/find your wigamig_public checkout "
                   "(default: ~/repos/wigamig_public).")
@click.option("--remote", default=None,
              help="Hub git remote to clone from (default: the public hub).")
@click.option("--submit/--no-submit", default=False,
              help="Actually publish: push (if you own the hub) or fork + open a "
                   "PR (if you don't). Default: just write the files + print steps.")
def centre_hub_publish(hub_dir: str | None, remote: str | None, submit: bool) -> None:
    from pathlib import Path as _P
    from ..core import hub_publish as _hp

    prof = _ci.read_centre()
    if prof is None:
        raise click.ClickException("no centre initialised; run `wigamig centre-init` first.")
    if not (getattr(prof, "age_recipient", "") or "").strip():
        raise click.ClickException(
            "no age key on the centre yet — run `wigamig centre-age-keygen` first "
            "so members can send you encrypted join requests.")
    try:
        res = _hp.prepare_listing(
            institution=prof.institution, name=prof.name,
            email=prof.join_email, recipient=prof.age_recipient,
            hub_dir=_P(hub_dir) if hub_dir else None,
            remote=remote or _hp.DEFAULT_HUB_REMOTE,
        )
    except _hp.HubPublishError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"hub clone:     {res.hub_dir}"
               + ("  (freshly cloned)" if res.cloned else "  (reused existing)"))
    click.echo(f"directory.tsv: {res.directory_action}")
    click.echo(f"README table:  {res.readme_action}")
    click.echo(f"\nYour directory row:\n    {res.row}")
    both_unchanged = (res.directory_action == "unchanged"
                      and res.readme_action == "unchanged")
    # NOTE: "unchanged" means the FILES already carry your row locally — NOT
    # that it's on the public hub. A prior run (or `--no-submit`) writes the
    # files without pushing, so `--submit` must still go on to publish them.
    if both_unchanged and not submit:
        click.echo("\nYour row is already written in the local hub clone, but that "
                   "doesn't mean it's on the public hub. Publish it with:\n"
                   "    wigamig centre-hub-publish --submit")
        return

    message = f"directory: list {prof.name}"
    gh_ok = _hp.gh_available()
    slug = None
    push_ok: bool | None = None
    if gh_ok:
        try:
            slug = _hp.upstream_slug(res.hub_dir)
            push_ok = _hp.can_push(slug)
        except _hp.HubPublishError:
            slug, push_ok = None, None

    # ---- guidance-only (default): tell the mayor what --submit will do -------
    if not submit:
        if push_ok:
            click.echo("\nYou have write access. Publish with:")
            click.echo("    wigamig centre-hub-publish --submit      # commits + pushes for you")
            click.echo("  …or by hand:")
            click.echo(f"    cd {res.hub_dir} && git add join/directory.tsv README.md "
                       f'&& git commit -m "{message}" && git push')
        else:
            click.echo("\nYou don't own the hub, so listing goes in as a pull request "
                       "(the maintainer reviews + merges). Open it with:")
            click.echo("    wigamig centre-hub-publish --submit      # forks + opens the PR for you")
            if not gh_ok:
                click.echo("  (needs the GitHub CLI: install `gh` + `gh auth login` first.)")
        return

    # ---- --submit: actually publish ----------------------------------------
    if not gh_ok:
        raise click.ClickException(
            "--submit needs the GitHub CLI to detect access and open a PR. "
            "Install `gh` and run `gh auth login`, then retry. (Or publish by "
            f"hand from {res.hub_dir}.)")
    try:
        if push_ok:
            out = _hp.submit_direct(res.hub_dir, message)
            click.echo(f"\n✓ {out.detail} — you're listed on the public hub.")
        else:
            branch = f"list-{(prof.unique_name or 'centre')}"
            title = f"directory: list {prof.name} ({prof.institution})"
            body = ("Adds a wigamig_public directory row for this centre "
                    "(registrar contact + age public key). Opened by "
                    "`wigamig centre-hub-publish`. No member data is included.")
            out = _hp.submit_pr(res.hub_dir, slug, branch=branch, message=message,
                                title=title, body=body)
            click.echo(f"\n✓ pull request opened: {out.detail}")
            click.echo("  The hub maintainer reviews + merges it; then you're listed.")
    except _hp.HubPublishError as exc:
        raise click.ClickException(str(exc)) from exc


_GROUP_SETUP_PROMPTS = [
    ("github",           "GitHub repo for the group (org/repo)"),
    ("notebook_host",    "Lab-notebook host (a machine name)"),
    ("notebook_path",    "Lab-notebook path on that host"),
    ("slack_workspace",  "The group's OWN Slack workspace (team id, e.g. T0…)"),
    ("slack_invite_url", "That workspace's join link"),
    ("data_host",        "Host for large datasets (e.g. biodatsci)"),
    ("data_raw",         "Raw data root"),
    ("data_refined",     "Refined data root"),
]


@click.command("group-setup",
                help="Fill in a group's post-creation details — GitHub repo, "
                     "lab-notebook host/path, the group's OWN Slack workspace, and "
                     "large-dataset location. Run by the PI after their lab/core "
                     "exists; writes to the group's lab.md.")
@click.argument("group")
@click.option("--set", "sets", multiple=True, metavar="KEY=VALUE",
              help="Set a field directly (repeatable): github, notebook_host, "
                   "notebook_path, slack_workspace, slack_invite_url, data_host, "
                   "data_raw, data_refined.")
@click.option("--non-interactive", is_flag=True,
              help="Don't prompt; apply only --set values.")
def group_setup(group: str, sets: tuple[str, ...], non_interactive: bool) -> None:
    from ..core import registrar as _R
    from ..core import hosts as _hosts

    if not _R.group_exists(group):
        raise click.ClickException(
            f"no lab or core named {group!r} — create it first (a lab/core join request).")
    current = _R.read_group_profile(group)
    try:
        known_hosts = set(_hosts.read().keys())
    except Exception:  # noqa: BLE001
        known_hosts = set()

    fields: dict[str, str] = {}
    for kv in sets:
        if "=" not in kv:
            raise click.ClickException(f"--set expects KEY=VALUE, got {kv!r}")
        k, v = kv.split("=", 1)
        fields[k.strip()] = v.strip()

    if not non_interactive:
        click.echo(f"Group setup for '{group}'. Enter = keep the current value "
                   "[in brackets]; leave blank to clear.\n")
        for key, label in _GROUP_SETUP_PROMPTS:
            if key in fields:
                continue
            cur = current.get(key, "")
            fields[key] = click.prompt(f"  {label}", default=cur, show_default=bool(cur))

    # Soft-validate notebook/data hosts against the machine registry.
    for hk in ("notebook_host", "data_host"):
        h = (fields.get(hk, current.get(hk, "")) or "").strip()
        if h and known_hosts and h not in known_hosts:
            click.secho(f"  ! host {h!r} isn't in your machine registry "
                        f"(~/.wigamig/hosts.yaml) — add it with `wigamig host add {h} …` "
                        "so notebooks/data can be reached.", fg="yellow", err=True)

    if not _R.update_group_profile(group, fields):
        raise click.ClickException(f"could not write the profile for {group!r}.")
    click.echo("\n✓ Saved to the group's lab.md. Current profile:")
    prof = _R.read_group_profile(group)
    if prof:
        for k, v in prof.items():
            click.echo(f"    {k}: {v}")
    else:
        click.echo("    (empty)")
    if not prof.get("github"):
        click.echo("\nTip: create a PRIVATE group repo (your agent toolkit + lab-mgmt), "
                   f"then set it:  wigamig group-setup {group} --set github=<org>/<repo>")


@click.command("group-reconcile",
                help="Group-level cable_guy (the PI runs this): propagate the "
                     "group's members into its OWN Slack workspace and GitHub "
                     "repo. Reports Slack workspace membership (free/Pro can't "
                     "API-invite — it surfaces the invite link) and, with "
                     "--apply, adds members as GitHub collaborators. Uses the "
                     "group's own token (~/.config/wigamig/groups/<group>/slack-token).")
@click.argument("group")
@click.option("--apply", is_flag=True,
              help="Actually add GitHub collaborators (default: report only).")
def group_reconcile_cmd(group: str, apply: bool) -> None:
    from ..core import group_reconcile as _gr
    from ..core import registrar as _R
    if not _R.group_exists(group):
        raise click.ClickException(f"no lab or core named {group!r}.")
    res = _gr.group_reconcile(group, apply=apply)
    click.echo(f"Group reconcile: {group}"
               + ("  (--apply)" if apply else "  (report only — no writes)"))
    click.echo("\nGroup Slack workspace:")
    for line in (res.slack or ["  (nothing to check)"]):
        click.echo(f"  {line}")
    if res.invite_url:
        click.echo(f"  invite link to send new members: {res.invite_url}")
    elif any("NOT in the group workspace" in s for s in res.slack):
        click.echo("  (set the group's slack_invite_url via `wigamig group-setup` "
                   "so you have a link to send.)")
    click.echo("\nGroup GitHub repo:")
    for line in (res.github or ["  (no github repo set — `wigamig group-setup "
                                f"{group} --set github=<org>/<repo>`)"]):
        click.echo(f"  {line}")
    if not apply and res.github:
        click.echo("\n  Re-run with --apply to add the GitHub collaborators.")


@click.command("group-remove-member",
                help="Remove a member from a group (the PI runs this): kick them "
                     "from the group's Slack channel, remove them as a GitHub "
                     "collaborator on the group's repo, and mark them removed in "
                     "the roster. The inverse of onboarding a member.")
@click.argument("group")
@click.argument("handle")
@click.option("--delete", is_flag=True,
              help="Delete the member's roster file instead of marking it "
                   "'status: removed' (the default keeps it for the audit trail).")
@click.option("--yes", is_flag=True,
              help="Skip the confirmation prompt.")
def group_remove_member(group: str, handle: str, delete: bool, yes: bool) -> None:
    from ..core import centre_provision as _cp
    from ..core import registrar as _R
    if not _R.group_exists(group):
        raise click.ClickException(f"no lab or core named {group!r}.")
    norm = handle.lstrip("@")
    info = _R.read_group_member(group, norm)
    if info is None:
        raise click.ClickException(f"@{norm} is not a member of {group}.")
    if not yes:
        click.confirm(
            f"Remove @{norm} ({info['email'] or 'no email'}) from {group}? "
            "This kicks them from the Slack channel and the GitHub repo",
            abort=True)
    probes = _cp.deprovision_member_from_group(group, handle=norm, delete=delete)
    click.echo(f"Removing @{norm} from {group}:")
    for p in probes:
        icon = "✓" if p.status == "ok" else ("!" if p.status == "warn" else "✗")
        click.echo(f"  [{icon}] {p.name}: {p.detail}")
    # Defense-in-depth: revoke their identity card in the centre CRL. Live access
    # was already pulled above (Slack/GitHub/registry); this stops the card itself
    # from verifying. Best-effort — needs the centre root key (mayor's machine).
    from ..core import revocation as _rev
    prof = _ci.read_centre()
    if prof is not None:
        centre = prof.unique_name or prof.install_id
        try:
            crl = _rev.revoke_member(centre, norm)
            click.echo(f"  [✓] card-revocation: added to CRL (serial "
                       f"{crl['payload']['serial']})")
        except _rev.RevocationError as exc:
            click.echo(f"  [!] card-revocation: deferred — {exc}")


_TOOLKIT_README = """# {group} toolkit — group agents + governance

This is **{group}**'s private toolkit. It holds the group's own Claude Code
agents that **override the general wigamig (commons) agents**, plus anything
else the group wants to version privately.

## How the override works

Claude Code resolves agents **most-specific-wins**: an agent in a *project's*
`.claude/agents/<name>.md` takes precedence over the same-named agent in the
machine commons (`~/.claude/agents/<name>.md`). So a `blacksmith.md` placed in a
project overrides the commons `blacksmith`; agents you don't override fall
through to the commons unchanged.

Put the group's custom/tuned agents in [`.claude/agents/`](.claude/agents/).
To use them in one of the group's projects, wire them into that project's
`.claude/agents/` (the wigamig install/adopt wizard does this when you pick
them). New group members clone this repo to get the group's agents.

**Keep this repo PRIVATE** — it may encode group-specific methods.
"""

_AGENTS_README = """# {group} agents (override the commons)

Drop group-specific agents here as `<name>.md` with the standard agent
frontmatter. Name a file after a commons agent (`blacksmith.md`, `bookworm.md`,
…) to **override** it for the group's projects, or use a new name (e.g.
`segmenter.md`) to add a discipline-specific agent on top of the commons.

See `_TEMPLATE.md` for the shape. Every agent must open its final reply with a
≤200-char verdict line (wigamig's headline-first rule).
"""

_AGENT_TEMPLATE = """---
name: <agent-name>            # same name as a commons agent = override it
description: 'MUST: first line of every final response is a <=200-char verdict.'
model: sonnet
required_tools: [Read, Write, Bash, Glob, Grep]
---

# <Agent name> ({group}-tuned)

<Your group-specific instructions. Because this file name matches a commons
agent, it overrides that agent in projects that wire it in.>
"""


@click.command("group-init-toolkit",
                help="Scaffold the group's PRIVATE agent-toolkit repo — where the "
                     "PI puts group agents that OVERRIDE the general wigamig "
                     "agents. Creates ~/repos/<group>_toolkit with .claude/agents/ "
                     "+ READMEs and git init; --create-repo also makes a private "
                     "GitHub repo and records it on the group profile.")
@click.argument("group")
@click.option("--dir", "target_dir", default=None,
              help="Where to scaffold (default: ~/repos/<group>_toolkit).")
@click.option("--create-repo", default="", metavar="OWNER/REPO",
              help="Also create a PRIVATE GitHub repo (gh) + push + record it.")
def group_init_toolkit(group: str, target_dir: str | None, create_repo: str) -> None:
    from pathlib import Path as _P
    import subprocess as _sp
    from ..core import registrar as _R

    if not _R.group_exists(group):
        raise click.ClickException(f"no lab or core named {group!r} — create it first.")
    root = _P(target_dir).expanduser() if target_dir else _P.home() / "repos" / f"{group}_toolkit"
    if root.exists() and any(root.iterdir()):
        raise click.ClickException(f"{root} already exists and isn't empty — move it aside.")
    (root / ".claude" / "agents").mkdir(parents=True, exist_ok=True)
    (root / "README.md").write_text(_TOOLKIT_README.format(group=group), encoding="utf-8")
    (root / ".claude" / "agents" / "README.md").write_text(
        _AGENTS_README.format(group=group), encoding="utf-8")
    (root / ".claude" / "agents" / "_TEMPLATE.md").write_text(
        _AGENT_TEMPLATE.format(group=group), encoding="utf-8")
    (root / ".gitignore").write_text(".claude/settings.json\n", encoding="utf-8")
    _sp.run(["git", "init", "-q", str(root)], check=False,
            stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)

    click.echo(f"✓ Scaffolded {root}")
    click.echo("    .claude/agents/  — put group agents here; they override the commons.")
    if create_repo:
        r = _sp.run(["gh", "repo", "create", create_repo, "--private",
                     "--source", str(root), "--remote", "origin", "--push"],
                    capture_output=True, text=True)
        if r.returncode == 0:
            click.echo(f"✓ Created private repo {create_repo} + pushed.")
            _R.update_group_profile(group, {"github": create_repo})
            click.echo(f"✓ Recorded github={create_repo} on the group profile.")
        else:
            click.echo(f"! gh repo create failed: "
                       f"{((r.stderr or r.stdout) or '').strip()[:160]}")
    else:
        click.echo("\nNext — make it a private repo and record it:")
        click.echo(f"    cd {root} && git add -A && git commit -m 'group toolkit'")
        click.echo(f"    gh repo create <org>/{group}_toolkit --private --source . --push")
        click.echo(f"    wigamig group-setup {group} --set github=<org>/{group}_toolkit")


@join_request_group.command("decrypt")
@click.argument("path", type=click.Path(exists=True, dir_okay=False))
def cmd_decrypt(path: str) -> None:
    """Decrypt an emailed .age join form and file it as a join request.

    The prospective member encrypted their form to the centre's public key
    (see the wigamig_public directory) and emailed you the ciphertext. This
    decrypts it with the centre's private key and files a pending request."""
    from ..core import age_crypto as _age
    from ..core import join_requests as _jr
    from pathlib import Path as _P
    try:
        plaintext = _age.decrypt(_P(path).read_text(encoding="utf-8"))
    except _age.AgeError as exc:
        raise click.ClickException(str(exc)) from exc
    try:
        req = _jr.file_request_from_form(plaintext, source=path)
    except _jr.JoinRequestError as exc:
        raise click.ClickException(f"form invalid: {exc}") from exc
    click.echo(f"Filed join request #{req.id:04d} ({req.kind} {req.proposed_name}, "
               f"from {req.requester_email or 'unknown'}).")
    click.echo(f"Approve with:  wigamig join-request approve {req.id}")
