"""
Purpose: Centre-level "PI proposes a cross-lab collaboration; registrar approves"
         workflow. The proposed collaboration's spec is filed in
         ``~/.wigamig/lab_info/collaboration_requests/<id>.md`` (the
         registrar's own repo). Approval creates the registry entry via
         the existing ``core.registrar.create_collaboration`` flow.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-14
Input:  PI proposal payload (collab name + partner groups + PIs + member subset).
Output: Approved → new entry in ``_registry.yaml``;
        Declined → state flag updated, file preserved as history.

The murmurent invariant is that the registrar manages the centre's registry
but does NOT decree collaborations on PIs' behalf — PIs propose, registrar
approves. Item #9 in the 2026-05-14 testing list. The request file format
mirrors ``core.requests.JoinRequest`` so the UI patterns stay consistent.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .frontmatter import dump_document, parse_file

COLLAB_REQUESTS_SUBDIR = "collaboration_requests"
REQUEST_ID_RE = re.compile(r"^(?P<id>\d+)\.md$")
VALID_STATES: tuple[str, ...] = ("pending", "approved", "declined")
TERMINAL_STATES = frozenset({"approved", "declined"})


class CollabRequestError(ValueError):
    """Base for collab-request lifecycle errors."""


class CollabRequestNotFound(CollabRequestError):
    """No matching collab-request file on disk."""


class CollabRequestStateError(CollabRequestError):
    """Tried to transition a request that's already terminal."""


@dataclass
class CollabRequest:
    """One pending/historical collaboration-create request.

    Free-floating from the per-lab requests/ system because the
    registrar (not the PI) is the approver and the registrar's view of
    pending work should aggregate across all labs without walking each
    lab's requests/ dir.
    """

    id: int
    requester: str                                 # @handle of the proposing PI
    proposed_name: str                             # collab short id, e.g. "imaging_clinical"
    proposed_groups: list[str] = field(default_factory=list)
    proposed_pis: list[str] = field(default_factory=list)
    proposed_member_subset: dict[str, list[str]] = field(default_factory=dict)
    proposed_oracle_vault: str | None = None
    justification: str = ""
    state: str = "pending"
    created_at: str | None = None
    resolved_at: str | None = None
    resolved_by: str | None = None
    decline_reason: str | None = None
    body: str = ""
    path: Path | None = None

    def to_meta(self) -> dict:
        meta: dict = {
            "id": self.id,
            "kind": "collaboration-create",
            "requester": self.requester,
            "proposed_name": self.proposed_name,
            "proposed_groups": list(self.proposed_groups),
            "proposed_pis": list(self.proposed_pis),
            "proposed_member_subset": {
                k: list(v) for k, v in self.proposed_member_subset.items()
            },
            "state": self.state,
        }
        for key, value in (
            ("proposed_oracle_vault", self.proposed_oracle_vault),
            ("justification", self.justification),
            ("created_at", self.created_at),
            ("resolved_at", self.resolved_at),
            ("resolved_by", self.resolved_by),
            ("decline_reason", self.decline_reason),
        ):
            if value is not None and value != "":
                meta[key] = value
        return meta


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def _lab_info_root(env: dict[str, str] | None = None) -> Path:
    """Avoid circular import with core.registrar by reading the env-var here."""
    import os

    source = os.environ if env is None else env
    base = source.get("WIGAMIG_LAB_INFO_ROOT")
    return Path(base).expanduser() if base else Path("~/.wigamig/lab_info").expanduser()


def requests_dir(env: dict[str, str] | None = None) -> Path:
    return _lab_info_root(env) / COLLAB_REQUESTS_SUBDIR


def request_path(req_id: int, env: dict[str, str] | None = None) -> Path:
    return requests_dir(env) / f"{req_id}.md"


def parse_request(path: Path) -> CollabRequest:
    parsed = parse_file(path)
    meta = parsed.meta or {}
    subset_raw = meta.get("proposed_member_subset") or {}
    subset: dict[str, list[str]] = {}
    if isinstance(subset_raw, dict):
        for k, v in subset_raw.items():
            subset[str(k)] = [str(item) for item in (v or [])]
    return CollabRequest(
        id=int(meta["id"]),
        requester=str(meta.get("requester") or ""),
        proposed_name=str(meta.get("proposed_name") or ""),
        proposed_groups=[str(g) for g in (meta.get("proposed_groups") or [])],
        proposed_pis=[str(p) for p in (meta.get("proposed_pis") or [])],
        proposed_member_subset=subset,
        proposed_oracle_vault=_opt(meta.get("proposed_oracle_vault")),
        justification=str(meta.get("justification") or ""),
        state=str(meta.get("state") or "pending"),
        created_at=_opt(meta.get("created_at")),
        resolved_at=_opt(meta.get("resolved_at")),
        resolved_by=_opt(meta.get("resolved_by")),
        decline_reason=_opt(meta.get("decline_reason")),
        body=parsed.body or "",
        path=path,
    )


def _opt(value):
    if value is None or value == "":
        return None
    return str(value)


def iter_requests(env: dict[str, str] | None = None) -> list[CollabRequest]:
    rdir = requests_dir(env)
    if not rdir.is_dir():
        return []
    out: list[CollabRequest] = []
    for child in rdir.iterdir():
        if not REQUEST_ID_RE.match(child.name):
            continue
        try:
            out.append(parse_request(child))
        except Exception:
            continue
    out.sort(key=lambda r: r.id)
    return out


def next_request_id(env: dict[str, str] | None = None) -> int:
    used = [r.id for r in iter_requests(env)]
    return (max(used) + 1) if used else 1


def write_request(req: CollabRequest, env: dict[str, str] | None = None) -> Path:
    rdir = requests_dir(env)
    rdir.mkdir(parents=True, exist_ok=True)
    body = req.body or _default_body(req)
    path = request_path(req.id, env)
    path.write_text(dump_document(req.to_meta(), body), encoding="utf-8")
    req.path = path
    return path


def _default_body(req: CollabRequest) -> str:
    parts = [
        f"# Collaboration request — `{req.proposed_name}`",
        "",
        f"Proposed by **{req.requester}** between **"
        + " + ".join(req.proposed_groups) + "**.",
        "",
    ]
    if req.justification.strip():
        parts.extend(["## Justification", "", req.justification.strip(), ""])
    if req.proposed_member_subset:
        parts.append("## Member subset")
        parts.append("")
        for group, members in req.proposed_member_subset.items():
            parts.append(f"- **{group}**: {', '.join(members) if members else '_(none)_'}")
        parts.append("")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Lifecycle: file / approve / decline
# ---------------------------------------------------------------------------


def file_request(
    *,
    requester: str,
    proposed_name: str,
    proposed_groups: list[str],
    proposed_pis: list[str],
    proposed_member_subset: dict[str, list[str]] | None = None,
    proposed_oracle_vault: str | None = None,
    justification: str = "",
    env: dict[str, str] | None = None,
) -> CollabRequest:
    """Persist a new collab-create request. Returns the saved request.

    Validation here is lightweight — the registrar's approval step
    re-runs the full ``create_collaboration`` validators, so any
    proposal that wouldn't fly will fail loudly then. We do reject the
    obvious shape errors (empty name / groups list) up front so the
    proposing PI gets immediate feedback.
    """
    if not requester or not requester.strip():
        raise CollabRequestError("requester is required")
    if not proposed_name or not proposed_name.strip():
        raise CollabRequestError("proposed_name is required")
    if not proposed_groups:
        raise CollabRequestError("at least one partner group is required")
    if not proposed_pis:
        raise CollabRequestError("at least one PI is required")

    req = CollabRequest(
        id=next_request_id(env),
        requester=requester if requester.startswith("@") else f"@{requester.lstrip('@')}",
        proposed_name=proposed_name.strip().lower(),
        proposed_groups=list(proposed_groups),
        proposed_pis=list(proposed_pis),
        proposed_member_subset=proposed_member_subset or {},
        proposed_oracle_vault=proposed_oracle_vault,
        justification=justification,
        state="pending",
        created_at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
    )
    write_request(req, env)
    return req


def _get(req_id: int, env: dict[str, str] | None = None) -> CollabRequest:
    path = request_path(req_id, env)
    if not path.is_file():
        raise CollabRequestNotFound(f"collab request {req_id} not found")
    return parse_request(path)


def approve(
    req_id: int,
    *,
    by_handle: str,
    env: dict[str, str] | None = None,
):
    """Approve a pending collab request.

    Flips state→approved, then delegates to the existing
    ``core.registrar.create_collaboration`` to actually register the
    collaboration in ``_registry.yaml``. The registry-creation step has
    its own validation (one-PI-per-active-group, member-subset coverage,
    etc.) — if it fails, the approval is rolled back to ``pending`` so
    the registrar can correct the proposal or ask the PI to amend.
    Returns the created ``CollaborationEntry``.
    """
    from . import registrar as _registrar

    req = _get(req_id, env)
    if req.state in TERMINAL_STATES:
        raise CollabRequestStateError(
            f"request {req_id} is already {req.state}; cannot approve")

    # Optimistically flip state so callers can see "in-flight"; revert on failure.
    now = _dt.datetime.now(_dt.timezone.utc).isoformat()
    req.state = "approved"
    req.resolved_at = now
    req.resolved_by = (by_handle if by_handle.startswith("@")
                       else f"@{by_handle.lstrip('@')}")
    write_request(req, env)

    try:
        entry = _registrar.create_collaboration(
            name=req.proposed_name,
            pis=list(req.proposed_pis),
            groups=list(req.proposed_groups),
            member_subset=dict(req.proposed_member_subset),
            oracle_vault=req.proposed_oracle_vault,
            env=env,
        )
    except Exception:
        # Roll back — keep the request so the registrar/PI can iterate.
        req.state = "pending"
        req.resolved_at = None
        req.resolved_by = None
        write_request(req, env)
        raise
    return entry


def decline(
    req_id: int,
    *,
    by_handle: str,
    reason: str = "",
    env: dict[str, str] | None = None,
) -> CollabRequest:
    """Decline a pending request. Free-text ``reason`` is recorded."""
    req = _get(req_id, env)
    if req.state in TERMINAL_STATES:
        raise CollabRequestStateError(
            f"request {req_id} is already {req.state}; cannot decline")
    req.state = "declined"
    req.resolved_at = _dt.datetime.now(_dt.timezone.utc).isoformat()
    req.resolved_by = (by_handle if by_handle.startswith("@")
                       else f"@{by_handle.lstrip('@')}")
    req.decline_reason = reason or None
    write_request(req, env)
    return req
