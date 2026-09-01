"""
Purpose: audit a lab/group roster against the PI's OWN certificate records, so
         the dashboard (and a scheduled routine) can answer "does every member
         hold a valid identity certificate?" — and flag the ones who don't.

Author: Mike Hallett (with Claude Code)
Date: 2026-07-13

Why this is possible from the PI's machine alone
------------------------------------------------
When the PI onboards someone with ``issue_member_card`` their machine records the
result in three local places — the roster (``members/<h>.md`` stamped with the
card's fingerprint + id), the issuance ledger
(``~/.murmurent/revocation/<centre>.issued.json``), and the revocation set (CRL).
That is everything needed to classify a member without contacting anyone:

  - ``uncertified`` — on the roster but no card was ever issued (no fingerprint on
    the roster AND no ledger entry). This is exactly what the old free-form
    "add member" button produced.
  - ``revoked``     — the member's card_id or fingerprint is in the revocation set.
  - ``expired``     — the ledger recorded the card's ``valid_until`` and it is past.
  - ``mismatch``    — the roster's fingerprint disagrees with what the PI issued
    (roster tampered / re-added by hand after issuance).
  - ``valid``       — has a card, in the ledger, not revoked, not expired.

Detection only. Removal is a separate, PI-confirmed action (see the dashboard
``/api/members/audit`` + the existing deactivate flow) — this module never
mutates the roster or the CRL.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

from . import membership as _mem
from . import revocation as _rev

# The classifications a member can land in. Anything other than ``valid`` is a
# finding the PI should look at.
VALID = "valid"
UNCERTIFIED = "uncertified"
REVOKED = "revoked"
EXPIRED = "expired"
MISMATCH = "mismatch"

_HUMAN = {
    UNCERTIFIED: "no identity certificate was ever issued to this member",
    REVOKED: "this member's certificate has been revoked",
    EXPIRED: "this member's certificate has expired",
    MISMATCH: "the roster fingerprint does not match the issued certificate",
}


@dataclass
class MemberCertStatus:
    """One roster member's certificate standing."""

    handle: str
    full_name: str
    role: str
    status: str            # roster status: active | inactive
    cert: str              # VALID | UNCERTIFIED | REVOKED | EXPIRED | MISMATCH
    detail: str = ""       # human-readable why (empty for VALID)
    is_pi: bool = False

    @property
    def valid(self) -> bool:
        return self.cert == VALID


def resolve_centre(env: dict | None = None) -> str:
    """The centre name the PI's cards/ledger are keyed under. Mirrors the
    resolution ``issuance`` uses at issue time so the audit reads the same
    ledger: the local identity card's ``centre`` first, then the machine's
    centre install record. Returns ``""`` if neither is set up."""
    try:
        from . import identity_card as _ic
        local = _ic.local_card(env=env) or {}
        c = str(local.get("centre") or "").strip()
        if c:
            return c
    except Exception:  # noqa: BLE001
        pass
    try:
        from . import centre_info as _ci
        centre = _ci.read_centre(env=env)
        if centre:
            return str(getattr(centre, "unique_name", "")
                       or getattr(centre, "install_id", "") or "").strip()
    except Exception:  # noqa: BLE001
        pass
    return ""


def _classify(rec, *, revoked: set[str], ledger: dict,
              now: _dt.datetime) -> tuple[str, str]:
    """Return ``(cert, detail)`` for one member record."""
    led = ledger.get(rec.handle.lower())
    has_card = bool(rec.card_fingerprint or rec.card_id)

    if not has_card and not led:
        return UNCERTIFIED, _HUMAN[UNCERTIFIED]

    # Revoked: either identifier appearing in the revocation set kills the card.
    if (rec.card_id and rec.card_id in revoked) or \
       (rec.card_fingerprint and rec.card_fingerprint in revoked):
        return REVOKED, _HUMAN[REVOKED]
    if led:
        lid, lfp = led.get("card_id"), led.get("fingerprint")
        if (lid and lid in revoked) or (lfp and lfp in revoked):
            return REVOKED, _HUMAN[REVOKED]

    # Expired: only decidable when the ledger recorded valid_until.
    vu = (led or {}).get("valid_until")
    if vu:
        try:
            exp = _dt.datetime.fromisoformat(str(vu).replace("Z", "+00:00"))
            if exp.tzinfo is not None:
                exp = exp.replace(tzinfo=None)
            if now > exp:
                return EXPIRED, f"certificate expired {str(vu)[:10]}"
        except ValueError:
            pass

    # Roster stamped with a fingerprint that isn't the one we issued.
    if led and rec.card_fingerprint and led.get("fingerprint") \
       and rec.card_fingerprint != led.get("fingerprint"):
        return MISMATCH, _HUMAN[MISMATCH]

    return VALID, ""


def audit(*, centre: str | None = None, now: _dt.datetime | None = None,
          include_inactive: bool = False,
          env: dict | None = None) -> list[MemberCertStatus]:
    """Classify every roster member's certificate standing.

    The PI is always reported as ``valid`` (they hold a PI card, not a member
    card, and cannot be removed) and never appears as a finding.
    """
    now = now or _dt.datetime.now()
    centre = resolve_centre(env) if centre is None else centre
    revoked = set(_rev.revoked_ids(centre)) if centre else set()
    ledger = _rev.issued_ledger(centre) if centre else {}

    try:
        pi = (_mem.pi_handle() or "").lstrip("@").lower()
    except Exception:  # noqa: BLE001
        pi = ""

    out: list[MemberCertStatus] = []
    for rec in _mem.iter_members(include_inactive=include_inactive):
        is_pi = rec.handle.lower() == pi
        if is_pi:
            out.append(MemberCertStatus(
                handle=rec.handle, full_name=rec.full_name, role=rec.role,
                status=rec.status, cert=VALID, is_pi=True))
            continue
        cert, detail = _classify(rec, revoked=revoked, ledger=ledger, now=now)
        out.append(MemberCertStatus(
            handle=rec.handle, full_name=rec.full_name, role=rec.role,
            status=rec.status, cert=cert, detail=detail, is_pi=False))
    return out


def findings(statuses: list[MemberCertStatus] | None = None,
             **kw) -> list[MemberCertStatus]:
    """Just the members who are NOT valid (the PI-actionable list)."""
    statuses = statuses if statuses is not None else audit(**kw)
    return [s for s in statuses if not s.valid]


def status_map(**kw) -> dict[str, str]:
    """``{handle: cert}`` for every member — used by the dashboard snapshot to
    stamp each roster row with its certificate standing."""
    return {s.handle.lower(): s.cert for s in audit(**kw)}
