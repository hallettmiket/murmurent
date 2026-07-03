"""
Purpose: Orchestration layer for wigamig's Slack communication fabric.
Author: Mike Hallett (with Claude Code)
Date: 2026-07-03

Wires the existing engines into the wigamig lifecycle so Slack is the primary
comms channel:
  - a private **mayor↔CC channel** where the code posts centre events;
  - a private **per-lab/core channel** named after the group, members-only;
  - `#general` for broadcasts (handled by `core/broadcasts.py`).

Reuses (does not re-implement):
  - `centre_provision.slack_create_channel` — create a private channel.
  - `slack_notify.invite_members_to_channel` — handle→email→uid→invite.
  - `slack_notify._lookup_channel_id_by_name` — recover an existing channel id.
  - `slack_notify.normalize_channel_name` — Slack channel-name validation.

**Best-effort + opt-in:** every function no-ops (returns None) when no Slack
token is configured, so `create_lab` / `create_core` / `init_centre` can call
them unconditionally without affecting the token-less dev/test paths. Nothing
here raises.
"""

from __future__ import annotations

import logging
from typing import Callable

log = logging.getLogger("wigamig.slack_comms")


# ---------------------------------------------------------------------------
# Guards / helpers
# ---------------------------------------------------------------------------

def token_present() -> bool:
    """True iff a Slack bot token is configured (enforcement/activity on)."""
    try:
        from ..dashboard import slack_notify
        return bool(slack_notify._token())
    except Exception:  # noqa: BLE001
        return False


def channel_name_for(group: str) -> str | None:
    """The Slack channel name for a lab/core = the group's own name,
    normalized to Slack rules (lowercase, `[a-z0-9_-]`, <=80). None if the
    name can't be made valid."""
    try:
        from ..dashboard import slack_notify
        return slack_notify.normalize_channel_name(group)
    except Exception:  # noqa: BLE001
        return None


def _create_channel(name: str, *, private: bool, creator: Callable | None):
    from . import centre_provision as cp
    creator = creator or cp.slack_create_channel
    return creator(name, private=private)


def _resolve_existing_channel(name: str) -> str:
    from ..dashboard import slack_notify
    return slack_notify._lookup_channel_id_by_name(name) or ""


# ---------------------------------------------------------------------------
# Group (lab / core) channels
# ---------------------------------------------------------------------------

def ensure_group_channel(
    group: str,
    email_map: dict[str, str] | None = None,
    *,
    private: bool = True,
    creator: Callable | None = None,
    inviter: Callable | None = None,
) -> dict | None:
    """Ensure a private Slack channel named after ``group`` exists and that
    the given members (``{handle: email}``) are in it.

    Returns a structured summary
    ``{channel_name, channel_id, created, invited, already_in, unresolved, error}``
    or ``None`` when no token is configured (nothing attempted). Idempotent:
    a `name_taken` create recovers the existing channel id, and the invite
    step skips members already present. Never raises.
    """
    if not token_present():
        return None
    chan = channel_name_for(group)
    if not chan:
        return {"channel_name": group, "channel_id": "", "created": False,
                "invited": [], "already_in": [], "unresolved": [],
                "error": f"invalid Slack channel name from {group!r}"}
    out = {"channel_name": chan, "channel_id": "", "created": False,
           "invited": [], "already_in": [], "unresolved": [], "error": ""}
    try:
        res = _create_channel(chan, private=private, creator=creator)
        if res.ok:
            out["channel_id"] = res.channel_id
            out["created"] = "created" in (res.detail or "").lower()
        elif res.error == "name_taken":
            out["channel_id"] = _resolve_existing_channel(chan)
            if not out["channel_id"]:
                out["error"] = "channel exists but its id could not be resolved"
                return out
        else:
            out["error"] = res.detail or res.error or "channel create failed"
            return out

        if out["channel_id"] and email_map:
            from ..dashboard import slack_notify
            inviter = inviter or slack_notify.invite_members_to_channel
            inv = inviter(out["channel_id"], list(email_map.keys()),
                          member_email_map=email_map)
            out["invited"] = inv.get("invited", [])
            out["already_in"] = inv.get("already_in", [])
            out["unresolved"] = inv.get("unresolved", [])
            if inv.get("error"):
                out["error"] = inv["error"]
    except Exception as exc:  # noqa: BLE001
        out["error"] = str(exc)
        log.warning("ensure_group_channel(%s) failed: %s", group, exc)
    return out


# ---------------------------------------------------------------------------
# Mayor ↔ CC channel
# ---------------------------------------------------------------------------

def ensure_mayor_channel(
    unique_name: str = "",
    *,
    creator: Callable | None = None,
) -> str | None:
    """Ensure the private mayor↔CC events channel exists; return its id (or
    ``None`` when no token). Channel name: ``wigamig-ops`` (per-centre, but a
    workspace hosts one centre, so a fixed name is fine and easy to find).
    Idempotent. Never raises."""
    if not token_present():
        return None
    name = channel_name_for("wigamig-ops")
    try:
        res = _create_channel(name, private=True, creator=creator)
        if res.ok:
            return res.channel_id
        if res.error == "name_taken":
            return _resolve_existing_channel(name) or None
        log.warning("ensure_mayor_channel failed: %s", res.detail or res.error)
    except Exception as exc:  # noqa: BLE001
        log.warning("ensure_mayor_channel errored: %s", exc)
    return None


__all__ = [
    "token_present", "channel_name_for",
    "ensure_group_channel", "ensure_mayor_channel",
]
