"""
Purpose: Project-join request registry stored in
         ``<lab-mgmt>/requests/<id>.md``. Anyone can file a request to
         join an existing project; the PI approves or declines via the
         dashboard's Requests panel (or the matching CLI commands).
Author: Mike Hallett (with Claude Code)
Date: 2026-05-08
Input: Markdown files with frontmatter, one per request.
Output: ``JoinRequest`` dataclass; lifecycle helpers that mutate it +
        persist back to disk.

Layout::

    <lab-mgmt>/requests/
    ├── 1.md          ← @bob asks to join dcis_sc_tutorial
    ├── 2.md          ← @cassie asks to join bbb_drug_screen
    └── ...

Each file's frontmatter declares: ``id, requester, project, kind,
justification, state, created_at, resolved_at, resolved_by,
decline_reason``. ``state`` is one of ``pending | approved | declined``.

Lifecycle:

  pending  --(approve)-->  approved      (membership added on the way)
  pending  --(decline)-->  declined      (with a reason)

Approval applies the side effect of adding the requester to the
project's ``CHARTER.md`` ``members:`` list and the ``MEMBERS`` file.
Decline only updates the request state.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal

from .frontmatter import dump_document, parse_file
from .projects import find_project
from .repo import MEMBERS_FILENAME, lab_mgmt_repo_root

REQUESTS_SUBDIR = "requests"
REQUEST_ID_RE = re.compile(r"^(?P<id>\d+)\.md$")
VALID_KINDS: tuple[str, ...] = ("project-join",)
VALID_STATES: tuple[str, ...] = ("pending", "approved", "declined")
TERMINAL_STATES = frozenset({"approved", "declined"})


class RequestError(ValueError):
    """Base for request lifecycle / state errors."""


class RequestStateError(RequestError):
    """Tried to transition a request that's already terminal."""


class RequestNotFound(RequestError):
    """No matching request file on disk."""


@dataclass
class JoinRequest:
    """One project-join request loaded from disk."""

    id: int
    requester: str
    project: str
    kind: str = "project-join"
    justification: str = ""
    state: str = "pending"
    created_at: str | None = None
    resolved_at: str | None = None
    resolved_by: str | None = None
    decline_reason: str | None = None
    body: str = ""
    path: Path | None = None

    def to_meta(self) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "id": self.id,
            "requester": self.requester,
            "project": self.project,
            "kind": self.kind,
            "justification": self.justification,
            "state": self.state,
        }
        for key, value in (
            ("created_at", self.created_at),
            ("resolved_at", self.resolved_at),
            ("resolved_by", self.resolved_by),
            ("decline_reason", self.decline_reason),
        ):
            if value is not None:
                meta[key] = value
        return meta


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def requests_dir() -> Path:
    """Resolve ``<lab-mgmt>/requests/``."""
    return lab_mgmt_repo_root() / REQUESTS_SUBDIR


def request_path(req_id: int) -> Path:
    """Resolve ``<lab-mgmt>/requests/<id>.md``."""
    return requests_dir() / f"{req_id}.md"


def parse_request(path: Path) -> JoinRequest:
    """Parse one request markdown file."""
    parsed = parse_file(path)
    meta = parsed.meta
    return JoinRequest(
        id=int(meta["id"]),
        requester=str(meta["requester"]),
        project=str(meta["project"]),
        kind=str(meta.get("kind", "project-join")),
        justification=str(meta.get("justification", "")),
        state=str(meta.get("state", "pending")),
        created_at=_opt_str(meta.get("created_at")),
        resolved_at=_opt_str(meta.get("resolved_at")),
        resolved_by=_opt_str(meta.get("resolved_by")),
        decline_reason=_opt_str(meta.get("decline_reason")),
        body=parsed.body,
        path=path,
    )


def iter_requests() -> list[JoinRequest]:
    """Return every request on disk, ordered by integer id."""
    out: list[JoinRequest] = []
    rdir = requests_dir()
    if not rdir.is_dir():
        return out
    for child in rdir.iterdir():
        m = REQUEST_ID_RE.match(child.name)
        if not m:
            continue
        try:
            out.append(parse_request(child))
        except Exception:
            continue
    out.sort(key=lambda r: r.id)
    return out


def next_request_id() -> int:
    used = [r.id for r in iter_requests()]
    return (max(used) + 1) if used else 1


def render_request(req: JoinRequest) -> str:
    """Render a request to its on-disk markdown form."""
    body = req.body or _default_body(req)
    return dump_document(req.to_meta(), body)


def write_request(req: JoinRequest) -> Path:
    """Persist ``req`` to ``<lab-mgmt>/requests/<id>.md``."""
    rdir = requests_dir()
    rdir.mkdir(parents=True, exist_ok=True)
    path = request_path(req.id)
    path.write_text(render_request(req), encoding="utf-8")
    req.path = path
    return path


# ---------------------------------------------------------------------------
# lifecycle
# ---------------------------------------------------------------------------


def file_request(
    *,
    requester: str,
    project: str,
    justification: str = "",
    today: _dt.date | None = None,
) -> JoinRequest:
    """File a new project-join request and persist it.

    Refuses if the requester is already a member of the project (so the
    PI's queue doesn't fill with duplicates).
    """
    today = today or _dt.date.today()
    repo = find_project(project)
    if repo is None:
        raise RequestError(f"project not found: {project}")
    norm = requester.lstrip("@").lower()
    if repo.members_path and repo.members_path.is_file():
        existing = {
            line.strip().lstrip("@").lower()
            for line in repo.members_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        }
        if norm in existing:
            raise RequestError(f"@{norm} is already a member of {project}")
    # Also refuse if there's already a pending request from the same person.
    for existing_req in iter_requests():
        if (
            existing_req.state == "pending"
            and existing_req.project == project
            and existing_req.requester.lstrip("@").lower() == norm
        ):
            raise RequestError(
                f"@{norm} already has a pending join request for {project} "
                f"(#{existing_req.id})"
            )

    req = JoinRequest(
        id=next_request_id(),
        requester=_at(requester),
        project=project,
        kind="project-join",
        justification=justification,
        state="pending",
        created_at=today.isoformat(),
    )
    write_request(req)
    return req


def approve(
    req: JoinRequest,
    *,
    approver: str,
    today: _dt.date | None = None,
) -> JoinRequest:
    """Mark the request approved and add the requester to the project."""
    if req.state in TERMINAL_STATES:
        raise RequestStateError(
            f"request #{req.id} is already {req.state}; cannot approve."
        )
    today = today or _dt.date.today()
    _add_to_project_members(req.project, req.requester)
    req.state = "approved"
    req.resolved_at = today.isoformat()
    req.resolved_by = _at(approver)
    return req


def decline(
    req: JoinRequest,
    *,
    decliner: str,
    reason: str,
    today: _dt.date | None = None,
) -> JoinRequest:
    """Mark the request declined with a reason."""
    if req.state in TERMINAL_STATES:
        raise RequestStateError(
            f"request #{req.id} is already {req.state}; cannot decline."
        )
    if not reason:
        raise RequestError("decline requires a reason")
    today = today or _dt.date.today()
    req.state = "declined"
    req.resolved_at = today.isoformat()
    req.resolved_by = _at(decliner)
    req.decline_reason = reason
    return req


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _at(handle: str) -> str:
    h = handle.strip()
    return h if h.startswith("@") else f"@{h}"


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return str(value)


def _default_body(req: JoinRequest) -> str:
    return (
        f"# Project-join request #{req.id}\n\n"
        f"**{req.requester}** asks to join **{req.project}**.\n\n"
        f"## Justification\n\n{req.justification or '_(none provided)_'}\n"
    )


def _add_to_project_members(project_name: str, handle: str) -> None:
    """Append ``handle`` to the project's CHARTER members list and MEMBERS file.

    Idempotent: if the handle is already there, this is a no-op. Mirrors
    what ``project_cmd.cmd_admit`` does, without the click dependencies,
    so the API can call it directly.
    """
    repo = find_project(project_name)
    if repo is None:
        raise RequestError(f"project not found: {project_name}")
    norm_handle = _at(handle)

    parsed = parse_file(repo.charter_path)
    members = [str(h) for h in parsed.meta.get("members") or []]
    if norm_handle not in members:
        members.append(norm_handle)
        parsed.meta["members"] = members
        repo.charter_path.write_text(
            dump_document(parsed.meta, parsed.body), encoding="utf-8"
        )

    members_path = repo.path / MEMBERS_FILENAME
    if members_path.is_file():
        existing_lines = members_path.read_text(encoding="utf-8").splitlines()
        existing_handles = {
            line.strip().lstrip("@").lower()
            for line in existing_lines
            if line.strip() and not line.strip().startswith("#")
        }
    else:
        existing_lines = ["# Project members (one handle per line)"]
        existing_handles = set()

    if norm_handle.lstrip("@").lower() not in existing_handles:
        existing_lines.append(norm_handle)
        members_path.write_text("\n".join(existing_lines) + "\n", encoding="utf-8")


def filter_pending(reqs: Iterable[JoinRequest]) -> list[JoinRequest]:
    return [r for r in reqs if r.state == "pending"]


def filter_for_requester(reqs: Iterable[JoinRequest], handle: str) -> list[JoinRequest]:
    norm = handle.lstrip("@").lower()
    return [r for r in reqs if r.requester.lstrip("@").lower() == norm]
