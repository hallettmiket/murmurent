"""
Purpose: Authorise + apply project-join request lifecycle from the
         dashboard. Wraps :mod:`wigamig.core.requests` with an actor
         check + audit logging so the API endpoints can refuse
         mismatched users instead of silently mutating files.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-08
Input: Caller's handle, request id, action name, optional reason.
Output: Updated :class:`wigamig.core.requests.JoinRequest` on success;
        typed exceptions on auth or state failure.

Authorisation matrix:

    action     | who can do it
    -----------+--------------------------------------------------
    file       | anyone (gated to non-members of the target project)
    approve    | the lab PI (from <lab-mgmt>/lab.md)
    decline    | the lab PI

The PI handle is read from ``<lab-mgmt>/lab.md`` per call (so a PR
against that file rotates the approver without a code change).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core import requests as req_core
from ..core.lab import pi_handle
from ..core.requests import JoinRequest, RequestError, RequestNotFound, RequestStateError
from . import audit_log


class RequestActionError(Exception):
    """Base for HTTP-mappable failures."""


class RequestForbidden(RequestActionError):
    """Caller isn't authorised for this transition (or unknown caller)."""


class RequestBadRequest(RequestActionError):
    """Action requires kwargs that weren't supplied (e.g. ``reason``)."""


class RequestConflict(RequestActionError):
    """Bad state transition (already approved/declined)."""


class RequestMissing(RequestActionError):
    """No matching request id, or referenced project doesn't exist."""


@dataclass(frozen=True)
class FileResult:
    request: JoinRequest


@dataclass(frozen=True)
class TransitionResult:
    request: JoinRequest


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def file_join_request(
    *,
    actor: str,
    project: str,
    justification: str = "",
) -> FileResult:
    """Anyone can file a request — no PI gate. Audited.

    Phase 5: before filing, check that the actor has a ``git_logins``
    entry for the project's git provider. Without one, the eventual
    approve flow can't add them as a collaborator on the project's
    remote, so the join is essentially DOA — better to surface that
    here than after approval.
    """
    if not actor:
        raise RequestForbidden("no actor identity resolved")

    # Provider gate. Reads the project's git_provider id (or legacy
    # repo_kind value) from its CHARTER.md and looks for a matching
    # git_logins[<provider_id>] on the actor's member profile.
    missing = _check_member_login_for_project(actor, project)
    if missing is not None:
        raise RequestBadRequest(
            f"You need to register your {missing!r} username in Member Profile → "
            "Git logins before joining this project. (The PI can't add you as a "
            f"collaborator on the {missing} remote until then.)"
        )

    try:
        req = req_core.file_request(
            requester=actor, project=project, justification=justification
        )
    except RequestError as exc:
        # Already-a-member, duplicate pending, missing project.
        msg = str(exc)
        if "not found" in msg:
            raise RequestMissing(msg) from exc
        raise RequestBadRequest(msg) from exc
    _log("request.file", req, actor, summary=_file_summary(req))
    return FileResult(request=req)


def _check_member_login_for_project(actor: str, project: str) -> str | None:
    """Return the provider id the actor needs a login for, or ``None``
    when they're already good.

    The check is best-effort: if we can't resolve the project's
    provider (missing CHARTER, missing lab.md, etc.) we let the
    request through rather than block on what might be transient
    state. Hard-fails (provider declared, login missing) raise.
    """
    try:
        from ..core import git_providers as _gp
        from ..core.frontmatter import parse_file
        from ..core.projects import project_path
        from ..core.repo import lab_mgmt_repo_root
    except Exception:
        return None
    try:
        charter = project_path(project) / "CHARTER.md"
        if not charter.is_file():
            return None
        meta = parse_file(charter).meta or {}
        provider_id = (
            str(meta.get("git_provider") or meta.get("repo_kind") or "github").strip()
        )
        # ``local`` / ``local-bare`` providers don't have per-user
        # logins — filesystem permissions on the bare repo are the
        # access control. Skip the gate.
        if provider_id in ("local", "local-bare"):
            return None
        member_file = lab_mgmt_repo_root() / "members" / f"{actor.lstrip('@')}.md"
        if not member_file.is_file():
            return None
        member_meta = parse_file(member_file).meta or {}
        logins = _gp.parse_logins(member_meta)
        if logins.get(provider_id):
            return None
        return provider_id
    except Exception:
        return None


def file_create_request(
    *,
    actor: str,
    project: str,
    proposed_members: list[str],
    sensitivity: str = "standard",
    proposed_lead: str | None = None,
    justification: str = "",
    repo_kind: str = "github",
    local_repo_root: str | None = None,
    host: str = "local",
) -> FileResult:
    """Propose creating a new project. PI approval scaffolds the repo."""
    if not actor:
        raise RequestForbidden("no actor identity resolved")
    try:
        req = req_core.file_create_request(
            requester=actor,
            project=project,
            proposed_members=proposed_members,
            sensitivity=sensitivity,
            proposed_lead=proposed_lead,
            justification=justification,
            repo_kind=repo_kind,
            local_repo_root=local_repo_root,
            host=host,
        )
    except RequestError as exc:
        msg = str(exc)
        raise RequestBadRequest(msg) from exc
    _log(
        "request.file",
        req,
        actor,
        summary=f"{req.requester} proposed new project {req.project}",
    )
    return FileResult(request=req)


def apply_action(
    *,
    request_id: int,
    action: str,
    actor: str,
    reason: str | None = None,
) -> TransitionResult:
    """Approve or decline a request. PI only."""
    if action not in {"approve", "decline"}:
        raise RequestBadRequest(f"unknown action: {action!r}")
    if not actor:
        raise RequestForbidden("no actor identity resolved")

    pi = pi_handle()
    if actor.lstrip("@").lower() != pi:
        raise RequestForbidden(
            f"only the lab PI (@{pi}) can {action} join requests; "
            f"caller is @{actor.lstrip('@')}"
        )

    path = req_core.request_path(request_id)
    if not path.is_file():
        raise RequestMissing(f"request #{request_id} not found")
    req = req_core.parse_request(path)

    try:
        if action == "approve":
            req_core.approve(req, approver=actor)
        elif action == "decline":
            if not reason:
                raise RequestBadRequest("decline requires a reason")
            req_core.decline(req, decliner=actor, reason=reason)
    except RequestStateError as exc:
        raise RequestConflict(str(exc)) from exc
    except RequestError as exc:
        raise RequestBadRequest(str(exc)) from exc

    req_core.write_request(req)
    _log(f"request.{action}", req, actor, summary=_action_summary(action, req, actor))
    return TransitionResult(request=req)


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


def _log(kind: str, req: JoinRequest, actor: str, *, summary: str) -> None:
    handle = actor if actor.startswith("@") else f"@{actor}"
    try:
        audit_log.write_event(
            actor=handle,
            kind=kind,
            project=req.project,
            target=f"request/{req.id}",
            summary=summary,
        )
    except OSError:
        pass


def _file_summary(req: JoinRequest) -> str:
    return f"{req.requester} requested to join {req.project}"


def _action_summary(action: str, req: JoinRequest, actor: str) -> str:
    handle = actor if actor.startswith("@") else f"@{actor}"
    if action == "approve":
        return f"{handle} approved {req.requester}'s request to join {req.project}"
    return f"{handle} declined {req.requester}'s request to join {req.project}"
