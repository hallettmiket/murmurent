"""
Purpose: Commit + push a single file to its containing git repo.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-15
Input: Absolute path to the file, a commit message.
Output: ``[Probe]`` describing each step. Caller decides whether to
        surface them to the UI or just log them.

Why this exists: dashboard saves (member profile, lab settings) used to
land in the working tree of lab_mgmt and stop there. A re-seed or
``git checkout`` would wipe the edit before it ever made it to a remote.
This helper closes the gap by staging + committing on every save and
attempting a best-effort push. Push failures (no network, no origin,
auth) are not fatal — the local commit is the durable part; push is
just the convenience for multi-machine workflows.

Design choices:
  - Idempotent: running on an unchanged file is a no-op (no empty
    commits, no error).
  - Best-effort push: returns a yellow probe on failure instead of red.
    The PI can ``git push`` manually later.
  - No-op on non-git paths: writing the file when its parent isn't a
    git checkout just skips silently — saves to ``~/.wigamig/`` (which
    is intentionally not git-tracked) still work.
"""

from __future__ import annotations

import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class GitProbe:
    """Minimal Probe shape — mirrors :class:`wigamig.core.preflight.Probe`
    so the same UI rendering works. Kept separate to avoid a circular
    import between preflight (depends on filesystem helpers) and
    git_persist (depends on subprocess git invocations).
    """

    name: str
    status: str  # ok | warn | fail
    detail: str
    required: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _git_root(path: Path) -> Path | None:
    """Return the git toplevel for ``path``, or ``None`` if not a git
    checkout. Used to decide whether to bother with commit/push at all.
    """
    res = subprocess.run(
        ["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"],
        check=False, capture_output=True, text=True,
    )
    if res.returncode != 0:
        return None
    return Path(res.stdout.strip())


def _is_dirty(repo: Path, file_rel: str) -> bool:
    """Does ``file_rel`` differ from HEAD inside ``repo``?

    ``git diff --quiet`` exits 0 when there is no diff, 1 when there is.
    We treat any other return code as 'unknown — assume dirty so we
    attempt a commit and let the commit step report the real error'.
    """
    res = subprocess.run(
        ["git", "-C", str(repo), "diff", "--quiet", "HEAD", "--", file_rel],
        check=False, capture_output=True, text=True,
    )
    return res.returncode != 0


def commit_and_push(
    file_path: Path,
    message: str,
    *,
    push: bool = True,
) -> list[GitProbe]:
    """Stage + commit ``file_path``, then optionally push.

    Returns one probe per step. The caller decides whether to render
    them inline (member/lab settings endpoints do) or just log them.

    Steps:
      1. ``git status`` — locate the repo. Skipped + ``ok`` if the file
         isn't inside a git checkout (e.g. ~/.wigamig saves).
      2. ``git add`` — stage the file.
      3. ``git commit`` — only if there is actually a diff against HEAD;
         skipped silently when the saved values match HEAD exactly.
      4. ``git push`` — best-effort; yellow probe on failure.
    """
    probes: list[GitProbe] = []
    path = Path(file_path)
    repo = _git_root(path)
    if repo is None:
        # Not a git checkout — the file is durable on disk but won't
        # be replicated. That's fine for files we intentionally keep
        # local (machine.yaml et al).
        probes.append(GitProbe(
            name="git",
            status="ok",
            detail="file is outside a git repo — saved to disk only",
            required=False,
        ))
        return probes
    try:
        file_rel = str(path.resolve().relative_to(repo))
    except ValueError:
        probes.append(GitProbe(
            name="git",
            status="warn",
            detail=f"{path} is not under the discovered repo {repo}",
            required=False,
        ))
        return probes

    # Stage. ``git add`` is idempotent and quiet — no separate probe
    # unless it fails (in which case we surface the stderr).
    add = subprocess.run(
        ["git", "-C", str(repo), "add", "--", file_rel],
        check=False, capture_output=True, text=True,
    )
    if add.returncode != 0:
        probes.append(GitProbe(
            name="git add",
            status="fail",
            detail=(add.stderr or add.stdout).strip() or "git add failed",
            required=False,
        ))
        return probes

    if not _is_dirty(repo, file_rel):
        probes.append(GitProbe(
            name="git commit",
            status="ok",
            detail="no changes vs HEAD — nothing to commit",
            required=False,
        ))
        if push:
            probes.append(_push(repo))
        return probes

    commit = subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", message, "--", file_rel],
        check=False, capture_output=True, text=True,
    )
    if commit.returncode != 0:
        probes.append(GitProbe(
            name="git commit",
            status="warn",
            detail=(commit.stderr or commit.stdout).strip() or "git commit failed",
            required=False,
        ))
        # Don't push on a failed commit — there is nothing new to send.
        return probes
    short_sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
        check=False, capture_output=True, text=True,
    ).stdout.strip() or "?"
    probes.append(GitProbe(
        name="git commit",
        status="ok",
        detail=f"{short_sha} — {message}",
        required=False,
    ))

    if push:
        probes.append(_push(repo))
    return probes


def _push(repo: Path) -> GitProbe:
    """Best-effort ``git push``. Yellow probe (not red) on failure so
    the save still looks successful in the UI."""
    # No origin = no push possible; treat as 'ok-skipped' rather than
    # warn so the user doesn't see a yellow row on a deliberately
    # offline lab_mgmt clone.
    origin = subprocess.run(
        ["git", "-C", str(repo), "remote", "get-url", "origin"],
        check=False, capture_output=True, text=True,
    )
    if origin.returncode != 0:
        return GitProbe(
            name="git push",
            status="ok",
            detail="no origin configured — skipped",
            required=False,
        )
    push = subprocess.run(
        ["git", "-C", str(repo), "push"],
        check=False, capture_output=True, text=True, timeout=30,
    )
    if push.returncode == 0:
        return GitProbe(
            name="git push",
            status="ok",
            detail=(push.stderr or push.stdout).strip().splitlines()[-1]
                if (push.stderr or push.stdout).strip() else "pushed",
            required=False,
        )
    return GitProbe(
        name="git push",
        status="warn",
        detail=(
            (push.stderr or push.stdout).strip().splitlines()[-1]
            if (push.stderr or push.stdout).strip()
            else f"push exited {push.returncode}"
        ) + " — commit saved locally; run `git push` manually when ready",
        required=False,
    )
