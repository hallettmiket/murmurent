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
    return ProjectSummary(
        name=str(parsed.meta.get("project", repo.path.name)),
        path=repo.path,
        sensitivity=str(parsed.meta["sensitivity"]),
        lead=str(parsed.meta["lead"]),
        members=tuple(seen),
        choreography=parsed.meta.get("choreography"),
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
