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
    REMOTE_POINTER_FILE,
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
DASHBOARD_WORKFLOW_TEMPLATE = _TEMPLATES_DIR / "github_workflows" / "dashboard.yml"

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
    repo_kind: str = "github",
    local_repo_root: str | None = None,
    github_org: str = "hallettmiket",
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
                repo_kind=repo_kind,
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

    # Adversary-stub + dashboard GH Action workflows
    workflow_dir = repo_dir / ".github" / "workflows"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    for template, dest_name in (
        (ADVERSARY_STUB_TEMPLATE, "adversary_stub.yml"),
        (DASHBOARD_WORKFLOW_TEMPLATE, "dashboard.yml"),
    ):
        dest = workflow_dir / dest_name
        if not dest.exists() and template.is_file():
            dest.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")

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

    if not skip_github:
        if repo_kind == "local":
            if not local_repo_root:
                raise click.ClickException(
                    "cmd_new(repo_kind='local') requires --local-repo-root"
                )
            bare_path = Path(local_repo_root).expanduser() / f"{name}.git"
            ensure_remote(repo_dir, name, kind="local", bare_repo_path=bare_path)
        elif _gh_available():
            ensure_remote(repo_dir, name, kind="github", org=github_org)

    return summary


# ---------------------------------------------------------------------------
# Remote install (R2 — Item 3, phase R2)
# ---------------------------------------------------------------------------


def _shellquote(s: str) -> str:
    """Quote ``s`` for inclusion in a remote bash -lc command."""
    import shlex
    return shlex.quote(s)


def cmd_new_remote(
    name: str,
    *,
    host_name: str,
    members_csv: str,
    description: str | None = None,
    sensitivity: str | None = None,
    choreography: str | None = None,
    reb_number: str | None = None,
    reb_expires: str | None = None,
    data_residency: str | None = None,
    lead: str | None = None,
    skip_github: bool = False,
    github_org: str = "hallettmiket",
) -> str:
    """Create a project on a remote SSH host and leave a local pointer.

    Flow on the laptop:
      1. Resolve and probe the host.
      2. SSH the host and run ``wigamig project new <name> ...`` there,
         scaffolding the working tree + git init + GitHub remote + the
         host's own lab-VM dirs.
      3. Write a *remote-pointer* directory at ``~/repos/<name>/``: just a
         CHARTER.md (with ``host:`` + ``remote_path:`` frontmatter) and a
         ``.wigamig-remote-pointer`` marker. The dashboard's existing
         ``iter_local_projects`` picks this up and renders a 🌐 chip.
      4. Write the lab-mgmt registry entry with ``host:`` + ``remote_path:``.

    Returns the remote project path (``<project_root>/<name>`` on host).
    """
    from ..core import hosts as _hosts
    from ..core import remote as _remote

    members = [m.strip() for m in members_csv.split(",") if m.strip()]
    if not members:
        raise click.ClickException("--members must list at least one handle")
    if lead is None:
        lead = members[0]
    members = [_at(h) for h in members]
    lead = _at(lead)

    if sensitivity is None:
        raise click.ClickException(
            "--sensitivity is required for remote project creation"
        )

    try:
        host = _hosts.resolve(host_name)
    except _hosts.HostNotFound as exc:
        raise click.ClickException(
            f"{exc}. Register it first with `wigamig host add`."
        ) from exc
    if not host.is_remote():
        raise click.ClickException(
            f"host {host_name!r} is local; use `wigamig project new` (no --host) instead."
        )

    rclient = _remote.Remote(host)
    probe = rclient.probe()
    if not probe.ok:
        raise click.ClickException(
            f"cannot reach host {host_name!r} ({host.ssh_host}): "
            f"{probe.stderr.strip() or 'ssh failed'}. Check ~/.ssh/config."
        )

    # Build the remote `wigamig project new` invocation.
    remote_argv = [
        "wigamig", "project", "new", _shellquote(name),
        "--members", _shellquote(",".join(members)),
        "--sensitivity", _shellquote(sensitivity),
        "--lead", _shellquote(lead),
    ]
    if description:    remote_argv += ["--description", _shellquote(description)]
    if choreography:   remote_argv += ["--choreography", _shellquote(choreography)]
    if reb_number:     remote_argv += ["--reb-number", _shellquote(reb_number)]
    if reb_expires:    remote_argv += ["--reb-expires", _shellquote(reb_expires)]
    if data_residency: remote_argv += ["--data-residency", _shellquote(data_residency)]
    if skip_github:    remote_argv += ["--skip-github"]
    cmd = " ".join(remote_argv)
    click.echo(f"→ creating project on {host_name} (this may take a moment)…")
    try:
        result = rclient.run(cmd, timeout=180)
    except _remote.RemoteError as exc:
        raise click.ClickException(
            f"remote wigamig failed on {host_name!r} (rc={exc.returncode}):\n"
            f"{exc.stderr.strip() or exc.stdout.strip() or 'no output'}"
        ) from exc
    click.echo(result.stdout.rstrip() or f"  (no stdout from remote wigamig)")

    remote_path = f"{host.project_root.rstrip('/')}/{name}"

    # Local pointer dir — minimal, no git.
    pointer_dir = project_path(name)
    if pointer_dir.exists():
        if not (pointer_dir / REMOTE_POINTER_FILE).is_file():
            raise click.ClickException(
                f"{pointer_dir} already exists and is not a remote pointer; refusing to overwrite."
            )
    pointer_dir.mkdir(parents=True, exist_ok=True)
    (pointer_dir / REMOTE_POINTER_FILE).write_text(
        f"# wigamig remote project pointer\n"
        f"# host: {host_name}\n"
        f"# remote_path: {remote_path}\n"
        f"# Do not run git here — the working tree lives on {host_name}.\n",
        encoding="utf-8",
    )
    summary = _shadow_summary(
        name=name, members=members, lead=lead, sensitivity=sensitivity,
        choreography=choreography, local_path=pointer_dir,
    )
    charter_text = render_charter(
        project=name, lead=lead, members=members,
        sensitivity=sensitivity,
        description=description or f"Project {name} (hosted on {host_name}).",
        choreography=choreography,
        reb_number=reb_number, reb_expires=reb_expires,
        data_residency=data_residency,
        created=_today(),
        repo_kind="github",
    )
    # Splice the host + remote_path into the rendered charter frontmatter.
    if "---\n" in charter_text:
        head, sep, rest = charter_text.partition("---\n")
        body, sep2, tail = rest.partition("---\n")
        body = body + f"host: {host_name}\nremote_path: {remote_path}\n"
        charter_text = head + sep + body + sep2 + tail
    (pointer_dir / "CHARTER.md").write_text(charter_text, encoding="utf-8")

    # Lab-mgmt registry entry with host fields.
    registry_path = lab_mgmt_project_registry_path(name)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        render_registry_entry(
            summary, today=_today(),
            host_name=host_name, remote_path=remote_path,
        ),
        encoding="utf-8",
    )

    click.echo(
        f"Project {name!r} created on {host_name} at {remote_path}.\n"
        f"Open in VSCode Remote-SSH:  vscode-remote://ssh-remote+{host.ssh_host}{remote_path}"
    )
    return remote_path


def _shadow_summary(
    *,
    name: str,
    members: list[str],
    lead: str,
    sensitivity: str,
    choreography: str | None,
    local_path: Path,
) -> ProjectSummary:
    """Build a :class:`ProjectSummary` for a remote pointer."""
    return ProjectSummary(
        name=name, path=local_path,
        sensitivity=sensitivity, lead=lead,
        members=tuple(members), choreography=choreography,
    )


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


def _set_origin_and_push(repo_dir: Path, remote_url: str) -> None:
    """Set ``origin`` to ``remote_url`` (add or update) and push main.

    Common tail for both ``github`` and ``local`` provisioning — only
    the URL form differs.
    """
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


def _ensure_origin_and_push(repo_dir: Path, name: str, *, org: str = "hallettmiket") -> None:
    """Legacy GitHub-specific entry point. Kept for callers that haven't
    migrated to :func:`ensure_remote` yet."""
    _set_origin_and_push(repo_dir, f"git@github.com:{org}/{name}.git")


def ensure_remote(
    repo_dir: Path,
    name: str,
    *,
    kind: str = "github",
    org: str = "hallettmiket",
    bare_repo_path: Path | str | None = None,
) -> str | None:
    """Provision the project's git origin and push, kind-aware.

    Returns the URL that was set as ``origin`` (so callers can persist
    it in CHARTER.md). Returns ``None`` if provisioning was skipped
    (e.g. ``kind="github"`` but ``gh`` CLI is missing).

    - ``kind="github"``: ``gh repo create <org>/<name>`` (idempotent),
      then ``origin = git@github.com:<org>/<name>.git``.
    - ``kind="local"``: ``git init --bare <bare_repo_path>`` (idempotent),
      then ``origin = <bare_repo_path>``.
    """
    if kind == "github":
        if not _gh_available():
            return None
        _ensure_github_repo(name, org=org)
        url = f"git@github.com:{org}/{name}.git"
        _set_origin_and_push(repo_dir, url)
        return url

    if kind == "local":
        if bare_repo_path is None:
            raise ValueError("ensure_remote(kind='local') requires bare_repo_path")
        bare = Path(bare_repo_path).expanduser()
        bare.parent.mkdir(parents=True, exist_ok=True)
        # ``git init --bare`` is idempotent: re-running on an existing
        # bare repo prints "Reinitialized…" and leaves it alone.
        if not (bare / "HEAD").exists():
            subprocess.run(
                ["git", "init", "--bare", str(bare)], check=False
            )
        _set_origin_and_push(repo_dir, str(bare))
        return str(bare)

    raise ValueError(f"unknown repo kind: {kind!r}")
