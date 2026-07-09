"""
Purpose: unify a lab member's cross-system identity — the wigamig **handle**, the
**email** (the join key), the **Slack user id**, and the **GitHub login** — into
one record. This is the Phase-A foundation the Slack/GitHub project provisioning
builds on: to invite a member to a private channel we need their Slack uid; to add
them to the repo we need their GitHub login; both hang off the email captured in
their member record.

Slack resolution is **injectable** (``slack_resolver``) and only happens when a
resolver is supplied or a token is available — so this module is import-safe and
unit-testable with no Slack token.

Note (known gap, tracked separately): identities are read from the lab-mgmt member
roster (``members/<handle>.md``). The standalone card-issuance ledger is a distinct
store; unifying the roster and the card ledger is a deliberate later decision. This
resolver reads the roster and will adopt the unified source when that lands.
"""

from __future__ import annotations

from . import membership as _m


def _default_slack_resolver(email: str) -> str | None:
    """email -> Slack user id via the shared bot token (lazy import to keep this
    module free of a core->dashboard dependency at import time)."""
    if not email:
        return None
    try:
        from ..dashboard import slack_notify as _sn
        return _sn._lookup_user_id_by_email(email)
    except Exception:  # noqa: BLE001 — no token / offline / not found
        return None


def member_identity(handle: str, *, slack_resolver=None) -> dict | None:
    """The unified identity for one member, or None if they have no member record.

    Returns ``{handle, email, github, slack_uid, in_workspace}``. ``slack_uid`` is
    None (and ``in_workspace`` False) when the member has no email, isn't in the
    Slack workspace, or no token/resolver is available — the caller decides what to
    do (e.g. surface "not in workspace" and offer the invite link)."""
    p = _m.member_path(handle)
    if not p.is_file():
        return None
    rec = _m.parse_member(p)
    resolver = slack_resolver or _default_slack_resolver
    slack_uid = resolver(rec.email) if rec.email else None
    return {
        "handle": rec.handle,
        "email": rec.email,
        "github": rec.github,
        "slack_uid": slack_uid,
        "in_workspace": slack_uid is not None,
    }


def iter_lab_identities(*, slack_resolver=None, active_only: bool = True) -> list[dict]:
    """Unified identities for every member of the lab (active by default)."""
    out: list[dict] = []
    for rec in _m.iter_members(include_inactive=not active_only):
        ident = member_identity(rec.handle, slack_resolver=slack_resolver)
        if ident is not None:
            out.append(ident)
    return out


__all__ = ["member_identity", "iter_lab_identities"]
