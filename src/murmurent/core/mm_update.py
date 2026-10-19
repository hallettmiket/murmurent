"""
Purpose: Report whether this machine's murmurent install is behind its
         upstream — the data behind the dashboard's "update available" banner
         (issue #41 pt 1).
Author: Mike Hallett (with Claude Code)
Date: 2026-07-21
Input: The murmurent repo the running code comes from (:func:`install_root`)
       + its git remote.
Output: :class:`UpdateStatus` — is there a newer push, and is it a safe
        fast-forward.

Notification-only by design: this fetches and counts, it never pulls or
restarts. The one-click pull + self-restart is a tracked upgrade (issue #41).
Best-effort throughout: an offline remote or a non-git checkout yields a benign
status, never an exception that could wedge the dashboard.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from .repo import murmurent_repo_root

_log = logging.getLogger(__name__)

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
    root: str = ""    # the checkout that was checked (shown in the banner)
    # In words for the banner (#185 follow-up): which copy, the version here and
    # upstream (they differ only after a release), and the new changes' titles.
    name: str = ""            # "murmurent_dev" or the checkout's folder name
    current_version: str = ""
    latest_version: str = ""
    changes: list = None      # up to 10 commit titles, newest first
    # Which branch the copy is on. The check always compares with the main
    # branch on GitHub: a copy left on a merged pull request's branch never
    # saw main move, and once that branch was deleted on GitHub the check had
    # nothing to compare with and the banner silently never appeared.
    branch: str = ""
    on_main: bool = True
    clean: bool = True        # no uncommitted changes to tracked files

    def __post_init__(self) -> None:
        if self.changes is None:
            self.changes = []

    def to_dict(self) -> dict:
        return asdict(self)


def install_root() -> Path:
    """The murmurent checkout whose code this process is running.

    ``$MURMURENT_REPO_ROOT`` wins when set. Otherwise, walk up from this file to
    the enclosing git checkout: an editable install runs from wherever it was
    installed (for a developer, ``murmurent_dev``), so checking the default
    ``~/repos/murmurent`` instead pulled a repo the dashboard was not running
    and the restart changed nothing (#185). Falls back to
    :func:`murmurent_repo_root` for a non-editable install.
    """
    if os.environ.get("MURMURENT_REPO_ROOT"):
        return murmurent_repo_root()
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / ".git").exists() and (parent / "pyproject.toml").is_file():
            return parent
    return murmurent_repo_root()


def _run_git(root, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, timeout=_GIT_TIMEOUT,
    )


def describe_running_code() -> dict:
    """What code this process runs: which checkout, development or release,
    branch and commit. Shown in the dashboard's top bar so a member can tell
    a murmurent_dev checkout from a release install (#185 follow-up).

    ``{label, kind, folder, branch, commit, dirty}``; ``kind`` is ``dev``
    (a checkout of murmurent_dev), ``checkout`` (another git checkout, such as
    a clone of the public release repo) or ``release`` (installed without
    git). Never raises; local git only, no network.
    """
    from .. import __version__
    root = install_root()
    out = {"label": f"release v{__version__}", "kind": "release",
           "folder": str(root), "branch": "", "commit": "", "dirty": False}
    if not (root / ".git").exists():
        return out
    try:
        def git(*a: str) -> str:
            r = subprocess.run(["git", "-C", str(root), *a], capture_output=True,
                               text=True, timeout=5)
            return r.stdout.strip() if r.returncode == 0 else ""
        branch = git("rev-parse", "--abbrev-ref", "HEAD")
        commit = git("rev-parse", "--short", "HEAD")
        dirty = bool(git("status", "--porcelain", "--untracked-files=no"))
    except (OSError, subprocess.SubprocessError):
        return out
    name = _copy_name(root)
    is_dev = name == "murmurent_dev"
    label = f"{name} · {branch} @ {commit}" + (" (edited)" if dirty else "")
    out.update(label=label, kind="dev" if is_dev else "checkout",
               branch=branch, commit=commit, dirty=dirty)
    return out


_VERSION_FILE = "src/murmurent/__init__.py"


def _version_at(root, ref: str) -> str:
    """murmurent's version number as committed at ``ref`` ("" if unreadable)."""
    import re
    try:
        out = _run_git(root, "show", f"{ref}:{_VERSION_FILE}")
    except (OSError, subprocess.SubprocessError):
        return ""
    m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', out.stdout or "", re.M)
    return m.group(1) if m else ""


def _copy_name(root) -> str:
    """"murmurent_dev" for a development checkout, else the folder's name."""
    try:
        remote = _run_git(root, "remote", "get-url", "origin").stdout
    except (OSError, subprocess.SubprocessError):
        remote = ""
    if "murmurent_dev" in remote or Path(root).name == "murmurent_dev":
        return "murmurent_dev"
    return Path(root).name


def _main_ref(root) -> tuple[str, str]:
    """``(remote ref, local branch name)`` of the main branch, e.g.
    ``("origin/main", "main")``; ``("", "")`` when there is none."""
    head = _run_git(root, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    ref = head.stdout.strip() if head.returncode == 0 else ""
    if not ref:
        for name in ("main", "master"):
            if _run_git(root, "rev-parse", "--verify", "--quiet",
                        f"refs/remotes/origin/{name}").returncode == 0:
                ref = f"origin/{name}"
                break
    return (ref, ref.split("/", 1)[1]) if "/" in ref else ("", "")


def check_update(*, fetch: bool = True) -> UpdateStatus:
    """Whether the local murmurent install is behind the main branch on GitHub.

    ``fetch=True`` (default) refreshes remote-tracking refs first so a brand-new
    push is seen; ``fetch=False`` compares against whatever was last fetched
    (instant, no network). Always compares with the main branch, whichever
    branch the copy is on. Never raises.
    """
    root = install_root()

    def _na(detail: str, *, is_git: bool = True, ok: bool = False) -> UpdateStatus:
        return UpdateStatus(is_git=is_git, ok=ok, behind=0, can_ff=False,
                            current="", latest="", detail=detail, root=str(root))

    if not (root / ".git").exists():
        return _na("not a git checkout — nothing to update", is_git=False)

    try:
        if fetch:
            fetched = _run_git(root, "fetch", "--quiet")
            if fetched.returncode != 0:
                # Offline / auth failure — report gracefully rather than erroring.
                return _na("couldn't reach the remote (offline?)")
        upstream, main_name = _main_ref(root)
        if not upstream:
            return _na("no main branch on GitHub to compare against")
        branch = _run_git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        on_main = branch == main_name
        dirty = _run_git(root, "status", "--porcelain", "--untracked-files=no")
        clean = dirty.returncode == 0 and not dirty.stdout.strip()

        current = _run_git(root, "rev-parse", "--short", "HEAD").stdout.strip()
        latest = _run_git(root, "rev-parse", "--short", upstream).stdout.strip()

        counted = _run_git(root, "rev-list", "--count", f"HEAD..{upstream}")
        behind = int(counted.stdout.strip() or "0") if counted.returncode == 0 else 0

        # Safe to bring up to date only when everything here is already in main
        # (no local commits of its own), so nothing can be lost.
        can_ff = _run_git(root, "merge-base", "--is-ancestor",
                          "HEAD", upstream).returncode == 0
        if not on_main:
            # Leaving a branch also needs a clean copy, so nothing uncommitted
            # is carried across or refused half way.
            can_ff = can_ff and clean

        detail = "up to date" if behind == 0 else f"{behind} new commit(s) upstream"
        if not on_main:
            detail += f" — this copy is on the branch {branch}, not {main_name}"
            if behind and not can_ff:
                detail += ("; it has changes of its own or uncommitted edits, so switch "
                           f"to {main_name} yourself")
        elif behind and not can_ff:
            detail += " — local has diverged, resolve manually"
        changes: list[str] = []
        if behind:
            log = _run_git(root, "log", "--no-merges", "--format=%s", "-n", "10",
                           f"HEAD..{upstream}")
            changes = [ln for ln in log.stdout.splitlines() if ln.strip()] if log.returncode == 0 else []
        latest_version = _version_at(root, upstream)
        return UpdateStatus(is_git=True, ok=True, behind=behind, can_ff=can_ff,
                            current=current, latest=latest, detail=detail,
                            root=str(root), name=_copy_name(root),
                            current_version=_version_at(root, "HEAD"),
                            latest_version=latest_version, changes=changes,
                            branch=branch, on_main=on_main, clean=clean)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return _na(f"update check failed: {exc}")


def apply_update() -> dict:
    """Fast-forward the local murmurent install to upstream. Does NOT restart —
    the caller schedules that after the HTTP response flushes.

    **Scope is deliberately narrow — this only updates code, never user data.**
    It runs ``git pull --ff-only`` inside the murmurent repo the dashboard runs
    from (:func:`install_root`) and nothing else. User identity/profile/tokens/keys live in
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
        if not st.on_main:
            return {**base, "ok": False, "detail": st.detail}
        return {**base, "ok": False,
                "detail": "local has diverged from upstream — resolve manually; "
                          "not pulling (your local commits are untouched)"}

    root = install_root()
    try:
        if not st.on_main:
            # Everything on this branch is already in main (checked above), so
            # switching back loses nothing. The branch itself is kept.
            upstream, main_name = _main_ref(root)
            switched = _run_git(root, "checkout", main_name)
            if switched.returncode != 0:
                err = (switched.stderr or switched.stdout or "git checkout failed").strip()
                return {**base, "ok": False, "detail": err.splitlines()[-1][:200]}
            pull = _run_git(root, "merge", "--ff-only", upstream)
        else:
            pull = _run_git(root, "pull", "--ff-only")
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
    socket is released and the new process re-binds the port.

    Re-runs the interpreter with its exact original arguments
    (``sys.orig_argv``), so ``murmurent dashboard``, ``python -m …`` and a
    systemd unit all restart the same way. ``os.execv(sys.argv[0], …)`` failed
    for ``python -m``, where ``argv[0]`` is a non-executable ``.py`` file, and
    the error vanished in the timer thread (#185).
    """
    args = [sys.executable, *sys.orig_argv[1:]]
    try:
        os.execv(sys.executable, args)
    except OSError as exc:
        _log.error("dashboard restart failed (%s); still running the old code", exc)
