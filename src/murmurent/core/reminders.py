"""
Purpose: Service-booking reminders — find requests whose slot.start is
         within the 24h or 1h window from now, and emit them once.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-22

Idempotency: each (request_id, window) pair is recorded in
``~/.murmurent/cores/<core>/reminders_sent.json`` after a successful
send. Re-running the scanner (every 15 min via CC ``/routine``) is a
no-op for already-sent reminders.

Windows:
  - 24h:  start ∈ [now + 23h, now + 25h]
  - 1h:   start ∈ [now + 55min, now + 65min]

Tolerance on the windows is wide enough that a 15-minute scanner
schedule never misses a slot. If a user books a slot less than 1h
out, only the 1h reminder fires (the 24h window is already past).

This module is pure logic — does not touch Slack itself; the CLI
wires the Slack post on top so tests can verify scan/record without
mocking Slack.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
from dataclasses import dataclass
from pathlib import Path

from . import registrar as _reg
from . import service_requests as _sr


WINDOW_24H = "24h"
WINDOW_1H  = "1h"
ALL_WINDOWS = (WINDOW_24H, WINDOW_1H)


@dataclass
class DueReminder:
    core: str
    request: _sr.RequestSummary
    window: str           # WINDOW_24H or WINDOW_1H
    minutes_until: int    # rounded; negative if slot has already started


def _wigamig_home() -> Path:
    return Path(os.environ.get("MURMURENT_HOME") or (Path.home() / ".murmurent"))


def _ledger_path(core: str) -> Path:
    return _wigamig_home() / "cores" / core / "reminders_sent.json"


def _load_ledger(core: str) -> dict[str, list[str]]:
    p = _ledger_path(core)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def already_sent(core: str, request_id: str, window: str) -> bool:
    ledger = _load_ledger(core)
    return window in (ledger.get(request_id) or [])


def record_sent(core: str, request_id: str, window: str) -> None:
    p = _ledger_path(core)
    p.parent.mkdir(parents=True, exist_ok=True)
    ledger = _load_ledger(core)
    sent = set(ledger.get(request_id) or [])
    sent.add(window)
    ledger[request_id] = sorted(sent)
    p.write_text(json.dumps(ledger, indent=2, sort_keys=True),
                  encoding="utf-8")


def _parse_iso(s: str) -> _dt.datetime | None:
    if not s:
        return None
    try:
        # Python's fromisoformat handles "+04:00" but not "Z"; the booking
        # endpoint always emits explicit offsets, so this is safe.
        return _dt.datetime.fromisoformat(s)
    except ValueError:
        return None


def _in_window(slot_start: _dt.datetime, now: _dt.datetime, window: str) -> bool:
    delta_min = (slot_start - now).total_seconds() / 60.0
    if window == WINDOW_24H:
        return 23 * 60 <= delta_min <= 25 * 60
    if window == WINDOW_1H:
        return 55 <= delta_min <= 65
    return False


def scan_due_reminders(
    *, now: _dt.datetime | None = None,
    env: dict[str, str] | None = None,
) -> list[DueReminder]:
    """Walk every core's scheduled requests; emit the (core, request,
    window) tuples whose slot.start falls in one of the reminder windows
    AND haven't already been recorded as sent."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=_dt.timezone.utc)
    try:
        reg = _reg.read_registry(env=env)
    except Exception:
        return []
    out: list[DueReminder] = []
    for core in reg.cores:
        for req in _sr.iter_requests(
            core.name, state=_sr.STATE_SCHEDULED, env=env,
        ):
            slot_dt = _parse_iso(req.booked_slot.start)
            if slot_dt is None:
                continue
            if slot_dt.tzinfo is None:
                slot_dt = slot_dt.replace(tzinfo=_dt.timezone.utc)
            for window in ALL_WINDOWS:
                if not _in_window(slot_dt, now, window):
                    continue
                if already_sent(core.name, req.request_id, window):
                    continue
                delta_min = int(round((slot_dt - now).total_seconds() / 60.0))
                out.append(DueReminder(
                    core=core.name, request=req,
                    window=window, minutes_until=delta_min,
                ))
    return out


__all__ = [
    "WINDOW_24H", "WINDOW_1H", "ALL_WINDOWS",
    "DueReminder",
    "already_sent", "record_sent",
    "scan_due_reminders",
]
