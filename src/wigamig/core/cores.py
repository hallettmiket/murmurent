"""
Purpose: Cores registry — enumerate the service cores registered at
         lab_mgmt/cores/<core>/core.md and expose their summary
         metadata for the dashboard + future MCPs.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-21
Input: ``lab_mgmt/cores/*/core.md`` files (frontmatter parsed via
       core.frontmatter).
Output: ``CoreSummary`` dataclass per core; lightweight enumerate
        helper for the registrar dashboard.

This module is the cores-side analogue of :mod:`core.projects` /
:mod:`core.membership`. It is read-only by design; mutation of the
cores registry (add/remove cores, rotate leader, add staff) goes
through the registrar HTTP endpoints (Phase 1 of the cores rollout
per docs/cores_plan.md §11) so each change lands one git commit at
a time on lab_mgmt with an audit-log entry.

The minimal Phase 0 contract: enumerate cores + read their top-level
frontmatter. Service catalog enumeration (Phase 2) gets its own
module to keep this one focused.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .frontmatter import parse_file
from .repo import lab_mgmt_repo_root


CORES_SUBDIR = "cores"
CORE_ENTRY_FILENAME = "core.md"


@dataclass
class CoreSummary:
    """Minimal core record the registrar dashboard renders.

    Mirrors the fields of :class:`core.projects.ProjectSummary` so the
    registrar UI can treat cores and projects with the same template.
    """

    name: str                        # short id, matches dir name (e.g. "biocore")
    display_name: str                # human label ("BioCORE")
    leader: str                      # "@handle"
    members: list[str] = field(default_factory=list)
    status: str = "active"           # "active" | "archived"
    description: str = ""
    website: str | None = None
    capabilities: list[str] = field(default_factory=list)
    service_modes: list[str] = field(default_factory=list)
    data_root: str | None = None
    path: Path | None = None         # path to the core.md file
    body: str = ""                   # markdown body (kept so registrar
                                      # can show a description preview)


def cores_dir() -> Path:
    """Return ``<lab_mgmt>/cores/``."""
    return lab_mgmt_repo_root() / CORES_SUBDIR


def core_path(name: str) -> Path:
    """Return the canonical ``cores/<name>/core.md`` path for ``name``."""
    return cores_dir() / name / CORE_ENTRY_FILENAME


def iter_cores(*, include_archived: bool = False) -> list[CoreSummary]:
    """Enumerate registered cores. Empty list when no cores/ dir exists.

    Defensive against malformed files: a core.md that fails to parse
    is silently skipped (consistent with how :func:`iter_members`
    handles bad member files).
    """
    root = cores_dir()
    if not root.is_dir():
        return []
    out: list[CoreSummary] = []
    for sub in sorted(root.iterdir()):
        if not sub.is_dir():
            continue
        entry = sub / CORE_ENTRY_FILENAME
        if not entry.is_file():
            continue
        try:
            parsed = parse_file(entry)
        except Exception:
            continue
        meta = parsed.meta or {}
        # ``kind: core`` is the canonical marker; defensive: skip files
        # that ended up here but aren't actually cores (e.g. a stale
        # lab.md mis-placed under cores/).
        if str(meta.get("kind") or "").lower() != "core":
            continue
        status = str(meta.get("status") or "active").lower()
        if status == "archived" and not include_archived:
            continue
        name = str(meta.get("core") or sub.name)
        out.append(CoreSummary(
            name=name,
            display_name=str(meta.get("name") or name),
            leader=str(meta.get("leader") or ""),
            members=[str(h) for h in (meta.get("members") or [])],
            status=status,
            description=str(meta.get("description") or "").strip(),
            website=meta.get("website") or None,
            capabilities=[str(c) for c in (meta.get("capabilities") or [])],
            service_modes=[str(s) for s in (meta.get("service_modes") or [])],
            data_root=meta.get("data_root") or None,
            path=entry,
            body=parsed.body or "",
        ))
    return out


def get_core(name: str) -> CoreSummary | None:
    """Single-core lookup by short id. Returns None when missing."""
    for c in iter_cores(include_archived=True):
        if c.name == name:
            return c
    return None


__all__ = [
    "CORES_SUBDIR",
    "CORE_ENTRY_FILENAME",
    "CoreSummary",
    "cores_dir",
    "core_path",
    "iter_cores",
    "get_core",
]
