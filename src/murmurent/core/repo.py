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
# Marks a lab-mgmt dir as a synthesized card-import fallback rather than a real
# clone (see ``identity_card.import_card`` + ``is_card_import_stub``).
CARD_STUB_MARKER = ".murmurent_card_stub"
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


def discover_lab_mgmt_clone_for_group(
    group: str, *, handle: str | None = None,
) -> Path | None:
    """A real lab_mgmt clone of ``group`` that lists ``handle``, or None.

    Group- and member-aware wrapper over :func:`_discover_lab_mgmt_clone` —
    which already does the hard parts (match on SHAPE not name, so a
    pre-convention ``~/repos/lab_mgmt`` is found as readily as a canonical
    ``~/repos/murmurent_lab_mgmt_<lab>``; prefer a roster containing the current
    user; refuse to guess when ambiguous). Two checks are layered on:

    - **group**: the clone must not *contradict* the group asked about, so a
      member of two groups can't have both registry entries collapse onto one
      clone. A clone whose ``lab.md`` declares no ``lab:`` is accepted —
      pre-convention clones predate the field.
    - **roster**: the clone must actually carry ``members/<handle>.md``. This
      one is load-bearing. ``_discover_lab_mgmt_clone`` only *prefers* rosters
      containing the current user and falls back to the full candidate set when
      none match, so without this check a member could be pointed at a clone
      that doesn't know them yet (the PI hasn't pushed their record, or they
      cloned early). ``is_member`` would then resolve False and the scoping gate
      would refuse them their own dashboard — strictly worse than the stub,
      whose entire job is to make ``is_member`` resolve. When the clone doesn't
      list them, the stub is the better answer and we say so by returning None.
    """
    found = _discover_lab_mgmt_clone()
    if found is None:
        return None
    declared = _lab_md_group(found)
    if declared and str(group) and declared != str(group):
        return None
    if handle and not (found / MEMBERS_SUBDIR / f"{handle}.md").is_file():
        return None
    return found


def _lab_md_group(path: Path) -> str:
    """The group name a lab_mgmt clone declares in ``lab.md`` (``lab:``), or ''."""
    try:
        from .frontmatter import parse_file as _parse_file

        meta = _parse_file(path / "lab.md").meta or {}
    except Exception:  # noqa: BLE001 — an unreadable lab.md just means "unknown"
        return ""
    return str(meta.get("lab") or "").strip()


def is_card_import_stub(path: str | Path) -> bool:
    """True when ``path`` is a synthesized card-import stub, not a real clone.

    ``import_card`` materializes a one-person lab-mgmt under ``lab_info/`` when a
    member has no clone, so ``is_member`` still resolves. That fallback is fine
    until a real clone shows up — then the stub must yield, because the registry
    path it wrote is entered as a thread-local override and would otherwise
    shadow the clone permanently (the member sees a roster of one: themselves).

    Detection is marker-first: stubs written from now on carry
    ``.murmurent_card_stub``. The heuristic below is only for stubs already in
    the field (issued before the marker existed) — it requires ALL of: living
    under ``lab_info_root()``, having no ``.git`` of its own, and a roster of at
    most one member. Callers must additionally confirm the machine owner is a
    plain *member* of the group (see ``registrar._heal_card_stub_entry``); a
    registrar-scaffolded lab on the mayor's own machine has the same shape and
    must never be mistaken for a stub.
    """
    p = Path(path).expanduser()
    if (p / CARD_STUB_MARKER).is_file():
        return True
    if (p / ".git").exists():
        return False  # a real clone, whatever else is true
    from . import registrar as _registrar

    try:
        root = _registrar.lab_info_root().resolve()
        if not p.resolve().is_relative_to(root):
            return False
    except (OSError, ValueError):
        return False
    try:
        roster = list((p / MEMBERS_SUBDIR).glob("*.md"))
    except OSError:
        return False
    return len(roster) <= 1


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


# ---------------------------------------------------------------------------
# Obsidian vault repos (issue #25)
# ---------------------------------------------------------------------------
#
# Two kinds of vault, two GitHub homes:
#   * PERSONAL vault  → private repo ``murmurent_vault`` on the *person's* own
#     GitHub. Every member (incl. the PI) has one. Holds their personal
#     oracle, lab-notebook, and other Tier-II notes.
#   * LAB (group) vault → per the PI's decision (issue #25) this is NOT a new
#     ``murmurent_vault_lab`` repo; it IS the existing lab-management repo
#     ``murmurent_lab_mgmt_<lab>`` (see :func:`lab_repo_path`). The lab oracle
#     already lives at ``<lab_mgmt>/oracle/``, members already get read access
#     via ``group_reconcile.grant_lab_mgmt_read``, and ``roster_sync`` already
#     keeps it fresh — so lab-vault storage, access, and sync are solved.
#
# The issue's proposed ``murmurent_vault_lab`` name is therefore superseded by
# the existing ``murmurent_lab_mgmt_<lab>`` convention. ``lab_vault_repo_name``
# below returns that canonical name so callers don't hardcode the superseded
# one.
PERSONAL_VAULT_REPO_NAME = "murmurent_vault"


def personal_vault_repo_name() -> str:
    """Canonical GitHub repo name for a member's personal Obsidian vault:
    ``murmurent_vault`` (a private repo on the person's own GitHub)."""
    return PERSONAL_VAULT_REPO_NAME


def personal_vault_path() -> Path:
    """Suggested clone path for the personal vault on this machine:
    ``<repos>/murmurent_vault``. This is the DEFAULT only — the actual
    per-machine location is stored as ``obsidian_vault_path`` in
    ``machine.yaml`` and may point anywhere (commonly an iCloud folder)."""
    return repos_root() / PERSONAL_VAULT_REPO_NAME


def lab_vault_repo_name(group: str) -> str:
    """Canonical GitHub repo name for the lab (group) vault of ``group``.

    Per issue #25 the lab vault is the existing lab-management repo, so this
    returns ``murmurent_lab_mgmt_<group>`` — NOT the issue's proposed (and
    now superseded) ``murmurent_vault_lab``. Kept as a named helper so the
    dashboard / docs can show "the lab vault is <this repo>" without
    re-deriving the convention."""
    return lab_repo_path(group).name


def lab_vault_path(group: str) -> Path:
    """Clone path for the lab (group) vault on this machine.

    Identical to :func:`lab_repo_path` — the lab vault IS the lab-mgmt clone.
    Prefer :func:`lab_mgmt_repo_root` when you want the *pinned* location a
    given machine actually resolved to; this helper only gives the canonical
    ``<repos>/murmurent_lab_mgmt_<group>`` default."""
    return lab_repo_path(group)


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
