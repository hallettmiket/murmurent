"""
Purpose: Post dashboard event notifications to Slack.
         Uses the Slack Web API (chat.postMessage) with a bot token
         stored in $MURMURENT_SLACK_TOKEN or ~/.config/murmurent/slack-token.
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
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)

_SLACK_API_URL = "https://slack.com/api/chat.postMessage"
_SLACK_API_CREATE = "https://slack.com/api/conversations.create"
_SLACK_API_LIST   = "https://slack.com/api/conversations.list"
_SLACK_API_INVITE = "https://slack.com/api/conversations.invite"
_SLACK_API_MEMBERS = "https://slack.com/api/conversations.members"
_SLACK_API_LOOKUP_BY_EMAIL = "https://slack.com/api/users.lookupByEmail"
_TOKEN_FILE = Path("~/.config/murmurent/slack-token").expanduser()

# Fallback channel IDs. ``_CHAN_DEFAULT`` is the LAST-RESORT channel for
# wigamig-generated notifications when no specific project/group channel
# applies. In a live centre it is superseded at send time by the private
# mayor↔CC channel (see ``_default_channel`` / ``_route`` below): #claude-test
# is only used during development or before ``centre-slack-setup`` has run.
# History: #claude-code (C0ANNQ1U5EZ) → #claude-test (C0B3D9DS6SE) on 2026-05-12.
_CHAN_DEFAULT = "C0B3D9DS6SE"
_CHAN_CLAUDE_CODE = _CHAN_DEFAULT  # back-compat alias for older callers
_CHAN_LAB_INFRA = "CDWPTRQ86"


def _default_channel() -> str:
    """Where murmurent system notifications land when no specific (project / lab /
    group) channel applies.

    Once a centre is initialised **and** has run ``centre-slack-setup`` — i.e.
    it has a private mayor↔CC channel (``mayor_channel_id`` = ``#murmurent-ops``,
    visible only to the mayor + the bot) — system messages default THERE instead
    of the historical shared dev channel. The dev channel (``_CHAN_DEFAULT``) is
    used only as a last resort: development, or a centre that hasn't wired its
    mayor channel yet.
    """
    try:
        from ..core import centre_init as _ci
        prof = _ci.read_centre()
        mayor_chan = (getattr(prof, "mayor_channel_id", "") or "").strip() if prof else ""
        if mayor_chan:
            return mayor_chan
    except Exception:  # noqa: BLE001 — routing must never break a notification
        pass
    return _CHAN_DEFAULT


def _route(channel: str) -> str:
    """Redirect the dev fallback channel to the centre's private mayor channel
    once one exists. Explicit per-group channel ids pass through unchanged."""
    if not channel or channel == _CHAN_DEFAULT:
        return _default_channel()
    return channel


@lru_cache(maxsize=1)
def _token() -> str | None:
    """Return the bot token, or None if not configured.

    Resolution: ``$MURMURENT_SLACK_TOKEN`` → ``~/.config/murmurent/slack-token``
    → the legacy ``$SLACK_BOT_TOKEN`` (unified with centre_provision so a
    single token drives both channel creation and posting/invites)."""
    env = os.environ.get("MURMURENT_SLACK_TOKEN", "").strip()
    if env:
        return env
    if _TOKEN_FILE.is_file():
        try:
            tok = _TOKEN_FILE.read_text(encoding="utf-8").strip()
            if tok:
                return tok
        except OSError:
            pass
    return os.environ.get("SLACK_BOT_TOKEN", "").strip() or None


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


def _write_charter_channel_id(
    project_slug: str,
    channel_id: str,
    *,
    channel_name: str | None = None,
) -> None:
    """Persist slack_channel_id (and optionally slack_channel_name) into
    the project's CHARTER.md frontmatter.

    Storing the name alongside the id lets future channel-lookup
    operations (e.g. recovery after a name_taken error) target the
    actual name in use rather than the ``proj-<slug>`` default —
    necessary when the lab opted for a non-conventional name at
    create time.
    """
    charter_path = Path(f"~/repos/{project_slug}/CHARTER.md").expanduser()
    if not charter_path.is_file():
        return
    try:
        text = charter_path.read_text(encoding="utf-8")
        text = _upsert_frontmatter_field(text, "slack_channel_id", channel_id)
        if channel_name is not None:
            text = _upsert_frontmatter_field(text, "slack_channel_name", channel_name)
        charter_path.write_text(text, encoding="utf-8")
    except OSError as exc:
        log.warning("Could not write slack_channel_id to %s: %s", charter_path, exc)


def _upsert_frontmatter_field(text: str, field: str, value: str) -> str:
    """Set ``field: value`` in a YAML frontmatter block. Idempotent.

    If the field already exists, replaces its value. Otherwise inserts
    a new line just before the closing ``---``. Pure text rewrite —
    avoids the full-yaml round-trip so a malformed frontmatter doesn't
    eat the user's other fields.
    """
    pattern = rf"^{re.escape(field)}:.*"
    if re.search(pattern, text, re.MULTILINE):
        return re.sub(pattern, f"{field}: {value}", text, flags=re.MULTILINE, count=1)
    lines = text.splitlines(keepends=True)
    in_front = False
    for i, line in enumerate(lines):
        if line.strip() == "---":
            if not in_front:
                in_front = True
            else:
                lines.insert(i, f"{field}: {value}\n")
                break
    return "".join(lines)


def _read_charter_channel_name(project_slug: str) -> str | None:
    """Read ``slack_channel_name`` from the project's CHARTER.md, or
    ``None`` when missing / unreadable. Used so a re-run of channel
    creation/recovery targets the same name that was provisioned the
    first time."""
    charter_path = Path(f"~/repos/{project_slug}/CHARTER.md").expanduser()
    if not charter_path.is_file():
        return None
    try:
        text = charter_path.read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"^slack_channel_name:\s*(\S+)", text, re.MULTILINE)
    return m.group(1) if m else None


class SlackScopeError(RuntimeError):
    """Slack denied the call with ``missing_scope`` — the bot needs more permissions.

    Distinct from generic errors so the dashboard can offer a manual
    escape hatch ("paste the channel ID") rather than just saying "check
    server logs."
    """

    def __init__(self, needed: str, message: str) -> None:
        super().__init__(message)
        self.needed = needed


def _lookup_channel_id_by_name(name: str) -> str | None:
    """Look up an existing Slack channel ID by exact channel name.

    Pages through ``conversations.list`` (public + private). Returns the
    channel ID on first match, or ``None`` if no match or no token.
    Raises :class:`SlackScopeError` when the bot lacks the scopes
    required to enumerate channels — that case can't be solved here
    (the user needs to either add the scope in Slack admin OR paste the
    channel ID manually).
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
                err = data.get("error", "")
                log.warning("Slack conversations.list failed: %s", err)
                if err == "missing_scope":
                    needed = data.get("needed") or "channels:read,groups:read"
                    raise SlackScopeError(
                        needed=str(needed),
                        message=(
                            "Slack bot lacks the scope to enumerate channels "
                            f"(needed: {needed}). Either add the scope to the "
                            "bot in Slack admin and reinstall, or paste the "
                            "channel ID manually via the 'Link existing "
                            "channel' button."
                        ),
                    )
                return None
            for ch in data.get("channels", []):
                if ch.get("name") == name:
                    return ch.get("id")
            cursor = (data.get("response_metadata") or {}).get("next_cursor") or ""
            if not cursor:
                break
        return None
    except SlackScopeError:
        raise
    except Exception as exc:  # noqa: BLE001
        log.warning("Slack lookup_channel_id_by_name error: %s", exc)
        return None


def default_channel_name(project_slug: str) -> str:
    """Return the wigamig-conventional channel name for a project slug.

    ``proj-{slug}`` with underscores → hyphens, lowercased, capped at
    80 chars (Slack's hard limit). Exposed as a module-level helper so
    UIs can render the same default in their placeholders.
    """
    return f"proj-{project_slug.lower().replace('_', '-')}"[:80]


_CHANNEL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,79}$")


def normalize_channel_name(raw: str) -> str | None:
    """Normalize a user-typed channel name and reject anything Slack
    would refuse.

    Slack channels are lowercase, max 80 chars, ``[a-z0-9_-]`` (must
    start with a letter or digit, no leading ``-`` / ``_``). Returns
    the cleaned name or ``None`` when it doesn't satisfy the rules so
    the caller can return a 422 rather than send a doomed API call.
    """
    if not raw:
        return None
    cleaned = raw.strip().lstrip("#").lower().replace(" ", "-")
    cleaned = cleaned[:80]
    return cleaned if _CHANNEL_NAME_RE.match(cleaned) else None


def create_project_channel(
    project_slug: str,
    channel_name: str | None = None,
) -> str | None:
    """Create a Slack channel for a project and return its ID.

    Channel name defaults to ``proj-{project_slug}`` (see
    :func:`default_channel_name`). Pass ``channel_name`` to override —
    useful when the lab already has a channel that doesn't follow the
    convention, or wants a different name at create time. The chosen
    name is persisted alongside the resolved ID in CHARTER.md so
    future recovery calls target the right name.

    If the channel already exists, the existing ID is recovered in
    this order: (1) ``slack_channel_id`` in the project's CHARTER.md,
    (2) a live lookup against Slack's ``conversations.list``. Returns
    ``None`` when no token is configured or the API call fails.
    """
    tok = _token()
    if not tok:
        return None
    # Resolution order for the channel name we actually try:
    #   1. explicit caller-supplied override (validated)
    #   2. ``slack_channel_name`` already saved in CHARTER.md
    #   3. murmurent default ``proj-<slug>``
    if channel_name is not None:
        validated = normalize_channel_name(channel_name)
        if validated is None:
            log.warning("Slack create_project_channel: invalid name %r", channel_name)
            return None
        channel_name = validated
    else:
        stored = _read_charter_channel_name(project_slug)
        channel_name = stored if stored else default_channel_name(project_slug)
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
            _write_charter_channel_id(project_slug, channel_id, channel_name=channel_name)
            return channel_id

        err = data.get("error", "")
        if err != "name_taken":
            log.warning("Slack create channel %s failed: %s", channel_name, err)
            return None

        # Channel already exists out-of-band. Recover its ID — first from
        # CHARTER, then via Slack's API. Persist the resolved
        # (id, name) tuple back to CHARTER so the next recovery is O(1).
        log.info("Slack channel %s already exists; recovering ID", channel_name)
        existing = _project_channel_id(project_slug)
        if existing and existing != _CHAN_CLAUDE_CODE:
            _write_charter_channel_id(project_slug, existing, channel_name=channel_name)
            return existing
        looked_up = _lookup_channel_id_by_name(channel_name)
        if looked_up:
            log.info("Recovered Slack channel %s → %s via list lookup",
                     channel_name, looked_up)
            _write_charter_channel_id(project_slug, looked_up, channel_name=channel_name)
            return looked_up
        log.warning(
            "Slack channel %s exists but the bot can't see it. Likely "
            "needs to be invited to the channel.", channel_name,
        )
        return None
    except SlackScopeError:
        # Let the endpoint surface this to the user with an actionable
        # error rather than the generic "check server logs."
        raise
    except Exception as exc:  # noqa: BLE001
        log.warning("Slack create_project_channel error: %s", exc)
        return None


def _open_dm(user_id: str, tok: str | None = None) -> str | None:
    """Open (or reuse) the bot↔user DM and return its ``D…`` channel id.

    Posting straight to a ``U…`` user id lands in the bot's *App messages*
    tab, not the recipient's Direct Messages — so any DM path must resolve the
    real IM channel first via ``conversations.open`` (needs the ``im:write``
    scope). Returns None on failure so callers can fall back."""
    tok = tok or _token()
    if not (tok and user_id):
        return None
    try:
        import httpx
        r = httpx.post(
            "https://slack.com/api/conversations.open",
            headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
            json={"users": user_id}, timeout=5,
        ).json()
        if r.get("ok"):
            return (r.get("channel") or {}).get("id")
        log.warning("conversations.open for %s failed: %s (add the im:write scope?)",
                    user_id, r.get("error"))
    except Exception as exc:  # noqa: BLE001
        log.warning("conversations.open error: %s", exc)
    return None


def _post(channel: str, text: str, *, token: str | None = None) -> bool:
    """Low-level POST to Slack. Returns True on success, False otherwise.

    Intentionally fire-and-forget: dashboard events should never fail
    because Slack is down or the token is wrong.

    ``token`` overrides the centre bot token — used by group-scoped senders
    (e.g. ``group_reconcile.send_group_dm``) whose recipient only exists in
    the group's OWN Slack workspace, not the centre's.
    """
    tok = token if token is not None else _token()
    if not tok:
        return False
    channel = _route(channel)
    # A bare user id → open the real DM channel so the message lands in the
    # recipient's Direct Messages, not the bot's App-messages tab. Fall back to
    # the user id if the DM can't be opened (e.g. no im:write scope).
    if channel and channel[:1] == "U":
        channel = _open_dm(channel, tok) or channel
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


def _upload_file(channel: str, *, filename: str, content: str,
                 title: str = "", initial_comment: str = "",
                 token: str | None = None) -> bool:
    """Upload ``content`` to ``channel`` as a real, downloadable file attachment.

    Uses Slack's current three-step external-upload flow
    (``files.getUploadURLExternal`` → POST the bytes to the returned URL →
    ``files.completeUploadExternal``); the legacy ``files.upload`` is deprecated.
    Requires the bot's ``files:write`` scope. ``initial_comment`` rides along as
    the message text next to the file, so callers can attach a bundle *and* the
    import instructions in one DM.

    Like :func:`_post`, this is fire-and-forget: any failure (missing scope,
    Slack outage) returns False so card issuance can fall back to manual
    delivery — it never raises.
    """
    tok = token if token is not None else _token()
    if not tok:
        return False
    channel = _route(channel)
    # A bare user id → open the real DM channel so the file lands in the
    # recipient's Direct Messages, not the bot's App-messages tab.
    if channel and channel[:1] == "U":
        channel = _open_dm(channel, tok) or channel
    data = content.encode("utf-8")
    try:
        import httpx  # already a project dependency

        # 1. Reserve a one-time upload URL + file id.
        reserved = httpx.get(
            "https://slack.com/api/files.getUploadURLExternal",
            headers={"Authorization": f"Bearer {tok}"},
            params={"filename": filename, "length": str(len(data))},
            timeout=5,
        ).json()
        if not reserved.get("ok"):
            log.warning("files.getUploadURLExternal failed: %s (add the files:write scope?)",
                        reserved.get("error"))
            return False
        upload_url = reserved.get("upload_url")
        file_id = reserved.get("file_id")
        if not (upload_url and file_id):
            return False

        # 2. POST the raw bytes to the returned upload URL (no bot token here).
        put = httpx.post(upload_url, content=data, timeout=10)
        if put.status_code != 200:
            log.warning("Slack file upload POST returned HTTP %s", put.status_code)
            return False

        # 3. Complete the upload and share it into the channel/DM.
        payload: dict = {
            "files": [{"id": file_id, "title": title or filename}],
            "channel_id": channel,
        }
        if initial_comment:
            payload["initial_comment"] = initial_comment
        done = httpx.post(
            "https://slack.com/api/files.completeUploadExternal",
            headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
            json=payload,
            timeout=5,
        ).json()
        if not done.get("ok"):
            log.warning("files.completeUploadExternal to %s failed: %s",
                        channel, done.get("error"))
            return False
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("Slack file upload error: %s", exc)
        return False


@dataclass
class SlackPostResult:
    """Structured outcome of a Slack post. ``ok`` False carries the Slack
    error code + a human hint so user-initiated actions can report it."""
    ok: bool
    link: str = ""
    error: str = ""
    detail: str = ""


def _post_error_hint(error: str, channel: str) -> str:
    """Map a Slack error code to an actionable, mayor-readable explanation."""
    hints = {
        "no_token": "no Slack token — set $MURMURENT_SLACK_TOKEN or put it in "
                    "~/.config/murmurent/slack-token.",
        "channel_not_found": f"channel {channel} was not found. The bot token is "
                    "almost certainly for a DIFFERENT Slack workspace than this "
                    "channel — use the token for the channel's own workspace.",
        "not_in_channel": f"the bot is not in {channel}. In Slack, `/invite` the "
                    "bot into that channel, then retry.",
        "is_archived": f"channel {channel} is archived — unarchive it in Slack.",
        "invalid_auth": "the bot token is wrong or has been revoked.",
        "token_revoked": "the bot token was revoked — reinstall the app and re-copy it.",
        "account_inactive": "the bot / token is deactivated.",
        "missing_scope": "the bot lacks the `chat:write` scope — add it and "
                    "Reinstall the app to the workspace.",
        "transport": "could not reach Slack (network error).",
    }
    return hints.get(error, f"Slack error: {error}")


def post_message_result(channel: str, text: str) -> SlackPostResult:
    """Post to Slack and return a STRUCTURED result (ok / error / hint / link).

    Unlike the fire-and-forget ``_post`` / ``post_and_link`` (which swallow
    failures so a flaky Slack never breaks a dashboard side-effect), this
    surfaces the failure — so user-initiated actions like
    ``murmurent broadcast send --apply`` can report exactly what went wrong and
    exit non-zero instead of falsely claiming success.
    """
    tok = _token()
    if not tok:
        return SlackPostResult(False, error="no_token",
                               detail=_post_error_hint("no_token", channel))
    channel = _route(channel)
    try:
        import httpx
        r = httpx.post(
            _SLACK_API_URL,
            headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
            json={"channel": channel, "text": text},
            timeout=5,
        )
        data = r.json()
        if not data.get("ok"):
            err = data.get("error") or "unknown"
            log.warning("Slack post to %s failed: %s", channel, err)
            return SlackPostResult(False, error=err, detail=_post_error_hint(err, channel))
        link = ""
        ts = data.get("ts")
        if ts:
            try:
                pl = httpx.get(
                    "https://slack.com/api/chat.getPermalink",
                    headers={"Authorization": f"Bearer {tok}"},
                    params={"channel": channel, "message_ts": ts},
                    timeout=5,
                ).json()
                if pl.get("ok"):
                    link = pl.get("permalink") or ""
            except Exception:  # noqa: BLE001
                pass
        return SlackPostResult(True, link=link)
    except Exception as exc:  # noqa: BLE001
        log.warning("Slack notification error: %s", exc)
        return SlackPostResult(False, error="transport",
                               detail=_post_error_hint("transport", channel))


def post_and_link(channel: str, text: str) -> str:
    """Back-compat wrapper: post + return the permalink ("" on failure or when
    Slack returns no permalink). Callers that must know *why* a post failed
    should use :func:`post_message_result`."""
    return post_message_result(channel, text).link


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
# Core member events (cores Phase 1e)
#
# Mirror the lab-side member_added function so the centre's Slack
# channel sees core staff churn the same way it sees lab staff churn.
# Posts to #claude-test (the lab's infrastructure channel) since cores
# don't yet have their own Slack channels per the cores rollout plan;
# Phase 6 may add per-core channels.
# ---------------------------------------------------------------------------


def core_member_added(
    *, core: str, handle: str, full_name: str, role: str,
    channel: str = _CHAN_CLAUDE_CODE,
) -> None:
    """Post a core-member-added event to Slack."""
    text = (
        f":busts_in_silhouette: *{full_name}* (@{handle}) "
        f"added to core *{core}* as *{role}*."
    )
    _post(channel, text)


def core_member_removed(
    *, core: str, handle: str,
    channel: str = _CHAN_CLAUDE_CODE,
) -> None:
    """Post a core-member-deactivated event to Slack. (Soft-remove —
    the file is preserved; the frontmatter status flips to inactive.)"""
    text = f":wave: @{handle} deactivated from core *{core}* (file preserved)."
    _post(channel, text)


def core_leader_rotated(
    *, core: str, old_handle: str, new_handle: str,
    channel: str = _CHAN_CLAUDE_CODE,
) -> None:
    """Post a core-leader-rotation event to Slack. Old leader becomes
    a staff member; new leader's role becomes core_leader."""
    text = (
        f":crown: Core *{core}*: leader rotated "
        f"@{old_handle} → @{new_handle}. The displaced handle is now "
        "a staff member of the core."
    )
    _post(channel, text)


# ---------------------------------------------------------------------------
# Core service catalog events (cores Phase 2c)
# ---------------------------------------------------------------------------


def core_service_added(
    *, core: str, slug: str, name: str, actor: str,
    channel: str = _CHAN_CLAUDE_CODE,
) -> None:
    """Post a new service catalog entry event."""
    text = (
        f":sparkles: Core *{core}*: service `{slug}` added "
        f"(*{name}*) by @{actor}."
    )
    _post(channel, text)


def core_service_updated(
    *, core: str, slug: str, fields: list[str], actor: str,
    channel: str = _CHAN_CLAUDE_CODE,
) -> None:
    """Post a service-edit event with the list of fields changed."""
    field_str = ", ".join(sorted(fields)) or "(no-op)"
    text = (
        f":pencil2: Core *{core}*: service `{slug}` updated "
        f"by @{actor} — fields: {field_str}."
    )
    _post(channel, text)


def core_service_archived(
    *, core: str, slug: str, actor: str,
    channel: str = _CHAN_CLAUDE_CODE,
) -> None:
    """Post a service-archival event."""
    text = (
        f":package: Core *{core}*: service `{slug}` archived (retired) "
        f"by @{actor}. File preserved."
    )
    _post(channel, text)


def core_request_booked(
    *, core: str, slug: str, request_id: str,
    requester: str, actor: str,
    start: str, end: str, total: float,
    channel: str = _CHAN_CLAUDE_CODE,
) -> None:
    """Post a booking event for a core service."""
    by = "" if requester.lstrip("@").lower() == actor.lower() else f" (booked by @{actor})"
    fee_str = f" — ${total:.2f}" if total else ""
    text = (
        f":calendar: Core *{core}*: {requester} booked `{slug}` "
        f"{start} → {end}{fee_str}. _id: {request_id}_{by}"
    )
    _post(channel, text)


def core_request_advanced(
    *, core: str, request_id: str,
    from_state: str, to_state: str,
    requester: str, actor: str,
    channel: str = _CHAN_CLAUDE_CODE,
) -> None:
    """Post a state-advancement event for a core service request."""
    text = (
        f":arrow_forward: Core *{core}*: request `{request_id}` "
        f"({requester}) {from_state} → *{to_state}* by @{actor}."
    )
    _post(channel, text)


def core_request_cancelled(
    *, core: str, request_id: str,
    requester: str, actor: str, reason: str = "",
    channel: str = _CHAN_CLAUDE_CODE,
) -> None:
    """Post a cancellation event."""
    by = (
        "" if requester.lstrip("@").lower() == actor.lower()
        else f" by @{actor}"
    )
    reason_str = f" — _{reason}_" if reason else ""
    text = (
        f":x: Core *{core}*: request `{request_id}` ({requester}) "
        f"cancelled{by}{reason_str}."
    )
    _post(channel, text)


def core_request_charge_confirmed(
    *, core: str, request_id: str, requester: str, actor: str,
    booked_total: float, actual_total: float, note: str = "",
    channel: str = _CHAN_CLAUDE_CODE,
) -> None:
    """Phase 4a: leader confirmed the final billable charge."""
    delta = actual_total - booked_total
    if abs(delta) < 0.005:
        delta_str = "= booked"
    elif delta > 0:
        delta_str = f"+${delta:.2f} vs booked"
    else:
        delta_str = f"-${abs(delta):.2f} vs booked"
    note_str = f" — _{note}_" if note else ""
    text = (
        f":moneybag: Core *{core}*: request `{request_id}` ({requester}) "
        f"charge confirmed by @{actor}: *${actual_total:.2f}* ({delta_str}){note_str}."
    )
    _post(channel, text)


def core_training_requested(
    *, core: str, training_slug: str, training_name: str,
    requester: str, trainers: list[str],
    location: str = "", duration_min: int = 0,
    note: str = "",
    channel: str = _CHAN_CLAUDE_CODE,
) -> None:
    """Member is asking a trainer to schedule a training session."""
    trainer_str = " ".join(trainers) if trainers else "(no trainer listed)"
    bits = [f":mortar_board: *{core}* training request — {requester} "
            f"wants {trainer_str} to train them on `{training_slug}` "
            f"(*{training_name}*)"]
    meta = []
    if duration_min:
        meta.append(f"{duration_min} min")
    if location:
        meta.append(location)
    if meta:
        bits.append(f" ({', '.join(meta)})")
    bits.append(".")
    if note:
        bits.append(f"\n> {note}")
    _post(channel, "".join(bits))


def core_request_reminder(
    *, core: str, request_id: str, requester: str,
    service: str, start: str, window: str,
    minutes_until: int,
    channel: str = _CHAN_CLAUDE_CODE,
) -> None:
    """Reminder ping for an upcoming booking. ``window`` is '24h' or '1h'."""
    emoji = ":alarm_clock:" if window == "1h" else ":bell:"
    when = f"in ~{minutes_until} min" if window == "1h" else f"tomorrow ({start})"
    text = (
        f"{emoji} Core *{core}* reminder ({window}): {requester} has "
        f"`{service}` booked {when}. _id: {request_id}_"
    )
    _post(channel, text)


def core_request_rescheduled(
    *, core: str, request_id: str,
    requester: str, actor: str,
    old_start: str, new_start: str,
    channel: str = _CHAN_CLAUDE_CODE,
) -> None:
    """Post a reschedule event."""
    by = (
        "" if requester.lstrip("@").lower() == actor.lower()
        else f" by @{actor}"
    )
    text = (
        f":calendar: Core *{core}*: request `{request_id}` ({requester}) "
        f"rescheduled {old_start} → *{new_start}*{by}."
    )
    _post(channel, text)


# ---------------------------------------------------------------------------
# Channel-member sync (item #11)
# ---------------------------------------------------------------------------


def _channel_member_ids(channel_id: str, *, token: str | None = None) -> set[str]:
    """Return the set of user IDs currently in ``channel_id`` (empty on failure).

    Pages through ``conversations.members`` so private channels with
    hundreds of members still resolve correctly. Best-effort: any HTTP
    or auth error returns an empty set rather than raising — the caller
    is doing a diff, and an empty "existing" set just means we try to
    invite everyone (Slack itself dedupes via ``already_in_channel``).
    ``token`` overrides the centre bot token (group/shared-workspace callers).
    """
    tok = token or _token()
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


def _lookup_user_id_by_email(email: str, *, token: str | None = None) -> str | None:
    """Return the Slack user_id for ``email`` (None if not in the workspace).
    ``token`` overrides the centre bot token (group/shared-workspace callers)."""
    tok = token or _token()
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

    return invite_members_to_channel(
        channel_id, member_handles, member_email_map=member_email_map)


def invite_members_to_channel(
    channel_id: str,
    member_handles: list[str],
    *,
    member_email_map: dict[str, str] | None = None,
    token: str | None = None,
) -> dict:
    """Invite ``member_handles`` to an existing channel by id.

    Resolves each handle→email→Slack user_id and batch-invites those not
    already present. Same structured result + idempotency as
    ``sync_project_channel_members`` (which now delegates here); reusable for
    lab/core channels which have no CHARTER-derived slug. Best-effort.
    ``token`` overrides the centre bot token (group/shared-workspace callers)."""
    tok = token or _token()
    if not tok:
        return {"channel_id": channel_id, "invited": [], "already_in": [],
                "unresolved": [{"handle": h, "reason": "no slack token configured"}
                               for h in member_handles],
                "error": "no slack token configured"}

    existing = _channel_member_ids(channel_id, token=tok)
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
        uid = _lookup_user_id_by_email(email, token=tok)
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
