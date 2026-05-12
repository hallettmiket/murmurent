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


def create_project_channel(project_slug: str) -> str | None:
    """Create a Slack channel for a project and return its ID.

    Channel name is ``proj-{project_slug}`` (hyphens, lowercase).  If the
    channel already exists the existing ID is retrieved from CHARTER.md.
    Returns None when no token is configured or the API call fails.
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
        if not data.get("ok"):
            err = data.get("error", "")
            if err == "name_taken":
                log.info("Slack channel %s already exists", channel_name)
                existing = _project_channel_id(project_slug)
                return existing if existing != _CHAN_CLAUDE_CODE else None
            log.warning("Slack create channel %s failed: %s", channel_name, err)
            return None
        channel_id: str = data["channel"]["id"]
        log.info("Created Slack channel %s → %s", channel_name, channel_id)
        return channel_id
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
