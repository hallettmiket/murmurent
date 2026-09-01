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

log = logging.getLogger("murmurent.join_notify")

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


def group_onboarding_steps(name: str, *, invite_url: str = "") -> list[str]:
    """The ordered checklist a NEW PI runs to stand up their group's
    environment. Shared by the invite email, the CLI next-steps block, and the
    Slack reminder so the three never drift. ``invite_url`` is the centre's
    Slack workspace join link (blank → the registrar hasn't set one yet)."""
    first = (f"Join the centre Slack workspace: {invite_url}" if invite_url
             else "Join the centre Slack workspace (the registrar will email you "
                  "the invite link).")
    return [
        first,
        f"Create your group's GitHub repo — you choose the org + visibility "
        f"(the mayor does NOT create it):  murmurent group-init-toolkit {name} --create-repo",
        f"Fill in your group's details — GitHub repo, lab-notebook host/path, "
        f"your group's OWN Slack workspace + invite link, large-dataset location:  "
        f"murmurent group-setup {name}",
        f"Propagate members into your group's Slack workspace + GitHub repo:  "
        f"murmurent group-reconcile {name} --apply",
    ]


def _fmt_provisioned(req, *, invite_url: str = "") -> str:
    """Message to the mayor/registrar (admin channel) when a lab/core is
    provisioned: confirms it + reminds them to email the new PI the invite."""
    role = "PI" if req.kind == "lab" else "leader"
    who = (req.requester_email or "").strip() or "the new " + role
    pi = (req.proposed_pi or "").strip()
    head = (f"✅ *{req.kind} `{req.proposed_name}` provisioned* — "
            f"{role}: {pi + ' · ' if pi else ''}{who}")
    if invite_url:
        action = (f"➡️ *Action for the registrar:* email {who} the workspace "
                  f"invite link so they can join and set up their group:\n{invite_url}")
    else:
        action = (f"➡️ *Action for the registrar:* set a workspace invite link "
                  f"(`murmurent centre-set slack_invite_url=…`), then email it to "
                  f"{who} so they can join.")
    setup = (f"Their group setup: `murmurent group-init-toolkit {req.proposed_name} "
             f"--create-repo` → `murmurent group-setup {req.proposed_name}` → "
             f"`murmurent group-reconcile {req.proposed_name} --apply`.")
    return f"{head}\n{action}\n{setup}"


def _fmt_new(req, *, pi: str = "") -> str:
    if req.kind == "member":
        who = req.proposed_pi or req.requester_email or "someone"
        head = (f"🆕 *Join request* #{req.id:04d} — {who} wants to join "
                f"*{req.proposed_name}*")
        if req.requester_email:
            head += f" · contact: {req.requester_email}"
        tail = f"\n> {req.justification}" if req.justification else ""
        actor = ("@" + pi.lstrip("@")) if (pi or "").strip() else "@<pi>"
        return (f"{head}{tail}\nApprove with "
                f"`murmurent join-request approve {req.id} --actor {actor}` "
                "or the /registrar Requests panel.")
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
            f"✅ Your murmurent join request #{req.id:04d} ({label}) was "
            f"*approved*. Check your email for the workspace invite link + "
            f"the steps to set up your group."
        )
    if req.state == "declined":
        reason = f" Reason: {req.decline_reason}" if req.decline_reason else ""
        return (
            f"❌ Your murmurent join request #{req.id:04d} ({label}) was "
            f"*declined*.{reason}"
        )
    if req.state == "failed":
        return (
            f"⚠️ Your murmurent join request #{req.id:04d} ({label}) was "
            f"approved but provisioning hit a snag; the registrar is on it."
        )
    return (
        f"Your murmurent join request #{req.id:04d} ({label}) is now "
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
    member_pi = ""
    try:
        if getattr(req, "kind", "") == "member":
            # A member request is the group's PI's call, not the mayor's — post
            # to the group's own channel (the PI is in it). Fall back to the
            # admin channel if the group has no channel yet. Capture the PI so
            # the approve hint names them instead of a placeholder.
            from . import registrar as _reg
            reg = _reg.read_registry(env)
            entry = next((g for g in [*reg.labs, *reg.cores]
                          if g.name == req.proposed_name), None)
            member_pi = getattr(entry, "pi", "") if entry else ""
            channel = (getattr(entry, "slack_channel_id", None) if entry else None) \
                or channel_resolver("admin", env=env)
        else:
            channel = channel_resolver("admin", env=env)
    except Exception as exc:  # noqa: BLE001 — e.g. channel not configured
        log.info("join_notify: target channel not resolved (%s); skipping", exc)
        return False
    if not channel:
        return False
    try:
        return bool(poster(channel, _fmt_new(req, pi=member_pi)))
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


def pi_onboarding_messages(group: str, *, centre_name: str = "your centre",
                           channel_name: str = "") -> list[str]:
    """The step-by-step DMs a PI receives once they join the workspace — one per
    line of the flow (registrar -> cable_guy -> security_guard -> dashboard).
    Shared so the messages stay consistent wherever they're sent."""
    ch = channel_name or group
    return [
        f"👋 Welcome to {centre_name}! You're now in the Slack workspace as PI of *{group}*.",
        f"📋 *registrar*: you're recorded as the PI of *{group}* in the centre registry.",
        f"🔌 *cable_guy*: your group's private channel *#{ch}* is ready and you've been added. "
        f"Your members will be added here as they join.",
        f"🛡️ *security_guard*: registered for *{group}* — it audits your group's shared "
        f"files + secrets on every push, so nothing sensitive leaks.",
        f"📝 *Next*: fill in your group's details in the lab dashboard — GitHub repo, "
        f"lab-notebook + Obsidian locations, and storage servers. Open Lab settings there.",
    ]


def notify_pi_onboarded(
    group: str,
    *,
    email: str,
    env=None,
    centre_name: str = "",
    channel_name: str = "",
    poster: PosterFn | None = None,
    user_resolver: UserResolverFn | None = None,
    messages: list[str] | None = None,
) -> bool:
    """DM the PI the step-by-step onboarding acknowledgement, once they've joined
    the workspace. Resolves them by email; best-effort + token-gated; returns
    True iff at least one DM was delivered."""
    if not _has_token():
        return False
    if not (email or "").strip():
        return False
    poster = poster or _default_poster
    user_resolver = user_resolver or _default_user_resolver
    if centre_name == "":
        try:
            from . import centre_init as _ci
            prof = _ci.read_centre(env=env)
            centre_name = (getattr(prof, "name", "") or "your centre") if prof else "your centre"
        except Exception:  # noqa: BLE001
            centre_name = "your centre"
    try:
        uid = user_resolver(email.strip())
    except Exception as exc:  # noqa: BLE001
        log.warning("join_notify: PI lookup failed: %s", exc)
        return False
    if not uid:
        log.info("join_notify: PI %s not in workspace yet; no onboarding DM", email)
        return False
    msgs = messages or pi_onboarding_messages(
        group, centre_name=centre_name, channel_name=channel_name)
    sent = False
    for m in msgs:
        try:
            if poster(uid, m):
                sent = True
        except Exception as exc:  # noqa: BLE001
            log.warning("join_notify.notify_pi_onboarded step failed: %s", exc)
    return sent


def notify_group_provisioned(
    req,
    *,
    env=None,
    poster: PosterFn | None = None,
    channel_resolver: ChannelResolverFn | None = None,
) -> bool:
    """Post to the admin/mayor channel that a lab/core was provisioned, and
    remind the registrar to email the new PI the workspace invite link.

    This is the mayor-facing counterpart to ``notify_decision`` (which DMs the
    requester — and no-ops when the brand-new PI isn't in the workspace yet).
    Best-effort + token-gated; never raises. Returns True iff a message posted.
    """
    if not _has_token():
        return False
    if getattr(req, "kind", "") not in ("lab", "core"):
        return False
    poster = poster or _default_poster
    channel_resolver = channel_resolver or _default_channel_resolver
    invite = ""
    try:
        from . import centre_init as _ci
        prof = _ci.read_centre(env=env)
        invite = (getattr(prof, "slack_invite_url", "") or "").strip() if prof else ""
    except Exception as exc:  # noqa: BLE001
        log.info("join_notify: centre read failed (%s); no invite link in reminder", exc)
    try:
        channel = channel_resolver("admin", env=env)
    except Exception as exc:  # noqa: BLE001 — admin channel not configured
        log.info("join_notify: admin channel not resolved (%s); skipping", exc)
        return False
    if not channel:
        return False
    try:
        return bool(poster(channel, _fmt_provisioned(req, invite_url=invite)))
    except Exception as exc:  # noqa: BLE001
        log.warning("join_notify.notify_group_provisioned failed: %s", exc)
        return False


__all__ = [
    "notify_new_request", "notify_decision", "notify_group_provisioned",
    "notify_pi_onboarded", "pi_onboarding_messages", "group_onboarding_steps",
]
