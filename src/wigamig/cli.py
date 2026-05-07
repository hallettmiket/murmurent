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

import click
from rich.console import Console
from rich.table import Table

from . import __version__
from .core.agents import load_registry
from .core.repo import wigamig_repo_root

NOT_IMPLEMENTED_MSG = "not yet implemented in v1"


def _stub(*_args, **_kwargs) -> None:
    """Default body for v1-deferred subcommands."""
    click.echo(NOT_IMPLEMENTED_MSG)


@click.group(help="wigamig — group-level agentic infrastructure CLI.")
@click.version_option(__version__, prog_name="wigamig")
def cli() -> None:
    """Top-level entry point."""


# ---------------------------------------------------------------------------
# install / onboard / doctor / offboard
# ---------------------------------------------------------------------------


@cli.command("install", help="Install wigamig agents and configuration locally.")
def install_cmd() -> None:
    _stub()


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
    _stub()


@project_group.command("describe", help="Print charter, MEMBERS, status.")
@click.argument("name")
def project_describe(name: str) -> None:
    _stub()


@project_group.command("new", help="Create a new project.")
@click.argument("name")
@click.option("--charter", "charter_path", required=True, type=click.Path())
@click.option("--members", "members_list", required=True)
def project_new(name: str, charter_path: str, members_list: str) -> None:
    _stub()


@project_group.command("members", help="Print the MEMBERS file for a project.")
@click.argument("name")
def project_members(name: str) -> None:
    _stub()


@project_group.command("admit", help="(PI) Add a member to a project.")
@click.argument("name")
@click.argument("member")
def project_admit(name: str, member: str) -> None:
    _stub()


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
    _stub()


# ---------------------------------------------------------------------------
# experiment
# ---------------------------------------------------------------------------


@cli.group("experiment", help="Manage experiments inside a project.")
def experiment_group() -> None:
    pass


@experiment_group.command("new", help="Scaffold a new experiment folder.")
@click.option("--project", "project_name", required=True)
@click.option("--name", "exp_name", required=True)
def experiment_new(project_name: str, exp_name: str) -> None:
    _stub()


@experiment_group.command("list", help="List experiments and their statuses.")
@click.option("--project", "project_name", default=None)
def experiment_list(project_name: str | None) -> None:
    _stub()


@experiment_group.command("status", help="Update an experiment's notebook status.")
@click.argument("project_name")
@click.argument("slug")
@click.option("--set", "set_value", required=True)
def experiment_status(project_name: str, slug: str, set_value: str) -> None:
    _stub()


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
    _stub()


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
@click.option("--to", "to_target", required=True)
@click.option("--kind", required=True, type=click.Choice(["skill", "experiment", "analysis"]))
@click.option("--description", required=True)
def sea_request(to_target: str, kind: str, description: str) -> None:
    _stub()


@sea_group.command("list", help="Browse SEAs.")
@click.option("--mine", is_flag=True)
@click.option("--incoming", is_flag=True)
@click.option("--outgoing", is_flag=True)
def sea_list(mine: bool, incoming: bool, outgoing: bool) -> None:
    _stub()


@sea_group.command("claim", help="Declare you'll perform an offered SEA.")
@click.argument("sea_id")
def sea_claim(sea_id: str) -> None:
    _stub()


@sea_group.command("complete", help="Mark operational completion of an SEA.")
@click.argument("sea_id")
@click.option("--delivery", required=True, type=click.Path())
def sea_complete(sea_id: str, delivery: str) -> None:
    _stub()


@sea_group.command("decline", help="Refuse an SEA with a reason.")
@click.argument("sea_id")
@click.option("--reason", required=True)
def sea_decline(sea_id: str, reason: str) -> None:
    _stub()


@sea_group.command("examine", help="Trigger common agents to scaffold the deliberation doc.")
@click.argument("sea_id")
def sea_examine(sea_id: str) -> None:
    _stub()


@sea_group.command("conclude", help="Close the deliberation; optionally promote a finding.")
@click.argument("sea_id")
@click.option("--statement", default=None, type=click.Path())
def sea_conclude(sea_id: str, statement: str | None) -> None:
    _stub()


@sea_group.command("reopen", help="Re-open a concluded deliberation.")
@click.argument("sea_id")
def sea_reopen(sea_id: str) -> None:
    _stub()


# ---------------------------------------------------------------------------
# experiment / project finalisation umbrella
# ---------------------------------------------------------------------------


@cli.command("finalize", help="Run examine then conclude end-to-end for a scope.")
@click.argument("scope", type=click.Choice(["sea", "experiment", "projects"]))
@click.argument("target_id")
def finalize_cmd(scope: str, target_id: str) -> None:
    _stub()


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
def dashboard_cmd(pi_view: bool, snapshot: bool, outstanding: bool) -> None:
    _stub()


# ---------------------------------------------------------------------------
# day-to-day verbs (push, pull, cite, publish, request-sea, review, capture, triage)
# ---------------------------------------------------------------------------


@cli.command("push", help="Push current branch (or finalize via PR).")
@click.argument("project_name")
@click.option("--message", default=None)
@click.option("--finalize", is_flag=True)
@click.option(
    "--refined", default=None, help="Recompute checksums for an experiment's refined dir."
)
def push_cmd(project_name: str, message: str | None, finalize: bool, refined: str | None) -> None:
    _stub()


@cli.command("pull", help="Fetch the latest project state.")
@click.argument("project_name")
def pull_cmd(project_name: str) -> None:
    _stub()


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


if __name__ == "__main__":  # pragma: no cover
    cli()
