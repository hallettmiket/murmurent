"""
Purpose: Keep the local lab_mgmt clone fresh so the roster (and every
        other lab-mgmt-backed panel) reflects what the PI last pushed.
Author: Mike Hallett (with Claude Code)
Date: 2026-07-14
Input: The lab_mgmt clone at :func:`core.repo.lab_mgmt_repo_root`.
Output: :class:`RosterSyncResult` — did the pull work, and how fresh is
        the roster now.

Every lab member has a read-only clone of lab_mgmt (docs/lab_mgmt.md);
the PI pushes roster changes to GitHub. This module is the member-side
"query the PI": a fast-forward-only ``git pull`` plus a freshness stamp.
Used by the dashboard's Lab Members update button
(``POST /api/members/refresh``) and by ``murmurent reconcile`` so the
daily routine keeps the roster current without anyone clicking anything.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .repo import lab_mgmt_repo_root

_GIT_TIMEOUT = 60  # seconds; a hung SSH/https remote must not wedge the dashboard


@dataclass
class RosterSyncResult:
    """Outcome of one pull (or freshness probe) of the lab_mgmt clone."""

    path: str            # the lab_mgmt clone this ran against
    is_git: bool         # False → plain dir (nothing to pull)
    ok: bool             # pull succeeded (or, for info(), repo readable)
    detail: str          # human-readable one-liner ("Already up to date.", error, …)
    as_of: str = ""      # ISO timestamp of the newest lab_mgmt commit ("" if unknown)

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "is_git": self.is_git,
            "ok": self.ok,
            "detail": self.detail,
            "as_of": self.as_of,
        }


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


def roster_info() -> RosterSyncResult:
    """Freshness probe only — no network, no mutation.

    Answers "where does this machine's roster come from and how old is
    it?" for the Lab Members panel's as-of stamp on initial render.
    """
    root = lab_mgmt_repo_root()
    if not root.is_dir():
        return RosterSyncResult(
            path=str(root), is_git=False, ok=False,
            detail=f"no lab_mgmt clone at {root} — clone it per docs/lab_mgmt.md",
        )
    if not (root / ".git").exists():
        return RosterSyncResult(
            path=str(root), is_git=False, ok=True,
            detail="lab_mgmt is not a git clone (local-only roster)",
        )
    return RosterSyncResult(
        path=str(root), is_git=True, ok=True, detail="",
        as_of=_last_commit_iso(root),
    )


def pull_lab_mgmt() -> RosterSyncResult:
    """Fast-forward the lab_mgmt clone from its remote.

    ``--ff-only`` on purpose: a member's clone is read-only, so any
    divergence means local hand-edits — refuse and say so rather than
    inventing a merge on the member's behalf. Never raises; the result
    carries the failure so callers (dashboard button, reconcile) can
    surface it without dying.

    Tolerated states (``ok=True``, nothing pulled):
      - clone has **no remote** — local-only lab_mgmt (e.g. the PI's
        machine before the repo is pushed to GitHub, or a solo lab);
      - branch has **no upstream** but a remote exists — we pull the
        current branch from the first remote explicitly instead of
        failing with git's set-upstream hint.
    """
    info = roster_info()
    if not info.is_git:
        return info
    root = Path(info.path)

    def _fail(detail: str) -> RosterSyncResult:
        return RosterSyncResult(path=info.path, is_git=True, ok=False,
                                detail=detail, as_of=_last_commit_iso(root))

    try:
        remotes = _run_git(root, "remote")
        remote_names = [r for r in (remotes.stdout or "").split() if r]
        if not remote_names:
            return RosterSyncResult(
                path=info.path, is_git=True, ok=True,
                detail="no remote configured — local-only lab_mgmt, nothing to pull",
                as_of=_last_commit_iso(root),
            )
        res = _run_git(root, "pull", "--ff-only")
        if res.returncode != 0 and "no tracking information" in (res.stderr or "").lower():
            # Remote exists but the branch has no upstream: pull the
            # current branch from the first remote explicitly.
            branch = _run_git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
            remote = "origin" if "origin" in remote_names else remote_names[0]
            res = _run_git(root, "pull", "--ff-only", remote, branch)
    except subprocess.TimeoutExpired:
        return _fail(f"git pull timed out after {_GIT_TIMEOUT}s")
    except (OSError, subprocess.SubprocessError) as exc:
        return _fail(str(exc))

    detail = (res.stdout or res.stderr or "").strip().splitlines()
    return RosterSyncResult(
        path=info.path, is_git=True, ok=res.returncode == 0,
        detail=detail[-1] if detail else ("ok" if res.returncode == 0 else "git pull failed"),
        as_of=_last_commit_iso(root),
    )
