"""
Purpose: Per-job storage layout + manifest for core service deliverables.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-22

Each booked service request maps to one job directory at:

    <lab_vm_root>/cores/<core>/jobs/<job_id>/
      manifest.json     # request_id, service, requester, lab, fee, state
      raw/              # core uploads raw instrument outputs here
      refined/          # core uploads derived deliverables here

NOT under <lab_vm_root>/{raw,refined}/  — those top-level dirs are
protected by the raw_guard + protected_paths hooks (lab rule:
``never delete or modify a file under raw/ or refined/``). The
cores tree sits in a sibling dir so leader writes are not blocked
by the hooks. Per-job dirs use the names ``raw`` / ``refined`` only
to mirror the conceptual split (lab rule applies to *lab* raw/refined,
not core deliverables that already separate provenance).

The manifest is the canonical small-metadata file the MCP server
reads to decide who's allowed to see what. Built fresh from the
RequestSummary on every booking + refreshed when the request state
changes (so completed jobs carry the final fee + actual_charge).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import service_requests as _sr
from .lab_vm import lab_vm_root


CORES_SUBDIR = "cores"
JOBS_SUBDIR  = "jobs"
RAW_SUBDIR   = "raw"
REFINED_SUBDIR = "refined"
MANIFEST_NAME = "manifest.json"


class JobError(RuntimeError):
    """Job-dir mutation failed (path escape, missing dir, …)."""


@dataclass
class JobFile:
    """One file under a job dir, as returned by list_files."""

    relpath: str            # path relative to the job dir (e.g. 'refined/fit.png')
    size_bytes: int
    is_dir: bool = False


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def cores_root(env: dict[str, str] | None = None) -> Path:
    """``<lab_vm_root>/cores/``."""
    return lab_vm_root(env) / CORES_SUBDIR


def core_jobs_dir(core: str, env: dict[str, str] | None = None) -> Path:
    """``<lab_vm_root>/cores/<core>/jobs/``."""
    return cores_root(env) / core / JOBS_SUBDIR


def job_dir(
    core: str, job_id: str, env: dict[str, str] | None = None,
) -> Path:
    """``<lab_vm_root>/cores/<core>/jobs/<job_id>/``."""
    return core_jobs_dir(core, env) / job_id


def manifest_path(
    core: str, job_id: str, env: dict[str, str] | None = None,
) -> Path:
    return job_dir(core, job_id, env) / MANIFEST_NAME


# ---------------------------------------------------------------------------
# Manifest readers / writers
# ---------------------------------------------------------------------------

def _manifest_from_request(req: _sr.RequestSummary) -> dict[str, Any]:
    """Project a RequestSummary into the manifest schema."""
    out: dict[str, Any] = {
        "job_id": req.job_id or req.request_id,
        "request_id": req.request_id,
        "core": req.core,
        "service": req.service,
        "requester": req.requester,
        "requester_lab": req.requester_lab,
        "state": req.state,
        "booked_slot": {
            "start": req.booked_slot.start,
            "end": req.booked_slot.end,
        },
        "fee_at_booking": {
            "tier": req.fee_at_booking.tier,
            "unit": req.fee_at_booking.unit,
            "total": req.fee_at_booking.total,
        },
        "created": req.created,
        "updated": req.updated,
    }
    if req.actual_charge is not None:
        out["actual_charge"] = {
            "tier": req.actual_charge.tier,
            "unit": req.actual_charge.unit,
            "total": req.actual_charge.total,
        }
    return out


def init_job(
    core: str,
    request: _sr.RequestSummary,
    env: dict[str, str] | None = None,
) -> Path:
    """Create the job dir + write manifest.json. Idempotent — safe to
    call on every booking even if the directory already exists. Returns
    the job dir path."""
    jid = request.job_id or request.request_id
    jdir = job_dir(core, jid, env)
    (jdir / RAW_SUBDIR).mkdir(parents=True, exist_ok=True)
    (jdir / REFINED_SUBDIR).mkdir(parents=True, exist_ok=True)
    refresh_manifest(core, request, env=env)
    return jdir


def refresh_manifest(
    core: str,
    request: _sr.RequestSummary,
    env: dict[str, str] | None = None,
) -> Path:
    """Atomically rewrite the manifest from the current RequestSummary.
    Called from lifecycle endpoints after state transitions so the
    on-disk manifest stays in sync with the request file."""
    jid = request.job_id or request.request_id
    p = manifest_path(core, jid, env)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(_manifest_from_request(request), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tmp.replace(p)
    return p


def read_manifest(
    core: str, job_id: str, env: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    p = manifest_path(core, job_id, env)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------------
# File enumeration (used by the dashboard + MCP)
# ---------------------------------------------------------------------------

def list_files(
    core: str, job_id: str, env: dict[str, str] | None = None,
) -> list[JobFile]:
    """Walk the job dir; return one JobFile per file (recursive).
    manifest.json is included so the UI can show it; the empty
    raw/ and refined/ stubs are silently skipped (only files,
    no empty dirs)."""
    jdir = job_dir(core, job_id, env)
    if not jdir.is_dir():
        return []
    out: list[JobFile] = []
    for p in sorted(jdir.rglob("*")):
        if not p.is_file():
            continue
        try:
            rel = p.relative_to(jdir)
        except ValueError:
            continue
        try:
            size = p.stat().st_size
        except OSError:
            continue
        out.append(JobFile(relpath=str(rel), size_bytes=int(size)))
    return out


def safe_resolve(
    core: str, job_id: str, relpath: str,
    env: dict[str, str] | None = None,
) -> Path:
    """Resolve ``relpath`` against the job dir, refusing escapes
    (``..``, absolute paths, symlinks that point outside). Used by
    every read/write endpoint as the gate against path traversal."""
    jdir = job_dir(core, job_id, env).resolve()
    if not jdir.is_dir():
        raise JobError(f"job dir not found: {core}/{job_id}")
    if not relpath or relpath.strip() == "":
        raise JobError("empty relpath")
    candidate = (jdir / relpath).resolve()
    try:
        candidate.relative_to(jdir)
    except ValueError:
        raise JobError(
            f"path escape: {relpath!r} resolves outside {jdir}"
        )
    return candidate


def bundle_job_tarball(
    core: str, job_id: str,
    *, exclude_manifest: bool = False,
    env: dict[str, str] | None = None,
) -> bytes:
    """Return the entire job dir as an in-memory ``.tar.gz`` blob.

    Phase 7b: small jobs only — caps are enforced by the HTTP / MCP
    layer (this helper itself doesn't size-check so tests can exercise
    arbitrary fixture sizes). For multi-GB jobs we'd want a streaming
    response instead; not in scope today.
    """
    import io, tarfile
    jdir = job_dir(core, job_id, env)
    if not jdir.is_dir():
        raise JobError(f"job dir not found: {core}/{job_id}")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for p in sorted(jdir.rglob("*")):
            if not p.is_file():
                continue
            try:
                rel = p.relative_to(jdir)
            except ValueError:
                continue
            if exclude_manifest and str(rel) == MANIFEST_NAME:
                continue
            tar.add(str(p), arcname=f"{job_id}/{rel}")
    return buf.getvalue()


def write_file(
    core: str, job_id: str, relpath: str, data: bytes,
    env: dict[str, str] | None = None,
) -> Path:
    """Write ``data`` to ``relpath`` inside the job dir. Creates
    intermediate directories. Refuses path escapes via safe_resolve.
    Returns the absolute path written.

    Only callable from server-side endpoints that have already
    verified the actor is the core leader or a registrar — the
    helper itself does not check permissions.
    """
    jdir = job_dir(core, job_id, env)
    if not jdir.is_dir():
        raise JobError(f"job dir not found: {core}/{job_id}")
    # safe_resolve refuses escapes; we then call it on the parent's
    # relpath only after the file exists (resolve needs an existing
    # leaf), so do the prefix check by hand here.
    jdir_resolved = jdir.resolve()
    target = (jdir / relpath)
    target_parent = target.parent.resolve()
    try:
        target_parent.relative_to(jdir_resolved)
    except ValueError:
        raise JobError(
            f"path escape: {relpath!r} resolves outside {jdir}"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(target)
    return target


__all__ = [
    "CORES_SUBDIR", "JOBS_SUBDIR", "RAW_SUBDIR", "REFINED_SUBDIR",
    "MANIFEST_NAME",
    "JobError", "JobFile",
    "cores_root", "core_jobs_dir", "job_dir", "manifest_path",
    "init_job", "refresh_manifest", "read_manifest",
    "list_files", "safe_resolve", "write_file",
    "bundle_job_tarball",
]
