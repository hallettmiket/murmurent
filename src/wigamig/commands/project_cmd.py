"""
Purpose: Implementations of ``wigamig project ...`` subcommands.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-07
Input: CLI arguments forwarded from :mod:`wigamig.cli`.
Output: Side effects on the local project repo + lab-mgmt registry; messages
        to stdout/stderr.
"""

from __future__ import annotations

import datetime as _dt
import shutil
import subprocess
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.table import Table

from ..core import lab_vm
from ..core.charter import (
    VALID_SENSITIVITY_TIERS,
    CharterError,
    render_charter,
    render_members_file,
    validate_charter,
)
from ..core.frontmatter import parse_file
from ..core.identity import resolve as resolve_identity
from ..core.projects import (
    ProjectSummary,
    find_project,
    iter_local_projects,
    lab_mgmt_project_registry_path,
    load_summary,
    project_path,
    projects_for_member,
    render_registry_entry,
)
from ..core.repo import MEMBERS_FILENAME, lab_mgmt_repo_root, read_members, require_project_repo

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent.parent / "templates"
ADVERSARY_STUB_TEMPLATE = _TEMPLATES_DIR / "github_workflows" / "adversary_stub.yml"

PROJECT_SUBDIRS = (
    "exp",
    "src",
    "src/protocols",
    "src/literature",
    "findings",
    "obsolete",
    "data",
    "seas",
    "deliberations",
)


def _today() -> str:
    return _dt.date.today().isoformat()


def _gh_available() -> bool:
    return shutil.which("gh") is not None


def cmd_list() -> int:
    """``wigamig project list`` — projects the current user is a member of."""
    identity = resolve_identity(allow_unknown=True)
    summaries = projects_for_member(identity.handle)
    if not summaries:
        click.echo(
            f"No projects found for @{identity.handle}. "
            "Create one with `wigamig project new` or check your handle."
        )
        return 0
    console = Console()
    table = Table(title=f"Projects for @{identity.handle}")
    table.add_column("name", style="bold")
    table.add_column("sensitivity")
    table.add_column("lead")
    table.add_column("members")
    for s in summaries:
        table.add_row(s.name, s.sensitivity, s.lead, ", ".join(s.members))
    console.print(table)
    return 0


def cmd_describe(name: str) -> int:
    """``wigamig project describe <name>`` — print charter, MEMBERS, status."""
    repo = find_project(name)
    if repo is None:
        raise click.ClickException(f"Project not found locally: {name}")
    parsed = parse_file(repo.charter_path)
    try:
        validate_charter(parsed.meta, context=str(repo.charter_path))
    except CharterError as exc:
        click.echo(f"WARNING: {exc}", err=True)
    summary = load_summary(repo)

    click.echo(f"# {summary.name}")
    click.echo(f"path:        {summary.path}")
    click.echo(f"sensitivity: {summary.sensitivity}")
    click.echo(f"lead:        {summary.lead}")
    if summary.choreography:
        click.echo(f"choreography: {summary.choreography}")
    if summary.sensitivity == "clinical":
        click.echo(f"reb_number:   {parsed.meta.get('reb_number')}")
        click.echo(f"reb_expires:  {parsed.meta.get('reb_expires')}")
        click.echo(f"data_residency: {parsed.meta.get('data_residency')}")
    click.echo(f"members ({len(summary.members)}):")
    for h in summary.members:
        click.echo(f"  - {h}")
    body = parsed.body.strip()
    if body:
        click.echo("")
        click.echo(body)
    return 0


def cmd_new(
    name: str,
    *,
    charter_path: str | None,
    members_csv: str,
    description: str | None = None,
    sensitivity: str | None = None,
    choreography: str | None = None,
    reb_number: str | None = None,
    reb_expires: str | None = None,
    data_residency: str | None = None,
    lead: str | None = None,
    skip_github: bool = False,
) -> ProjectSummary:
    """``wigamig project new`` — scaffold the local project repo + GitHub repo.

    The function is reusable so the seed script can call it directly.
    """
    members = [m.strip() for m in members_csv.split(",") if m.strip()]
    if not members:
        raise click.ClickException("--members must list at least one handle")
    if lead is None:
        lead = members[0]
    members = [_at(h) for h in members]
    lead = _at(lead)

    try:
        if charter_path is not None and Path(charter_path).is_file():
            existing = parse_file(charter_path)
            meta = dict(existing.meta)
            meta.setdefault("project", name)
            meta.setdefault("members", members)
            meta.setdefault("lead", lead)
            if sensitivity:
                meta["sensitivity"] = sensitivity
            if choreography:
                meta["choreography"] = choreography
            if reb_number:
                meta["reb_number"] = reb_number
            if reb_expires:
                meta["reb_expires"] = reb_expires
            if data_residency:
                meta["data_residency"] = data_residency
            validate_charter(meta, context=str(charter_path))
            body = existing.body or f"# {name}\n\nProject charter for {name}.\n"
            charter_text = _serialize_charter(meta, body)
        else:
            if sensitivity is None:
                raise click.ClickException("--sensitivity (or a charter file) is required")
            body_text = description or (
                f"Project {name}. Edit this charter to describe scope, deliverables, and "
                "the choreography in effect."
            )
            charter_text = render_charter(
                project=name,
                lead=lead,
                members=members,
                sensitivity=sensitivity,
                description=body_text,
                choreography=choreography,
                reb_number=reb_number,
                reb_expires=reb_expires,
                data_residency=data_residency,
                created=_today(),
            )
    except CharterError as exc:
        raise click.ClickException(str(exc)) from exc

    repo_dir = project_path(name)
    repo_dir.mkdir(parents=True, exist_ok=True)
    for sub in PROJECT_SUBDIRS:
        (repo_dir / sub).mkdir(parents=True, exist_ok=True)
        gitkeep = repo_dir / sub / ".gitkeep"
        if not any((repo_dir / sub).iterdir()):
            gitkeep.write_text("", encoding="utf-8")

    charter_file = repo_dir / "CHARTER.md"
    if not charter_file.exists():
        charter_file.write_text(charter_text, encoding="utf-8")

    members_file = repo_dir / MEMBERS_FILENAME
    if not members_file.exists():
        members_file.write_text(render_members_file(members), encoding="utf-8")

    readme = repo_dir / "README.md"
    if not readme.exists():
        readme.write_text(
            f"# {name}\n\nWigamig project. See `CHARTER.md` for scope and `MEMBERS` for access.\n",
            encoding="utf-8",
        )

    # Adversary-stub GH Action workflow
    workflow_dir = repo_dir / ".github" / "workflows"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    workflow_dest = workflow_dir / "adversary_stub.yml"
    if not workflow_dest.exists() and ADVERSARY_STUB_TEMPLATE.is_file():
        workflow_dest.write_text(
            ADVERSARY_STUB_TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8"
        )

    # Lab-VM dirs
    lab_vm.project_raw_dir(name).mkdir(parents=True, exist_ok=True)
    lab_vm.project_refined_dir(name).mkdir(parents=True, exist_ok=True)

    # Local git init + initial commit (idempotent)
    if not (repo_dir / ".git").is_dir():
        subprocess.run(["git", "init", "-b", "main"], cwd=str(repo_dir), check=True)
    if _git_has_changes(repo_dir):
        subprocess.run(["git", "add", "-A"], cwd=str(repo_dir), check=True)
        subprocess.run(
            ["git", "commit", "-m", f"seed project {name}"],
            cwd=str(repo_dir),
            check=True,
        )

    # Lab-mgmt registry entry
    repo = find_project(name)
    if repo is None:
        raise click.ClickException(f"Internal error: project {name} not visible after creation.")
    summary = load_summary(repo)
    registry_path = lab_mgmt_project_registry_path(name)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    if not registry_path.exists():
        registry_path.write_text(render_registry_entry(summary, today=_today()), encoding="utf-8")

    if not skip_github and _gh_available():
        _ensure_github_repo(name)
        _ensure_origin_and_push(repo_dir, name)

    return summary


def cmd_admit(name: str, member: str) -> int:
    """``wigamig project admit <name> <member>``: append to MEMBERS + open PR.

    For the smoke test we apply changes locally on a feature branch and then ask
    the user (or seed script) to run ``wigamig push --finalize`` for a PR. v1
    keeps the operation simple: we update CHARTER members + the MEMBERS file
    on a topic branch and commit; PR opening is deferred to phase 3.
    """
    repo = require_project_repo(project_path(name))
    parsed = parse_file(repo.charter_path)
    members = [str(h) for h in parsed.meta.get("members") or []]
    handle = _at(member)
    if handle in members:
        click.echo(f"@{handle.lstrip('@')} is already a member of {name}.")
        return 0

    members.append(handle)
    parsed.meta["members"] = members
    repo.charter_path.write_text(_serialize_charter(parsed.meta, parsed.body), encoding="utf-8")

    members_path = repo.path / MEMBERS_FILENAME
    members_path.write_text(render_members_file(members), encoding="utf-8")

    click.echo(f"Updated {repo.charter_path} and {members_path} (added {handle}).")
    click.echo(
        "Run `wigamig push --finalize` (phase 3) to open the admit PR. "
        "For the smoke test, commit the change locally for now."
    )
    return 0


def cmd_sensitivity(name: str, set_value: str | None) -> int:
    """``wigamig project sensitivity <name> [--set <tier>]``."""
    repo = find_project(name)
    if repo is None:
        raise click.ClickException(f"Project not found locally: {name}")
    parsed = parse_file(repo.charter_path)
    current = parsed.meta.get("sensitivity")
    if set_value is None:
        click.echo(current)
        return 0
    if set_value not in VALID_SENSITIVITY_TIERS:
        raise click.ClickException(
            f"--set must be one of {VALID_SENSITIVITY_TIERS!r}; got {set_value!r}"
        )
    parsed.meta["sensitivity"] = set_value
    if set_value == "clinical":
        for required in ("reb_number", "reb_expires", "data_residency"):
            if required not in parsed.meta:
                raise click.ClickException(
                    f"raising to clinical requires {required} in CHARTER.md; "
                    "edit the charter and re-run."
                )
    try:
        validate_charter(parsed.meta, context=str(repo.charter_path))
    except CharterError as exc:
        raise click.ClickException(str(exc)) from exc
    repo.charter_path.write_text(_serialize_charter(parsed.meta, parsed.body), encoding="utf-8")
    click.echo(f"Sensitivity for {name}: {current} -> {set_value}")
    return 0


def cmd_members(name: str) -> int:
    """``wigamig project members <name>`` — print MEMBERS file content."""
    repo = find_project(name)
    if repo is None:
        raise click.ClickException(f"Project not found locally: {name}")
    if repo.members_path is None:
        raise click.ClickException(f"No MEMBERS file in {repo.path}")
    for h in read_members(repo.members_path):
        click.echo(h)
    return 0


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _at(handle: str) -> str:
    handle = handle.strip()
    return handle if handle.startswith("@") else f"@{handle}"


def _serialize_charter(meta: dict[str, Any], body: str) -> str:
    """Re-emit a charter file with deterministic frontmatter ordering.

    Keep the design's preferred ordering: project, lead, sensitivity,
    choreography, REB block, created, members.
    """
    ordered: list[tuple[str, Any]] = []
    for key in (
        "project",
        "lead",
        "sensitivity",
        "choreography",
        "reb_number",
        "reb_expires",
        "data_residency",
        "created",
    ):
        if key in meta and meta[key] is not None:
            ordered.append((key, meta[key]))
    members = meta.get("members") or []

    lines = ["---"]
    for key, value in ordered:
        if isinstance(value, str):
            if key in {"lead"}:
                lines.append(f"{key}: {value!r}")
            else:
                lines.append(f"{key}: {value}")
        else:
            lines.append(f"{key}: {value}")
    lines.append("members:")
    for h in members:
        lines.append(f"  - {h!r}")
    lines.append("---")
    body_text = body.lstrip("\n")
    if body_text and not body_text.endswith("\n"):
        body_text += "\n"
    return "\n".join(lines) + "\n\n" + body_text


def _git_has_changes(repo_dir: Path) -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(repo_dir),
        check=True,
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip())


def _ensure_github_repo(name: str, *, org: str = "hallettmiket") -> None:
    """Idempotent ``gh repo create --private`` wrapper."""
    if not _gh_available():
        return
    view = subprocess.run(
        ["gh", "repo", "view", f"{org}/{name}", "--json", "name"],
        check=False,
        capture_output=True,
        text=True,
    )
    if view.returncode == 0:
        return
    subprocess.run(
        [
            "gh",
            "repo",
            "create",
            f"{org}/{name}",
            "--private",
            "--description",
            f"Wigamig project {name} (smoke-test seed).",
        ],
        check=False,
    )


def _ensure_origin_and_push(repo_dir: Path, name: str, *, org: str = "hallettmiket") -> None:
    remote_url = f"git@github.com:{org}/{name}.git"
    existing = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=str(repo_dir),
        check=False,
        capture_output=True,
        text=True,
    )
    if existing.returncode != 0:
        subprocess.run(
            ["git", "remote", "add", "origin", remote_url], cwd=str(repo_dir), check=False
        )
    elif existing.stdout.strip() != remote_url:
        subprocess.run(
            ["git", "remote", "set-url", "origin", remote_url],
            cwd=str(repo_dir),
            check=False,
        )
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=str(repo_dir), check=False)
