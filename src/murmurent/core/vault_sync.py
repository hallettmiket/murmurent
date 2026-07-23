"""
Purpose: Keep the per-member **personal** Obsidian vault (``murmurent_vault``)
         synchronised with its GitHub remote — best-effort commit+push on write,
         fast-forward-only pull + a freshness stamp on read.
Author: Mike Hallett (with Claude Code)
Date: 2026-07-16
Input: This machine's personal-vault clone (``machine.yaml.obsidian_vault_path``).
Output: :class:`CommitResult` (write side) and :class:`VaultSyncResult`
        (read side, mirroring ``core.roster_sync.RosterSyncResult``).

Issue #25, Part B (§3). The lab (group) vault is the lab-mgmt repo and is
already synced by :mod:`core.roster_sync`; this module is the *personal*-vault
analogue. The single hard contract (memo §6.2): a network / remote failure must
NEVER crash the write — :func:`commit_and_push` swallows every git failure and
reports it, exactly like :func:`core.roster_sync.pull_lab_mgmt`.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

_GIT_TIMEOUT = 60  # seconds; a hung SSH/https remote must not wedge a write


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def personal_vault_root() -> Path | None:
    """This machine's personal-vault clone root, or ``None`` when unregistered.

    Resolved from ``~/.murmurent/machine.yaml`` (``obsidian_vault_path``) — the
    same per-machine pin ``murmurent vault init`` writes and the Machine window
    edits. Deliberately does NOT fall back to the ``<repos>/murmurent_vault``
    default: this function answers "where is the clone I should sync?", and a
    default that doesn't exist would make the freshness probe lie. Importing
    ``machine_settings`` is deferred so the core module stays importable without
    the dashboard's optional deps.
    """
    try:
        from ..dashboard import machine_settings as _ms  # noqa: PLC0415

        s = _ms.load()
    except Exception:  # noqa: BLE001 — best-effort; unregistered on any failure
        return None
    raw = (s.obsidian_vault_path or "").strip()
    # "NA" (any casing) is the explicit "no personal vault on this machine"
    # marker (same set machine_settings._derive_vault_name treats as empty), not
    # a real path — treat it as unregistered so callers never resolve a bogus
    # ``NA`` directory (which the machine-registry mirror would otherwise create
    # in the CWD).
    if not raw or raw.lower() in {"na", "n/a", "none", "n.a.", "not applicable"}:
        return None
    return Path(raw).expanduser()


# ---------------------------------------------------------------------------
# git helpers (mirroring core.roster_sync)
# ---------------------------------------------------------------------------


def _run_git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, timeout=_GIT_TIMEOUT,
    )


def _last_commit_iso(root: Path) -> str:
    """ISO date of the newest commit, '' when unknown (not a repo, no commits)."""
    try:
        res = _run_git(root, "log", "-1", "--format=%cI")
    except (OSError, subprocess.SubprocessError):
        return ""
    return res.stdout.strip() if res.returncode == 0 else ""


def _enclosing_dir(path: str | Path) -> Path:
    """The directory to run git from: ``path`` if it's a dir, else its parent.

    A caller may hand us a freshly-written *file* inside the vault; git needs a
    directory. We do not resolve symlinks — an iCloud vault is often reached via
    one and resolving it can wander outside the worktree.
    """
    p = Path(path).expanduser()
    return p if p.is_dir() else p.parent


# ---------------------------------------------------------------------------
# Write side — commit + push (best-effort, never raises)
# ---------------------------------------------------------------------------


@dataclass
class CommitResult:
    """Outcome of a best-effort personal-vault commit+push.

    ``ok`` reflects the *local* safety of the write: it is ``True`` whenever the
    working tree ended in a clean, committed (or nothing-to-commit) state, even
    if the subsequent push failed. A remote/network failure sets ``pushed=False``
    and records the reason in ``detail`` but leaves ``ok=True`` — losing the
    push must never look like losing the write (memo §6.2).
    """

    ok: bool
    committed: bool
    pushed: bool
    detail: str

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "committed": self.committed,
            "pushed": self.pushed,
            "detail": self.detail,
        }


def _push(root: Path) -> tuple[bool, str]:
    """Best-effort ``git push`` from ``root``. Returns ``(pushed, detail)``.

    Tolerates the two benign no-op states (same policy as
    :func:`core.roster_sync.pull_lab_mgmt`): a clone with **no remote** (local
    -only, e.g. before ``vault init`` wires GitHub) and a branch with **no
    upstream** (push the current branch to the first remote explicitly).
    """
    try:
        remotes = _run_git(root, "remote")
        remote_names = [r for r in (remotes.stdout or "").split() if r]
        if not remote_names:
            return (False, "no remote configured — local-only vault, nothing to push")
        res = _run_git(root, "push")
        low = (res.stderr or "").lower()
        if res.returncode != 0 and ("no upstream" in low or "no configured push" in low
                                    or "has no upstream" in low):
            branch = _run_git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
            remote = "origin" if "origin" in remote_names else remote_names[0]
            res = _run_git(root, "push", "-u", remote, branch or "HEAD")
    except subprocess.TimeoutExpired:
        return (False, f"git push timed out after {_GIT_TIMEOUT}s")
    except (OSError, subprocess.SubprocessError) as exc:
        return (False, str(exc))
    if res.returncode == 0:
        return (True, "pushed")
    tail = (res.stderr or res.stdout or "").strip().splitlines()
    return (False, tail[-1] if tail else "git push failed")


def commit_and_push(path: str | Path, *, message: str, add_all: bool = True) -> CommitResult:
    """Commit any pending changes under the personal vault and push — best-effort.

    ``path`` may be the vault root or any file/dir inside it. Stages
    (``git add -A`` by default, else just ``path``), commits when there is
    something to commit, then pushes. NEVER raises: a not-a-repo path, a
    nothing-to-commit tree, and a failed push each come back as a
    :class:`CommitResult` the caller can log and move past.
    """
    root = _enclosing_dir(path)
    if not root.exists():
        return CommitResult(ok=False, committed=False, pushed=False,
                            detail=f"path does not exist: {root}")
    try:
        top = _run_git(root, "rev-parse", "--show-toplevel")
    except (OSError, subprocess.SubprocessError) as exc:
        return CommitResult(ok=False, committed=False, pushed=False, detail=str(exc))
    if top.returncode != 0:
        return CommitResult(ok=False, committed=False, pushed=False,
                            detail="not a git repository (nothing to commit or push)")
    worktree = Path(top.stdout.strip() or str(root))

    try:
        if add_all:
            _run_git(worktree, "add", "-A")
        else:
            _run_git(worktree, "add", "--", str(Path(path).expanduser().name))
        status = _run_git(worktree, "status", "--porcelain")
        if not status.stdout.strip():
            # Clean tree: nothing new to commit, but there may be local commits
            # not yet pushed — still attempt a best-effort push.
            pushed, detail = _push(worktree)
            return CommitResult(ok=True, committed=False, pushed=pushed,
                                detail=("nothing to commit; " + detail))
        commit = _run_git(worktree, "commit", "-m", message)
        if commit.returncode != 0:
            tail = (commit.stderr or commit.stdout or "").strip().splitlines()
            return CommitResult(ok=False, committed=False, pushed=False,
                                detail=tail[-1] if tail else "git commit failed")
    except subprocess.TimeoutExpired:
        return CommitResult(ok=False, committed=False, pushed=False,
                            detail=f"git commit timed out after {_GIT_TIMEOUT}s")
    except (OSError, subprocess.SubprocessError) as exc:
        return CommitResult(ok=False, committed=False, pushed=False, detail=str(exc))

    pushed, detail = _push(worktree)
    return CommitResult(ok=True, committed=True, pushed=pushed, detail=detail)


# ---------------------------------------------------------------------------
# Read side — freshness + fast-forward pull (mirrors core.roster_sync)
# ---------------------------------------------------------------------------


@dataclass
class VaultSyncResult:
    """Outcome of one freshness probe or ff-only pull of the personal vault."""

    path: str
    is_git: bool
    ok: bool
    detail: str
    as_of: str = ""

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "is_git": self.is_git,
            "ok": self.ok,
            "detail": self.detail,
            "as_of": self.as_of,
        }


def vault_info() -> VaultSyncResult:
    """Freshness probe only — no network, no mutation.

    Answers "where does this machine's personal vault live and how fresh is it?"
    for the Personal-Oracle panel's "as of <date>" stamp on initial render.
    """
    root = personal_vault_root()
    if root is None:
        return VaultSyncResult(
            path="", is_git=False, ok=False,
            detail="no personal vault registered — run `murmurent vault init` or "
                   "set the vault path in Machine settings",
        )
    if not root.is_dir():
        return VaultSyncResult(
            path=str(root), is_git=False, ok=False,
            detail=f"no personal vault clone at {root} — run `murmurent vault init`",
        )
    if not (root / ".git").exists():
        return VaultSyncResult(
            path=str(root), is_git=False, ok=True,
            detail="personal vault is not a git clone (local-only)",
        )
    return VaultSyncResult(
        path=str(root), is_git=True, ok=True, detail="",
        as_of=_last_commit_iso(root),
    )


def pull_personal_vault() -> VaultSyncResult:
    """Fast-forward the personal-vault clone from its remote.

    ``--ff-only`` on purpose: the personal vault is single-writer *per person*
    but multi-machine, so any divergence means the user edited on two machines —
    refuse-and-say rather than invent a merge. Never raises; tolerates the same
    benign no-op states as :func:`core.roster_sync.pull_lab_mgmt` (no remote /
    no upstream).
    """
    info = vault_info()
    if not info.is_git:
        return info
    root = Path(info.path)

    def _fail(detail: str) -> VaultSyncResult:
        return VaultSyncResult(path=info.path, is_git=True, ok=False,
                               detail=detail, as_of=_last_commit_iso(root))

    try:
        remotes = _run_git(root, "remote")
        remote_names = [r for r in (remotes.stdout or "").split() if r]
        if not remote_names:
            return VaultSyncResult(
                path=info.path, is_git=True, ok=True,
                detail="no remote configured — local-only vault, nothing to pull",
                as_of=_last_commit_iso(root),
            )
        res = _run_git(root, "pull", "--ff-only")
        if res.returncode != 0 and "no tracking information" in (res.stderr or "").lower():
            branch = _run_git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
            remote = "origin" if "origin" in remote_names else remote_names[0]
            res = _run_git(root, "pull", "--ff-only", remote, branch)
    except subprocess.TimeoutExpired:
        return _fail(f"git pull timed out after {_GIT_TIMEOUT}s")
    except (OSError, subprocess.SubprocessError) as exc:
        return _fail(str(exc))

    detail = (res.stdout or res.stderr or "").strip().splitlines()
    return VaultSyncResult(
        path=info.path, is_git=True, ok=res.returncode == 0,
        detail=detail[-1] if detail else ("ok" if res.returncode == 0 else "git pull failed"),
        as_of=_last_commit_iso(root),
    )


__all__ = [
    "CommitResult", "VaultSyncResult", "personal_vault_root",
    "commit_and_push", "vault_info", "pull_personal_vault",
]
