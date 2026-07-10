"""
Purpose: Mirror one day of one Slack channel into a markdown file at
         ``<lab-mgmt>/slack/<channel>/<YYYY-MM-DD>.md``. Phase 11 of
         the slack-integration design.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-08
Input: Slack web API (via :mod:`slack_sdk`); ``$MURMURENT_SLACK_TOKEN``
       or ``~/.config/wigamig/slack-token`` (mode 0600) for the token.
Output: One markdown file per (channel, date), with frontmatter and
        threaded message bodies. Forward-compatible with the
        distillation pipeline (:mod:`murmurent.core.slack_distill`).

Channel monitoring is opt-in: a channel is only mirrored when its
**topic** contains the exact marker ``[oracle:on]``. Members can
flip it off by editing the channel topic; nothing here parses
private channels the bot wasn't invited to.

Token resolution order (first match wins):
  1. ``$MURMURENT_SLACK_TOKEN``
  2. ``~/.config/wigamig/slack-token`` (single line, mode 0600)
  3. raise — refuse to silently no-op
"""

from __future__ import annotations

import datetime as _dt
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol

from .frontmatter import dump_document
from .repo import lab_mgmt_repo_root

SLACK_SUBDIR = "slack"
TOKEN_FILE = Path("~/.config/wigamig/slack-token").expanduser()
ORACLE_MARKER = "[oracle:on]"


class SlackMirrorError(Exception):
    """Slack adapter failure that we want to surface, not swallow."""


# ---------------------------------------------------------------------------
# Token resolution
# ---------------------------------------------------------------------------


def resolve_token() -> str:
    """Resolve the bot OAuth token. Raises if not found."""
    env = os.environ.get("MURMURENT_SLACK_TOKEN", "").strip()
    if env:
        return env
    if TOKEN_FILE.is_file():
        try:
            return TOKEN_FILE.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise SlackMirrorError(f"could not read {TOKEN_FILE}: {exc}") from exc
    raise SlackMirrorError(
        f"No Slack token. Set $MURMURENT_SLACK_TOKEN or write to {TOKEN_FILE}."
    )


# ---------------------------------------------------------------------------
# Slack client (mockable interface)
# ---------------------------------------------------------------------------


class SlackClientLike(Protocol):
    """Subset of slack_sdk.WebClient we use; lets tests mock cheaply."""

    def conversations_list(self, *, types: str = ...) -> dict: ...
    def conversations_info(self, *, channel: str) -> dict: ...
    def conversations_history(
        self, *, channel: str, oldest: str, latest: str, limit: int = ...
    ) -> dict: ...
    def conversations_replies(
        self, *, channel: str, ts: str, oldest: str = ..., latest: str = ...
    ) -> dict: ...
    def users_info(self, *, user: str) -> dict: ...


def make_client(token: str | None = None) -> SlackClientLike:
    """Construct a Slack ``WebClient``. ``token`` defaults to ``resolve_token()``."""
    from slack_sdk import WebClient  # type: ignore[import-not-found]

    return WebClient(token=token or resolve_token())


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Message:
    """One Slack message normalised for mirror rendering."""

    ts: str  # Slack epoch.microseconds string, e.g. "1714128842.001234"
    iso_local: str  # YYYY-MM-DDTHH:MM:SS local time
    user_handle: str  # ``@allie`` (resolved from user_id when possible)
    text: str
    thread_ts: str | None = None  # parent ts when this is a reply
    is_thread_parent: bool = False


# ---------------------------------------------------------------------------
# Channel discovery (opt-in via topic marker)
# ---------------------------------------------------------------------------


def list_monitored_channels(client: SlackClientLike) -> list[dict]:
    """Return the public/private channels whose topic contains ``[oracle:on]``.

    Each row is ``{id, name, topic}``. Caller mirrors each individually.
    """
    out: list[dict] = []
    try:
        resp = client.conversations_list(types="public_channel,private_channel")
    except Exception as exc:
        raise SlackMirrorError(f"conversations_list failed: {exc}") from exc
    for ch in resp.get("channels", []):
        topic = ((ch.get("topic") or {}).get("value") or "")
        if ORACLE_MARKER in topic:
            out.append({
                "id": ch.get("id"),
                "name": ch.get("name"),
                "topic": topic,
            })
    return out


def is_oracle_on(client: SlackClientLike, channel_id: str) -> bool:
    """Cheap probe: does this single channel have ``[oracle:on]`` in its topic?"""
    try:
        resp = client.conversations_info(channel=channel_id)
    except Exception as exc:
        raise SlackMirrorError(f"conversations_info({channel_id}) failed: {exc}") from exc
    topic = (((resp.get("channel") or {}).get("topic") or {}).get("value") or "")
    return ORACLE_MARKER in topic


# ---------------------------------------------------------------------------
# Fetch one day
# ---------------------------------------------------------------------------


def fetch_day(
    client: SlackClientLike,
    *,
    channel_id: str,
    date: _dt.date,
    user_cache: dict[str, str] | None = None,
) -> list[Message]:
    """Fetch all messages + thread replies posted to ``channel_id`` on ``date``.

    Times are converted to local time for the iso_local field; the
    underlying ``ts`` is preserved as the canonical key.
    """
    user_cache = user_cache if user_cache is not None else {}

    start = _dt.datetime.combine(date, _dt.time(0, 0, 0))
    end = _dt.datetime.combine(date, _dt.time(23, 59, 59, 999999))
    oldest = f"{start.timestamp():.6f}"
    latest = f"{end.timestamp():.6f}"

    try:
        history = client.conversations_history(
            channel=channel_id, oldest=oldest, latest=latest, limit=1000
        )
    except Exception as exc:
        raise SlackMirrorError(f"conversations_history failed: {exc}") from exc

    out: list[Message] = []
    for raw in history.get("messages", []):
        ts = raw.get("ts", "")
        thread_ts = raw.get("thread_ts")
        is_parent = bool(thread_ts) and thread_ts == ts
        out.append(_normalise(raw, client, user_cache, is_thread_parent=is_parent))
        # Pull replies for thread parents that landed today.
        if is_parent:
            try:
                replies = client.conversations_replies(
                    channel=channel_id, ts=ts, oldest=oldest, latest=latest
                )
            except Exception:
                continue
            for r in replies.get("messages", [])[1:]:  # [0] is the parent itself
                out.append(_normalise(r, client, user_cache))

    out.sort(key=lambda m: float(m.ts))
    return out


def _normalise(
    raw: dict,
    client: SlackClientLike,
    user_cache: dict[str, str],
    *,
    is_thread_parent: bool = False,
) -> Message:
    ts = str(raw.get("ts", ""))
    try:
        epoch = float(ts)
    except ValueError:
        epoch = 0.0
    iso_local = _dt.datetime.fromtimestamp(epoch).strftime("%Y-%m-%dT%H:%M:%S")
    user_id = raw.get("user") or raw.get("bot_id") or "unknown"
    handle = _resolve_handle(client, user_id, user_cache)
    return Message(
        ts=ts,
        iso_local=iso_local,
        user_handle=handle,
        text=str(raw.get("text", "")),
        thread_ts=str(raw.get("thread_ts")) if raw.get("thread_ts") else None,
        is_thread_parent=is_thread_parent,
    )


def _resolve_handle(client: SlackClientLike, user_id: str, cache: dict[str, str]) -> str:
    if user_id in cache:
        return cache[user_id]
    if not user_id or user_id == "unknown":
        cache[user_id] = "@unknown"
        return "@unknown"
    try:
        resp = client.users_info(user=user_id)
        prof = (resp.get("user") or {}).get("profile") or {}
        name = prof.get("display_name") or prof.get("real_name") or user_id
        handle = f"@{name}" if not name.startswith("@") else name
    except Exception:
        handle = f"@{user_id}"
    cache[user_id] = handle
    return handle


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def slack_dir() -> Path:
    return lab_mgmt_repo_root() / SLACK_SUBDIR


def channel_dir(channel_name: str) -> Path:
    return slack_dir() / channel_name


def mirror_path(channel_name: str, date: _dt.date) -> Path:
    return channel_dir(channel_name) / f"{date.isoformat()}.md"


def render_mirror(
    *,
    channel_name: str,
    date: _dt.date,
    messages: Iterable[Message],
    workspace: str = "",
) -> str:
    """Render one day's mirror to its on-disk markdown form."""
    msgs = list(messages)
    participants = sorted({m.user_handle for m in msgs})
    meta = {
        "channel": channel_name,
        "date": date.isoformat(),
        "message_count": len(msgs),
        "participants": participants,
    }
    if workspace:
        meta["slack_workspace"] = workspace

    body_lines: list[str] = []
    for m in msgs:
        # HH:MM is the friendly display; the canonical key is the ts in
        # frontmatter when distillation needs to cite back.
        time_str = m.iso_local[11:16] if "T" in m.iso_local else m.iso_local
        prefix = "## "
        if m.thread_ts and not m.is_thread_parent:
            prefix = "### "  # threaded reply — indented heading
        body_lines.append(f"{prefix}{time_str} · {m.user_handle}")
        if m.text.strip():
            body_lines.append("")
            body_lines.append(m.text)
        body_lines.append("")
    return dump_document(meta, "\n".join(body_lines))


def write_mirror(
    *,
    channel_name: str,
    date: _dt.date,
    messages: Iterable[Message],
    workspace: str = "",
) -> Path:
    cdir = channel_dir(channel_name)
    cdir.mkdir(parents=True, exist_ok=True)
    path = mirror_path(channel_name, date)
    path.write_text(
        render_mirror(channel_name=channel_name, date=date, messages=messages, workspace=workspace),
        encoding="utf-8",
    )
    return path


def mirror_channel_day(
    *,
    channel_name: str,
    channel_id: str,
    date: _dt.date,
    workspace: str = "",
    client: SlackClientLike | None = None,
) -> Path:
    """End-to-end: fetch + persist one channel for one day."""
    client = client or make_client()
    if not is_oracle_on(client, channel_id):
        raise SlackMirrorError(
            f"channel {channel_name!r} ({channel_id}) is not opted-in. "
            f"Add {ORACLE_MARKER!r} to its topic first."
        )
    msgs = fetch_day(client, channel_id=channel_id, date=date)
    return write_mirror(
        channel_name=channel_name, date=date, messages=msgs, workspace=workspace
    )
