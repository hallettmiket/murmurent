"""
Purpose: Discover wigamig project repos and the lab-mgmt project registry.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-07
Input: Local filesystem (``~/repos`` by default), ``$WIGAMIG_PROJECTS_ROOT``,
       and the lab-mgmt repo's ``projects/`` index.
Output: Helpers that list projects a member belongs to and resolve a project's
        local repo path.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .charter import validate_charter
from .frontmatter import parse_file
from .repo import CHARTER_FILENAME, MEMBERS_FILENAME, ProjectRepo, lab_mgmt_repo_root, read_members

DEFAULT_PROJECTS_ROOT = Path("~/repos").expanduser()
PROJECTS_ROOT_ENV = "WIGAMIG_PROJECTS_ROOT"
PROJECT_REGISTRY_DIR = "projects"


@dataclass(frozen=True)
class ProjectSummary:
    """Lightweight summary of a project for listings."""

    name: str
    path: Path
    sensitivity: str
    lead: str
    members: tuple[str, ...]
    choreography: str | None
    # 2026-05-14: lab the project belongs to (e.g. "hallett", "vdumeaux").
    # Populated from CHARTER.md frontmatter; ``None`` means the charter
    # predates the field (treated as visible to every lab in callers).
    lab: str | None = None
    # Lifecycle status: "active" (default) or "archived". Archived projects
    # are excluded from the active dashboard list but still surface in the
    # "Decommissioned" section, and can be unarchived without touching the
    # underlying files. See core.decommission.
    status: str = "active"
    decommissioned_at: str | None = None
    decommissioned_by: str | None = None


def projects_root(env: dict[str, str] | None = None) -> Path:
    """Return ``~/repos`` (or ``$WIGAMIG_PROJECTS_ROOT``) — where local project repos live."""
    source = os.environ if env is None else env
    return Path(source.get(PROJECTS_ROOT_ENV, DEFAULT_PROJECTS_ROOT)).expanduser()


def project_path(name: str, env: dict[str, str] | None = None) -> Path:
    """Return the local path for project ``name`` (``~/repos/<name>``)."""
    return projects_root(env) / name


def find_project(name: str, env: dict[str, str] | None = None) -> ProjectRepo | None:
    """Return the local :class:`ProjectRepo` for ``name`` if it exists."""
    candidate = project_path(name, env)
    charter = candidate / CHARTER_FILENAME
    if not charter.is_file():
        return None
    members_path = candidate / MEMBERS_FILENAME
    return ProjectRepo(
        path=candidate,
        charter_path=charter,
        members_path=members_path if members_path.is_file() else None,
    )


def load_summary(repo: ProjectRepo) -> ProjectSummary:
    """Parse a project's CHARTER.md into a :class:`ProjectSummary`."""
    parsed = parse_file(repo.charter_path)
    validate_charter(parsed.meta, context=str(repo.charter_path))
    members_meta = parsed.meta.get("members") or []
    members_file = read_members(repo.members_path) if repo.members_path is not None else []
    # Prefer charter MEMBERS list; supplement with MEMBERS file (some operations
    # update the file ahead of the charter).
    seen: list[str] = []
    for handle in list(members_meta) + list(members_file):
        if handle not in seen:
            seen.append(handle)
    lab_value = parsed.meta.get("lab")
    status_value = str(parsed.meta.get("status") or "active").strip().lower() or "active"
    deco_at = parsed.meta.get("decommissioned_at")
    deco_by = parsed.meta.get("decommissioned_by")
    return ProjectSummary(
        name=str(parsed.meta.get("project", repo.path.name)),
        path=repo.path,
        sensitivity=str(parsed.meta["sensitivity"]),
        lead=str(parsed.meta["lead"]),
        members=tuple(seen),
        choreography=parsed.meta.get("choreography"),
        lab=str(lab_value) if lab_value else None,
        status=status_value,
        decommissioned_at=str(deco_at) if deco_at else None,
        decommissioned_by=str(deco_by) if deco_by else None,
    )


def iter_local_projects(env: dict[str, str] | None = None) -> list[ProjectRepo]:
    """Walk ``~/repos`` and return every immediate child that has a CHARTER.md."""
    root = projects_root(env)
    if not root.is_dir():
        return []
    found: list[ProjectRepo] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        charter = child / CHARTER_FILENAME
        if not charter.is_file():
            continue
        members_path = child / MEMBERS_FILENAME
        found.append(
            ProjectRepo(
                path=child,
                charter_path=charter,
                members_path=members_path if members_path.is_file() else None,
            )
        )
    return found


def projects_for_member(handle: str, env: dict[str, str] | None = None) -> list[ProjectSummary]:
    """Return summaries of projects whose MEMBERS list contains ``handle``.

    The handle is matched case-insensitively against both ``@handle`` and the
    bare form, since project charters are written with the ``@``-prefixed form
    while the env-supplied identity may not be.
    """
    norm = _normalize_handle(handle)
    out: list[ProjectSummary] = []
    for repo in iter_local_projects(env):
        try:
            summary = load_summary(repo)
        except Exception:
            continue
        for m in summary.members:
            if _normalize_handle(m) == norm:
                out.append(summary)
                break
    return out


def _normalize_handle(handle: str) -> str:
    return handle.strip().lstrip("@").lower()


def lab_mgmt_project_registry_path(name: str, env: dict[str, str] | None = None) -> Path:
    """Return the path to ``lab-mgmt-repo/projects/<name>.md``."""
    return lab_mgmt_repo_root(env) / PROJECT_REGISTRY_DIR / f"{name}.md"


REMOTE_POINTER_FILE = ".wigamig-remote-pointer"


def render_registry_entry(
    summary: ProjectSummary,
    *,
    today: str,
    host_name: str = "local",
    remote_path: str = "",
) -> str:
    """Render a markdown registry entry for ``lab-mgmt-repo/projects/<name>.md``.

    ``host_name`` defaults to ``"local"``; pass a registered host name
    (e.g. ``"biodatsci"``) when the working tree lives on a remote host.
    ``remote_path`` is the absolute path on that host and is required
    when ``host_name`` is anything other than ``"local"``.
    """
    members_yaml = "\n".join(f"  - {m!r}" for m in summary.members)
    chor_line = f"choreography: {summary.choreography}\n" if summary.choreography else ""
    host_lines = ""
    if host_name and host_name != "local":
        if not remote_path:
            raise ValueError("remote_path is required when host_name is non-local")
        host_lines = f"host: {host_name}\nremote_path: {remote_path}\n"
    return (
        "---\n"
        f"project: {summary.name}\n"
        f"path: {summary.path}\n"
        f"sensitivity: {summary.sensitivity}\n"
        f"lead: {summary.lead!r}\n"
        f"{chor_line}"
        f"{host_lines}"
        f"created: {today}\n"
        "members:\n"
        f"{members_yaml}\n"
        "---\n\n"
        f"# {summary.name}\n\n"
        "Auto-generated registry entry. Edit the project repo's `CHARTER.md` to change\n"
        "the canonical metadata; this file mirrors it for cross-project lookups.\n"
    )


def is_remote_pointer(project_dir: Path) -> bool:
    """True if ``project_dir`` is a remote-project pointer (no working tree).

    Remote-pointer dirs contain a single ``.wigamig-remote-pointer`` marker
    file alongside a CHARTER.md whose frontmatter carries ``host:`` and
    ``remote_path:``. Calls into git here would all fail; the dashboard
    surfaces them with a 🌐 chip and the "Open in VSCode" button generates
    a ``vscode-remote://ssh-remote+<host><path>`` URL instead.
    """
    return (project_dir / REMOTE_POINTER_FILE).is_file()


def read_remote_pointer(project_dir: Path) -> tuple[str, str] | None:
    """Return ``(host_name, remote_path)`` for a remote pointer, else ``None``.

    Reads CHARTER.md frontmatter. Returns ``None`` if the dir isn't a
    pointer, the charter is missing, or required fields are absent.
    """
    if not is_remote_pointer(project_dir):
        return None
    charter = project_dir / CHARTER_FILENAME
    if not charter.is_file():
        return None
    try:
        meta = parse_file(charter).meta
    except Exception:
        return None
    host = str(meta.get("host", "")).strip()
    remote_path = str(meta.get("remote_path", "")).strip()
    if not host or host == "local" or not remote_path:
        return None
    return host, remote_path


# ---------------------------------------------------------------------------
# Decommission (soft delete) — preserves files, flips status flags only
# ---------------------------------------------------------------------------


class ProjectNotFound(LookupError):
    """Raised when archive/unarchive can't locate the project on disk."""


def _set_charter_status(
    charter_path: Path,
    *,
    status: str,
    by_handle: str | None,
    timestamp: str | None,
) -> None:
    """Re-write CHARTER.md so its frontmatter reflects the new lifecycle state.

    Surgical edit: parse the existing frontmatter, mutate the relevant
    keys, re-serialise. We preserve key order to keep diffs readable.
    Body content is untouched. The dashboard's load_summary picks up the
    new status on next render.
    """
    import yaml as _yaml

    from .frontmatter import parse_file as _pf

    parsed = _pf(charter_path)
    meta = dict(parsed.meta or {})
    meta["status"] = status
    if status == "archived":
        if timestamp:
            meta["decommissioned_at"] = timestamp
        if by_handle:
            meta["decommissioned_by"] = by_handle
    else:
        meta.pop("decommissioned_at", None)
        meta.pop("decommissioned_by", None)

    front = _yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
    body = parsed.body or ""
    charter_path.write_text(f"---\n{front}\n---\n\n{body.lstrip()}", encoding="utf-8")


def _set_registry_status(
    name: str,
    *,
    status: str,
    by_handle: str | None,
    timestamp: str | None,
    env: dict[str, str] | None = None,
) -> None:
    """Mirror the status flip in ``lab_mgmt/projects/<name>.md`` if present.

    The lab-mgmt project registry file is the canonical cross-project
    lookup the dashboard consults. Keeping it in sync with CHARTER avoids
    "the project shows archived in one view, active in another."
    Missing file is a no-op (legacy projects without a registry entry).
    """
    import yaml as _yaml

    from .frontmatter import parse_file as _pf

    path = lab_mgmt_project_registry_path(name, env)
    if not path.is_file():
        return
    parsed = _pf(path)
    meta = dict(parsed.meta or {})
    meta["status"] = status
    if status == "archived":
        if timestamp:
            meta["decommissioned_at"] = timestamp
        if by_handle:
            meta["decommissioned_by"] = by_handle
    else:
        meta.pop("decommissioned_at", None)
        meta.pop("decommissioned_by", None)
    front = _yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
    body = parsed.body or ""
    path.write_text(f"---\n{front}\n---\n\n{body.lstrip()}", encoding="utf-8")


def archive_project(
    name: str,
    *,
    by_handle: str,
    rationale: str = "",
    env: dict[str, str] | None = None,
):
    """Soft-delete project ``name``: flip status flags, write a decommission report.

    Returns the path to the report on disk. Raises ``ProjectNotFound`` if
    the project has no CHARTER.md under ``~/repos/<name>``. The function
    is idempotent — re-running on an already-archived project rewrites
    the timestamp but doesn't error.

    No filesystem entries (working clone, lab-VM paths, Slack channel,
    GitHub repo) are deleted by this function. They appear in the report
    as a manual cleanup checklist for the user to review.
    """
    import datetime as _dt

    from .decommission import CleanupItem, DecommissionRecord, write_report

    repo = find_project(name, env)
    if repo is None:
        raise ProjectNotFound(f"no project named {name!r} under {projects_root(env)}")
    summary = load_summary(repo)

    now = _dt.datetime.now(_dt.timezone.utc).isoformat()
    actor = by_handle if by_handle.startswith("@") else f"@{by_handle.lstrip('@')}"

    _set_charter_status(repo.charter_path, status="archived",
                        by_handle=actor, timestamp=now)
    _set_registry_status(name, status="archived",
                         by_handle=actor, timestamp=now, env=env)

    # Build the cleanup checklist. Each entry is a path/URL/handle the
    # user may want to clean up by hand — wigamig never touches these.
    items: list[CleanupItem] = [
        CleanupItem(
            path=str(repo.path),
            note="Working clone on this machine. Move to an archive folder, delete, or leave in place.",
        ),
        CleanupItem(
            path=f"github.com/<org>/{name}",
            note="GitHub repo (if you published it). Consider archiving the repo on github.com.",
        ),
        CleanupItem(
            path=f"lab_base/raw/{name}",
            note="Raw data on the lab server. Usually retained per data-storage policy; review before deleting.",
            severity="private",
        ),
        CleanupItem(
            path=f"lab_base/refined/{name}",
            note="Refined outputs on the lab server. May contain analyses you want to keep or move aside.",
            severity="private",
        ),
        CleanupItem(
            path=f"proj-{name}",
            note="Slack channel. The bot can't archive channels itself; archive via the Slack UI when ready.",
        ),
    ]
    if summary.sensitivity == "clinical":
        items.append(CleanupItem(
            path=f"lab_base/repos/{name}.git",
            note="Private bare git remote (sensitive project). May still be cloned on other machines.",
            severity="private",
        ))

    record = DecommissionRecord(
        kind="project",
        name=name,
        decommissioned_by=actor,
        cleanup_items=items,
        rationale=rationale,
        extra_meta={"sensitivity": summary.sensitivity,
                    "lab": summary.lab or ""},
    )
    return write_report(record)


def unarchive_project(
    name: str,
    *,
    env: dict[str, str] | None = None,
) -> None:
    """Bring an archived project back. Flips status flags only.

    Idempotent — calling on an active project is a no-op. The original
    decommission report stays on disk as a historical record.
    """
    repo = find_project(name, env)
    if repo is None:
        raise ProjectNotFound(f"no project named {name!r} under {projects_root(env)}")
    _set_charter_status(repo.charter_path, status="active",
                        by_handle=None, timestamp=None)
    _set_registry_status(name, status="active",
                         by_handle=None, timestamp=None, env=env)
