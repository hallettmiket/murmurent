"""
Purpose: Report whether this machine's murmurent install (``~/repos/murmurent``)
         is behind its upstream — the data behind the dashboard's "update
         available" banner (issue #41 pt 1).
Author: Mike Hallett (with Claude Code)
Date: 2026-07-21
Input: The murmurent repo on disk (``murmurent_repo_root()``) + its git remote.
Output: :class:`UpdateStatus` — is there a newer push, and is it a safe
        fast-forward.

Notification-only by design: this fetches and counts, it never pulls or
restarts. The one-click pull + self-restart is a tracked upgrade (issue #41).
Best-effort throughout: an offline remote or a non-git checkout yields a benign
status, never an exception that could wedge the dashboard.
"""

from __future__ import annotations

import subprocess
from dataclasses import asdict, dataclass

from .repo import murmurent_repo_root

# A status poll hits the network (git fetch); keep it snappy so an unreachable
# remote can't hang the dashboard load.
_GIT_TIMEOUT = 20


@dataclass
class UpdateStatus:
    """Outcome of one upstream-freshness check of the murmurent install."""

    is_git: bool      # False → not a git checkout, nothing to update
    ok: bool          # the check ran end to end (a failed fetch → False)
    behind: int       # commits upstream has that local doesn't (0 → current)
    can_ff: bool      # local HEAD is a strict ancestor of upstream (safe ff pull)
    current: str      # short local HEAD sha
    latest: str       # short upstream sha
    detail: str       # human-readable one-liner

    def to_dict(self) -> dict:
        return asdict(self)


def _run_git(root, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, timeout=_GIT_TIMEOUT,
    )


def check_update(*, fetch: bool = True) -> UpdateStatus:
    """Whether the local murmurent install is behind upstream.

    ``fetch=True`` (default) refreshes remote-tracking refs first so a brand-new
    push is seen; ``fetch=False`` compares against whatever was last fetched
    (instant, no network). Never raises.
    """
    root = murmurent_repo_root()

    def _na(detail: str, *, is_git: bool = True, ok: bool = False) -> UpdateStatus:
        return UpdateStatus(is_git=is_git, ok=ok, behind=0, can_ff=False,
                            current="", latest="", detail=detail)

    if not (root / ".git").exists():
        return _na("not a git checkout — nothing to update", is_git=False)

    try:
        up = _run_git(root, "rev-parse", "--abbrev-ref",
                      "--symbolic-full-name", "@{u}")
        if up.returncode != 0:
            return _na("current branch has no upstream to compare against")
        upstream = up.stdout.strip()

        if fetch:
            fetched = _run_git(root, "fetch", "--quiet")
            if fetched.returncode != 0:
                # Offline / auth failure — report gracefully rather than erroring.
                return _na("couldn't reach the remote (offline?)")

        current = _run_git(root, "rev-parse", "--short", "HEAD").stdout.strip()
        latest = _run_git(root, "rev-parse", "--short", upstream).stdout.strip()

        counted = _run_git(root, "rev-list", "--count", f"HEAD..{upstream}")
        behind = int(counted.stdout.strip() or "0") if counted.returncode == 0 else 0

        # Safe to `git pull --ff-only` only when local is a strict ancestor of
        # upstream (no local commits / divergence — cf. the force-push case).
        can_ff = _run_git(root, "merge-base", "--is-ancestor",
                          "HEAD", upstream).returncode == 0

        detail = "up to date" if behind == 0 else f"{behind} new commit(s) upstream"
        if behind and not can_ff:
            detail += " — local has diverged, resolve manually"
        return UpdateStatus(is_git=True, ok=True, behind=behind, can_ff=can_ff,
                            current=current, latest=latest, detail=detail)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return _na(f"update check failed: {exc}")


def apply_update() -> dict:
    """Fast-forward the local murmurent install to upstream. Does NOT restart —
    the caller schedules that after the HTTP response flushes.

    **Scope is deliberately narrow — this only updates code, never user data.**
    It runs ``git pull --ff-only`` inside the murmurent repo (``~/repos/
    murmurent``) and nothing else. User identity/profile/tokens/keys live in
    ``~/.murmurent``, the roster in its own clone, and data under the data root —
    all *outside* this repo, so a pull cannot reach them. ``--ff-only`` refuses
    to overwrite: if local commits have diverged, or uncommitted changes would
    conflict, it aborts and reports rather than clobbering. Untracked files (e.g.
    a nested ``murmurent_lab_mgmt_*``) are never touched by git.

    Returns ``{ok, pulled, restart, detail, from, to}`` — ``restart`` True only
    when a fast-forward actually happened.
    """
    st = check_update(fetch=True)
    base = {"pulled": False, "restart": False, "from": st.current, "to": st.latest}

    if not st.is_git:
        return {**base, "ok": False, "detail": "not a git checkout — nothing to update"}
    if not st.ok:
        return {**base, "ok": False, "detail": st.detail}
    if st.behind == 0:
        return {**base, "ok": True, "detail": "already up to date"}
    if not st.can_ff:
        # Never force over a diverged / dirty install — surface it instead.
        return {**base, "ok": False,
                "detail": "local has diverged from upstream — resolve manually; "
                          "not pulling (your local commits are untouched)"}

    try:
        pull = _run_git(murmurent_repo_root(), "pull", "--ff-only")
    except (OSError, subprocess.SubprocessError) as exc:
        return {**base, "ok": False, "detail": f"git pull failed: {exc}"}
    if pull.returncode != 0:
        # e.g. uncommitted changes that would be overwritten — git refused, safe.
        err = (pull.stderr or pull.stdout or "git pull --ff-only failed").strip()
        return {**base, "ok": False, "detail": err.splitlines()[-1][:200]}

    return {**base, "ok": True, "pulled": True, "restart": True,
            "detail": f"updated {st.current} → {st.latest}; restarting"}


def reexec() -> None:
    """Replace the running process with a fresh copy of itself so the just-pulled
    code takes effect. Python's sockets are close-on-exec, so the old listening
    socket is released and the new process re-binds the port. Preserves the exact
    launch command (``sys.argv``) — port, ``--hifi``, etc."""
    import os
    import sys

    os.execv(sys.argv[0], sys.argv)
