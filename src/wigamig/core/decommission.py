"""
Purpose: Soft-delete ("decommission") helper for wigamig entities.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-14
Input: kind/name/decommissioner/manual_cleanup_items lists from the
       per-entity archive helpers (projects, machines, installations,
       SEAs, users).
Output: A markdown report at ``~/.wigamig/decommissions/<date>_<kind>_<slug>.md``
        listing what wigamig disconnected and what the user may want to
        clean up by hand.

Why a "decommission report" instead of `rm -rf`?
    wigamig must NEVER delete files in the user's installation. Every
    "remove" action in the dashboard is a *disconnect*: flip a status
    flag, leave the bytes alone, and produce a report so the user can
    decide what (if anything) to clean up manually. The report is
    durable, audit-friendly, and reversible — unarchive flips the flag
    back. See item #15 in the 2026-05-14 dashboard testing list.
"""

from __future__ import annotations

import datetime as _dt
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml


def _decommission_dir() -> Path:
    """Resolve the report dir, env-overridable for test isolation.

    ``$WIGAMIG_DECOMMISSION_DIR`` lets pytest redirect the output to a
    tmp_path so test runs don't pollute the user's real ``~/.wigamig/``.
    """
    env = os.environ.get("WIGAMIG_DECOMMISSION_DIR")
    if env:
        return Path(env).expanduser()
    return Path("~/.wigamig/decommissions").expanduser()


# Resolved at import time for back-compat with anything that reads
# ``DECOMMISSION_DIR`` directly; the *write paths* re-resolve via
# ``_decommission_dir()`` on every call so monkeypatch.setenv works.
DECOMMISSION_DIR = _decommission_dir()


@dataclass(frozen=True)
class CleanupItem:
    """One row in the manual-cleanup checklist."""

    path: str                              # the path/URL/channel name
    note: str                              # what to do with it
    severity: str = "review"               # "review" | "info" | "private"


@dataclass(frozen=True)
class DecommissionRecord:
    """Inputs the helper needs to write a report."""

    kind: str                              # "project" | "machine" | "installation" | "sea" | "user"
    name: str                              # entity short ID (e.g. "mp1")
    decommissioned_by: str                 # @handle of the actor
    cleanup_items: list[CleanupItem] = field(default_factory=list)
    rationale: str = ""                    # optional free-text from the user
    extra_meta: dict[str, str] = field(default_factory=dict)


_SLUG_RE = re.compile(r"[^a-z0-9_]+")


def _slug(text: str) -> str:
    """Lowercase + collapse non-[a-z0-9_] runs to '_'. Bounded length."""
    s = _SLUG_RE.sub("_", text.lower()).strip("_")
    return (s or "unnamed")[:64]


def report_path(record: DecommissionRecord, *, today: _dt.date | None = None) -> Path:
    """Compute the on-disk path for the decommission report.

    Pattern: ``~/.wigamig/decommissions/YYYY-MM-DD_<kind>_<slug>.md``. If
    multiple reports for the same entity land on the same day, an integer
    suffix is appended (``_2``, ``_3``, …) per the project's versioning
    rule — the highest integer is the most recent.
    """
    day = (today or _dt.date.today()).isoformat()
    stem = f"{day}_{_slug(record.kind)}_{_slug(record.name)}"
    candidate = _decommission_dir() / f"{stem}.md"
    if not candidate.exists():
        return candidate
    n = 2
    while True:
        candidate = _decommission_dir() / f"{stem}_{n}.md"
        if not candidate.exists():
            return candidate
        n += 1


def write_report(
    record: DecommissionRecord,
    *,
    today: _dt.date | None = None,
    now: _dt.datetime | None = None,
) -> Path:
    """Write the report to disk and return the path.

    The report is plain markdown with a YAML frontmatter block so it's
    easy to grep + machine-readable. The body is a checklist the user
    can tick off as they handle each cleanup item.
    """
    _decommission_dir().mkdir(parents=True, exist_ok=True)
    path = report_path(record, today=today)
    ts = (now or _dt.datetime.now(_dt.timezone.utc)).isoformat()
    meta = {
        "kind": record.kind,
        "name": record.name,
        "decommissioned_by": record.decommissioned_by,
        "decommissioned_at": ts,
        "reversible": True,
        **record.extra_meta,
    }
    front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
    lines: list[str] = [
        "---", front, "---", "",
        f"# Decommission report — {record.kind} `{record.name}`", "",
        f"Disconnected from wigamig by **{record.decommissioned_by}** at {ts}. ",
        "No files were modified on disk; the entity's metadata was flipped to "
        "`status: archived` so it stops appearing in active dashboards. "
        "Run the matching `unarchive` action to bring it back.",
        "",
    ]
    if record.rationale.strip():
        lines.extend(["## Why", "", record.rationale.strip(), ""])
    if record.cleanup_items:
        lines.extend([
            "## Manual cleanup checklist",
            "",
            "wigamig will NEVER touch these on your behalf. Review each item "
            "and decide whether to delete, archive, or leave alone:",
            "",
        ])
        for item in record.cleanup_items:
            severity_pill = (
                "[private] " if item.severity == "private"
                else "[info] "  if item.severity == "info"
                else ""
            )
            lines.append(f"- [ ] {severity_pill}`{item.path}` — {item.note}")
        lines.append("")
    else:
        lines.extend([
            "## Manual cleanup checklist",
            "",
            "_(none — wigamig did not detect any external resources to review.)_",
            "",
        ])
    lines.extend([
        "## Reverse this",
        "",
        f"From the dashboard's Decommissioned section, click **unarchive** "
        f"on this `{record.kind}` to flip its status back to `active`. The "
        "report stays here as a historical record either way.",
        "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def list_reports(*, kind: str | None = None) -> list[Path]:
    """Return every decommission report on disk, newest first.

    Pass ``kind`` to filter to one entity type. Used by the UI's
    "Decommissioned" section to render the history.
    """
    if not _decommission_dir().is_dir():
        return []
    out = sorted(_decommission_dir().glob("*.md"), reverse=True)
    if kind is None:
        return out
    needle = f"_{_slug(kind)}_"
    return [p for p in out if needle in p.name]
