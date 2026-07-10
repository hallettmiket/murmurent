"""
Purpose: Authorise + apply SEA lifecycle transitions from the dashboard
         (Phase 4). Wraps :mod:`murmurent.core.sea` with actor checks so the
         ``POST /api/sea/...`` endpoints can refuse mismatched users
         instead of silently mutating files.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-08
Input: Caller's handle, project name, SEA id, action name, action kwargs.
Output: Updated :class:`murmurent.core.sea.Sea` on success; typed exceptions
        on auth or state failure (mapped to HTTP codes by the server).

Authorisation matrix (incoming = recipient, outgoing = requester):

    action      | who can do it
    ------------+----------------------------------------------------------
    claim       | to_handle (recipient)
    complete    | to_handle
    decline     | to_handle
    examine     | to_handle OR from_handle (the squad)
    conclude    | to_handle OR from_handle
    reopen      | to_handle OR from_handle
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..core import sea as sea_core
from ..core.projects import find_project
from ..core.sea import Sea, SeaTransitionError
from . import audit_log

ActionName = Literal["claim", "complete", "decline", "examine", "conclude", "reopen"]


class SeaActionError(Exception):
    """Base for all SEA-action failures we map to HTTP status codes."""


class SeaNotFound(SeaActionError):
    """Project or SEA missing on disk."""


class SeaForbidden(SeaActionError):
    """Caller is not authorised to perform this action."""


class SeaConflict(SeaActionError):
    """SEA state doesn't allow the requested transition."""


class SeaBadRequest(SeaActionError):
    """Action requires kwargs that weren't supplied (e.g. ``delivery``)."""


@dataclass(frozen=True)
class ActionResult:
    """Returned to the caller on success."""

    sea: Sea
    project: str


# Actor authorisation predicates per action.
def _is_recipient(sea: Sea, actor: str) -> bool:
    return sea.to_handle.lstrip("@").lower() == actor.lstrip("@").lower()


def _is_squad(sea: Sea, actor: str) -> bool:
    norm = actor.lstrip("@").lower()
    return norm in {sea.from_handle.lstrip("@").lower(), sea.to_handle.lstrip("@").lower()}


_AUTH = {
    "claim": _is_recipient,
    "complete": _is_recipient,
    "decline": _is_recipient,
    "examine": _is_squad,
    "conclude": _is_squad,
    "reopen": _is_squad,
}


def apply_action(
    *,
    project: str,
    sea_id: int,
    action: str,
    actor: str,
    delivery: str | None = None,
    reason: str | None = None,
) -> ActionResult:
    """Authorise + apply ``action`` to SEA ``sea_id`` in ``project``.

    Caller is expected to handle persistence-side concerns (this module
    persists the SEA file but does not commit it; commits remain a CLI
    concern in v1).
    """
    if action not in _AUTH:
        raise SeaBadRequest(f"unknown action: {action!r}")

    if not actor:
        raise SeaForbidden("no actor identity resolved")

    repo = find_project(project)
    if repo is None:
        raise SeaNotFound(f"project not found: {project}")

    path = sea_core.sea_path(repo, sea_id)
    if not path.is_file():
        raise SeaNotFound(f"SEA #{sea_id} not found in {project}")

    sea = sea_core.parse_sea(path)

    if not _AUTH[action](sea, actor):
        raise SeaForbidden(
            f"@{actor.lstrip('@')} cannot {action} SEA #{sea_id} "
            f"(from {sea.from_handle}, to {sea.to_handle})"
        )

    try:
        if action == "claim":
            sea_core.claim(sea)
        elif action == "complete":
            if not delivery:
                raise SeaBadRequest("complete requires a delivery path")
            sea_core.complete(sea, delivery=delivery)
        elif action == "decline":
            if not reason:
                raise SeaBadRequest("decline requires a reason")
            sea_core.decline(sea, reason=reason)
        elif action == "examine":
            sea_core.mark_examined(sea)
        elif action == "conclude":
            sea_core.mark_concluded(sea)
        elif action == "reopen":
            sea_core.reopen(sea)
    except SeaTransitionError as exc:
        raise SeaConflict(str(exc)) from exc

    sea_core.write_sea(repo, sea)
    _log_event(action, sea, actor, project, delivery=delivery, reason=reason)
    return ActionResult(sea=sea, project=project)


def _log_event(
    action: str,
    sea: Sea,
    actor: str,
    project: str,
    *,
    delivery: str | None = None,
    reason: str | None = None,
) -> None:
    """Append one ``sea.<action>`` row to the lab-mgmt audit chain.

    Audit must never block the action — failures here are swallowed.
    """
    handle = actor if actor.startswith("@") else f"@{actor}"
    summary = _action_summary(action, sea, handle, delivery=delivery, reason=reason)
    try:
        audit_log.write_event(
            actor=handle,
            kind=f"sea.{action}",
            project=project,
            target=f"sea/{sea.id}",
            summary=summary,
        )
    except OSError:
        pass


def _action_summary(
    action: str,
    sea: Sea,
    actor: str,
    *,
    delivery: str | None = None,
    reason: str | None = None,
) -> str:
    """One-line, human-readable summary for the dashboard notifs feed."""
    base = f"{actor} {action} SEA #{sea.id}"
    if action == "complete" and delivery:
        return f"{base} (delivery: {delivery})"
    if action == "decline" and reason:
        return f"{base} ({reason})"
    return base
