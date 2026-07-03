"""
Purpose: Slack routing for the centre join flow (Phase 2 communication
         backbone). When a join request is filed, notify the centre's
         registrars via the admin broadcast channel; when it is resolved,
         DM the requester with the outcome.
Author: Mike Hallett (with Claude Code)
Date: 2026-07-03

Every function here is **best-effort and never raises** — a join request
must still succeed if Slack is down, the bot token is missing, or the
admin channel isn't configured yet. That mirrors ``dashboard/slack_notify``
(fire-and-forget). All Slack I/O is injectable so tests never hit the wire.

Defaults resolve to the live helpers:
  - ``poster``           → ``slack_notify._post(channel, text)``
  - ``channel_resolver`` → ``broadcasts.channel_id_for(audience, env=...)``
  - ``user_resolver``    → ``slack_notify._lookup_user_id_by_email(email)``

The routing is intentionally coarse: new requests post to the **admin**
channel (the mayor + registrars watch it) rather than DMing each registrar
individually, and the requester is DM'd by the email they supplied. DMing
the matched PI directly is a later refinement (needs a handle→Slack-id map).
"""

from __future__ import annotations

import logging
from typing import Callable

log = logging.getLogger("wigamig.join_notify")

# Injectable seams (see module docstring). Kept as module attributes so
# callers/tests can monkeypatch, and so the live imports stay lazy.
PosterFn = Callable[[str, str], bool]
ChannelResolverFn = Callable[..., str]
UserResolverFn = Callable[[str], "str | None"]


def _default_poster(channel: str, text: str) -> bool:
    from ..dashboard import slack_notify
    return slack_notify._post(channel, text)


def _default_channel_resolver(audience: str, *, env=None) -> str:
    from . import broadcasts
    return broadcasts.channel_id_for(audience, env=env)


def _default_user_resolver(email: str):
    from ..dashboard import slack_notify
    return slack_notify._lookup_user_id_by_email(email)


def _has_token() -> bool:
    """Cheap short-circuit so a token-less environment (most tests, a
    laptop with no Slack configured) does zero Slack work."""
    try:
        from ..dashboard import slack_notify
        return bool(slack_notify._token())
    except Exception:  # noqa: BLE001
        return False


def _fmt_new(req) -> str:
    bits = [
        f"🆕 *New join request* #{req.id:04d}",
        f"kind: `{req.kind}`",
        f"name: `{req.proposed_name}`",
    ]
    if req.proposed_pi:
        bits.append(f"PI: {req.proposed_pi}")
    if req.institution_affiliation:
        bits.append(f"from: {req.institution_affiliation}")
    if req.requester_email:
        bits.append(f"contact: {req.requester_email}")
    head = " · ".join(bits)
    tail = ""
    if req.justification:
        tail = f"\n> {req.justification}"
    return f"{head}{tail}\nReview + approve/decline in the /registrar dashboard."


def _fmt_decision(req) -> str:
    label = f"{req.kind} `{req.proposed_name}`"
    if req.state in ("approved", "provisioned"):
        return (
            f"✅ Your wigamig join request #{req.id:04d} ({label}) was "
            f"*approved*. The registrar will follow up with next steps."
        )
    if req.state == "declined":
        reason = f" Reason: {req.decline_reason}" if req.decline_reason else ""
        return (
            f"❌ Your wigamig join request #{req.id:04d} ({label}) was "
            f"*declined*.{reason}"
        )
    if req.state == "failed":
        return (
            f"⚠️ Your wigamig join request #{req.id:04d} ({label}) was "
            f"approved but provisioning hit a snag; the registrar is on it."
        )
    return (
        f"Your wigamig join request #{req.id:04d} ({label}) is now "
        f"`{req.state}`."
    )


def notify_new_request(
    req,
    *,
    env=None,
    poster: PosterFn | None = None,
    channel_resolver: ChannelResolverFn | None = None,
) -> bool:
    """Post a summary of a newly-filed request to the admin channel.

    Returns True iff a message was posted. Never raises.
    """
    if not _has_token():
        return False
    poster = poster or _default_poster
    channel_resolver = channel_resolver or _default_channel_resolver
    try:
        channel = channel_resolver("admin", env=env)
    except Exception as exc:  # noqa: BLE001 — e.g. channel not configured
        log.info("join_notify: admin channel not configured (%s); skipping", exc)
        return False
    if not channel:
        return False
    try:
        return bool(poster(channel, _fmt_new(req)))
    except Exception as exc:  # noqa: BLE001
        log.warning("join_notify.notify_new_request failed: %s", exc)
        return False


def notify_decision(
    req,
    *,
    env=None,
    poster: PosterFn | None = None,
    user_resolver: UserResolverFn | None = None,
) -> bool:
    """DM the requester with the approve/decline/failed outcome.

    Looks the requester up by the email they supplied. Returns True iff a
    DM was sent (False if they aren't in the workspace). Never raises.
    """
    if not _has_token():
        return False
    if not (req.requester_email or "").strip():
        return False
    poster = poster or _default_poster
    user_resolver = user_resolver or _default_user_resolver
    try:
        uid = user_resolver(req.requester_email.strip())
    except Exception as exc:  # noqa: BLE001
        log.warning("join_notify: user lookup failed: %s", exc)
        return False
    if not uid:
        log.info("join_notify: %s not in Slack workspace; no DM sent",
                 req.requester_email)
        return False
    try:
        # chat.postMessage with channel=<user_id> opens/uses the DM.
        return bool(poster(uid, _fmt_decision(req)))
    except Exception as exc:  # noqa: BLE001
        log.warning("join_notify.notify_decision failed: %s", exc)
        return False


__all__ = ["notify_new_request", "notify_decision"]
