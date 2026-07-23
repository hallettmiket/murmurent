"""
Purpose: Fork commons agents into personal, upgrade-surviving copies and track
         drift against the commons (a git-merge-style indicator).
Author: Mike Hallett (with Claude Code)
Date: 2026-07-20
Input: The commons agents dir (``<murmurent-repo>/agents/``), the installed CC
       agents dir (``~/.claude/agents/``), and the fork home
       (``<vault>/agent_forks/`` when a personal vault is registered on this
       machine, else the legacy ``~/.murmurent/agent_forks/`` — canonical
       copies + ``agent_forks.yaml``).
Output: ``AgentStatus`` records + fork/unfork side effects.

Design
------
``scripts/setup.sh`` symlinks each commons ``agents/<name>.md`` into
``~/.claude/agents/`` but PRESERVES any file there that is NOT a symlink. So a
personal copy survives ``git pull`` / re-runs only if it is a real (non-symlink)
file. A fork therefore:

  1. writes the canonical copy to ``~/.murmurent/agent_forks/<name>.md`` (the
     single, git-trackable home a member can ``git init`` + push), and
  2. installs the working copy at ``~/.claude/agents/<name>.md`` as a **hardlink**
     to that canonical file — a hardlink is not a symlink, so setup.sh preserves
     it, and both paths share one inode so an in-place edit to either is seen by
     the other with no sync step. If a hardlink can't be made (cross-device), we
     fall back to a plain copy.

Provenance for drift lives in ``agent_forks.yaml`` — the sha256 of the commons
file AT fork time (``source_sha``) plus the fork timestamp. That one hash drives
both indicators:

  * upstream-changed  = sha256(current commons file) != source_sha
  * locally-modified  = sha256(local working copy)   != source_sha

Multi-machine sync (issue #80)
------------------------------
When a personal vault is registered on this machine, the fork home is
``<vault>/agent_forks/`` — an allowlist-tracked vault folder — so the canonical
copies + manifest ride ``murmurent vault sync`` to the member's GitHub and back
onto every other machine. ``migrate_legacy_forks()`` moves an existing
``~/.murmurent/agent_forks/`` into the vault once (idempotent, non-destructive);
``murmurent agent relink`` re-materialises the working copies after a vault
pull on a second machine. Without a registered vault, the legacy
``~/.murmurent/agent_forks/`` home keeps working unchanged.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .agents import load_agent
from .repo import murmurent_repo_root

FORKS_DIRNAME = "agent_forks"
MANIFEST_FILENAME = "agent_forks.yaml"

#: Test/override pin for the fork home (mirrors ``MURMURENT_CC_AGENTS_DIR``).
ENV_FORKS_DIR = "MURMURENT_AGENT_FORKS_DIR"


class AgentForkError(RuntimeError):
    """Raised on an invalid fork/unfork request (unknown agent, already forked …)."""


# ---------------------------------------------------------------------------
# path resolution — each dir is independently overridable for tests
# ---------------------------------------------------------------------------


def commons_agents_dir() -> Path:
    """The commons agents dir inside the murmurent clone (``<repo>/agents``)."""
    return murmurent_repo_root() / "agents"


def installed_agents_dir() -> Path:
    """The Claude Code agents dir this machine loads (``~/.claude/agents``).

    Honours ``$MURMURENT_CC_AGENTS_DIR`` so tests (and unusual installs) can
    redirect it without touching the developer's real ``~/.claude``.
    """
    override = os.environ.get("MURMURENT_CC_AGENTS_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".claude" / "agents"


def _wig_home() -> Path:
    return Path(os.environ.get("MURMURENT_HOME", str(Path.home() / ".murmurent")))


def legacy_forks_dir() -> Path:
    """The pre-#80 fork home (``~/.murmurent/agent_forks``) — machine-local,
    so a fork made here never reached the member's other machines."""
    return _wig_home() / FORKS_DIRNAME


def forks_dir() -> Path:
    """The canonical, git-trackable fork home.

    Resolution order:

    1. ``$MURMURENT_AGENT_FORKS_DIR`` (tests / unusual installs),
    2. ``<vault>/agent_forks/`` when a personal vault is registered on this
       machine (``machine.yaml``) — the fork copies + manifest then ride
       ``murmurent vault sync`` across the member's machines (issue #80),
    3. the legacy ``~/.murmurent/agent_forks/`` (no vault → single-machine
       behaviour, unchanged).
    """
    pin = os.environ.get(ENV_FORKS_DIR, "").strip()
    if pin:
        return Path(pin).expanduser()
    try:
        from . import vault_sync as _vs  # deferred: optional dashboard deps

        root = _vs.personal_vault_root()
    except Exception:  # noqa: BLE001 — unresolvable vault → legacy home
        root = None
    if root is not None:
        return Path(root) / FORKS_DIRNAME
    return legacy_forks_dir()


def manifest_path() -> Path:
    """The fork provenance manifest (``<forks_dir>/agent_forks.yaml``)."""
    return forks_dir() / MANIFEST_FILENAME


def commons_agent_path(name: str) -> Path:
    return commons_agents_dir() / f"{name}.md"


def commons_agent_names() -> set[str]:
    """Every agent the commons currently ships."""
    base = commons_agents_dir()
    if not base.is_dir():
        return set()
    return {p.stem for p in base.glob("*.md")}


# ---------------------------------------------------------------------------
# hashing + manifest I/O
# ---------------------------------------------------------------------------


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def load_manifest() -> dict:
    """Read ``agent_forks.yaml`` → ``{"forks": {name: {...}}}`` (empty if absent)."""
    path = manifest_path()
    if not path.is_file():
        return {"forks": {}}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    forks = data.get("forks")
    if not isinstance(forks, dict):
        forks = {}
    return {"forks": forks}


def save_manifest(data: dict) -> None:
    forks_dir().mkdir(parents=True, exist_ok=True)
    manifest_path().write_text(
        yaml.safe_dump({"forks": data.get("forks", {})}, sort_keys=True, allow_unicode=True),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# status / drift
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentStatus:
    """The install + drift state of one agent in ``~/.claude/agents/``."""

    name: str
    kind: str  # "linked" | "forked" | "user-file"
    description: str = ""
    # forked-only fields (None for linked/user-file):
    in_commons: bool | None = None
    upstream_changed: bool | None = None
    locally_modified: bool | None = None
    forked_at: str | None = None

    @property
    def diverged(self) -> bool:
        """Both sides moved since the fork point — the merge case."""
        return bool(self.upstream_changed) and bool(self.locally_modified)


def _describe(path: Path) -> str:
    """Best-effort one-line description from an agent file's frontmatter."""
    try:
        return load_agent(path).description
    except Exception:  # noqa: BLE001 — a malformed override still lists, sans blurb
        return ""


def status_for(name: str) -> AgentStatus | None:
    """Status of a single installed agent, or ``None`` if it isn't installed."""
    dest = installed_agents_dir() / f"{name}.md"
    if not dest.exists() and not dest.is_symlink():
        return None

    if dest.is_symlink():
        return AgentStatus(name=name, kind="linked", description=_describe(dest))

    manifest = load_manifest()["forks"]
    entry = manifest.get(name)
    if entry is None:
        # A real file we never forked — a hand-authored override setup.sh preserves.
        return AgentStatus(name=name, kind="user-file", description=_describe(dest))

    source_sha = str(entry.get("source_sha", ""))
    commons = commons_agent_path(name)
    in_commons = commons.is_file()
    upstream_changed = in_commons and _sha256_file(commons) != source_sha
    locally_modified = _sha256_file(dest) != source_sha
    return AgentStatus(
        name=name,
        kind="forked",
        description=_describe(dest),
        in_commons=in_commons,
        upstream_changed=upstream_changed,
        locally_modified=locally_modified,
        forked_at=entry.get("forked_at"),
    )


def iter_status() -> list[AgentStatus]:
    """Status for every agent in ``~/.claude/agents/`` (sorted by name)."""
    base = installed_agents_dir()
    if not base.is_dir():
        return []
    out: list[AgentStatus] = []
    for path in sorted(base.glob("*.md")):
        st = status_for(path.stem)
        if st is not None:
            out.append(st)
    return out


def iter_forks() -> list[AgentStatus]:
    """Status for the forked agents only (what ``agent drift`` reports on)."""
    forked = set(load_manifest()["forks"])
    return [st for st in iter_status() if st.name in forked]


# ---------------------------------------------------------------------------
# fork / unfork
# ---------------------------------------------------------------------------


def _install_working_copy(canonical: Path, dest: Path) -> str:
    """Place the working copy at ``dest``. Prefer a hardlink to ``canonical``
    (one inode, two non-symlink paths); fall back to a plain copy cross-device.

    Returns "hardlink" or "copy" for reporting.
    """
    if dest.exists() or dest.is_symlink():
        dest.unlink()
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(canonical, dest)
        return "hardlink"
    except OSError:
        dest.write_bytes(canonical.read_bytes())
        return "copy"


@dataclass(frozen=True)
class ForkResult:
    name: str
    canonical: Path
    working: Path
    method: str  # "hardlink" | "copy"
    source_sha: str
    forked_at: str


def fork_agent(name: str, *, force: bool = False) -> ForkResult:
    """Replace the ``~/.claude/agents/<name>.md`` symlink with a personal copy.

    Refuses if ``name`` is not a commons agent, or if a real file already sits
    there (already forked / hand-authored) unless ``force`` re-snapshots it from
    the current commons.
    """
    commons = commons_agent_path(name)
    if not commons.is_file():
        known = ", ".join(sorted(commons_agent_names())) or "(none)"
        raise AgentForkError(
            f"{name!r} is not a known commons agent. Known agents: {known}."
        )

    dest = installed_agents_dir() / f"{name}.md"
    manifest = load_manifest()
    if dest.exists() and not dest.is_symlink() and not force:
        already = name in manifest["forks"]
        what = "already forked" if already else "a user-authored file already exists"
        raise AgentForkError(
            f"{name!r}: {what} at {dest}. Re-run with --force to overwrite it "
            f"with a fresh copy of the current commons version."
        )

    source_bytes = commons.read_bytes()
    source_sha = _sha256_bytes(source_bytes)
    forked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    canonical = forks_dir() / f"{name}.md"
    canonical.parent.mkdir(parents=True, exist_ok=True)
    canonical.write_bytes(source_bytes)
    method = _install_working_copy(canonical, dest)

    manifest["forks"][name] = {
        "source_sha": source_sha,
        "forked_at": forked_at,
        "source_path": str(commons),
    }
    save_manifest(manifest)
    return ForkResult(
        name=name,
        canonical=canonical,
        working=dest,
        method=method,
        source_sha=source_sha,
        forked_at=forked_at,
    )


def unfork_agent(name: str, *, force: bool = False) -> Path:
    """Restore the commons symlink, dropping the personal copy + manifest entry.

    Returns the restored symlink path. Refuses if ``name`` was never forked
    (unless ``force``) or if the commons no longer ships it (can't relink).
    """
    manifest = load_manifest()
    dest = installed_agents_dir() / f"{name}.md"
    if name not in manifest["forks"] and not force:
        raise AgentForkError(
            f"{name!r} is not a tracked fork (nothing in the manifest). "
            f"Re-run with --force to relink it to the commons anyway."
        )

    commons = commons_agent_path(name)
    if not commons.is_file():
        raise AgentForkError(
            f"{name!r} is no longer a commons agent — cannot restore the symlink. "
            f"Delete {dest} by hand if you want it gone."
        )

    if dest.exists() or dest.is_symlink():
        dest.unlink()
    canonical = forks_dir() / f"{name}.md"
    if canonical.exists():
        canonical.unlink()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.symlink_to(commons)

    if name in manifest["forks"]:
        del manifest["forks"][name]
        save_manifest(manifest)
    return dest


# ---------------------------------------------------------------------------
# legacy-home migration (issue #80: forks ride the vault across machines)
# ---------------------------------------------------------------------------


def migrate_legacy_forks() -> dict:
    """One-time move of ``~/.murmurent/agent_forks/`` into the vault fork home.

    Idempotent and non-destructive:

    * no vault registered (``forks_dir()`` IS the legacy dir) → no-op;
    * files already present in the vault home are never overwritten (skipped);
    * the member's live working copy wins: if ``~/.claude/agents/<name>.md``
      diverged from the legacy canonical (the copy-fallback install case), its
      bytes become the vault canonical before re-linking;
    * the legacy dir is kept on disk, renamed to ``agent_forks.migrated`` as a
      backup (left untouched if that name already exists).

    Returns a summary dict (``migrated``, ``copied``, ``skipped``,
    ``relinked``, ``backup``, ``detail``).
    """
    legacy = legacy_forks_dir()
    target = forks_dir()
    out: dict = {"migrated": False, "from": str(legacy), "to": str(target),
                 "copied": [], "skipped": [], "relinked": [], "backup": "",
                 "detail": ""}
    if target == legacy:
        out["detail"] = "no personal vault registered — fork home unchanged"
        return out
    if not legacy.is_dir() or not any(legacy.iterdir()):
        out["detail"] = "no legacy fork home — nothing to migrate"
        return out

    target.mkdir(parents=True, exist_ok=True)
    for src in sorted(p for p in legacy.iterdir() if p.is_file()):
        dst = target / src.name
        if dst.exists():
            out["skipped"].append(src.name)  # vault copy wins — never clobber
            continue
        dst.write_bytes(src.read_bytes())
        out["copied"].append(src.name)

    # Re-point the installed working copies at the migrated canonicals so an
    # edit keeps flowing into the vault (hardlink; plain copy cross-device).
    for name in sorted(load_manifest()["forks"]):
        canonical = target / f"{name}.md"
        if not canonical.is_file():
            continue
        dest = installed_agents_dir() / f"{name}.md"
        if dest.exists() and not dest.is_symlink() \
                and dest.read_bytes() != canonical.read_bytes():
            # A copy-fallback working copy carries edits the legacy canonical
            # never saw — the member's live copy is the truth.
            canonical.write_bytes(dest.read_bytes())
        _install_working_copy(canonical, dest)
        out["relinked"].append(name)

    backup = legacy.with_name(legacy.name + ".migrated")
    if not backup.exists():
        try:
            legacy.rename(backup)
            out["backup"] = str(backup)
        except OSError:
            pass  # copy already landed; a stubborn legacy dir is harmless
    out["migrated"] = True
    out["detail"] = (f"moved {len(out['copied'])} file(s) into {target} "
                     f"({len(out['skipped'])} already there)")
    return out
