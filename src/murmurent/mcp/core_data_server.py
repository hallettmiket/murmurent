"""
Purpose: ``murmurent-core-data`` MCP server. Exposes a core's per-job
         delivery directories to the requester's lab via Claude Code,
         with identity-checked access at every tool boundary.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-22
Input: stdio MCP protocol; tools are also callable directly from tests
       via the ``tool_*`` shims (no MCP SDK required at import time).
Output: JSON-serialisable dicts.

Run as a server::

    python -m murmurent.mcp.core_data_server

Design (Phase 5d of the cores rollout, plan §8):

  - The MCP runs on the lab server, close to ``$WIGAMIG_LAB_VM_ROOT``.
    Members' Claude Code sessions connect via stdio over SSH (same
    pattern as the existing ``murmurent-oracle`` server).
  - Identity comes from ``$WIGAMIG_USER`` set by the murmurent shell
    wrapper, fallback ``$USER``. We use ``core.lab.load_lab_config().lab``
    to determine the caller's lab and gate per-job reads on
    ``manifest.requester_lab == caller_lab``.
  - Core staff (leader / registrar) see every job in their core;
    other-lab readers only see their own bookings.
  - All reads logged to ``~/.wigamig/cores/<core>/access.log`` so the
    leader has an audit trail.

Tools shipped in 5d (sketch):

  list_my_jobs(core?, state?, limit=50)
      → jobs whose requester_lab matches the caller (or every job if
        caller is leader/registrar of the named core)
  get_job_manifest(core, job_id)
      → manifest.json contents
  list_job_files(core, job_id)
      → directory listing
  read_job_file(core, job_id, relpath, max_bytes=10_485_760)
      → file contents (base64-encoded for binary safety)

``bundle_job`` deferred to a follow-up — it needs a streaming response
shape the FastMCP wrapper handles differently from the simple JSON tools.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from ..core import jobs as _jobs
from ..core import lab as _lab
from ..core import registrar as _reg
from ..core import service_requests as _sr


# ---------------------------------------------------------------------------
# Identity + access control
# ---------------------------------------------------------------------------

class AccessDenied(RuntimeError):
    """Caller's lab does not match the job's requester_lab."""


def _caller_handle() -> str:
    raw = (os.environ.get("WIGAMIG_USER")
           or os.environ.get("USER") or "").strip()
    return raw.lstrip("@").lower()


def _caller_lab() -> str:
    try:
        return _lab.load_lab_config().lab.lower()
    except Exception:
        return ""


def _is_core_staff(core: str, handle: str) -> bool:
    """Leader of <core> OR a centre registrar."""
    if not handle:
        return False
    try:
        reg = _reg.read_registry()
    except Exception:
        return False
    entry = next((c for c in reg.cores if c.name == core), None)
    if entry is None:
        return False
    if entry.pi.lstrip("@").lower() == handle:
        return True
    try:
        return _reg.is_registrar(handle)
    except Exception:
        return False


def _can_read_job(core: str, manifest: dict[str, Any]) -> tuple[bool, str]:
    """Decide whether the current caller may read this job. Returns
    ``(ok, reason)``; reason is empty on success."""
    handle = _caller_handle()
    if not handle:
        return False, "no WIGAMIG_USER / USER set"
    if _is_core_staff(core, handle):
        return True, ""
    caller_lab = _caller_lab()
    job_lab = str(manifest.get("requester_lab") or "").lower()
    if caller_lab and caller_lab == job_lab:
        return True, ""
    return False, (
        f"@{handle} (lab={caller_lab!r}) is not in the job's "
        f"requesting lab ({job_lab!r}) and not core staff."
    )


def _audit_log(core: str, event: str, **fields: Any) -> None:
    """Append one JSON line to ~/.wigamig/cores/<core>/access.log."""
    try:
        home = Path(os.environ.get("WIGAMIG_HOME") or (Path.home() / ".wigamig"))
        log = home / "cores" / core / "access.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "caller": _caller_handle(),
            "event": event,
            "core": core,
            **fields,
        }
        with log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Tools (also called directly by tests)
# ---------------------------------------------------------------------------

def tool_list_my_jobs(
    core: str | None = None,
    state: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Enumerate jobs the caller can see. When ``core`` omitted: scans
    every registered core. When ``state`` provided: filter."""
    handle = _caller_handle()
    caller_lab = _caller_lab()
    try:
        reg = _reg.read_registry()
        cores = ([c for c in reg.cores if c.name == core]
                 if core else list(reg.cores))
    except Exception:
        cores = []
    rows: list[dict[str, Any]] = []
    for c in cores:
        for req in _sr.iter_requests(c.name, state=state):
            manifest = {
                "requester_lab": req.requester_lab,
            }
            ok, _reason = _can_read_job(c.name, manifest)
            if not ok:
                continue
            rows.append({
                "core": c.name,
                "job_id": req.job_id or req.request_id,
                "request_id": req.request_id,
                "service": req.service,
                "state": req.state,
                "requester": req.requester,
                "requester_lab": req.requester_lab,
                "slot_start": req.booked_slot.start,
                "fee_total": req.fee_at_booking.total,
            })
            if len(rows) >= limit:
                break
        if len(rows) >= limit:
            break
    _audit_log("_all" if not core else core, "list_my_jobs",
                 state=state, returned=len(rows))
    return {"caller": handle, "caller_lab": caller_lab,
            "count": len(rows), "jobs": rows}


def tool_get_job_manifest(core: str, job_id: str) -> dict[str, Any]:
    m = _jobs.read_manifest(core, job_id)
    if m is None:
        return {"ok": False, "error": f"job not found: {core}/{job_id}"}
    ok, reason = _can_read_job(core, m)
    if not ok:
        _audit_log(core, "get_job_manifest_denied",
                    job_id=job_id, reason=reason)
        return {"ok": False, "error": reason}
    _audit_log(core, "get_job_manifest", job_id=job_id)
    return {"ok": True, "manifest": m}


def tool_list_job_files(core: str, job_id: str) -> dict[str, Any]:
    m = _jobs.read_manifest(core, job_id)
    if m is None:
        return {"ok": False, "error": f"job not found: {core}/{job_id}"}
    ok, reason = _can_read_job(core, m)
    if not ok:
        _audit_log(core, "list_job_files_denied",
                    job_id=job_id, reason=reason)
        return {"ok": False, "error": reason}
    files = _jobs.list_files(core, job_id)
    _audit_log(core, "list_job_files",
                 job_id=job_id, count=len(files))
    return {
        "ok": True, "core": core, "job_id": job_id,
        "files": [{"relpath": f.relpath, "size_bytes": f.size_bytes}
                   for f in files],
    }


def tool_bundle_job(
    core: str, job_id: str,
    *, exclude_manifest: bool = False,
    max_bytes: int = 100 * 1024 * 1024,
) -> dict[str, Any]:
    """Return the entire job dir as a single base64-encoded tar.gz.

    Caps the bundle at ``max_bytes`` (default 100MB) since MCP
    responses live in agent context. For larger jobs, fall back to
    per-file ``read_job_file`` calls.
    """
    m = _jobs.read_manifest(core, job_id)
    if m is None:
        return {"ok": False, "error": f"job not found: {core}/{job_id}"}
    ok, reason = _can_read_job(core, m)
    if not ok:
        _audit_log(core, "bundle_job_denied", job_id=job_id, reason=reason)
        return {"ok": False, "error": reason}
    try:
        blob = _jobs.bundle_job_tarball(
            core, job_id, exclude_manifest=exclude_manifest,
        )
    except _jobs.JobError as exc:
        return {"ok": False, "error": str(exc)}
    if len(blob) > max_bytes:
        _audit_log(core, "bundle_job_too_large",
                    job_id=job_id, size=len(blob))
        return {
            "ok": False,
            "error": (f"bundle is {len(blob)} bytes (> max {max_bytes}); "
                       "list_job_files + read_job_file each file individually."),
            "size_bytes": len(blob),
        }
    _audit_log(core, "bundle_job", job_id=job_id, size=len(blob))
    return {
        "ok": True, "core": core, "job_id": job_id,
        "size_bytes": len(blob),
        "format": "tar.gz",
        "content_base64": base64.b64encode(blob).decode("ascii"),
    }


def tool_read_job_file(
    core: str, job_id: str, relpath: str,
    max_bytes: int = 10 * 1024 * 1024,
) -> dict[str, Any]:
    """Returns ``{ok, content_base64, size_bytes}`` on success or
    ``{ok: False, error}`` on refusal."""
    m = _jobs.read_manifest(core, job_id)
    if m is None:
        return {"ok": False, "error": f"job not found: {core}/{job_id}"}
    ok, reason = _can_read_job(core, m)
    if not ok:
        _audit_log(core, "read_job_file_denied",
                    job_id=job_id, relpath=relpath, reason=reason)
        return {"ok": False, "error": reason}
    try:
        p = _jobs.safe_resolve(core, job_id, relpath)
    except _jobs.JobError as exc:
        return {"ok": False, "error": str(exc)}
    if not p.is_file():
        return {"ok": False, "error": f"file not found: {relpath}"}
    try:
        size = p.stat().st_size
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    if size > max_bytes:
        _audit_log(core, "read_job_file_too_large",
                    job_id=job_id, relpath=relpath, size=size)
        return {"ok": False,
                "error": f"file too large ({size} > {max_bytes}); "
                          "increase max_bytes or split the request."}
    data = p.read_bytes()
    _audit_log(core, "read_job_file",
                 job_id=job_id, relpath=relpath, size=size)
    return {
        "ok": True, "core": core, "job_id": job_id, "relpath": relpath,
        "size_bytes": size,
        "content_base64": base64.b64encode(data).decode("ascii"),
    }


# ---------------------------------------------------------------------------
# MCP server wiring (lazy SDK import)
# ---------------------------------------------------------------------------

def _build_server():  # pragma: no cover - only when SDK installed
    from mcp.server.fastmcp import FastMCP  # type: ignore[import-not-found]
    server = FastMCP(
        name="murmurent-core-data",
        instructions=(
            "Read per-job deliverables from a core's job directory. "
            "Identity check: caller's lab must match the job's "
            "requester_lab (or caller must be core staff). All reads "
            "logged to ~/.wigamig/cores/<core>/access.log."
        ),
    )

    @server.tool(name="list_my_jobs",
                  description="List jobs you can read. Filter by core, state, limit.")
    def _list_my_jobs(core: str | None = None, state: str | None = None,
                       limit: int = 50) -> str:
        return json.dumps(tool_list_my_jobs(core=core, state=state, limit=limit))

    @server.tool(name="get_job_manifest",
                  description="Read manifest.json for one job.")
    def _get_manifest(core: str, job_id: str) -> str:
        return json.dumps(tool_get_job_manifest(core, job_id))

    @server.tool(name="list_job_files",
                  description="List every file in the job dir.")
    def _list_files(core: str, job_id: str) -> str:
        return json.dumps(tool_list_job_files(core, job_id))

    @server.tool(name="read_job_file",
                  description="Read one file from a job (base64). Size-capped.")
    def _read_file(core: str, job_id: str, relpath: str,
                    max_bytes: int = 10 * 1024 * 1024) -> str:
        return json.dumps(tool_read_job_file(core, job_id, relpath,
                                              max_bytes=max_bytes))

    @server.tool(name="bundle_job",
                  description="Entire job dir as a single base64 tar.gz. Size-capped.")
    def _bundle(core: str, job_id: str,
                 exclude_manifest: bool = False,
                 max_bytes: int = 100 * 1024 * 1024) -> str:
        return json.dumps(tool_bundle_job(core, job_id,
                                            exclude_manifest=exclude_manifest,
                                            max_bytes=max_bytes))

    return server


def main() -> int:  # pragma: no cover
    server = _build_server()
    server.run()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())


__all__ = [
    "AccessDenied",
    "tool_list_my_jobs", "tool_get_job_manifest",
    "tool_list_job_files", "tool_read_job_file",
    "tool_bundle_job",
]
