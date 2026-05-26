"""
Purpose: Centre-wide broadcast messaging — tier-tailored Slack pings
         to {everyone, pis, leaders, admin} via the centre's shared
         workspace.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-26

Item 3 of the post-smoke design conversation. Senders pick an
audience (`everyone | pis | leaders | admin`); the system resolves
that to a channel ID from the registrar profile's
``broadcast_channels`` mapping and posts via Slack. Every send is
audit-logged at:

    <lab_info>/broadcasts/<YYYY-MM>.md

… so a centre admin can always recover "who broadcast what to whom
on which day".

Channel topology lives in the centre's registrar.md frontmatter so
different institutions can name their channels however they like:

    broadcast_channels:
      everyone: C0EVERYONE
      pis:      C0PIS
      leaders:  C0LEADERS
      admin:    C0ADMIN

Missing channel IDs surface as a clear "audience not configured"
error rather than silently dropping the broadcast.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .registrar import (
    _git_commit_all, _git_init_if_needed, lab_info_root, read_profile,
)


BROADCASTS_SUBDIR = "broadcasts"
VALID_AUDIENCES = ("everyone", "pis", "leaders", "admin")


class BroadcastError(RuntimeError):
    """Broadcast failed (unknown audience, channel not configured, …)."""


@dataclass
class Broadcast:
    """One audit-logged broadcast event."""

    iso_ts: str
    audience: str
    channel_id: str
    sender: str                            # @handle (no leading @)
    message: str                           # raw text the sender typed
    message_link: str = ""                 # Slack permalink when known
    tags: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Paths + channel resolver
# ---------------------------------------------------------------------------

def broadcasts_dir(env: dict[str, str] | None = None) -> Path:
    return lab_info_root(env) / BROADCASTS_SUBDIR


def _ledger_path(now: _dt.datetime | None = None,
                  env: dict[str, str] | None = None) -> Path:
    now = now or _dt.datetime.now(_dt.timezone.utc)
    return broadcasts_dir(env) / f"{now.year:04d}-{now.month:02d}.md"


def channel_id_for(
    audience: str,
    *,
    env: dict[str, str] | None = None,
) -> str:
    """Resolve an audience to its Slack channel ID via the registrar
    profile. Raises BroadcastError if audience is invalid or the
    channel hasn't been configured yet."""
    aud = (audience or "").strip().lower()
    if aud not in VALID_AUDIENCES:
        raise BroadcastError(
            f"audience must be one of {VALID_AUDIENCES} (got {audience!r})"
        )
    profile = read_profile(env=env) or {}
    mapping = profile.get("broadcast_channels") or {}
    if not isinstance(mapping, dict):
        raise BroadcastError(
            "registrar.md frontmatter has broadcast_channels but it's "
            "not a mapping; fix it to: {everyone: C…, pis: C…, …}"
        )
    cid = str(mapping.get(aud) or "").strip()
    if not cid:
        raise BroadcastError(
            f"no channel configured for audience {aud!r}; add it under "
            f"broadcast_channels in registrar.md (or via the registrar "
            f"dashboard's profile editor)."
        )
    return cid


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

def _render_ledger_entry(b: Broadcast) -> str:
    head = f"## {b.iso_ts} · {b.audience} · @{b.sender}"
    meta_lines = [f"- channel: `{b.channel_id}`"]
    if b.message_link:
        meta_lines.append(f"- link: {b.message_link}")
    if b.tags:
        meta_lines.append(f"- tags: {', '.join(b.tags)}")
    body = b.message.rstrip()
    return "\n".join([head, "", *meta_lines, "", "> " + body.replace("\n", "\n> "), ""])


def append_to_ledger(
    b: Broadcast,
    *,
    env: dict[str, str] | None = None,
) -> Path:
    """Append the broadcast to its month-ledger file + commit."""
    p = _ledger_path(env=env)
    p.parent.mkdir(parents=True, exist_ok=True)
    header = f"# Broadcasts — {p.stem}\n\n"
    existing = p.read_text(encoding="utf-8") if p.is_file() else header
    p.write_text(existing + _render_ledger_entry(b) + "\n", encoding="utf-8")
    root = lab_info_root(env)
    _git_init_if_needed(root)
    _git_commit_all(root,
        f"broadcasts: @{b.sender} → {b.audience}: "
        f"{(b.message[:60] + '…') if len(b.message) > 60 else b.message}")
    return p


def iter_recent(
    *,
    limit: int = 20,
    env: dict[str, str] | None = None,
) -> list[Broadcast]:
    """Read the current + prior month ledgers and return up to
    ``limit`` most-recent Broadcast records, newest first.

    Light-weight parser: we wrote them ourselves so the format is
    stable. Best-effort — bad lines skip silently.
    """
    out: list[Broadcast] = []
    now = _dt.datetime.now(_dt.timezone.utc)
    months = [
        (now.year, now.month),
        ((now.year if now.month > 1 else now.year - 1),
         (now.month - 1 if now.month > 1 else 12)),
    ]
    for yr, mo in months:
        p = broadcasts_dir(env) / f"{yr:04d}-{mo:02d}.md"
        if not p.is_file():
            continue
        out.extend(_parse_ledger(p))
    out.sort(key=lambda b: b.iso_ts, reverse=True)
    return out[: max(1, int(limit))]


def _parse_ledger(path: Path) -> list[Broadcast]:
    out: list[Broadcast] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return out
    # Split on "## " headers — each is one broadcast.
    chunks = text.split("\n## ")
    for i, chunk in enumerate(chunks):
        if i == 0:
            continue   # the header preamble
        head, _, rest = chunk.partition("\n")
        # head: "2026-05-26T... · audience · @sender"
        parts = [p.strip() for p in head.split("·")]
        if len(parts) < 3:
            continue
        iso_ts, aud, sender = parts[0], parts[1], parts[2].lstrip("@")
        channel_id, link = "", ""
        for line in rest.splitlines():
            if line.startswith("- channel:"):
                channel_id = line.split(":", 1)[1].strip().strip("`")
            elif line.startswith("- link:"):
                link = line.split(":", 1)[1].strip()
        # Message is the quoted block (> ...).
        msg_lines = [l[2:] if l.startswith("> ") else l[1:] if l.startswith(">") else None
                     for l in rest.splitlines()]
        msg = "\n".join([l for l in msg_lines if l is not None]).strip()
        out.append(Broadcast(
            iso_ts=iso_ts, audience=aud, channel_id=channel_id,
            sender=sender, message=msg, message_link=link,
        ))
    return out


# ---------------------------------------------------------------------------
# Public API used by the HTTP endpoint + CLI
# ---------------------------------------------------------------------------

def send_broadcast(
    *,
    audience: str,
    message: str,
    sender: str,
    tags: list[str] | None = None,
    env: dict[str, str] | None = None,
    poster=None,                           # injectable for tests
) -> Broadcast:
    """Resolve channel, post to Slack, persist to ledger. Returns the
    Broadcast (with ``message_link`` populated on success).

    ``poster`` is an optional callable ``(channel_id, text) -> link``
    so tests can inject a fake; defaults to the live Slack helper.
    """
    if not (message or "").strip():
        raise BroadcastError("message is required")
    if not (sender or "").strip():
        raise BroadcastError("sender is required")
    sender_clean = sender.lstrip("@").lower()
    audience_clean = (audience or "").strip().lower()
    cid = channel_id_for(audience_clean, env=env)
    # Keep microseconds so back-to-back sends sort deterministically;
    # display layer is welcome to round them away.
    now = _dt.datetime.now(_dt.timezone.utc)
    text = f"📣 *{audience_clean}* broadcast from @{sender_clean}\n{message.strip()}"
    if poster is None:
        from ..dashboard import slack_notify as _slack
        link = ""
        try:
            link = _slack.post_and_link(cid, text) or ""
        except Exception as exc:
            raise BroadcastError(f"Slack post failed: {exc}") from exc
    else:
        link = poster(cid, text) or ""
    b = Broadcast(
        iso_ts=now.isoformat().replace("+00:00", "Z"),
        audience=audience_clean,
        channel_id=cid,
        sender=sender_clean,
        message=message.strip(),
        message_link=link,
        tags=list(tags or []),
    )
    append_to_ledger(b, env=env)
    return b


__all__ = [
    "BROADCASTS_SUBDIR", "VALID_AUDIENCES",
    "BroadcastError", "Broadcast",
    "broadcasts_dir", "channel_id_for",
    "append_to_ledger", "iter_recent",
    "send_broadcast",
]
