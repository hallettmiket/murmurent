"""
Purpose: Post dashboard event notifications to Slack.
         Uses the Slack Web API (chat.postMessage) with a bot token
         stored in $WIGAMIG_SLACK_TOKEN or ~/.config/wigamig/slack-token.
         All functions are no-ops when no token is configured, so the
         server starts cleanly without Slack auth.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-11
Input: Event data from dashboard API endpoints.
Output: HTTP POST to Slack; silent no-op when token is absent.
"""

from __future__ import annotations

import logging
import os
import re
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)

_SLACK_API_URL = "https://slack.com/api/chat.postMessage"
_SLACK_API_CREATE = "https://slack.com/api/conversations.create"
_SLACK_API_LIST   = "https://slack.com/api/conversations.list"
_SLACK_API_INVITE = "https://slack.com/api/conversations.invite"
_SLACK_API_MEMBERS = "https://slack.com/api/conversations.members"
_SLACK_API_LOOKUP_BY_EMAIL = "https://slack.com/api/users.lookupByEmail"
_TOKEN_FILE = Path("~/.config/wigamig/slack-token").expanduser()

# Fallback channel IDs. ``_CHAN_DEFAULT`` is where wigamig-generated
# notifications land when a project has no slack_channel_id in its
# CHARTER. Previously pointed at #claude-code (C0ANNQ1U5EZ); moved to
# #claude-test (C0B3D9DS6SE) on 2026-05-12 because #claude-code became
# too noisy for non-developer members of the lab.
_CHAN_DEFAULT = "C0B3D9DS6SE"
_CHAN_CLAUDE_CODE = _CHAN_DEFAULT  # back-compat alias for older callers
_CHAN_LAB_INFRA = "CDWPTRQ86"


@lru_cache(maxsize=1)
def _token() -> str | None:
    """Return the bot token, or None if not configured."""
    env = os.environ.get("WIGAMIG_SLACK_TOKEN", "").strip()
    if env:
        return env
    if _TOKEN_FILE.is_file():
        try:
            tok = _TOKEN_FILE.read_text(encoding="utf-8").strip()
            if tok:
                return tok
        except OSError:
            pass
    return None


def _project_channel_id(project_slug: str) -> str:
    """Return the Slack channel ID stored in the project's CHARTER.md, or the default lab channel."""
    charter_path = Path(f"~/repos/{project_slug}/CHARTER.md").expanduser()
    if charter_path.is_file():
        try:
            text = charter_path.read_text(encoding="utf-8")
            m = re.search(r"^slack_channel_id:\s*(\S+)", text, re.MULTILINE)
            if m:
                return m.group(1)
        except OSError:
            pass
    return _CHAN_CLAUDE_CODE


def _write_charter_channel_id(project_slug: str, channel_id: str) -> None:
    """Persist slack_channel_id into the project's CHARTER.md frontmatter."""
    charter_path = Path(f"~/repos/{project_slug}/CHARTER.md").expanduser()
    if not charter_path.is_file():
        return
    try:
        text = charter_path.read_text(encoding="utf-8")
        if "slack_channel_id:" in text:
            text = re.sub(r"^slack_channel_id:.*", f"slack_channel_id: {channel_id}", text, flags=re.MULTILINE)
        else:
            lines = text.splitlines(keepends=True)
            in_front = False
            for i, line in enumerate(lines):
                if line.strip() == "---":
                    if not in_front:
                        in_front = True
                    else:
                        lines.insert(i, f"slack_channel_id: {channel_id}\n")
                        break
            text = "".join(lines)
        charter_path.write_text(text, encoding="utf-8")
    except OSError as exc:
        log.warning("Could not write slack_channel_id to %s: %s", charter_path, exc)


def _lookup_channel_id_by_name(name: str) -> str | None:
    """Look up an existing Slack channel ID by exact channel name.

    Pages through ``conversations.list`` (public + private). Returns the
    channel ID on first match, or ``None`` if no match or no token. The
    pre-existing CHARTER.md-only lookup couldn't recover from the case
    where a channel had been created out-of-band — this fills that gap.
    """
    tok = _token()
    if not tok:
        return None
    try:
        import httpx

        cursor = ""
        for _ in range(10):  # cap pagination to avoid runaway loops
            params = {"types": "public_channel,private_channel", "limit": 1000}
            if cursor:
                params["cursor"] = cursor
            r = httpx.get(
                _SLACK_API_LIST,
                headers={"Authorization": f"Bearer {tok}"},
                params=params,
                timeout=8,
            )
            data = r.json()
            if not data.get("ok"):
                log.warning("Slack conversations.list failed: %s", data.get("error"))
                return None
            for ch in data.get("channels", []):
                if ch.get("name") == name:
                    return ch.get("id")
            cursor = (data.get("response_metadata") or {}).get("next_cursor") or ""
            if not cursor:
                break
        return None
    except Exception as exc:  # noqa: BLE001
        log.warning("Slack lookup_channel_id_by_name error: %s", exc)
        return None


def create_project_channel(project_slug: str) -> str | None:
    """Create a Slack channel for a project and return its ID.

    Channel name is ``proj-{project_slug}`` (hyphens, lowercase). If the
    channel already exists, the existing ID is recovered in this order:
    (1) ``slack_channel_id`` in the project's CHARTER.md, (2) a live
    lookup against Slack's ``conversations.list``. The found ID is then
    written back to CHARTER.md so subsequent calls are O(1). Returns
    ``None`` when no token is configured or the API call fails.
    """
    tok = _token()
    if not tok:
        return None
    channel_name = f"proj-{project_slug.lower().replace('_', '-')}"[:80]
    try:
        import httpx

        r = httpx.post(
            _SLACK_API_CREATE,
            headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
            json={"name": channel_name, "is_private": False},
            timeout=5,
        )
        data = r.json()
        if data.get("ok"):
            channel_id: str = data["channel"]["id"]
            log.info("Created Slack channel %s → %s", channel_name, channel_id)
            return channel_id

        err = data.get("error", "")
        if err != "name_taken":
            log.warning("Slack create channel %s failed: %s", channel_name, err)
            return None

        # Channel already exists out-of-band. Recover its ID — first from
        # CHARTER, then via Slack's API.
        log.info("Slack channel %s already exists; recovering ID", channel_name)
        existing = _project_channel_id(project_slug)
        if existing and existing != _CHAN_CLAUDE_CODE:
            return existing
        looked_up = _lookup_channel_id_by_name(channel_name)
        if looked_up:
            log.info("Recovered Slack channel %s → %s via list lookup",
                     channel_name, looked_up)
            return looked_up
        log.warning(
            "Slack channel %s exists but the bot can't see it. Likely "
            "needs to be invited to the channel.", channel_name,
        )
        return None
    except Exception as exc:  # noqa: BLE001
        log.warning("Slack create_project_channel error: %s", exc)
        return None


def _post(channel: str, text: str) -> bool:
    """Low-level POST to Slack. Returns True on success, False otherwise.

    Intentionally fire-and-forget: dashboard events should never fail
    because Slack is down or the token is wrong.
    """
    tok = _token()
    if not tok:
        return False
    try:
        import httpx  # already a project dependency

        r = httpx.post(
            _SLACK_API_URL,
            headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
            json={"channel": channel, "text": text},
            timeout=5,
        )
        data = r.json()
        if not data.get("ok"):
            log.warning("Slack post to %s failed: %s", channel, data.get("error"))
            return False
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("Slack notification error: %s", exc)
        return False


# ── Public notification functions ──────────────────────────────────────────

def sea_state_change(
    *,
    project: str,
    sea_id: int,
    actor: str,
    action: str,
    description: str,
    new_state: str,
    channel: str | None = None,
) -> None:
    """Post a SEA lifecycle event to the project's Slack channel (or #claude-test as fallback)."""
    resolved_channel = channel if channel is not None else _project_channel_id(project)
    emoji = {
        "claim": ":hand:",
        "complete": ":white_check_mark:",
        "examine": ":eyes:",
        "conclude": ":trophy:",
        "decline": ":x:",
        "reopen": ":arrows_counterclockwise:",
    }.get(action, ":bell:")
    text = (
        f"{emoji} *SEA #{sea_id}* in `{project}` — *{action}* by @{actor}\n"
        f">{description}\n"
        f"State: `{new_state}`"
    )
    _post(resolved_channel, text)


def oracle_approval(
    *,
    slug: str,
    action: str,
    actor: str,
    title: str,
    channel: str = _CHAN_CLAUDE_CODE,
) -> None:
    """Post an oracle entry approval / rejection to Slack."""
    emoji = ":books:" if action == "approve" else ":wastebasket:"
    text = (
        f"{emoji} *Oracle entry {action}d* by @{actor}\n"
        f">*{title}* (`{slug}`)"
    )
    _post(channel, text)


def project_request(
    *,
    kind: str,
    project: str,
    actor: str,
    channel: str = _CHAN_CLAUDE_CODE,
) -> None:
    """Post a new project or join request to Slack."""
    text = (
        f":memo: *New {kind} request* from @{actor} for project `{project}`\n"
        f">Pending PI review on the dashboard."
    )
    _post(channel, text)


def member_added(
    *,
    handle: str,
    full_name: str,
    role: str,
    channel: str = _CHAN_CLAUDE_CODE,
) -> None:
    """Post a new member addition to Slack."""
    text = f":tada: *{full_name}* (@{handle}) added to the lab as *{role}*."
    _post(channel, text)


# ---------------------------------------------------------------------------
# Channel-member sync (item #11)
# ---------------------------------------------------------------------------


def _channel_member_ids(channel_id: str) -> set[str]:
    """Return the set of user IDs currently in ``channel_id`` (empty on failure).

    Pages through ``conversations.members`` so private channels with
    hundreds of members still resolve correctly. Best-effort: any HTTP
    or auth error returns an empty set rather than raising — the caller
    is doing a diff, and an empty "existing" set just means we try to
    invite everyone (Slack itself dedupes via ``already_in_channel``).
    """
    tok = _token()
    if not tok:
        return set()
    out: set[str] = set()
    try:
        import httpx

        cursor = ""
        for _ in range(20):
            params: dict[str, str | int] = {"channel": channel_id, "limit": 1000}
            if cursor:
                params["cursor"] = cursor
            r = httpx.get(
                _SLACK_API_MEMBERS,
                headers={"Authorization": f"Bearer {tok}"},
                params=params,
                timeout=8,
            )
            data = r.json()
            if not data.get("ok"):
                log.warning("Slack conversations.members(%s) failed: %s",
                            channel_id, data.get("error"))
                return out
            out.update(data.get("members", []) or [])
            cursor = (data.get("response_metadata") or {}).get("next_cursor") or ""
            if not cursor:
                break
    except Exception as exc:  # noqa: BLE001
        log.warning("Slack conversations.members error: %s", exc)
    return out


def _lookup_user_id_by_email(email: str) -> str | None:
    """Return the Slack user_id for ``email`` (None if not in the workspace)."""
    tok = _token()
    if not tok or not email:
        return None
    try:
        import httpx

        r = httpx.get(
            _SLACK_API_LOOKUP_BY_EMAIL,
            headers={"Authorization": f"Bearer {tok}"},
            params={"email": email},
            timeout=8,
        )
        data = r.json()
        if not data.get("ok"):
            return None
        return (data.get("user") or {}).get("id")
    except Exception as exc:  # noqa: BLE001
        log.warning("Slack users.lookupByEmail error: %s", exc)
        return None


def sync_project_channel_members(
    project_slug: str,
    member_handles: list[str],
    *,
    member_email_map: dict[str, str] | None = None,
) -> dict:
    """Add every handle in ``member_handles`` to the project's Slack channel.

    ``member_email_map`` maps a handle to a verified email; the helper
    resolves each handle's email to a Slack user_id and invites them.
    Handles without an email mapping or without a Slack workspace
    account are reported in the result's ``unresolved`` list.

    Returns a structured summary the dashboard can render:
      ``{"channel_id", "invited": [...], "already_in": [...],
        "unresolved": [{"handle", "reason"}, ...], "error": str | None}``

    Idempotent: members already in the channel are a no-op.
    """
    tok = _token()
    if not tok:
        return {"channel_id": None, "invited": [], "already_in": [],
                "unresolved": [{"handle": h, "reason": "no slack token configured"}
                               for h in member_handles],
                "error": "no slack token configured"}

    channel_id = _project_channel_id(project_slug)
    if channel_id == _CHAN_CLAUDE_CODE:
        # No channel ID in CHARTER → try to look it up by name (same recovery
        # path as create_project_channel's name_taken branch).
        channel_name = f"proj-{project_slug.lower().replace('_', '-')}"[:80]
        looked_up = _lookup_channel_id_by_name(channel_name)
        if looked_up:
            channel_id = looked_up
            _write_charter_channel_id(project_slug, channel_id)
        else:
            return {"channel_id": None, "invited": [], "already_in": [],
                    "unresolved": [{"handle": h, "reason": "project has no slack channel yet"}
                                   for h in member_handles],
                    "error": f"no slack channel for project {project_slug!r}"}

    existing = _channel_member_ids(channel_id)
    email_map = member_email_map or {}
    invited: list[str] = []
    already_in: list[str] = []
    unresolved: list[dict] = []
    user_ids_to_invite: list[str] = []
    handle_for_uid: dict[str, str] = {}

    for handle in member_handles:
        norm = handle.lstrip("@").lower()
        email = email_map.get(norm) or email_map.get(handle)
        if not email:
            unresolved.append({"handle": handle, "reason": "no email on record"})
            continue
        uid = _lookup_user_id_by_email(email)
        if not uid:
            unresolved.append({"handle": handle,
                               "reason": f"no slack account for {email}"})
            continue
        if uid in existing:
            already_in.append(handle)
            continue
        user_ids_to_invite.append(uid)
        handle_for_uid[uid] = handle

    if user_ids_to_invite:
        try:
            import httpx

            r = httpx.post(
                _SLACK_API_INVITE,
                headers={"Authorization": f"Bearer {tok}",
                         "Content-Type": "application/json"},
                json={"channel": channel_id, "users": ",".join(user_ids_to_invite)},
                timeout=10,
            )
            data = r.json()
            if data.get("ok"):
                invited.extend(handle_for_uid[u] for u in user_ids_to_invite)
            else:
                err = data.get("error", "")
                # ``already_in_channel`` means some of the batch were
                # already members; treat as success for those.
                if err == "already_in_channel":
                    already_in.extend(handle_for_uid[u] for u in user_ids_to_invite)
                else:
                    return {"channel_id": channel_id, "invited": [],
                            "already_in": already_in, "unresolved": unresolved,
                            "error": f"slack invite failed: {err}"}
        except Exception as exc:  # noqa: BLE001
            return {"channel_id": channel_id, "invited": [],
                    "already_in": already_in, "unresolved": unresolved,
                    "error": f"slack invite error: {exc}"}

    return {"channel_id": channel_id, "invited": invited,
            "already_in": already_in, "unresolved": unresolved, "error": None}
