"""
Purpose: keep a repo's ``.claude/agents/`` links to the commons on the machine
         that made them (issue #150).
Author: Mike Hallett (with Claude Code)
Date: 2026-10-14
Input: a repo working tree
Output: a managed ``.gitignore`` block; lists of offending links for the push
        guards, ``murmurent repo status`` and ``repo upgrade`` to report

``murmurent repo adopt`` links the picked commons agents into
``<repo>/.claude/agents/`` by ABSOLUTE path into this member's own copy of the
commons, e.g. ``/home/<me>/repos/murmurent/agents/bookworm.md``. Git stores a
symbolic link as the path it points to, so a committed link sends every other
member's copy of the repo into someone else's home folder, which they usually
cannot read. Claude Code prefers a repo's own agent file to the one in
``~/.claude/agents/``, so those agents then fail for them with no warning.

Three defences live here:

* :func:`update_gitignore` writes one ``.gitignore`` line per linked agent, by
  name. A pattern cannot tell a link from a file, and a group's own tuned agents
  are ordinary files in the same folder that MUST stay committable, so the
  block names exactly the links murmurent made and nothing else.
* :func:`is_machine_link` is what the push guards ask before staging a path.
* :func:`tracked_machine_links` finds links that were committed before the
  block existed, so ``repo status`` and ``repo upgrade`` can say how to repair.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

AGENTS_REL = ".claude/agents"
BLOCK_BEGIN = "# >>> murmurent: per-machine agent links, never commit (issue #150)"
BLOCK_END = "# <<< murmurent agent links"

#: Git's file mode for a symbolic link.
_SYMLINK_MODE = "120000"


def _points_outside(repo: Path, link_parent: Path, target: str) -> bool:
    """True when ``target`` (as stored in a link under ``link_parent``)
    resolves somewhere outside ``repo``."""
    t = Path(target)
    if not t.is_absolute():
        t = link_parent / t
    try:
        Path(os.path.normpath(t)).relative_to(os.path.normpath(repo.resolve()))
    except ValueError:
        return True
    return False


def is_machine_link(repo: Path, rel_path: str) -> bool:
    """True if ``rel_path`` is a link under ``.claude/agents/`` that points
    outside ``repo``: the kind that only works on the machine that made it."""
    rel = rel_path.strip().strip('"')
    if not rel.startswith(AGENTS_REL + "/"):
        return False
    p = repo / rel
    if not p.is_symlink():
        return False
    try:
        target = os.readlink(p)
    except OSError:
        return False
    return _points_outside(repo, p.parent, target)


def tracked_machine_links(repo: Path) -> list[tuple[str, str]]:
    """``(path, target)`` for every link under ``.claude/agents/`` that git
    TRACKS and that points outside the repo. Read from git's index, not the
    disk, so a link already repaired on disk but still committed is found.

    Returns ``[]`` when ``repo`` is not a git repository or git is missing.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "ls-files", "-s", "--", AGENTS_REL],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode != 0:
        return []
    found: list[tuple[str, str]] = []
    for line in out.stdout.splitlines():
        meta, _, path = line.partition("\t")
        fields = meta.split()
        if len(fields) < 2 or fields[0] != _SYMLINK_MODE:
            continue
        blob = subprocess.run(
            ["git", "-C", str(repo), "cat-file", "-p", fields[1]],
            capture_output=True, text=True, timeout=10, check=False,
        )
        target = blob.stdout.strip()
        if blob.returncode == 0 and _points_outside(repo, (repo / path).parent, target):
            found.append((path, target))
    return found


def repair_hint(repo: Path) -> str:
    """The two steps that undo a committed link, in plain words."""
    return (
        f"Stop tracking them (this leaves your own copies alone): "
        f"git -C {repo} rm --cached -q {AGENTS_REL}/<name>.md for each one, then "
        f"commit and push. Everyone else working in this repo then runs "
        f"`murmurent repo upgrade {repo}` straight after their next pull, which "
        f"re-creates their own links."
    )


def update_gitignore(repo: Path, linked: list[str]) -> bool:
    """Make ``repo/.gitignore`` hold exactly one managed block naming
    ``.claude/agents/<name>.md`` for each name in ``linked``.

    The block is rewritten in place on every call, so an agent dropped from the
    pick leaves the list. An empty ``linked`` removes the block. Everything
    outside the block is left as it was. Returns True if the file changed.
    """
    gi = repo / ".gitignore"
    text = gi.read_text(encoding="utf-8") if gi.is_file() else ""
    lines = text.splitlines()

    kept: list[str] = []
    inside = False
    for ln in lines:
        if ln.strip() == BLOCK_BEGIN:
            inside = True
            continue
        if inside:
            if ln.strip() == BLOCK_END:
                inside = False
            continue
        kept.append(ln)
    while kept and not kept[-1].strip():
        kept.pop()

    if linked:
        if kept:
            kept.append("")
        kept.append(BLOCK_BEGIN)
        kept.extend(f"{AGENTS_REL}/{n}.md" for n in sorted(set(linked)))
        kept.append(BLOCK_END)

    new = "\n".join(kept) + "\n" if kept else ""
    if new == text:
        return False
    if not new and not gi.exists():
        return False
    gi.write_text(new, encoding="utf-8")
    return True
