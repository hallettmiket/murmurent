"""
Purpose: locate the murmurent commons (agents, rules, skills, templates),
         whether murmurent was installed from a git clone or from a wheel.
Author: Mike Hallett (with Claude Code)
Date: 2026-09-01
Input: $MURMURENT_REPO_ROOT / $MURMURENT_COMMONS_ROOT, or the installed package
Output: a Path whose children are ``agents/``, ``rules/``, ``skills/``, ``templates/``

Until 2026.9.3 the commons could only come from a clone, so
``pip``/``uv tool install murmurent`` produced a CLI with nothing to wire into
``~/.claude/`` and every install needed ``git clone`` first. The wheel now
force-includes the commons under ``murmurent/commons/`` and this module is what
finds them.

A CLONE WINS OVER THE PACKAGED COPY, always. Editing an agent in your clone has
to be what the next session loads; if the packaged copy could win, a developer
would edit a file and see no effect, which is the worst failure this could have.
The packaged copy is the fallback for people who never cloned anything.
"""

from __future__ import annotations

import os
from pathlib import Path

from .repo import murmurent_repo_root

#: Subdirectories that make a directory recognisably "the commons".
COMMONS_DIRS = ("agents", "rules", "skills")


def _looks_like_commons(path: Path) -> bool:
    """True when ``path`` holds the commons, rather than merely existing.

    Checked by CONTENT, not by name or by the directory being present: an empty
    ``~/repos/murmurent`` left behind by a failed clone must not out-rank the
    packaged copy and leave a member with no agents.
    """
    return all((path / d).is_dir() for d in COMMONS_DIRS) and any(
        (path / "agents").glob("*.md")
    )


def packaged_commons_root() -> Path:
    """The commons shipped inside the installed wheel."""
    return Path(__file__).resolve().parent.parent / "commons"


def commons_root() -> Path:
    """Where to read agents, rules and skills from.

    Resolution order, first hit wins:

    1. ``$MURMURENT_COMMONS_ROOT`` — an explicit override, for tests and for
       unusual installs. Honoured even if it does not look like the commons,
       because an override that is silently ignored is worse than one that
       fails loudly downstream.
    2. The murmurent clone (``$MURMURENT_REPO_ROOT`` or ``~/repos/murmurent``),
       **if it actually contains the commons**.
    3. The copy inside the installed package.

    Falls back to (2) when nothing qualifies, so error messages still name the
    clone people expect rather than a path inside site-packages.
    """
    override = os.environ.get("MURMURENT_COMMONS_ROOT")
    if override:
        return Path(override).expanduser()

    clone = murmurent_repo_root()
    if _looks_like_commons(clone):
        return clone

    packaged = packaged_commons_root()
    if _looks_like_commons(packaged):
        return packaged

    return clone


def commons_source() -> str:
    """``"clone"``, ``"package"`` or ``"override"`` — for install output.

    Someone whose agents are wrong needs to know which copy they are reading.
    """
    if os.environ.get("MURMURENT_COMMONS_ROOT"):
        return "override"
    root = commons_root()
    try:
        if root.resolve() == packaged_commons_root().resolve():
            return "package"
    except OSError:
        pass
    return "clone"
