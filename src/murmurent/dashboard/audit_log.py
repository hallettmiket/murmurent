"""
Purpose: Read + write the lab-management audit chain at
         ``<lab-mgmt>/audit/<YYYY-MM-DD>.jsonl``. Phase 5 surfaces these
         rows as the dashboard's notifications feed.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-08
Input: Append-only JSONL files; one event per line.
Output: ``Event`` dataclasses sorted newest-first.

This is **not** the per-machine ``~/.claude/wigamig-audit/`` log used by
the PostToolUse hook (that one captures every Claude tool call). The
chain here records *domain* events the lab cares about — SEA lifecycle
transitions, project membership changes, oracle publishes — and is
committed to the lab-mgmt repo so every member sees the same history.

Each row is a JSON object with these required keys:

    ts         ISO-8601 UTC timestamp
    actor      ``@handle`` of the person triggering the event
    kind       dotted event name, e.g. ``sea.claim``, ``sea.complete``
    project    project repo name, or ``""`` if lab-wide
    target     domain target, e.g. ``sea/4``, ``inventory/4_oht``
    summary    human-readable one-liner for the dashboard

Optional keys are forward-compatible (writers may add; readers ignore).
"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from ..core.repo import lab_mgmt_repo_root

AUDIT_SUBDIR = "audit"
AUDIT_DATE_FMT = "%Y-%m-%d"


@dataclass(frozen=True)
class Event:
    """One row from the audit chain."""

    ts: _dt.datetime
    actor: str
    kind: str
    project: str
    target: str
    summary: str

    @classmethod
    def from_dict(cls, raw: dict) -> "Event":
        return cls(
            ts=_parse_ts(raw.get("ts", "")) or _dt.datetime.now(_dt.timezone.utc),
            actor=str(raw.get("actor", "")),
            kind=str(raw.get("kind", "")),
            project=str(raw.get("project", "")),
            target=str(raw.get("target", "")),
            summary=str(raw.get("summary", "")),
        )


# ---------------------------------------------------------------------------
# write
# ---------------------------------------------------------------------------


def audit_dir() -> Path:
    """Resolve ``<lab-mgmt>/audit/``."""
    return lab_mgmt_repo_root() / AUDIT_SUBDIR


def write_event(
    *,
    actor: str,
    kind: str,
    project: str,
    target: str,
    summary: str,
    when: _dt.datetime | None = None,
) -> Path:
    """Append one event row to today's audit log. Returns the file path.

    Audit must never block the calling action — callers should swallow
    ``OSError``. Failures here mean a missing notif, not a missing
    transition.
    """
    when = when or _dt.datetime.now(_dt.timezone.utc)
    actor = actor if actor.startswith("@") else f"@{actor}"
    row = {
        "ts": when.astimezone(_dt.timezone.utc).isoformat(),
        "actor": actor,
        "kind": kind,
        "project": project,
        "target": target,
        "summary": summary,
    }
    target_dir = audit_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{when.strftime(AUDIT_DATE_FMT)}.jsonl"
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")
    return path


# ---------------------------------------------------------------------------
# read
# ---------------------------------------------------------------------------


def read_recent(
    *,
    days: int = 14,
    limit: int = 50,
    today: _dt.date | None = None,
) -> list[Event]:
    """Return the most recent ``limit`` events across the last ``days`` days.

    Newest first. Missing files / unreadable lines are skipped silently.

    The "today" default is UTC-anchored to match ``write_event``, which
    files rows under their UTC date. Mixing local + UTC dates here would
    drop newly-written rows for the few hours each night where local
    and UTC are on different calendar days (bit-rot observed
    2026-05-14 23:08 EDT → 2026-05-15 00:08 UTC; events written under
    the 15th, but a local ``date.today()`` reader was looking back from
    the 14th). The explicit ``today=`` kwarg is preserved for tests
    that pin a specific date.
    """
    today = today or _dt.datetime.now(_dt.timezone.utc).date()
    files = []
    for offset in range(days):
        d = today - _dt.timedelta(days=offset)
        path = audit_dir() / f"{d.strftime(AUDIT_DATE_FMT)}.jsonl"
        if path.is_file():
            files.append(path)

    events: list[Event] = []
    for path in files:
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(raw, dict):
                    continue
                events.append(Event.from_dict(raw))
        except OSError:
            continue

    events.sort(key=lambda e: e.ts, reverse=True)
    return events[:limit]


def has_any_events(*, days: int = 30, today: _dt.date | None = None) -> bool:
    """Return True if the audit chain has at least one row in ``days``.

    Cheap probe used by ``snapshot._notifs`` to decide between the
    audit-backed feed and the SEA-timestamp fallback. UTC-anchored to
    match ``write_event`` (see read_recent for the rationale).
    """
    today = today or _dt.datetime.now(_dt.timezone.utc).date()
    for offset in range(days):
        d = today - _dt.timedelta(days=offset)
        if (audit_dir() / f"{d.strftime(AUDIT_DATE_FMT)}.jsonl").is_file():
            return True
    return False


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _parse_ts(value: str) -> _dt.datetime | None:
    if not value:
        return None
    try:
        return _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def humanize(when: _dt.datetime, *, now: _dt.datetime | None = None) -> str:
    """Format ``when`` for the notifs panel.

    Today, <60s -> ``"just now"``
    Today, <60min -> ``"Nm ago"``
    Today, >=60min -> ``"HH:MM"`` (24h, local)
    Yesterday -> ``"yesterday"``
    Older -> ``"Nd ago"``
    """
    now = now or _dt.datetime.now(_dt.timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=_dt.timezone.utc)
    delta = now - when
    secs = delta.total_seconds()
    if 0 <= secs < 60:
        return "just now"
    if 0 <= secs < 3600 and now.date() == when.date():
        mins = int(secs // 60)
        return f"{mins}m ago"
    if now.date() == when.date():
        return when.astimezone().strftime("%H:%M")
    if now.date() - when.date() == _dt.timedelta(days=1):
        return "yesterday"
    days = (now.date() - when.date()).days
    return f"{days}d ago"
