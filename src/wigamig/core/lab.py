"""
Purpose: Read the lab-mgmt group config (``<lab-mgmt>/lab.md``).
         Replaces the hard-coded ``PI_HANDLE`` / ``LAB_MANAGER_HANDLE``
         constants with a single source of truth that lives next to
         the data and is editable via PR.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-08
Input: ``<lab-mgmt>/lab.md`` markdown with a frontmatter block. The
       file may be missing on a fresh clone; the loader returns a
       sensible default in that case so wigamig still boots.
Output: ``LabConfig`` dataclass with ``lab`` (slug), ``name``,
        ``pi`` (handle stripped of leading ``@``), institution,
        department, slack_workspace.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .frontmatter import parse_file
from .repo import lab_mgmt_repo_root

LAB_FILE = "lab.md"

# Hard-coded fallback used only when ``<lab-mgmt>/lab.md`` is missing
# (e.g. a fresh clone, before ``wigamig install``). Tests reset this
# via ``WIGAMIG_LAB_MGMT_REPO``.
_DEFAULT_LAB = ""  # institution-agnostic: no fabricated fallback lab
_DEFAULT_PI = ""   # institution-agnostic: never invent a PI handle


@dataclass(frozen=True)
class LabConfig:
    """Resolved lab.md contents (handles stripped of leading ``@``)."""

    lab: str
    name: str
    pi: str
    institution: str
    department: str
    slack_workspace: str | None = None
    # GitHub org for this lab's repos. Empty = unconfigured: CLI commands
    # that create/push a GitHub remote must fail safe (refuse) rather than
    # substitute another lab's org.
    github_org: str = ""
    path: Path | None = None


def _strip_at(handle: Any) -> str:
    if not handle:
        return ""
    s = str(handle).strip()
    return s.lstrip("@").lower()


def lab_path() -> Path:
    """Return ``<lab-mgmt>/lab.md`` (file may not exist)."""
    return lab_mgmt_repo_root() / LAB_FILE


def load_lab_config() -> LabConfig:
    """Read ``<lab-mgmt>/lab.md`` once.

    Falls back to a default (lab=hallett, pi=mhallet) when the file is
    missing so wigamig still boots on a fresh checkout. Tests can set
    ``WIGAMIG_LAB_MGMT_REPO`` to point at a fixture dir.
    """
    path = lab_path()
    if not path.is_file():
        # No lab.md yet (fresh checkout, before setup). Return a NEUTRAL config
        # — never fabricate a specific lab's identity (that leaked one real
        # lab's PI/name/institution onto every install).
        return LabConfig(
            lab=_DEFAULT_LAB,
            name="",
            pi=_DEFAULT_PI,
            institution="",
            department="",
            slack_workspace=None,
            path=None,
        )
    meta = parse_file(path).meta or {}
    return LabConfig(
        lab=str(meta.get("lab") or _DEFAULT_LAB),
        name=str(meta.get("name") or ""),
        pi=_strip_at(meta.get("pi") or _DEFAULT_PI),
        institution=str(meta.get("institution") or ""),
        department=str(meta.get("department") or ""),
        slack_workspace=(
            str(meta["slack_workspace"]) if meta.get("slack_workspace") else None
        ),
        github_org=str(meta.get("github_org") or ""),
        path=path,
    )


def pi_handle() -> str:
    """Convenience: just the PI handle (lower-case, no ``@``)."""
    return load_lab_config().pi
