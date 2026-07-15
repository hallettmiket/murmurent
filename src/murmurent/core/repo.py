"""
Purpose: Discover murmurent repos and the active project on disk.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-06
Input: Filesystem (current working directory, ``$MURMURENT_REPO_ROOT``,
       ``$MURMURENT_LAB_MGMT_REPO``).
Output: Helpers that locate the murmurent repo, the lab-management repo, and the
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
# The lab_mgmt roster lives in a ``members/`` subdir (one <handle>.md per member);
# distinct from the project-level ``MEMBERS`` file above.
MEMBERS_SUBDIR = "members"
DEFAULT_MURMURENT_REPO = Path("~/repos/murmurent").expanduser()
# 2026-05-14: repo is being renamed from "hallett-lab-mgmt" to the per-group
# convention "lab_mgmt". During the transition we prefer the new path but
# fall back to the legacy name so existing clones keep working.
DEFAULT_LAB_MGMT_REPO = Path("~/repos/lab_mgmt").expanduser()
LEGACY_LAB_MGMT_REPO  = Path("~/repos/hallett-lab-mgmt").expanduser()

# Per-request lab-mgmt override. FastAPI dispatches sync handlers into a
# threadpool, so thread-local state is request-scoped without env-var
# contention. When a request resolves the viewer's lab (e.g. core_lead),
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


def murmurent_repo_root(env: dict[str, str] | None = None) -> Path:
    """Resolve the murmurent repo root, honouring ``$MURMURENT_REPO_ROOT`` if set."""
    env = os.environ if env is None else env
    return Path(env.get("MURMURENT_REPO_ROOT", DEFAULT_MURMURENT_REPO)).expanduser()


def lab_mgmt_repo_root(env: dict[str, str] | None = None) -> Path:
    """Resolve the lab-management repo root.

    The canonical repo is ``~/repos/murmurent_lab_mgmt_<lab>`` (see
    ``lab_repo_path``); everything below is the machinery that finds it — plus
    fallbacks for pre-convention clones.

    Resolution order:
      1. Thread-local override set by ``use_lab_mgmt_root()`` — used by the
         FastAPI dashboard to point each request at the viewer's own lab
         (so @core_lead sees her lab_mgmt, @the_pi sees his).
      2. ``$MURMURENT_LAB_MGMT_REPO`` env var
      3. This machine's pinned pointer (``~/.murmurent/lab_mgmt_path``), written
         by ``pi-init`` and by discovery below.
      4. ``~/repos/lab_mgmt`` if it exists (pre-convention name)
      5. ``~/repos/hallett-lab-mgmt`` (legacy fallback) if it exists
      6. Discovery: an unambiguous lab_mgmt-shaped clone under ``repos_root()``
         — the member-machine case — pinned on the way out.
      7. ``~/repos/lab_mgmt`` (last-resort default, even if missing)
    """
    override = getattr(_thread_local, "lab_mgmt_root", None)
    if override is not None:
        return Path(override).expanduser()
    env = os.environ if env is None else env
    explicit = env.get("MURMURENT_LAB_MGMT_REPO")
    if explicit:
        return Path(explicit).expanduser()
    pinned = _pinned_lab_mgmt_path()          # persistent pointer (set by pi-init)
    if pinned is not None:
        return pinned
    if DEFAULT_LAB_MGMT_REPO.exists():
        return DEFAULT_LAB_MGMT_REPO
    if LEGACY_LAB_MGMT_REPO.exists():
        return LEGACY_LAB_MGMT_REPO
    # Everything above missed. A MEMBER machine (no env var, no pin — they
    # never ran pi-init) natural-names its clone after the repo itself
    # (``~/repos/murmurent_lab_mgmt_<lab>``), NOT ``~/repos/lab_mgmt``, so the
    # roster silently resolves to a non-existent default and every panel goes
    # empty. Self-heal: scan for a clone that looks like a lab_mgmt repo and,
    # on an unambiguous hit, pin it so this discovery runs exactly once.
    discovered = _discover_lab_mgmt_clone()
    if discovered is not None:
        return discovered
    return DEFAULT_LAB_MGMT_REPO


def _looks_like_lab_mgmt_clone(path: Path) -> bool:
    """A directory is a plausible lab_mgmt clone when it carries both a
    ``lab.md`` (the group config) and a ``members/`` roster directory."""
    return (path / "lab.md").is_file() and (path / MEMBERS_SUBDIR).is_dir()


def _discover_lab_mgmt_clone() -> Path | None:
    """Best-effort discovery of a member's lab_mgmt clone under ``repos_root()``.

    Only called when the env var, the pinned pointer, and both default paths
    have all missed — i.e. the member-machine case. Scans the top level of
    ``repos_root()`` for directories that look like a lab_mgmt clone (``lab.md``
    + ``members/``). When the current user's handle can be resolved, candidates
    whose roster contains that handle are preferred.

    Returns the discovered clone on a **unique** hit — and PINS it (via
    :func:`set_lab_mgmt_path`) so subsequent resolutions take the pinned branch
    above and never re-scan. On zero or ambiguous hits it returns ``None`` and
    the caller falls through to the unchanged default (no pin written).

    Loop-safe: pinning is what stops the recursion (the next call short-circuits
    on ``_pinned_lab_mgmt_path``); this function itself never calls
    ``lab_mgmt_repo_root``.
    """
    root = repos_root()
    try:
        entries = sorted(p for p in root.iterdir() if p.is_dir())
    except OSError:
        return None

    candidates = [p for p in entries if _looks_like_lab_mgmt_clone(p)]
    if not candidates:
        return None

    # Prefer a clone whose roster actually contains the current user. If the
    # handle can't be resolved (or matches nothing), fall back to the full set.
    handle = _current_handle()
    if handle:
        member_file = f"{handle}.md"
        with_me = [p for p in candidates if (p / MEMBERS_SUBDIR / member_file).is_file()]
        if with_me:
            candidates = with_me

    if len(candidates) != 1:
        # Zero (shouldn't happen here) or ambiguous — don't guess, don't pin.
        return None

    found = candidates[0]
    try:
        set_lab_mgmt_path(found)
    except OSError:
        # Couldn't persist the pointer; still return the live hit for this call.
        pass
    return found


def _current_handle() -> str | None:
    """Resolve the current user's bare handle for discovery, or ``None``.

    Tolerant: never raises, and treats the sentinel ``unknown`` identity as
    unresolved so discovery falls back to the whole candidate set.
    """
    try:
        from . import identity as _identity

        ident = _identity.resolve(allow_unknown=True)
    except Exception:  # noqa: BLE001
        return None
    handle = (ident.handle or "").strip().lstrip("@")
    if not handle or handle == "unknown":
        return None
    return handle


def _wig_home() -> Path:
    return Path(os.environ.get("MURMURENT_HOME", str(Path.home() / ".murmurent")))


def _lab_mgmt_pointer_path() -> Path:
    return _wig_home() / "lab_mgmt_path"


def _pinned_lab_mgmt_path() -> Path | None:
    """This machine's pinned lab-mgmt repo (written by ``set_lab_mgmt_path``), or
    None. Lets a standalone PI's roster resolve without an exported env var."""
    p = _lab_mgmt_pointer_path()
    if not p.is_file():
        return None
    try:
        txt = p.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return Path(txt).expanduser() if txt else None


def repos_root() -> Path:
    """The base directory for working clones — ``~/repos`` by default, overridable
    with ``$MURMURENT_REPOS_ROOT`` (tests isolate it)."""
    return Path(os.environ.get("MURMURENT_REPOS_ROOT", str(Path.home() / "repos"))).expanduser()


def lab_repo_path(group: str) -> Path:
    """The canonical lab-management repo path for ``group``:
    ``<repos>/murmurent_lab_mgmt_<group>``.

    This name is the convention, not a mere default — the GitHub repo carries it
    too (``<owner>/murmurent_lab_mgmt_<group>``), so a clone, an invitation, and
    a directory listing all say which lab they belong to. ``pi-init`` scaffolds
    here; ``docs/lab_mgmt.md`` documents it for humans."""
    safe = "".join(c if (c.isalnum() or c in "-_") else "_" for c in str(group or ""))
    return repos_root() / f"murmurent_lab_mgmt_{safe}"


def set_lab_mgmt_path(path: str | Path) -> None:
    """Persistently point ``lab_mgmt_repo_root()`` at a lab's own management repo
    (canonically ``~/repos/murmurent_lab_mgmt_<lab>``). Honours ``MURMURENT_HOME``.
    An explicit ``$MURMURENT_LAB_MGMT_REPO`` still overrides it."""
    p = _lab_mgmt_pointer_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(str(Path(path).expanduser()) + "\n", encoding="utf-8")


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
            "No murmurent project found. Run from inside a project repo " "(must contain CHARTER.md)."
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
