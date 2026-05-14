"""
Purpose: Discover wigamig repos and the active project on disk.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-06
Input: Filesystem (current working directory, ``$WIGAMIG_REPO_ROOT``,
       ``$WIGAMIG_LAB_MGMT_REPO``).
Output: Helpers that locate the wigamig repo, the lab-management repo, and the
        active project repo (the nearest ancestor containing ``CHARTER.md``).
"""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

CHARTER_FILENAME = "CHARTER.md"
MEMBERS_FILENAME = "MEMBERS"
DEFAULT_WIGAMIG_REPO = Path("~/repos/wigamig").expanduser()
# 2026-05-14: repo is being renamed from "hallett-lab-mgmt" to the per-group
# convention "lab_mgmt". During the transition we prefer the new path but
# fall back to the legacy name so existing clones keep working.
DEFAULT_LAB_MGMT_REPO = Path("~/repos/lab_mgmt").expanduser()
LEGACY_LAB_MGMT_REPO  = Path("~/repos/hallett-lab-mgmt").expanduser()

# Per-request lab-mgmt override. FastAPI dispatches sync handlers into a
# threadpool, so thread-local state is request-scoped without env-var
# contention. When a request resolves the viewer's lab (e.g. vdumeaux),
# the dashboard sets this override so every downstream call to
# ``lab_mgmt_repo_root()`` returns that lab's repo for the duration of
# the request. See ``use_lab_mgmt_root`` below.
_thread_local = threading.local()


class RepoDiscoveryError(RuntimeError):
    """Raised when an expected repo or marker cannot be located."""


@dataclass(frozen=True)
class ProjectRepo:
    """The active project repo discovered by walking up from a starting path."""

    path: Path
    charter_path: Path
    members_path: Path | None


def wigamig_repo_root(env: dict[str, str] | None = None) -> Path:
    """Resolve the wigamig repo root, honouring ``$WIGAMIG_REPO_ROOT`` if set."""
    env = os.environ if env is None else env
    return Path(env.get("WIGAMIG_REPO_ROOT", DEFAULT_WIGAMIG_REPO)).expanduser()


def lab_mgmt_repo_root(env: dict[str, str] | None = None) -> Path:
    """Resolve the lab-management repo root.

    Resolution order:
      1. Thread-local override set by ``use_lab_mgmt_root()`` — used by the
         FastAPI dashboard to point each request at the viewer's own lab
         (so @vdumeaux sees her lab_mgmt, @mhallet sees his).
      2. ``$WIGAMIG_LAB_MGMT_REPO`` env var
      3. ``~/repos/lab_mgmt`` if it exists
      4. ``~/repos/hallett-lab-mgmt`` (legacy fallback) if it exists
      5. ``~/repos/lab_mgmt`` (the canonical default, even if missing)
    """
    override = getattr(_thread_local, "lab_mgmt_root", None)
    if override is not None:
        return Path(override).expanduser()
    env = os.environ if env is None else env
    explicit = env.get("WIGAMIG_LAB_MGMT_REPO")
    if explicit:
        return Path(explicit).expanduser()
    if DEFAULT_LAB_MGMT_REPO.exists():
        return DEFAULT_LAB_MGMT_REPO
    if LEGACY_LAB_MGMT_REPO.exists():
        return LEGACY_LAB_MGMT_REPO
    return DEFAULT_LAB_MGMT_REPO


@contextmanager
def use_lab_mgmt_root(path: str | Path | None):
    """Override ``lab_mgmt_repo_root()`` for the calling thread.

    Used by per-request dashboard handlers: at request entry the server
    resolves the viewer's lab via the registrar's ``_registry.yaml`` and
    enters this context manager, then every downstream call to
    ``iter_members()`` / ``members_dir()`` / ``compliance.md`` / etc.
    automatically resolves to that lab's lab_mgmt repo. Pass ``None`` to
    fall through to the env-var / default resolution.
    """
    previous = getattr(_thread_local, "lab_mgmt_root", None)
    _thread_local.lab_mgmt_root = Path(path).expanduser() if path else None
    try:
        yield
    finally:
        _thread_local.lab_mgmt_root = previous


def find_project_repo(start: str | Path | None = None) -> ProjectRepo | None:
    """Walk up from ``start`` to find the nearest ancestor containing ``CHARTER.md``.

    Parameters
    ----------
    start:
        Path to start the upward walk from. Defaults to ``Path.cwd()``.

    Returns
    -------
    ProjectRepo | None
        Discovered project repo, or ``None`` if no charter is found before the
        filesystem root.
    """
    current = Path(start).resolve() if start is not None else Path.cwd().resolve()
    if current.is_file():
        current = current.parent

    for candidate in (current, *current.parents):
        charter = candidate / CHARTER_FILENAME
        if charter.is_file():
            members_path = candidate / MEMBERS_FILENAME
            return ProjectRepo(
                path=candidate,
                charter_path=charter,
                members_path=members_path if members_path.is_file() else None,
            )
    return None


def require_project_repo(start: str | Path | None = None) -> ProjectRepo:
    """Like :func:`find_project_repo` but raises :class:`RepoDiscoveryError` on miss."""
    repo = find_project_repo(start)
    if repo is None:
        raise RepoDiscoveryError(
            "No wigamig project found. Run from inside a project repo " "(must contain CHARTER.md)."
        )
    return repo


def read_members(members_path: Path) -> list[str]:
    """Read a ``MEMBERS`` file and return the list of member handles.

    Lines starting with ``#`` and blank lines are ignored. A leading ``@`` is
    preserved on each handle so the result can be compared verbatim to charter
    frontmatter (which uses ``@handle`` notation).
    """
    handles: list[str] = []
    for raw in members_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        handles.append(line)
    return handles
