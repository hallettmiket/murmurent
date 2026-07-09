"""
Purpose: provision a cert-project's shared infrastructure — starting with a
private Slack channel — with membership synced to the project's CERTIFIED
members. Cert-projects are the authoritative project model, so this is Phase C
of the Slack↔CC plan re-keyed onto them.

Everything is best-effort + injectable: the Slack seams (``creator`` / ``inviter``)
no-op without a bot token, so the test suite stays green token-free. The
handle→email map comes from the lab roster (``members/<handle>.md``), which
already carries each member's email + github.

Author: Mike Hallett (with Claude Code)
Input: the cert-project registry + the lab roster + a Slack bot token (env or
       ``~/.config/wigamig/slack-token``).
Output: a private channel per project; ``slack_channel_id`` stamped on the record.
"""

from __future__ import annotations

from . import cert_projects as _cp
from . import membership as _mem


class CertProvisionError(RuntimeError):
    """A cert-project provisioning step could not be completed."""


def slack_channel_name(project: str) -> str:
    """Slack channel name for a cert-project: the project name, lowercased and
    reduced to Slack's allowed charset (a–z, 0–9, ``-``, ``_``), capped at 80.
    ``_`` is preserved (matches wigamig's identifier convention)."""
    s = "".join(c if (c.isalnum() or c in "-_") else "-" for c in str(project).lower())
    return s.strip("-_")[:80] or "project"


def member_email_map(handles=None) -> dict[str, str]:
    """``{bare-lowercased-handle: email}`` from the lab roster, optionally limited
    to ``handles``. The roster is the source of truth for member email."""
    want = None if handles is None else {str(h).lstrip("@").lower() for h in handles}
    out: dict[str, str] = {}
    for m in _mem.iter_members():
        h = m.handle.lstrip("@").lower()
        if m.email and (want is None or h in want):
            out[h] = m.email
    return out


def _default_creator(name: str):
    from . import centre_provision as _prov
    return _prov.slack_create_channel(name, private=True)


def _default_inviter(channel_id: str, handles: list[str], *, member_email_map: dict):
    from ..dashboard import slack_notify as _sn
    return _sn.invite_members_to_channel(channel_id, handles,
                                         member_email_map=member_email_map)


def provision_slack(project: str, *, lab: str | None = None,
                    env: dict | None = None, creator=None, inviter=None) -> dict:
    """Ensure a private Slack channel for cert-project ``project`` and invite its
    certified members. Stamps ``slack_channel_id`` on the record the first time.
    Idempotent: an already-provisioned project re-syncs membership without
    re-creating the channel. Returns a structured summary; reports ``missing_token``
    (not an error) when there is no Slack token, so callers/tests degrade cleanly.

    ``creator`` / ``inviter`` are injectable seams (default to the real Slack
    engines, which themselves no-op without a token)."""
    cp = _cp.get(project, env)
    if cp is None:
        raise CertProvisionError(f"no cert-project named {project!r}")
    creator = creator or _default_creator
    inviter = inviter or _default_inviter

    channel_id = cp.slack_channel_id
    created = False
    if not channel_id:
        res = creator(slack_channel_name(project))
        if not getattr(res, "ok", False):
            return {"ok": False, "channel_id": None, "created": False,
                    "error": getattr(res, "error", "channel_create_failed"),
                    "detail": getattr(res, "detail", ""),
                    "invited": [], "already_in": [], "unresolved": []}
        channel_id = res.channel_id
        created = True
        _cp.upsert(project, lab=(lab or cp.lab), slack_channel_id=channel_id, env=env)

    handles = [m.lstrip("@") for m in cp.members]
    inv = inviter(channel_id, handles, member_email_map=member_email_map(handles))
    return {"ok": True, "channel_id": channel_id, "created": created,
            "invited": inv.get("invited", []), "already_in": inv.get("already_in", []),
            "unresolved": inv.get("unresolved", []), "error": inv.get("error")}


__all__ = ["CertProvisionError", "slack_channel_name", "member_email_map",
           "provision_slack"]
