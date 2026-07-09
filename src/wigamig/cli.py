"""
Purpose: Wigamig CLI entry point. Builds the full command tree from cli_manual.md;
         most subcommands stub out with a clear message in v1 phase 1. Phase-1
         working commands: ``agent list``, ``--help`` everywhere.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-06
Input: Command-line arguments.
Output: Side effects per subcommand; v1 working commands write to stdout.
"""

from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from . import __version__
from .commands import dashboard_cmd as dashboard_impl
from .commands import experiment_cmd, install_cmd, project_cmd
from .commands import push_cmd as push_impl
from .commands import reconcile_cmd as reconcile_impl
from .commands import sea_cmd
from .commands import security_cmd as security_impl
from .core.agents import load_registry
from .core.repo import wigamig_repo_root

NOT_IMPLEMENTED_MSG = "not yet implemented in v1"


def _stub(*_args, **_kwargs) -> None:
    """Default body for v1-deferred subcommands."""
    click.echo(NOT_IMPLEMENTED_MSG)


@click.group(help="wigamig — group-level agentic infrastructure CLI.")
@click.version_option(__version__, prog_name="wigamig")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Top-level entry point."""
    # Clone-first identity: the first real command a member runs after cloning
    # mints THIS machine's ed25519 keypair (their unique wigamig ID). Idempotent
    # + best-effort; ``WIGAMIG_NO_AUTOKEY`` (set by the test suite) opts out. Only
    # runs when a subcommand is actually being invoked, not for bare/--help/--version.
    if ctx.invoked_subcommand:
        from .core import identity_bootstrap as _ib

        _ib.ensure_local_keypair()


# ---------------------------------------------------------------------------
# install / onboard / doctor / offboard
# ---------------------------------------------------------------------------


@cli.command("install", help="Install wigamig hooks + MCP into ~/.claude/settings.json.")
@click.option("--hooks", is_flag=True, help="Install hook + MCP registrations only (phase 4).")
@click.option(
    "--settings",
    "settings_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Override the settings.json target path (mostly for tests).",
)
@click.option("--no-backup", is_flag=True, help="Skip the .bak copy of settings.json.")
def install_command(hooks: bool, settings_path: Path | None, no_backup: bool) -> None:
    if not hooks:
        click.echo("not yet implemented in v1 (use --hooks to install hooks + MCP).")
        return
    install_cmd.cmd_install(hooks=hooks, settings_path=settings_path, backup=not no_backup)


@cli.command("onboard", help="One-shot setup for a new member (clone, key, profile, PR).")
@click.argument("group")
@click.option("--profile", required=True, help="Onboarding profile to apply.")
def onboard_cmd(group: str, profile: str) -> None:
    _stub()


@cli.command("doctor", help="Verify the local install is healthy.")
def doctor_cmd() -> None:
    _stub()


@cli.command("offboard", help="PI-only mirror of onboard.")
@click.option("--member", required=True, help="GitHub handle of the departing member.")
def offboard_cmd(member: str) -> None:
    _stub()


# ---------------------------------------------------------------------------
# agent
# ---------------------------------------------------------------------------


@cli.group("agent", help="Manage agent installs from the registry.")
def agent_group() -> None:
    pass


@agent_group.command("list", help="List available agents in the registry.")
@click.option("--group", "group_name", default=None, help="Filter to a specific guild.")
def agent_list(group_name: str | None) -> None:
    """Print agent name + freeze flag + short description."""
    registry_dir = wigamig_repo_root() / "agents"
    agents = load_registry(registry_dir)
    if not agents:
        click.echo(f"No agents found in {registry_dir}.")
        return

    console = Console()
    table = Table(title="Agents")
    table.add_column("name", style="bold")
    table.add_column("freeze")
    table.add_column("description", overflow="fold")
    for record in agents:
        table.add_row(record.name, record.freeze, record.description)
    console.print(table)


@agent_group.command("add", help="Install an agent locally.")
@click.argument("name")
def agent_add(name: str) -> None:
    _stub()


@agent_group.command("remove", help="Uninstall an agent locally.")
@click.argument("name")
@click.option("--purge", is_flag=True, help="Also delete agent memory.")
def agent_remove(name: str, purge: bool) -> None:
    _stub()


@agent_group.command("update", help="Pull the latest agent registry; relink frozen.")
def agent_update() -> None:
    _stub()


# ---------------------------------------------------------------------------
# preference
# ---------------------------------------------------------------------------


@cli.group("preference", help="Manage personal preference profile.")
def preference_group() -> None:
    pass


@preference_group.command("show", help="Print the effective preferences profile.")
def preference_show() -> None:
    _stub()


@preference_group.command("set", help="Set a preference field.")
@click.argument("field")
@click.argument("value")
def preference_set(field: str, value: str) -> None:
    _stub()


@preference_group.command("unset", help="Remove a preference field.")
@click.argument("field")
def preference_unset(field: str) -> None:
    _stub()


@preference_group.command("validate", help="Validate the profile against vocabularies.")
def preference_validate() -> None:
    _stub()


# ---------------------------------------------------------------------------
# host
# ---------------------------------------------------------------------------


@cli.group("host", help="Manage remote install targets (laptops, biodatsci, …).")
def host_group() -> None:
    """Hosts are registered in ~/.wigamig/hosts.yaml; ``local`` is built-in."""


@host_group.command("list", help="Print every registered host.")
def host_list_cmd() -> None:
    from .commands import host_cmd as _host_cmd
    raise SystemExit(_host_cmd.cmd_list())


@host_group.command("add", help="Register a new SSH host as an install target.")
@click.argument("name")
@click.option(
    "--ssh-host",
    required=True,
    help="Alias in ~/.ssh/config (e.g. 'biodatsci'). Omit to register a local host.",
)
@click.option("--remote-user", default="", help="Username on the remote host.")
@click.option("--project-root", default="~/repos", show_default=True,
              help="Where projects live on the remote host.")
@click.option("--lab-vm-root", default="/data/lab_vm", show_default=True,
              help="Where /data/lab_vm/{raw,refined} live on the remote host.")
@click.option("--vault-root", default="~/Obsidian", show_default=True,
              help="Where the user's Obsidian vault lives on the remote host.")
@click.option("--mount-point", default="",
              help="Optional SSHFS mount point on the laptop (for Obsidian).")
@click.option("--description", default="", help="Free-form note for `host list`.")
def host_add_cmd(
    name: str, ssh_host: str, remote_user: str,
    project_root: str, lab_vm_root: str, vault_root: str,
    mount_point: str, description: str,
) -> None:
    from .commands import host_cmd as _host_cmd
    raise SystemExit(_host_cmd.cmd_add(
        name=name, ssh_host=ssh_host, remote_user=remote_user,
        project_root=project_root, lab_vm_root=lab_vm_root, vault_root=vault_root,
        mount_point=mount_point, description=description,
    ))


@host_group.command("remove", help="Drop a host from the registry. 'local' cannot be removed.")
@click.argument("name")
def host_remove_cmd(name: str) -> None:
    from .commands import host_cmd as _host_cmd
    raise SystemExit(_host_cmd.cmd_remove(name))


@host_group.command("test", help="Probe SSH + wigamig + lab_vm + gh on a registered host.")
@click.argument("name")
def host_test_cmd(name: str) -> None:
    from .commands import host_cmd as _host_cmd
    raise SystemExit(_host_cmd.cmd_test(name))


# ---------------------------------------------------------------------------
# group
# ---------------------------------------------------------------------------


@cli.group("group", help="Manage group memberships.")
def group_group() -> None:
    pass


@group_group.command("list", help="List groups visible from your identity.")
def group_list() -> None:
    _stub()


@group_group.command("join", help="Request membership in a group.")
@click.argument("group")
def group_join(group: str) -> None:
    _stub()


@group_group.command("leave", help="Remove yourself from a group.")
@click.argument("group")
def group_leave(group: str) -> None:
    _stub()


# ---------------------------------------------------------------------------
# role
# ---------------------------------------------------------------------------


@cli.group("role", help="Manage group-level roles.")
def role_group() -> None:
    pass


@role_group.command("list", help="List roles and current operators.")
@click.option("--group", "group_name", default=None)
def role_list(group_name: str | None) -> None:
    _stub()


@role_group.command("describe", help="Print a role's charter and operators.")
@click.argument("role")
def role_describe(role: str) -> None:
    _stub()


@role_group.command("assign", help="(PI) Open a role-transition issue.")
@click.argument("role")
@click.argument("member")
def role_assign(role: str, member: str) -> None:
    _stub()


@role_group.command("revoke", help="(PI) Open a revoke issue.")
@click.argument("role")
@click.argument("member")
def role_revoke(role: str, member: str) -> None:
    _stub()


@role_group.command("transfer", help="(PI) Open a transfer issue.")
@click.argument("role")
@click.argument("from_member", metavar="FROM")
@click.argument("to_member", metavar="TO")
def role_transfer(role: str, from_member: str, to_member: str) -> None:
    _stub()


@role_group.command("ack", help="Acknowledge a proposed role assignment.")
@click.argument("issue")
def role_ack(issue: str) -> None:
    _stub()


# ---------------------------------------------------------------------------
# project
# ---------------------------------------------------------------------------


@cli.group("project", help="Manage projects.")
def project_group() -> None:
    pass


@project_group.command("list", help="List projects you are a member of.")
def project_list() -> None:
    project_cmd.cmd_list()


@project_group.command("describe", help="Print charter, MEMBERS, status.")
@click.argument("name")
def project_describe(name: str) -> None:
    project_cmd.cmd_describe(name)


@project_group.command("new", help="Create a new project.")
@click.argument("name")
@click.option("--charter", "charter_path", default=None, type=click.Path())
@click.option("--members", "members_list", required=True, help="Comma-separated handles.")
@click.option(
    "--sensitivity",
    type=click.Choice(["standard", "restricted", "clinical"]),
    default=None,
)
@click.option("--lead", default=None, help="Project lead handle (defaults to first member).")
@click.option("--description", default=None, help="One-paragraph charter body.")
@click.option("--choreography", default=None)
@click.option("--reb-number", "reb_number", default=None)
@click.option("--reb-expires", "reb_expires", default=None)
@click.option("--data-residency", "data_residency", default=None)
@click.option("--skip-github", is_flag=True, help="Skip the gh repo create + push step.")
@click.option(
    "--host",
    "host_name",
    default="local",
    show_default=True,
    help="Install target. 'local' = this laptop; any other registered host (see "
         "`wigamig host list`) scaffolds the project on that machine over SSH "
         "and leaves a remote-pointer placeholder in ~/repos/<name>/.",
)
def project_new(
    name: str,
    charter_path: str | None,
    members_list: str,
    sensitivity: str | None,
    lead: str | None,
    description: str | None,
    choreography: str | None,
    reb_number: str | None,
    reb_expires: str | None,
    data_residency: str | None,
    skip_github: bool,
    host_name: str,
) -> None:
    if host_name and host_name != "local":
        if charter_path is not None:
            raise click.ClickException(
                "--charter is not yet supported with --host; pass --description instead."
            )
        project_cmd.cmd_new_remote(
            name,
            host_name=host_name,
            members_csv=members_list,
            description=description,
            sensitivity=sensitivity,
            choreography=choreography,
            reb_number=reb_number,
            reb_expires=reb_expires,
            data_residency=data_residency,
            lead=lead,
            skip_github=skip_github,
        )
        return
    project_cmd.cmd_new(
        name,
        charter_path=charter_path,
        members_csv=members_list,
        description=description,
        sensitivity=sensitivity,
        choreography=choreography,
        reb_number=reb_number,
        reb_expires=reb_expires,
        data_residency=data_residency,
        lead=lead,
        skip_github=skip_github,
    )


@project_group.command("members", help="Print the MEMBERS file for a project.")
@click.argument("name")
def project_members(name: str) -> None:
    project_cmd.cmd_members(name)


@project_group.command("admit", help="(PI) Add a member to a project.")
@click.argument("name")
@click.argument("member")
def project_admit(name: str, member: str) -> None:
    project_cmd.cmd_admit(name, member)


@project_group.command("release", help="(PI) Remove a member from a project.")
@click.argument("name")
@click.argument("member")
def project_release(name: str, member: str) -> None:
    _stub()


@project_group.command("pause", help="(PI) Mark a project inactive.")
@click.argument("name")
def project_pause(name: str) -> None:
    _stub()


@project_group.command("resume", help="(PI) Mark a project active.")
@click.argument("name")
def project_resume(name: str) -> None:
    _stub()


@project_group.command("end", help="(PI) Terminal event for a project.")
@click.argument("name")
@click.option("--reason", required=True)
def project_end(name: str, reason: str) -> None:
    _stub()


@project_group.command("archive", help="(PI) Archive a project repo + data.")
@click.argument("name")
def project_archive(name: str) -> None:
    _stub()


@project_group.command("sensitivity", help="Read or change a project's sensitivity tier.")
@click.argument("name")
@click.option(
    "--set",
    "set_value",
    type=click.Choice(["standard", "restricted", "clinical"]),
    default=None,
)
def project_sensitivity(name: str, set_value: str | None) -> None:
    project_cmd.cmd_sensitivity(name, set_value)


@project_group.command("backfill",
                       help="Mirror existing CHARTER code-projects into the "
                            "cert-project registry (the authoritative model). "
                            "Idempotent; run once to migrate.")
def project_backfill() -> None:
    from .core import cert_projects as _cp
    try:
        names = _cp.backfill_from_charter()
    except _cp.CertProjectError as exc:
        raise click.ClickException(str(exc)) from exc
    if not names:
        click.echo("No CHARTER projects found under ~/repos to backfill.")
        return
    click.echo(f"✓ backfilled {len(names)} project(s) into the cert-project "
               f"registry: {', '.join(sorted(names))}")


@project_group.command("provision-slack",
                       help="(PI) Create the cert-project's private Slack channel "
                            "and invite its certified members. Idempotent; needs a "
                            "Slack bot token.")
@click.argument("name")
def project_provision_slack(name: str) -> None:
    from .core import cert_provision as _cprov
    try:
        out = _cprov.provision_slack(name)
    except _cprov.CertProvisionError as exc:
        raise click.ClickException(str(exc)) from exc
    if not out["ok"]:
        raise click.ClickException(
            f"could not create channel ({out.get('error')}): {out.get('detail')}")
    verb = "created + " if out["created"] else "reused; "
    click.echo(f"✓ channel {verb}synced ({out['channel_id']}).")
    if out["invited"]:
        click.echo(f"  invited: {', '.join(out['invited'])}")
    if out["already_in"]:
        click.echo(f"  already in: {', '.join(out['already_in'])}")
    for u in out["unresolved"]:
        click.echo(f"  ! {u.get('handle')}: {u.get('reason')}")


@project_group.command("provision-github",
                       help="(PI) Create the cert-project's private GitHub repo "
                            "and add its certified members as collaborators. "
                            "Idempotent; needs the gh CLI.")
@click.argument("name")
@click.option("--org", default="", help="GitHub org (default: lab.md github_org).")
def project_provision_github(name: str, org: str) -> None:
    from .core import cert_provision as _cprov
    try:
        out = _cprov.provision_github(name, org=org or None)
    except _cprov.CertProvisionError as exc:
        raise click.ClickException(str(exc)) from exc
    if not out["ok"]:
        raise click.ClickException(
            f"could not provision repo ({out.get('error')}): {out.get('detail')}")
    click.echo(f"✓ repo {out['repo']} ready.")
    for c in out["collaborators"]:
        mark = {"ok": "✓", "fail": "!", "no_github": "·"}.get(c.get("status"), "·")
        who = c.get("login") or c.get("handle")
        click.echo(f"  {mark} {c.get('handle')} → {who}: {c.get('detail', c.get('status'))}")


# ---------------------------------------------------------------------------
# experiment
# ---------------------------------------------------------------------------


@cli.group("experiment", help="Manage experiments inside a project.")
def experiment_group() -> None:
    pass


@experiment_group.command("new", help="Scaffold a new experiment folder.")
@click.option("--project", "project_name", required=True)
@click.option("--name", "exp_name", required=True)
@click.option(
    "--status",
    "status",
    default="planned",
    type=click.Choice(["planned", "running", "complete", "failed", "inconclusive"]),
)
@click.option(
    "--analysis-status",
    "analysis_status",
    default="not_started",
    type=click.Choice(["not_started", "examined", "concluded"]),
)
def experiment_new(project_name: str, exp_name: str, status: str, analysis_status: str) -> None:
    experiment_cmd.cmd_new(project_name, exp_name, status=status, analysis_status=analysis_status)


@experiment_group.command("list", help="List experiments and their statuses.")
@click.option("--project", "project_name", default=None)
def experiment_list(project_name: str | None) -> None:
    experiment_cmd.cmd_list(project_name)


@experiment_group.command("status", help="Update an experiment's notebook status.")
@click.argument("project_name")
@click.argument("slug")
@click.option("--set", "set_value", required=True)
def experiment_status(project_name: str, slug: str, set_value: str) -> None:
    experiment_cmd.cmd_status(project_name, slug, set_value)


@experiment_group.command("ingest", help="Classify and copy raw + derived files.")
@click.argument("project_name")
@click.argument("slug")
@click.argument("source", type=click.Path(exists=False))
@click.option("--instrument", default=None)
@click.option("--accept", is_flag=True)
@click.option("--dry-run", is_flag=True)
def experiment_ingest(
    project_name: str,
    slug: str,
    source: str,
    instrument: str | None,
    accept: bool,
    dry_run: bool,
) -> None:
    experiment_cmd.cmd_ingest(
        project_name,
        slug,
        source,
        instrument=instrument,
        accept=accept,
        dry_run=dry_run,
    )


@experiment_group.command("attach", help="Attach a documentation file to an experiment.")
@click.argument("project_name")
@click.argument("slug")
@click.argument("file_path", type=click.Path())
def experiment_attach(project_name: str, slug: str, file_path: str) -> None:
    _stub()


# ---------------------------------------------------------------------------
# squad
# ---------------------------------------------------------------------------


@cli.group("squad", help="Manage squads (subgroups).")
def squad_group() -> None:
    pass


@squad_group.command("form", help="Create a squad.")
@click.option("--scope", required=True, type=click.Choice(["project", "experiment", "sea"]))
@click.option("--target", required=True)
@click.option("--lead", required=True)
@click.option("--members", required=True)
def squad_form(scope: str, target: str, lead: str, members: str) -> None:
    _stub()


@squad_group.command("list", help="Browse squads.")
@click.option("--scope", default=None)
@click.option("--member", default=None)
def squad_list(scope: str | None, member: str | None) -> None:
    _stub()


@squad_group.command("describe", help="Print a squad's charter, lead, and members.")
@click.argument("name")
def squad_describe(name: str) -> None:
    _stub()


@squad_group.command("invite", help="Propose adding a member to a squad.")
@click.argument("name")
@click.argument("member")
def squad_invite(name: str, member: str) -> None:
    _stub()


@squad_group.command("release", help="Remove a member from a squad.")
@click.argument("name")
@click.argument("member")
def squad_release(name: str, member: str) -> None:
    _stub()


@squad_group.command("transfer-lead", help="Open a lead-transfer issue.")
@click.argument("name")
@click.argument("new_lead")
def squad_transfer_lead(name: str, new_lead: str) -> None:
    _stub()


@squad_group.command("dissolve", help="End a squad.")
@click.argument("name")
def squad_dissolve(name: str) -> None:
    _stub()


@squad_group.command("promote", help="Upgrade a squad's scope.")
@click.argument("name")
@click.option("--to", "new_scope", required=True)
def squad_promote(name: str, new_scope: str) -> None:
    _stub()


# ---------------------------------------------------------------------------
# sea (operational + finalisation)
# ---------------------------------------------------------------------------


@cli.group("sea", help="Manage SEAs (Skill / Experiment-as-event / Analysis).")
def sea_group() -> None:
    pass


@sea_group.command("request", help="File an SEA request.")
@click.option("--project", "project_name", default=None)
@click.option("--to", "to_target", required=True)
@click.option("--kind", required=True, type=click.Choice(["skill", "experiment", "analysis"]))
@click.option("--description", required=True)
def sea_request(project_name: str | None, to_target: str, kind: str, description: str) -> None:
    sea_cmd.cmd_request(
        project_name=project_name,
        to_target=to_target,
        kind=kind,
        description=description,
    )


@sea_group.command("list", help="Browse SEAs.")
@click.option("--project", "project_name", default=None)
@click.option("--mine", is_flag=True)
@click.option("--incoming", is_flag=True)
@click.option("--outgoing", is_flag=True)
def sea_list(project_name: str | None, mine: bool, incoming: bool, outgoing: bool) -> None:
    sea_cmd.cmd_list(project_name=project_name, mine=mine, incoming=incoming, outgoing=outgoing)


@sea_group.command("claim", help="Declare you'll perform an offered SEA.")
@click.argument("sea_id", type=int)
@click.option("--project", "project_name", default=None)
def sea_claim(sea_id: int, project_name: str | None) -> None:
    sea_cmd.cmd_claim(sea_id, project_name=project_name)


@sea_group.command("complete", help="Mark operational completion of an SEA.")
@click.argument("sea_id", type=int)
@click.option("--delivery", required=True, type=click.Path())
@click.option("--project", "project_name", default=None)
def sea_complete(sea_id: int, delivery: str, project_name: str | None) -> None:
    sea_cmd.cmd_complete(sea_id, delivery=delivery, project_name=project_name)


@sea_group.command("decline", help="Refuse an SEA with a reason.")
@click.argument("sea_id", type=int)
@click.option("--reason", required=True)
@click.option("--project", "project_name", default=None)
def sea_decline(sea_id: int, reason: str, project_name: str | None) -> None:
    sea_cmd.cmd_decline(sea_id, reason=reason, project_name=project_name)


@sea_group.command("examine", help="Trigger common agents to scaffold the deliberation doc.")
@click.argument("sea_id", type=int)
@click.option("--project", "project_name", default=None)
def sea_examine(sea_id: int, project_name: str | None) -> None:
    sea_cmd.cmd_examine(sea_id, project_name=project_name)


@sea_group.command("conclude", help="Close the deliberation; optionally promote a finding.")
@click.argument("sea_id", type=int)
@click.option("--statement", default=None, type=click.Path())
@click.option("--project", "project_name", default=None)
def sea_conclude(sea_id: int, statement: str | None, project_name: str | None) -> None:
    sea_cmd.cmd_conclude(sea_id, statement=statement, project_name=project_name)


@sea_group.command("reopen", help="Re-open a concluded deliberation.")
@click.argument("sea_id", type=int)
@click.option("--project", "project_name", default=None)
def sea_reopen(sea_id: int, project_name: str | None) -> None:
    sea_cmd.cmd_reopen(sea_id, project_name=project_name)


# ---------------------------------------------------------------------------
# experiment / project finalisation umbrella
# ---------------------------------------------------------------------------


@cli.command("finalize", help="Run examine then conclude end-to-end for a scope.")
@click.argument("scope", type=click.Choice(["sea", "experiment", "project"]))
@click.argument("target_id")
@click.option("--project", "project_name", default=None)
def finalize_cmd(scope: str, target_id: str, project_name: str | None) -> None:
    sea_cmd.cmd_finalize(scope, target_id, project_name=project_name)


# ---------------------------------------------------------------------------
# discuss
# ---------------------------------------------------------------------------


@cli.group("discuss", help="Record discussions and decisions.")
def discuss_group() -> None:
    pass


@discuss_group.command("new", help="Scaffold a discussion file.")
@click.option("--project", "project_name", required=True)
@click.option("--topic", required=True)
@click.option("--participants", default=None)
def discuss_new(project_name: str, topic: str, participants: str | None) -> None:
    _stub()


@discuss_group.command("list", help="Browse discussions.")
@click.option("--project", "project_name", default=None)
@click.option("--open", "open_only", is_flag=True)
def discuss_list(project_name: str | None, open_only: bool) -> None:
    _stub()


@discuss_group.command("close", help="Set the outcome on a discussion.")
@click.argument("discussion_id")
@click.option(
    "--outcome",
    required=True,
    type=click.Choice(["decided", "open", "blocked", "tabled"]),
)
@click.option("--decision", default=None)
def discuss_close(discussion_id: str, outcome: str, decision: str | None) -> None:
    _stub()


# ---------------------------------------------------------------------------
# teach
# ---------------------------------------------------------------------------


@cli.group("teach", help="Codify protocols and skills.")
def teach_group() -> None:
    pass


@teach_group.command("protocol", help="Scaffold a protocol.")
@click.option("--name", required=True)
@click.option("--scope", default="project", type=click.Choice(["project", "group", "center"]))
@click.option("--from-experiment", "from_experiment", nargs=2, default=None)
def teach_protocol(name: str, scope: str, from_experiment: tuple[str, str] | None) -> None:
    _stub()


@teach_group.command("skill", help="Scaffold a Claude Code skill.")
@click.option("--name", required=True)
@click.option("--scope", default="group", type=click.Choice(["group", "center"]))
def teach_skill(name: str, scope: str) -> None:
    _stub()


@teach_group.command("promote", help="Move a protocol or skill to a wider scope.")
@click.argument("name")
@click.option("--to", "new_scope", required=True)
def teach_promote(name: str, new_scope: str) -> None:
    _stub()


# ---------------------------------------------------------------------------
# freeze
# ---------------------------------------------------------------------------


@cli.group("freeze", help="Snapshot project state for citation.")
def freeze_group() -> None:
    pass


@freeze_group.command("create", help="Compute manifest, create tag, encrypt bundle.")
@click.argument("project_name")
@click.option("--purpose", required=True)
@click.option("--include-raw", is_flag=True)
def freeze_create(project_name: str, purpose: str, include_raw: bool) -> None:
    _stub()


@freeze_group.command("list", help="List past freezes for a project.")
@click.argument("project_name")
def freeze_list(project_name: str) -> None:
    _stub()


@freeze_group.command("restore", help="Extract a freeze to a temp location.")
@click.argument("project_name")
@click.argument("tag")
@click.option("--to", "destination", default=None, type=click.Path())
def freeze_restore(project_name: str, tag: str, destination: str | None) -> None:
    _stub()


# ---------------------------------------------------------------------------
# compliance / audit / secrets / breach
# ---------------------------------------------------------------------------


@cli.group("compliance", help="Compliance status and certification commands.")
def compliance_group() -> None:
    pass


@compliance_group.command("status", help="Show compliance state.")
@click.option("--project", "project_name", default=None)
def compliance_status(project_name: str | None) -> None:
    _stub()


@compliance_group.command("certify", help="Record a certification on your member profile.")
@click.argument("cert_name")
@click.option("--expires", required=True)
def compliance_certify(cert_name: str, expires: str) -> None:
    _stub()


@cli.group("audit", help="Audit log + adversary invocations.")
def audit_group() -> None:
    pass


@audit_group.command("verify", help="Walk the audit chain and verify signatures.")
@click.argument("repo_path")
def audit_verify(repo_path: str) -> None:
    _stub()


@audit_group.command("run", help="Invoke adversary on a path or PR.")
@click.argument("target")
def audit_run(target: str) -> None:
    _stub()


@cli.group("secret", help="Manage secrets.")
def secret_group() -> None:
    pass


@secret_group.command("rotate", help="Rotate a secret.")
@click.argument("scope", type=click.Choice(["personal", "group", "project"]))
@click.argument("name")
def secret_rotate(scope: str, name: str) -> None:
    _stub()


@cli.command("breach", help="Open a breach incident.")
@click.argument("project_name")
@click.option("--description", required=True)
def breach_cmd(project_name: str, description: str) -> None:
    _stub()


# ---------------------------------------------------------------------------
# dashboard
# ---------------------------------------------------------------------------


@cli.command("dashboard", help="Open the wigamig dashboard or print snapshots.")
@click.option("--pi", "pi_view", is_flag=True, help="Open PI view (rejected if not PI).")
@click.option("--snapshot", is_flag=True, help="Print the latest markdown snapshot.")
@click.option("--outstanding", is_flag=True, help="Print only the Outstanding panel.")
@click.option(
    "--hifi",
    is_flag=True,
    help="Launch the FastAPI hi-fi dashboard (Phase 0 of the redesign).",
)
@click.option("--host", default="127.0.0.1", show_default=True, help="Hi-fi server host.")
@click.option("--port", default=8770, show_default=True, type=int, help="Hi-fi server port.")
def dashboard_cmd(
    pi_view: bool,
    snapshot: bool,
    outstanding: bool,
    hifi: bool,
    host: str,
    port: int,
) -> None:
    dashboard_impl.cmd_dashboard(
        pi_view=pi_view,
        snapshot=snapshot,
        outstanding=outstanding,
        hifi=hifi,
        host=host,
        port=port,
    )


# ---------------------------------------------------------------------------
# day-to-day verbs (push, pull, cite, publish, request-sea, review, capture, triage)
# ---------------------------------------------------------------------------


@cli.command("push", help="Push current branch (or finalize via PR).")
@click.argument("project_name")
@click.option("--message", default=None)
@click.option("--finalize", is_flag=True)
@click.option("--topic", default=None, help="Personal-branch topic suffix (default: wip).")
@click.option(
    "--refined", default=None, help="Recompute checksums for an experiment's refined dir."
)
def push_cmd(
    project_name: str,
    message: str | None,
    finalize: bool,
    topic: str | None,
    refined: str | None,
) -> None:
    push_impl.cmd_push(
        project_name,
        message=message,
        finalize=finalize,
        refined=refined,
        topic=topic,
    )


@cli.command("pull", help="Fetch the latest project state.")
@click.argument("project_name")
def pull_cmd(project_name: str) -> None:
    push_impl.cmd_pull(project_name)


@cli.command("cite", help="Resolve and insert a citation.")
@click.argument("reference")
def cite_cmd(reference: str) -> None:
    _stub()


@cli.command("publish", help="Promote a finding to the group oracle.")
@click.argument("artefact", type=click.Path())
@click.option("--to", "destination", required=True)
def publish_cmd(artefact: str, destination: str) -> None:
    _stub()


@cli.command("request-sea", help="File an SEA request on the group request board.")
@click.option("--to", "to_target", required=True)
@click.option("--kind", required=True, type=click.Choice(["skill", "experiment", "analysis"]))
@click.option("--description", required=True)
def request_sea_cmd(to_target: str, kind: str, description: str) -> None:
    _stub()


@cli.command("review", help="Open a review session for a PR.")
@click.argument("pr_url")
def review_cmd(pr_url: str) -> None:
    _stub()


@cli.command("capture", help="Open inbox/<date>.md for a quick note.")
def capture_cmd() -> None:
    _stub()


@cli.command("triage", help="Process the inbox into structured notes.")
def triage_cmd() -> None:
    _stub()


# ---------------------------------------------------------------------------
# request (project-join, Phase 8)
# ---------------------------------------------------------------------------


@cli.group("request", help="File or manage project-join requests.")
def request_group() -> None:
    pass


@request_group.command("join", help="Ask the PI to admit you to a project.")
@click.argument("project")
@click.option("--reason", "justification", default="", help="Why you want in (visible to PI).")
def request_join_cmd(project: str, justification: str) -> None:
    from .core.identity import resolve as resolve_identity
    from .dashboard import request_actions

    actor = resolve_identity(allow_unknown=False).handle
    try:
        result = request_actions.file_join_request(
            actor=actor, project=project, justification=justification
        )
    except request_actions.RequestActionError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        f"Filed request #{result.request.id}: {result.request.requester} → {project}."
    )


@request_group.command("list", help="Browse requests (defaults to your own).")
@click.option("--all", "list_all", is_flag=True, help="(PI) show every pending request.")
def request_list_cmd(list_all: bool) -> None:
    from .core import requests as req_core
    from .core.identity import resolve as resolve_identity
    from .core.lab import pi_handle

    me = resolve_identity(allow_unknown=False).handle.lower()
    if list_all and me != pi_handle().lower():
        raise click.ClickException(
            f"--all is PI-only (lab PI per lab.md is @{pi_handle()})."
        )
    rows = req_core.iter_requests()
    if not list_all:
        rows = [r for r in rows if r.requester.lstrip("@").lower() == me]
    if not rows:
        click.echo("No requests match.")
        return
    console = Console()
    table = Table(title="Project-join requests")
    table.add_column("id", style="bold")
    table.add_column("requester")
    table.add_column("project")
    table.add_column("state")
    table.add_column("created")
    for r in rows:
        table.add_row(
            str(r.id), r.requester, r.project, r.state, r.created_at or "—"
        )
    console.print(table)


@request_group.command("approve", help="(PI) Approve a request — adds requester to MEMBERS.")
@click.argument("request_id", type=int)
def request_approve_cmd(request_id: int) -> None:
    from .core.identity import resolve as resolve_identity
    from .dashboard import request_actions

    actor = resolve_identity(allow_unknown=False).handle
    try:
        result = request_actions.apply_action(
            request_id=request_id, action="approve", actor=actor
        )
    except request_actions.RequestActionError as exc:
        raise click.ClickException(str(exc)) from exc
    r = result.request
    click.echo(
        f"Approved request #{r.id}. {r.requester} added to {r.project} "
        f"(commit + push to share)."
    )


@request_group.command("decline", help="(PI) Decline a request with a reason.")
@click.argument("request_id", type=int)
@click.option("--reason", required=True)
def request_decline_cmd(request_id: int, reason: str) -> None:
    from .core.identity import resolve as resolve_identity
    from .dashboard import request_actions

    actor = resolve_identity(allow_unknown=False).handle
    try:
        result = request_actions.apply_action(
            request_id=request_id, action="decline", actor=actor, reason=reason
        )
    except request_actions.RequestActionError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Declined request #{result.request.id}: {reason}")


# ---------------------------------------------------------------------------
# slack (Phase 11): mirror + distil
# ---------------------------------------------------------------------------


@cli.group("slack", help="Mirror Slack channels + distil to oracle drafts.")
def slack_group() -> None:
    pass


@slack_group.command("mirror", help="Fetch one channel, one day -> <lab-mgmt>/slack/.")
@click.option("--channel", "channel_name", required=True, help="Channel name (no leading #).")
@click.option("--channel-id", default=None, help="Slack channel id; auto-resolved if omitted.")
@click.option("--date", "date_iso", default=None, help="ISO date (default: yesterday).")
def slack_mirror_cmd(channel_name: str, channel_id: str | None, date_iso: str | None) -> None:
    import datetime as _dt
    from .core import slack_mirror as _sm
    from .core.lab import load_lab_config

    if date_iso:
        date = _dt.date.fromisoformat(date_iso)
    else:
        date = _dt.date.today() - _dt.timedelta(days=1)

    try:
        client = _sm.make_client()
    except _sm.SlackMirrorError as exc:
        raise click.ClickException(str(exc)) from exc

    if channel_id is None:
        # resolve via channel listing
        channels = _sm.list_monitored_channels(client)
        match = next((c for c in channels if c["name"] == channel_name), None)
        if match is None:
            raise click.ClickException(
                f"channel #{channel_name} not in [oracle:on] list. "
                f"Add the marker to its topic, or pass --channel-id."
            )
        channel_id = match["id"]

    try:
        path = _sm.mirror_channel_day(
            channel_name=channel_name,
            channel_id=channel_id,
            date=date,
            workspace=load_lab_config().slack_workspace or "",
            client=client,
        )
    except _sm.SlackMirrorError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Mirrored #{channel_name} {date.isoformat()} -> {path}")


@slack_group.command("distil", help="Distil one mirror file into oracle drafts.")
@click.option("--channel", "channel_name", required=True)
@click.option("--date", "date_iso", default=None, help="ISO date (default: yesterday).")
def slack_distil_cmd(channel_name: str, date_iso: str | None) -> None:
    import datetime as _dt
    from .core import slack_distill as _distill
    from .core import slack_mirror as _sm
    from .core.lab import load_lab_config

    if date_iso:
        date = _dt.date.fromisoformat(date_iso)
    else:
        date = _dt.date.today() - _dt.timedelta(days=1)
    mirror_path = _sm.mirror_path(channel_name, date)
    if not mirror_path.is_file():
        raise click.ClickException(
            f"no mirror at {mirror_path}; run `wigamig slack mirror` first."
        )

    try:
        result = _distill.distill_mirror(
            mirror_path=mirror_path,
            channel_name=channel_name,
            date=date,
            lab_name=load_lab_config().name,
        )
    except _distill.DistillError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        f"Distilled #{channel_name} {date.isoformat()}: "
        f"{len(result.drafts_written)} draft(s)."
    )
    for p in result.drafts_written:
        click.echo(f"  -> {p}")


# ---------------------------------------------------------------------------
# oracle (Phase 11 approval flow)
# ---------------------------------------------------------------------------


@cli.group("oracle", help="Manage oracle drafts and published entries.")
def oracle_group() -> None:
    pass


@oracle_group.command("drafts", help="List oracle entries awaiting approval.")
def oracle_drafts_cmd() -> None:
    from .core import slack_distill as _distill

    drafts = _distill.iter_drafts()
    if not drafts:
        click.echo("No drafts.")
        return
    console = Console()
    table = Table(title="Oracle drafts")
    table.add_column("slug", style="bold")
    table.add_column("title")
    for path in drafts:
        from .core.frontmatter import parse_file
        meta = parse_file(path).meta or {}
        table.add_row(path.name, str(meta.get("title", path.stem)))
    console.print(table)


@oracle_group.command("approve", help="(PI) Promote a draft to published.")
@click.argument("slug")
def oracle_approve_cmd(slug: str) -> None:
    from .core import slack_distill as _distill
    from .core.identity import resolve as resolve_identity
    from .core.lab import pi_handle
    from .core.repo import lab_mgmt_repo_root as _root

    actor = resolve_identity(allow_unknown=False).handle.lower()
    if actor != pi_handle().lower():
        raise click.ClickException(
            f"only the PI (@{pi_handle()}) can approve drafts."
        )
    path = _root() / "oracle" / (slug if slug.endswith(".md") else f"{slug}.md")
    try:
        _distill.approve_draft(path, approver=actor)
    except _distill.DistillError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Approved {path}")


@oracle_group.command("decline", help="(PI) Decline a draft with a reason.")
@click.argument("slug")
@click.option("--reason", required=True)
def oracle_decline_cmd(slug: str, reason: str) -> None:
    from .core import slack_distill as _distill
    from .core.identity import resolve as resolve_identity
    from .core.lab import pi_handle
    from .core.repo import lab_mgmt_repo_root as _root

    actor = resolve_identity(allow_unknown=False).handle.lower()
    if actor != pi_handle().lower():
        raise click.ClickException(
            f"only the PI (@{pi_handle()}) can decline drafts."
        )
    path = _root() / "oracle" / (slug if slug.endswith(".md") else f"{slug}.md")
    try:
        _distill.decline_draft(path, reason=reason)
    except _distill.DistillError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Declined {path}: {reason}")


# -- Personal-vault → Lab Oracle promotion (different flow than the
# Slack-distil one above; this one is initiated by the user, not by an
# automated Slack mirror).


@oracle_group.command("path", help="Print the personal Oracle dir on this machine.")
def oracle_path_cmd() -> None:
    """Used by the Oracle agent to resolve its vault without hardcoding
    a per-machine path."""
    from .core import oracle_publish as _op
    try:
        click.echo(str(_op.personal_oracle_dir()))
    except _op.OracleError as exc:
        raise click.ClickException(str(exc)) from exc


@oracle_group.command("vault-drafts", help="List personal-vault Oracle drafts awaiting publish.")
def oracle_vault_drafts_cmd() -> None:
    from .core import oracle_publish as _op
    try:
        drafts = _op.iter_vault_drafts()
    except _op.OracleError as exc:
        raise click.ClickException(str(exc)) from exc
    if not drafts:
        click.echo(f"No drafts in {_op.vault_drafts_dir()}")
        return
    console = Console()
    table = Table(title=f"Vault drafts ({_op.vault_drafts_dir()})")
    table.add_column("slug", style="bold")
    table.add_column("title")
    table.add_column("project")
    table.add_column("sensitivity")
    for path in drafts:
        from .core.frontmatter import parse_file
        meta = parse_file(path).meta or {}
        table.add_row(
            path.stem,
            str(meta.get("title", path.stem)),
            str(meta.get("project", "—")),
            str(meta.get("sensitivity", "—")),
        )
    console.print(table)


@oracle_group.command("publish", help="Publish a vault draft to the Lab Oracle.")
@click.argument("slug")
@click.option("--push/--no-push", default=False,
              help="Run `git push` after the commit (default: commit-only).")
@click.option("--dry-run", is_flag=True,
              help="Validate + copy, but skip git commit. Use to preview the result.")
def oracle_publish_cmd(slug: str, push: bool, dry_run: bool) -> None:
    """Promote a draft from <vault>/oracle/drafts/<slug>.md to the Lab
    Oracle. Refuses sensitivity=clinical|restricted entries.
    """
    from .core import oracle_publish as _op
    from .core.identity import resolve as resolve_identity

    try:
        committer = resolve_identity(allow_unknown=False).handle
    except Exception as exc:
        raise click.ClickException(
            f"could not resolve your handle (set WIGAMIG_USER): {exc}"
        ) from exc

    try:
        result = _op.publish_draft(
            slug, committer=committer, commit=not dry_run, push=push,
        )
    except _op.OracleError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"Published {result.source.name} → {result.target}")
    if result.commit_sha:
        click.echo(f"  commit:  {result.commit_sha}")
    if result.pushed:
        click.echo("  pushed:  yes")
    elif result.commit_sha:
        click.echo("  pushed:  no (re-run with --push or `git push` manually)")


# ---------------------------------------------------------------------------
# member (Phase 13: roster mgmt)
# ---------------------------------------------------------------------------


@cli.group("member", help="Manage the lab's member roster.")
def member_group() -> None:
    pass


@member_group.command("list", help="List every member with their status.")
def member_list_cmd() -> None:
    from .core import membership as _m
    members = _m.iter_members()
    if not members:
        click.echo("No members.")
        return
    console = Console()
    table = Table(title="Lab roster")
    table.add_column("handle", style="bold")
    table.add_column("full_name")
    table.add_column("role")
    table.add_column("status")
    for rec in members:
        table.add_row(
            f"@{rec.handle}", rec.full_name, rec.role, rec.status
        )
    console.print(table)


@member_group.command("add", help="(PI) Add a new member to the roster.")
@click.argument("handle")
@click.option("--full-name", required=True)
@click.option("--role", default="postdoc")
def member_add_cmd(handle: str, full_name: str, role: str) -> None:
    from .core import membership as _m
    from .core.identity import resolve as resolve_identity
    from .core.lab import pi_handle

    actor = resolve_identity(allow_unknown=False).handle.lower()
    if actor != pi_handle().lower():
        raise click.ClickException(f"Only the PI (@{pi_handle()}) can add members.")
    try:
        rec = _m.add(handle=handle, full_name=full_name, role=role)
    except _m.MembershipError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Added @{rec.handle} ({rec.full_name}, {rec.role}).")


@member_group.command("deactivate", help="(PI) Mark a member inactive.")
@click.argument("handle")
def member_deactivate_cmd(handle: str) -> None:
    from .core import membership as _m
    from .core.identity import resolve as resolve_identity
    from .core.lab import pi_handle

    actor = resolve_identity(allow_unknown=False).handle.lower()
    if actor != pi_handle().lower():
        raise click.ClickException(f"Only the PI (@{pi_handle()}) can deactivate members.")
    try:
        rec = _m.set_status(handle, _m.INACTIVE)
    except _m.MembershipError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Deactivated @{rec.handle}.")


@member_group.command("activate", help="(PI) Reactivate a previously-deactivated member.")
@click.argument("handle")
def member_activate_cmd(handle: str) -> None:
    from .core import membership as _m
    from .core.identity import resolve as resolve_identity
    from .core.lab import pi_handle

    actor = resolve_identity(allow_unknown=False).handle.lower()
    if actor != pi_handle().lower():
        raise click.ClickException(f"Only the PI (@{pi_handle()}) can activate members.")
    try:
        rec = _m.set_status(handle, _m.ACTIVE)
    except _m.MembershipError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Activated @{rec.handle}.")


# Register the `wigamig reconcile` subcommand. Kept at the bottom so
# it sees the fully-built `cli` group object.
reconcile_impl.add_to_cli(cli)
security_impl.add_to_cli(cli)

from .commands.calendar_cmd import core_calendar_auth as _core_calendar_auth
cli.add_command(_core_calendar_auth)

from .commands.reminders_cmd import core_remind as _core_remind
cli.add_command(_core_remind)

from .commands.invoice_cmd import core_invoice as _core_invoice
cli.add_command(_core_invoice)

from .commands.common_seas_cmd import common_sea as _common_sea
cli.add_command(_common_sea)

from .commands.broadcast_cmd import broadcast as _broadcast
cli.add_command(_broadcast)

from .commands.project_centre_cmd import centre_project as _centre_project
cli.add_command(_centre_project)

from .commands.centre_cmd import centre_init as _centre_init_cmd
from .commands.centre_cmd import centre_status as _centre_status_cmd
from .commands.centre_cmd import centre_slack_smoke as _centre_slack_smoke
from .commands.centre_cmd import centre_slack_setup as _centre_slack_setup
from .commands.centre_cmd import centre_age_keygen as _centre_age_keygen
from .commands.centre_cmd import centre_root_keygen as _centre_root_keygen
from .commands.centre_cmd import centre_set as _centre_set
from .commands.centre_cmd import onboard_check as _onboard_check
from .commands.centre_cmd import identity_card as _identity_card
from .commands.centre_cmd import identity_import as _identity_import
from .commands.centre_cmd import identity_init as _identity_init
from .commands.centre_cmd import whoami as _whoami
from .commands.init_cmd import init_command as _init_command
from .commands.centre_cmd import enroll as _enroll
from .commands.centre_cmd import issue_pi_card_cmd as _issue_pi_card_cmd
from .commands.centre_cmd import issue_member_card_cmd as _issue_member_card_cmd
from .commands.centre_cmd import issue_project_card_cmd as _issue_project_card_cmd
from .commands.centre_cmd import revoke_project_cmd as _revoke_project_cmd
from .commands.centre_cmd import import_signed_card_cmd as _import_signed_card_cmd
from .commands.centre_cmd import pi_init as _pi_init
from .commands.centre_cmd import revoke_cmd as _revoke_cmd
from .commands.centre_cmd import crl_cmd as _crl_cmd
from .commands.centre_cmd import centre_pin as _centre_pin
from .commands.centre_cmd import centre_hub_publish as _centre_hub_publish
from .commands.centre_cmd import group_setup as _group_setup
from .commands.centre_cmd import group_reconcile_cmd as _group_reconcile_cmd
from .commands.centre_cmd import group_remove_member as _group_remove_member
from .commands.centre_cmd import group_init_toolkit as _group_init_toolkit
from .commands.centre_cmd import join_request_group as _join_request_group
cli.add_command(_centre_init_cmd)
cli.add_command(_centre_status_cmd)
cli.add_command(_centre_slack_smoke)
cli.add_command(_centre_slack_setup)
cli.add_command(_centre_age_keygen)
cli.add_command(_centre_root_keygen)
cli.add_command(_centre_set)
cli.add_command(_onboard_check)
cli.add_command(_identity_card)
cli.add_command(_identity_import)
cli.add_command(_identity_init)
cli.add_command(_whoami)
cli.add_command(_init_command)
cli.add_command(_enroll)
cli.add_command(_issue_pi_card_cmd)
cli.add_command(_issue_member_card_cmd)
cli.add_command(_issue_project_card_cmd)
cli.add_command(_revoke_project_cmd)
cli.add_command(_import_signed_card_cmd)
cli.add_command(_pi_init)
cli.add_command(_revoke_cmd)
cli.add_command(_crl_cmd)
cli.add_command(_centre_pin)
cli.add_command(_centre_hub_publish)
cli.add_command(_group_setup)
cli.add_command(_group_reconcile_cmd)
cli.add_command(_group_remove_member)
cli.add_command(_group_init_toolkit)
cli.add_command(_join_request_group)


if __name__ == "__main__":  # pragma: no cover
    cli()
