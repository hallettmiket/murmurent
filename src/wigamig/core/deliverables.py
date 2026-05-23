"""
Purpose: Cross-job delivery status for a core's leader dashboard.
         "How many of my recent jobs have deliverables uploaded?
         Which ones has the requester actually downloaded?"
Author: Mike Hallett (with Claude Code)
Date: 2026-05-22

Reads from two existing sources:
  - core/service_requests: enumerates jobs (we walk requests, the
    job_id == request_id)
  - core/jobs: per-job manifest + file listing
  - ~/.wigamig/cores/<core>/access.log (MCP audit log): tells us
    whether the requester has pulled anything yet

No new persistence; everything is computed on demand.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from . import jobs as _jobs
from . import service_requests as _sr


@dataclass
class DeliverableRow:
    """One row of the deliverables overview card."""

    job_id: str
    service: str
    requester: str
    requester_lab: str
    state: str
    slot_start: str
    file_count: int = 0
    bytes_total: int = 0
    last_upload_at: str = ""               # max(mtime) across the job dir; "" when empty
    last_access_at: str = ""               # max(ts) in access.log for this job; "" when no reads
    accessed_by: list[str] = field(default_factory=list)


def _access_log_path(core: str) -> Path:
    home = Path(os.environ.get("WIGAMIG_HOME") or (Path.home() / ".wigamig"))
    return home / "cores" / core / "access.log"


def _read_access_log(core: str) -> dict[str, dict]:
    """Parse the MCP access log; return ``{job_id: {ts, callers}}`` with
    only the most-recent successful access per job."""
    p = _access_log_path(core)
    if not p.is_file():
        return {}
    by_job: dict[str, dict] = {}
    try:
        with p.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                jid = str(rec.get("job_id") or "")
                evt = str(rec.get("event") or "")
                # Only count successful reads (not _denied / _too_large).
                if not jid or "denied" in evt or "too_large" in evt:
                    continue
                if evt not in {"read_job_file", "bundle_job",
                                "list_job_files", "get_job_manifest"}:
                    continue
                ts = str(rec.get("ts") or "")
                caller = str(rec.get("caller") or "")
                entry = by_job.setdefault(jid, {"ts": "", "callers": set()})
                if ts > entry["ts"]:
                    entry["ts"] = ts
                if caller:
                    entry["callers"].add(caller)
    except OSError:
        return {}
    return by_job


def overview(
    *,
    core: str,
    limit: int = 50,
    include_terminal: bool = True,
    env: dict[str, str] | None = None,
) -> list[DeliverableRow]:
    """Build the deliverables overview rows for the leader card.

    Sort: live jobs first (by slot.start asc), then terminal
    (by slot.start desc — most recent completed visible first).
    Capped at ``limit`` rows.
    """
    access = _read_access_log(core)
    rows: list[DeliverableRow] = []
    for req in _sr.iter_requests(core, env=env,
                                    include_terminal=include_terminal):
        jid = req.job_id or req.request_id
        files = _jobs.list_files(core, jid, env=env)
        file_count = len(files)
        bytes_total = sum(f.size_bytes for f in files)
        last_upload = ""
        jdir = _jobs.job_dir(core, jid, env)
        if jdir.is_dir():
            mtimes = []
            for p in jdir.rglob("*"):
                if p.is_file():
                    try:
                        mtimes.append(p.stat().st_mtime)
                    except OSError:
                        pass
            if mtimes:
                from datetime import datetime, timezone
                last_upload = datetime.fromtimestamp(
                    max(mtimes), tz=timezone.utc,
                ).strftime("%Y-%m-%dT%H:%M:%SZ")
        acc = access.get(jid) or {"ts": "", "callers": set()}
        rows.append(DeliverableRow(
            job_id=jid,
            service=req.service,
            requester=req.requester,
            requester_lab=req.requester_lab,
            state=req.state,
            slot_start=req.booked_slot.start,
            file_count=file_count,
            bytes_total=bytes_total,
            last_upload_at=last_upload,
            last_access_at=acc["ts"],
            accessed_by=sorted(acc["callers"]),
        ))
    live = [r for r in rows
            if r.state not in (_sr.STATE_COMPLETED, _sr.STATE_CANCELLED)]
    term = [r for r in rows
            if r.state in (_sr.STATE_COMPLETED, _sr.STATE_CANCELLED)]
    live.sort(key=lambda r: r.slot_start or "")
    term.sort(key=lambda r: r.slot_start or "", reverse=True)
    return (live + term)[:max(1, int(limit))]


__all__ = ["DeliverableRow", "overview"]
