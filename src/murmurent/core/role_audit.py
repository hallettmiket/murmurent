"""
Purpose: Per-machine append-only log of role transitions on the dashboard.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-13
Input: Calls from the FastAPI login endpoints recording who picked which
       role at what time from what source address.
Output: JSON Lines file at ``~/.murmurent/role_audit.log`` (one event per line).

This is a **local** auditing trail. The user has access to it — anyone
holding the laptop can read or rotate it — but every role choice the
dashboard server witnesses lands here, so even a fabricated role claim
leaves a record. Separate from ``dashboard/audit_log.py`` (which logs
*domain* events to the lab-mgmt repo) and from ``~/.claude/murmurent-audit/``
(which logs every Claude tool call).

Each row is a JSON object with keys::

    ts       ISO-8601 UTC timestamp
    handle   netname the user claimed (lower-case, no leading @)
    role     "member" | "pi" | "registrar"
    source   client address as the FastAPI request saw it (e.g. "127.0.0.1")
    allowed  bool — whether the server granted the role
    reason   short string when ``allowed`` is False (e.g. "not_pi")
"""

from __future__ import annotations

import datetime as _dt
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

DEFAULT_LOG_PATH = Path.home() / ".murmurent" / "role_audit.log"
ENV_VAR = "MURMURENT_ROLE_AUDIT_LOG"

# Three lenses only. A PI leads either a lab or a core — same lens for
# both (issue #18); "core_leader" was retired as a login role.
VALID_ROLES = frozenset({"member", "pi", "registrar"})


def log_path(env: dict[str, str] | None = None) -> Path:
    """Return the audit log path (env-overridable for tests)."""
    source = os.environ if env is None else env
    return Path(source.get(ENV_VAR, DEFAULT_LOG_PATH)).expanduser()


@dataclass(frozen=True)
class RoleEvent:
    """One row of the role-transition log."""

    ts: _dt.datetime
    handle: str
    role: str
    source: str
    allowed: bool
    reason: str = ""


def record(
    *,
    handle: str,
    role: str,
    source: str,
    allowed: bool,
    reason: str = "",
    env: dict[str, str] | None = None,
    now: _dt.datetime | None = None,
) -> RoleEvent:
    """Append one role-transition event to the local audit log.

    ``now`` is injectable so tests can pin timestamps. Returns the
    :class:`RoleEvent` actually written.
    """
    ts = (now or _dt.datetime.now(_dt.timezone.utc)).astimezone(_dt.timezone.utc)
    norm_handle = (handle or "").strip().lstrip("@").lower()
    norm_role = (role or "").strip().lower()
    event = RoleEvent(
        ts=ts,
        handle=norm_handle,
        role=norm_role,
        source=source or "unknown",
        allowed=bool(allowed),
        reason=(reason or "").strip(),
    )
    path = log_path(env)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(
        {
            "ts": ts.isoformat(),
            "handle": norm_handle,
            "role": norm_role,
            "source": event.source,
            "allowed": event.allowed,
            "reason": event.reason,
        },
        ensure_ascii=False,
    )
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    return event


def read_all(env: dict[str, str] | None = None) -> list[RoleEvent]:
    """Return every event in the log, oldest-first. Empty if missing."""
    path = log_path(env)
    if not path.is_file():
        return []
    out: list[RoleEvent] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = _parse_ts(raw.get("ts"))
        if ts is None:
            continue
        out.append(
            RoleEvent(
                ts=ts,
                handle=str(raw.get("handle", "")),
                role=str(raw.get("role", "")),
                source=str(raw.get("source", "")),
                allowed=bool(raw.get("allowed", False)),
                reason=str(raw.get("reason", "")),
            )
        )
    return out


def recent_for(handle: str, *, limit: int = 20, env: dict[str, str] | None = None) -> list[RoleEvent]:
    """Newest-first slice of the log filtered to one handle."""
    norm = (handle or "").strip().lstrip("@").lower()
    rows = [e for e in read_all(env) if e.handle == norm]
    rows.sort(key=lambda e: e.ts, reverse=True)
    return rows[:limit]


def _parse_ts(value: object) -> _dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        ts = _dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=_dt.timezone.utc)
    return ts


__all__ = [
    "VALID_ROLES",
    "RoleEvent",
    "log_path",
    "record",
    "read_all",
    "recent_for",
]
