"""
Purpose: Render and update experiment ``notebook.md`` entries.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-07
Input: Experiment metadata (project, slug, performer, status); ingest results
       (raw and instrument-output paths with SHA-256 sums).
Output: Markdown text for new notebooks; updated frontmatter dicts on existing
        notebooks after ingest.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

CHUNK_SIZE = 1 << 16

VALID_STATUSES: tuple[str, ...] = (
    "planned",
    "running",
    "complete",
    "failed",
    "inconclusive",
)
VALID_ANALYSIS_STATUSES: tuple[str, ...] = (
    "not_started",
    "examined",
    "concluded",
)


@dataclass(frozen=True)
class ChecksumEntry:
    """One file with its SHA-256 hex digest."""

    path: Path
    sha256: str


def sha256_file(path: str | Path) -> str:
    """Return the SHA-256 hex digest of ``path``."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


def render_notebook(
    *,
    project: str,
    experiment: str,
    date: str,
    performer: list[str],
    status: str = "planned",
    analysis_status: str = "not_started",
    protocol: str | None = None,
    equipment: list[str] | None = None,
    reagents: list[str] | None = None,
    tags: list[str] | None = None,
) -> str:
    """Render a ``notebook.md`` entry with frontmatter pre-filled.

    Required frontmatter is per the design (`group_level.md` § notebook.md). All
    list-type fields default to empty (`[]`); they're filled in by the experiment
    owner and the ingest verb.
    """
    if status not in VALID_STATUSES:
        raise ValueError(f"status must be one of {VALID_STATUSES!r}; got {status!r}")
    if analysis_status not in VALID_ANALYSIS_STATUSES:
        raise ValueError(
            f"analysis_status must be one of {VALID_ANALYSIS_STATUSES!r}; "
            f"got {analysis_status!r}"
        )

    performer_yaml = ", ".join(repr(p) for p in performer)
    equipment_yaml = ", ".join(repr(e) for e in (equipment or []))
    reagents_yaml = ", ".join(repr(r) for r in (reagents or []))
    tags_yaml = ", ".join(repr(t) for t in (tags or []))
    protocol_line = f"protocol: '{protocol}'\n" if protocol else "protocol: null\n"

    return (
        "---\n"
        f"experiment: {experiment}\n"
        f"date: {date}\n"
        f"performer: [{performer_yaml}]\n"
        f"project: '[[{project}]]'\n"
        f"{protocol_line}"
        f"equipment: [{equipment_yaml}]\n"
        f"reagents: [{reagents_yaml}]\n"
        "immutable_data: []\n"
        "append_only_data: []\n"
        "instrument_outputs: []\n"
        "checksums: {}\n"
        f"status: {status}\n"
        f"analysis_status: {analysis_status}\n"
        "examined_at: null\n"
        "concluded_at: null\n"
        f"tags: [{tags_yaml}]\n"
        "---\n\n"
        f"# {experiment}\n\n"
        "_Brief description of the experiment goes here._\n\n"
        "## Plan\n\n"
        "## Procedure\n\n"
        "## Notes\n\n"
        "## Outcome\n"
    )


def update_with_ingest(
    meta: dict[str, Any],
    *,
    raw_files: Iterable[ChecksumEntry],
    instrument_files: Iterable[ChecksumEntry],
) -> dict[str, Any]:
    """Return a copy of ``meta`` with immutable / instrument / checksum fields set.

    Existing entries are merged: paths are deduplicated and the checksums map is
    extended (new digests overwrite old ones for the same path, which is the
    desired behaviour after a re-ingest).

    Dual-name transition: writes the new ``immutable_data`` field but still reads
    a legacy ``raw_data`` field if present (migrating it to the new name).
    """
    updated = dict(meta)
    # Read new name first; fall back to the legacy ``raw_data`` for back-compat.
    immutable_paths = list(updated.get("immutable_data") or updated.get("raw_data") or [])
    instr_paths = list(updated.get("instrument_outputs") or [])
    checksums = dict(updated.get("checksums") or {})

    for entry in raw_files:
        s = str(entry.path)
        if s not in immutable_paths:
            immutable_paths.append(s)
        checksums[s] = entry.sha256
    for entry in instrument_files:
        s = str(entry.path)
        if s not in instr_paths:
            instr_paths.append(s)
        checksums[s] = entry.sha256

    updated["immutable_data"] = immutable_paths
    updated.pop("raw_data", None)  # migrate legacy field to the new name
    updated["instrument_outputs"] = instr_paths
    updated["checksums"] = checksums
    return updated
