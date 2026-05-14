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
