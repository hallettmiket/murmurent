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
# Kept for older callers; murmurent_repo_root() reads repos_root() at call time,
# so a machine's own repositories folder is honoured (#166).
DEFAULT_MURMURENT_REPO = Path.home() / "repos" / "murmurent"
# A group's records repo lives at exactly one place on a machine:
# ``<repos>/murmurent_lab_mgmt_<group>`` (see ``lab_repo_path``). The identity
# card says which groups the owner belongs to, and that is the whole lookup.
# ``DEFAULT_LAB_MGMT_REPO`` is the honest last-resort return for a machine
# with no card and no registry entry: it is group-less and never exists on
# disk, so every lookup against it misses cleanly and the resulting message
# names the convention rather than a stale path.
DEFAULT_LAB_MGMT_REPO = Path.home() / "repos" / "murmurent_lab_mgmt"  # never exists; see above

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
    if env.get("MURMURENT_REPO_ROOT"):
        return Path(env["MURMURENT_REPO_ROOT"]).expanduser()
    return repos_root() / "murmurent"


def lab_mgmt_repo_root(env: dict[str, str] | None = None) -> Path:
    """Resolve the lab records repo this machine acts on.

    The canonical repo is ``<repos>/murmurent_lab_mgmt_<group>`` (see
    ``lab_repo_path``), and the machine owner's identity card says which
    groups they belong to. There is no pin file, no folder scan and no
    placeholder roster: a missing clone resolves to the canonical path and
    the caller says "clone it there".

    Resolution order:
      1. Thread-local override set by ``use_lab_mgmt_root()``: the dashboard
         points each request at the viewer's own group.
      2. ``$MURMURENT_LAB_MGMT_REPO``: an explicit operator pin to one repo
         (tests, scripted use, unusual deployments).
      3. The identity card: the first group the owner leads, else the first
         group they are a member of, at its canonical path.
      4. The centre registry, for a machine with no card (a registrar-created
         lab on the mayor's machine lives under ``lab_info/``).
      5. ``DEFAULT_LAB_MGMT_REPO``, which never exists on disk.
    """
    override = getattr(_thread_local, "lab_mgmt_root", None)
    if override is not None:
        return Path(override).expanduser()
    env = os.environ if env is None else env
    explicit = env.get("MURMURENT_LAB_MGMT_REPO")
    if explicit:
        return Path(explicit).expanduser()
    own = records_repo_for_owner(env)
    if own is not None:
        return own
    registered = _registry_lab_mgmt_for_owner(env)
    if registered is not None:
        return registered
    return DEFAULT_LAB_MGMT_REPO


@dataclass(frozen=True)
class OwnerGroup:
    """One group the machine owner belongs to, read from their identity card."""

    group: str
    kind: str      # "lab" | "core"
    role: str      # "leader" | "member"
    pi: str = ""   # the group's PI/leader handle, without the "@"

    @property
    def path(self) -> Path:
        return lab_repo_path(self.group)

    @property
    def leads(self) -> bool:
        return self.role == "leader"


def owner_groups(env: dict[str, str] | None = None) -> list[OwnerGroup]:
    """Every group on the machine owner's identity card, led groups first.

    The card is the one source of truth for membership on a member's own
    machine. Returns ``[]`` when there is no card. Never raises.
    """
    try:
        from . import identity_card as _ic

        card = _ic.local_card(env)
    except Exception:  # noqa: BLE001 - an unreadable card means no groups
        return []
    if not card:
        return []
    out: list[OwnerGroup] = []
    for role in card.get("roles") or []:
        kind = str(role.get("kind") or "")
        group = str(role.get("group") or "").strip()
        if not group:
            continue
        pi = str(role.get("pi") or "").lstrip("@").lower()
        if kind == "lab_pi":
            out.append(OwnerGroup(group, "lab", "leader", pi))
        elif kind == "core_leader":
            out.append(OwnerGroup(group, "core", "leader", pi))
        elif kind == "member":
            gk = "core" if str(role.get("group_kind") or "lab") == "core" else "lab"
            out.append(OwnerGroup(group, gk, "member", pi))
    out.sort(key=lambda g: 0 if g.leads else 1)
    return out


def records_repo_for_owner(env: dict[str, str] | None = None) -> Path | None:
    """The canonical records repo of the owner's primary group, or None
    when the machine has no identity card. Led groups win over memberships."""
    groups = owner_groups(env)
    return groups[0].path if groups else None


def _registry_lab_mgmt_for_owner(env: dict[str, str] | None = None) -> Path | None:
    """The machine owner's group per the centre registry, or None.

    Only consulted when the owner has no identity card. Returns the recorded
    path even if it is not on disk: that is the right answer (panels render
    empty until it is cloned). Best-effort and fully isolated: a missing
    handle, an empty registry, or any import hiccup yields ``None``. The
    registrar import is function-local to break the ``repo`` <-> ``registrar``
    cycle.
    """
    handle = _current_handle()
    if not handle:
        return None
    try:
        from . import registrar as _reg

        match = _reg.lab_mgmt_path_for_handle(handle, env)
    except Exception:  # noqa: BLE001 - registry trouble must never break resolution
        return None
    if match is None:
        return None
    return Path(match[1]).expanduser()


def _looks_like_lab_mgmt_clone(path: Path) -> bool:
    """A directory is a plausible records repo when it carries both ``lab.md``
    (the group config) and a ``members/`` roster directory."""
    return (path / "lab.md").is_file() and (path / MEMBERS_SUBDIR).is_dir()


def find_misplaced_records_clone(group: str) -> Path | None:
    """A clone of ``group``'s records repo sitting at the wrong path, or None.

    Only the top level of the repositories folder is checked, and only
    folders whose ``lab.md`` names ``group``. This is a hint for the "move it
    here" message; nothing is pinned or rewritten.
    """
    root = repos_root()
    want = lab_repo_path(group)
    try:
        entries = sorted(p for p in root.iterdir() if p.is_dir())
    except OSError:
        return None
    for p in entries:
        if p == want or not _looks_like_lab_mgmt_clone(p):
            continue
        if _lab_md_group(p) == str(group):
            return p
    return None


def records_clone_hint(group: str, *, remote: str = "") -> str:
    """One sentence telling the owner how to get ``group``'s records repo
    onto this machine: move a misplaced clone, or clone it from GitHub."""
    want = lab_repo_path(group)
    misplaced = find_misplaced_records_clone(group)
    if misplaced is not None:
        return (f"Your copy of the lab records is at {misplaced}; move it to the "
                f"standard place:  mv {misplaced} {want}")
    slug = github_slug(remote) if remote else f"<owner>/{want.name}"
    return (f"Clone the lab records to {want}:  gh repo clone {slug} {want}"
            f"   (if that is refused, `murmurent doctor` says why)")


def github_slug(remote: str) -> str:
    """``owner/name`` from any GitHub remote URL (SSH or HTTPS), else ''."""
    url = (remote or "").strip()
    for prefix in ("git@github.com:", "https://github.com/",
                   "http://github.com/", "ssh://git@github.com/"):
        if url.startswith(prefix):
            slug = url[len(prefix):].strip("/")
            return slug[:-4] if slug.endswith(".git") else slug
    return ""


def _lab_md_group(path: Path) -> str:
    """The group name a lab_mgmt clone declares in ``lab.md`` (``lab:``), or ''."""
    try:
        from .frontmatter import parse_file as _parse_file

        meta = _parse_file(path / "lab.md").meta or {}
    except Exception:  # noqa: BLE001 — an unreadable lab.md just means "unknown"
        return ""
    return str(meta.get("lab") or "").strip()


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


#: Where this machine's own settings live (also written by the dashboard).
MACHINE_SETTINGS_FILE = Path.home() / ".murmurent" / "machine.yaml"
#: Folder names people commonly use, in the order `suggest_repos_root` tries them.
COMMON_REPOS_FOLDERS = ("repos", "repo", "repositories")


def _machine_repos_root() -> str:
    """``repos_root`` from this machine's ``machine.yaml``, or ""."""
    try:
        import yaml
        data = yaml.safe_load(MACHINE_SETTINGS_FILE.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 - a missing or broken file means "not set"
        return ""
    value = data.get("repos_root") if isinstance(data, dict) else None
    return str(value).strip() if value else ""


def repos_root_and_source() -> tuple[Path, str]:
    """This machine's repositories folder, and where that answer came from.

    Order (issue #166): ``$MURMURENT_REPOS_ROOT`` (tests, unusual installs),
    then ``repos_root`` in ``~/.murmurent/machine.yaml`` (set by
    ``murmurent init``, ``murmurent config repos-root`` or the dashboard), then
    ``~/repos``. People use ``~/repo``, ``~/repositories`` and others, so this
    is a choice per machine, never an assumption.
    """
    env = os.environ.get("MURMURENT_REPOS_ROOT", "").strip()
    if env:
        return Path(env).expanduser(), "the MURMURENT_REPOS_ROOT environment variable"
    configured = _machine_repos_root()
    if configured:
        return Path(configured).expanduser(), f"repos_root in {MACHINE_SETTINGS_FILE}"
    return Path.home() / "repos", "the default (nothing set)"


def repos_root() -> Path:
    """The base directory for working clones on this machine.

    Every path to a repository on this machine must be built from this, never
    from a literal ``~/repos``: ``tests/test_repos_root_guard.py`` fails on a
    new one.
    """
    return repos_root_and_source()[0]


def suggest_repos_root() -> Path:
    """The folder to offer when asking: the first common name that exists
    (``~/repos``, ``~/repo``, ``~/repositories``), else ``~/repos``."""
    for name in COMMON_REPOS_FOLDERS:
        candidate = Path.home() / name
        if candidate.is_dir():
            return candidate
    return Path.home() / COMMON_REPOS_FOLDERS[0]


def set_repos_root(folder: str | Path) -> Path:
    """Record ``folder`` as this machine's repositories folder in machine.yaml.

    Every other line of the file is kept. Returns the folder as stored. The
    folder need not exist yet; it is created on first use.
    """
    import yaml
    target = Path(str(folder)).expanduser()
    try:
        stored = "~/" + str(target.relative_to(Path.home())) if target != Path.home() else "~"
    except ValueError:
        stored = str(target)
    data: dict = {}
    if MACHINE_SETTINGS_FILE.is_file():
        loaded = yaml.safe_load(MACHINE_SETTINGS_FILE.read_text(encoding="utf-8"))
        data = loaded if isinstance(loaded, dict) else {}
    data["repos_root"] = stored
    MACHINE_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    MACHINE_SETTINGS_FILE.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return target


def repos_root_for_display() -> str:
    """The repositories folder written as a person would type it (``~/repos``)."""
    root = repos_root()
    try:
        return "~/" + str(root.relative_to(Path.home()))
    except ValueError:
        return str(root)


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

    Identical to :func:`lab_repo_path` — the lab vault IS the lab-mgmt clone."""
    return lab_repo_path(group)


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


MARKER_FILENAME = ".murmurent.yaml"


def find_project_repo(start: str | Path | None = None) -> ProjectRepo | None:
    """Walk up from ``start`` to find the nearest ancestor that is a murmurent
    project repo.

    A repo is identified by its ``.murmurent.yaml`` readiness marker — the
    single on-disk "this is a murmurent project" signal (issue #28). A legacy
    ``CHARTER.md`` is accepted as a fallback so pre-migration clones (which
    predate the marker) still resolve; once ``murmurent project migrate-charters``
    has run, only the marker remains.

    Parameters
    ----------
    start:
        Path to start the upward walk from. Defaults to ``Path.cwd()``.

    Returns
    -------
    ProjectRepo | None
        Discovered project repo, or ``None`` if neither the marker nor a legacy
        charter is found before the filesystem root. ``charter_path`` always
        points at ``<repo>/CHARTER.md`` (which may not exist post-migration) so
        legacy readers keep a stable field to probe.
    """
    current = Path(start).resolve() if start is not None else Path.cwd().resolve()
    if current.is_file():
        current = current.parent

    for candidate in (current, *current.parents):
        if (candidate / MARKER_FILENAME).is_file() or (candidate / CHARTER_FILENAME).is_file():
            members_path = candidate / MEMBERS_FILENAME
            return ProjectRepo(
                path=candidate,
                charter_path=candidate / CHARTER_FILENAME,
                members_path=members_path if members_path.is_file() else None,
            )
    return None


def require_project_repo(start: str | Path | None = None) -> ProjectRepo:
    """Like :func:`find_project_repo` but raises :class:`RepoDiscoveryError` on miss."""
    repo = find_project_repo(start)
    if repo is None:
        raise RepoDiscoveryError(
            "No murmurent project found. Run from inside a project repo "
            "(must contain a .murmurent.yaml marker)."
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
