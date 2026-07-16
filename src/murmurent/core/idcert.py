"""
Purpose: the identity-card CERTIFICATE layer — turns raw ed25519 signatures
(``core/idkeys.py``) into a verifiable **root → PI → member** chain of trust.

Trust hierarchy mirrors the org:

    Centre root key  --signs-->  PI card  --embeds PI pubkey, signs-->  member card

Verification rules baked in from the adversary + security_guard design reviews:

  - **The verifier never trusts a key the card hands it.** A PI card is verified
    with the *pinned centre root key* (trust anchor), not any key inside the card.
    A member card is verified with the PI's public key taken from the *PI card's
    root-signed payload* — so the whole chain hangs off the one pinned root.
  - **Chain shape is enforced**: exactly root→PI→member, member cards are
    leaf-only (``kind == "member"`` can never act as an issuer), and the PI card
    must have been temporally valid at the moment the member card was issued.
  - **CRL is mandatory and FAIL-CLOSED.** A verifier with no fresh, root-signed
    revocation list REFUSES the card. TTL is long (90 days) so timely revocation
    depends entirely on the CRL being reachable — hence fail-closed.
  - **Sign exact canonical bytes over the whole payload** (via idkeys), fixed
    algorithm, no unsigned fields. Signed cards transport as JSON, never YAML
    (YAML would coerce ISO timestamps to datetimes and desync the signature).
  - **Proof-of-possession at issuance**: before an issuer binds a subject's
    fingerprint into a card, the subject signs a fresh nonce challenge proving
    they hold the matching private key.
  - **Trust anchor pinning (TOFU)**: the centre root pubkey is pinned locally on
    first import; a later mismatch fails closed rather than trusting the new key.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from . import idkeys as K

SIGNED_CARD_VERSION = 1
DEFAULT_TTL_DAYS = 90          # long TTL → CRL fail-closed is the real revocation
CRL_MAX_AGE_DAYS = 7           # a CRL older than this is "stale" → refuse (fail-closed)
DEFAULT_SKEW_SECONDS = 300     # tolerated clock skew on temporal checks


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _home() -> Path:
    return Path(os.environ.get("MURMURENT_HOME", str(Path.home() / ".murmurent")))


def _norm(handle: str) -> str:
    return "@" + str(handle or "").lstrip("@").strip().lower()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(s: str) -> datetime:
    dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _as_pub(x):
    return K.decode_public(x) if isinstance(x, str) else x


def dumps(card: dict) -> str:
    """Serialize a signed card / CRL for transport (JSON — never YAML)."""
    return json.dumps(card, ensure_ascii=False, indent=2)


def loads(text: str) -> dict:
    data = json.loads(text)
    if not isinstance(data, dict) or "payload" not in data or "signature" not in data:
        raise ValueError("not a signed card (missing payload/signature)")
    return data


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Verdict:
    ok: bool
    reason: str = ""
    handle: str = ""
    group: str | None = None
    fingerprint: str = ""
    pubkey: str = ""
    kind: str = ""
    roles: tuple = field(default_factory=tuple)

    def __bool__(self) -> bool:  # so `if verify_...():` reads naturally
        return self.ok


# ---------------------------------------------------------------------------
# Issuance
# ---------------------------------------------------------------------------

def _card_payload(*, kind, centre, handle, subject_pub, group, roles,
                  issuer_handle, issuer_pub, issued_at, ttl_days, card_id):
    ia = issued_at or _now()
    subj = _as_pub(subject_pub)
    return {
        "version": SIGNED_CARD_VERSION,
        "kind": kind,
        "centre": centre or "",
        "subject": {
            "handle": _norm(handle),
            "fingerprint": K.fingerprint(subj),
            "pubkey": K.encode_public(subj),
        },
        "group": group,
        "roles": list(roles or []),
        "issuer": {
            "handle": _norm(issuer_handle),
            "fingerprint": K.fingerprint(issuer_pub),
        },
        "issued_at": _iso(ia),
        "not_before": _iso(ia),
        "valid_until": _iso(ia + timedelta(days=ttl_days)),
        "card_id": card_id or uuid4().hex,
    }


def _sign_envelope(payload: dict, priv: Ed25519PrivateKey) -> dict:
    return {"payload": payload, "signature": K.sign(payload, priv)}


def issue_pi_card(*, handle, pi_pubkey, centre, root_priv: Ed25519PrivateKey,
                  issuer_handle="", roles=None, issued_at=None,
                  ttl_days=DEFAULT_TTL_DAYS, card_id=None) -> dict:
    """Centre root signs a PI card attesting ``handle`` belongs to the centre.

    ``pi_pubkey`` (the PI's own signing key) is embedded and thereby authenticated
    by the root signature — it is the key that will later verify this PI's member
    cards."""
    payload = _card_payload(
        kind="pi", centre=centre, handle=handle, subject_pub=pi_pubkey,
        group=None, roles=roles, issuer_handle=issuer_handle,
        issuer_pub=root_priv.public_key(), issued_at=issued_at,
        ttl_days=ttl_days, card_id=card_id)
    return _sign_envelope(payload, root_priv)


def issue_member_card(*, handle, member_pubkey, group, centre,
                      pi_priv: Ed25519PrivateKey, pi_handle="", roles=None,
                      issued_at=None, ttl_days=DEFAULT_TTL_DAYS,
                      card_id=None) -> dict:
    """A PI (group registrar) signs a member card binding the member's pubkey
    fingerprint to a group. Leaf card — a member can never issue."""
    payload = _card_payload(
        kind="member", centre=centre, handle=handle, subject_pub=member_pubkey,
        group=group, roles=roles, issuer_handle=pi_handle,
        issuer_pub=pi_priv.public_key(), issued_at=issued_at,
        ttl_days=ttl_days, card_id=card_id)
    return _sign_envelope(payload, pi_priv)


def issue_project_lead_card(*, handle, lead_pubkey, project, lab, centre,
                            pi_priv: Ed25519PrivateKey, pi_handle="",
                            issued_at=None, ttl_days=DEFAULT_TTL_DAYS,
                            card_id=None) -> dict:
    """The PI signs a **delegation credential**: ``handle`` is the lead of
    ``<lab>/<project>`` and may sign project cards for it with their own key.

    Distinct ``kind == "project_lead"`` (not ``member`` + role) so chain shape
    stays structural: a lead card can never pass ``verify_member_card`` and a
    member card can never act as an issuer in ``verify_project_card``. Revoking
    this card's ``card_id`` on the CRL kills every project card it signed —
    the mid-chain CRL check in :func:`verify_project_card` fails closed.

    The PI==lead case is plain self-delegation (``lead_pubkey`` is the PI's own
    key); the chain verifies identically."""
    group = f"{lab}/{project}"
    payload = _card_payload(
        kind="project_lead", centre=centre, handle=handle,
        subject_pub=lead_pubkey, group=group,
        roles=[{"kind": "project_lead", "project": project, "lab": lab,
                "group": group}],
        issuer_handle=pi_handle, issuer_pub=pi_priv.public_key(),
        issued_at=issued_at, ttl_days=ttl_days, card_id=card_id)
    return _sign_envelope(payload, pi_priv)


def issue_project_card_by_lead(*, handle, member_pubkey, group, centre,
                               lead_priv: Ed25519PrivateKey, lead_handle="",
                               roles=None, issued_at=None,
                               ttl_days=DEFAULT_TTL_DAYS, card_id=None) -> dict:
    """The project **lead** signs a member's project card with the lead's OWN
    key. ``group`` is the project realm (``<lab>/<project>``) and must equal
    the lead card's ``group`` — :func:`verify_project_card` enforces that the
    delegation is scoped to exactly this project. Leaf card (``kind ==
    "member"``), same envelope shape as :func:`issue_member_card`."""
    payload = _card_payload(
        kind="member", centre=centre, handle=handle, subject_pub=member_pubkey,
        group=group, roles=roles, issuer_handle=lead_handle,
        issuer_pub=lead_priv.public_key(), issued_at=issued_at,
        ttl_days=ttl_days, card_id=card_id)
    return _sign_envelope(payload, lead_priv)


# ---------------------------------------------------------------------------
# CRL (signed by the centre root; mandatory + fail-closed on verify)
# ---------------------------------------------------------------------------

def build_crl(*, centre, revoked, root_priv: Ed25519PrivateKey, serial: int,
              issued_at=None) -> dict:
    """Build a root-signed revocation list.

    ``revoked`` is a set/list of card_ids and/or subject fingerprints. ``serial``
    is monotonic so a verifier that tracks the last-seen serial can reject a
    replayed older list (freshness is also bounded by ``issued_at`` + max-age)."""
    ia = issued_at or _now()
    payload = {
        "version": 1,
        "centre": centre or "",
        "serial": int(serial),
        "issued_at": _iso(ia),
        "revoked": sorted(set(revoked or [])),
    }
    return {"payload": payload, "signature": K.sign(payload, root_priv)}


def _check_crl(crl, root_pub, now, centre, *, max_age_days=CRL_MAX_AGE_DAYS):
    """Returns (ok, revoked_set, reason). Fail-closed: anything wrong → not ok."""
    if not crl:
        return (False, set(), "no CRL supplied (fail-closed)")
    p, sig = crl.get("payload"), crl.get("signature")
    if not isinstance(p, dict) or not sig:
        return (False, set(), "malformed CRL")
    if not K.verify(p, sig, root_pub):
        return (False, set(), "unverifiable CRL (bad root signature)")
    if centre and p.get("centre") != centre:
        return (False, set(), "CRL centre mismatch")
    try:
        ia = _parse(p["issued_at"])
    except Exception:  # noqa: BLE001
        return (False, set(), "bad CRL timestamp")
    if now - ia > timedelta(days=max_age_days):
        return (False, set(), "stale CRL (fail-closed)")
    return (True, set(p.get("revoked") or []), "")


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def _temporal_reason(payload, now, skew):
    try:
        nb, vu = _parse(payload["not_before"]), _parse(payload["valid_until"])
    except Exception:  # noqa: BLE001
        return "bad card timestamps"
    if now + skew < nb:
        return "not yet valid"
    if now - skew > vu:
        return "expired"
    return ""


def verify_pi_card(card, *, root_pub, now=None, skew_seconds=DEFAULT_SKEW_SECONDS,
                   crl=None, centre=None, require_crl=True) -> Verdict:
    """Verify a PI card against the pinned centre root key.

    ``root_pub`` MUST be the trust-anchor key (see :func:`load_pinned_root`), not
    a key read out of the card."""
    now = now or _now()
    skew = timedelta(seconds=skew_seconds)
    if not isinstance(card, dict):
        return Verdict(False, "malformed card")
    p, sig = card.get("payload"), card.get("signature")
    if not isinstance(p, dict) or not sig:
        return Verdict(False, "malformed card")
    if p.get("version") != SIGNED_CARD_VERSION:
        return Verdict(False, "unsupported card version")
    if p.get("kind") != "pi":
        return Verdict(False, "not a PI card")
    if centre and p.get("centre") != centre:
        return Verdict(False, "wrong centre")
    if not K.verify(p, sig, root_pub):
        return Verdict(False, "bad root signature")
    if r := _temporal_reason(p, now, skew):
        return Verdict(False, r)
    if require_crl:
        ok, revoked, reason = _check_crl(crl, root_pub, now, centre or p.get("centre"))
        if not ok:
            return Verdict(False, reason)
        if p["card_id"] in revoked or p["subject"]["fingerprint"] in revoked:
            return Verdict(False, "revoked")
    subj = p["subject"]
    return Verdict(True, "ok", handle=subj["handle"], group=None,
                   fingerprint=subj["fingerprint"], pubkey=subj["pubkey"],
                   kind="pi", roles=tuple(p.get("roles") or ()))


def verify_member_card(member_card, pi_card, *, root_pub, now=None,
                       skew_seconds=DEFAULT_SKEW_SECONDS, crl=None, centre=None,
                       require_crl=True) -> Verdict:
    """Verify a member card by walking the full chain to the pinned root.

    1. the PI card verifies against ``root_pub`` (and CRL);
    2. the member card verifies against the PI pubkey *from the PI card* (never
       from the member card), the issuer fingerprints match, the member card is
       ``kind == "member"`` (leaf), it is temporally valid, and the PI card was
       valid at the member card's issue time;
    3. the member card is not on the (fail-closed) CRL.
    """
    now = now or _now()
    skew = timedelta(seconds=skew_seconds)
    # The CRL is a verification-wide input, not a per-card one — validate it once
    # up front so a missing/stale/forged CRL reports cleanly (fail-closed) rather
    # than surfacing as "PI card invalid: ...". Per-card revocation is still
    # checked against it below.
    if require_crl:
        ok, _revoked, reason = _check_crl(crl, root_pub, now, centre)
        if not ok:
            return Verdict(False, reason)
    pv = verify_pi_card(pi_card, root_pub=root_pub, now=now,
                        skew_seconds=skew_seconds, crl=crl, centre=centre,
                        require_crl=require_crl)
    if not pv.ok:
        return Verdict(False, f"PI card invalid: {pv.reason}")
    pi_payload = pi_card["payload"]
    pi_pubkey = pi_payload["subject"]["pubkey"]
    pi_fpr = pi_payload["subject"]["fingerprint"]

    if not isinstance(member_card, dict):
        return Verdict(False, "malformed member card")
    p, sig = member_card.get("payload"), member_card.get("signature")
    if not isinstance(p, dict) or not sig:
        return Verdict(False, "malformed member card")
    if p.get("version") != SIGNED_CARD_VERSION:
        return Verdict(False, "unsupported card version")
    if p.get("kind") != "member":                     # leaf-only enforcement
        return Verdict(False, "not a member card")
    if centre and p.get("centre") != centre:
        return Verdict(False, "wrong centre")
    if p.get("centre") != pi_payload.get("centre"):
        return Verdict(False, "centre mismatch across chain")
    if (p.get("issuer") or {}).get("fingerprint") != pi_fpr:
        return Verdict(False, "issuer/PI mismatch")
    # signature checked with the PI key FROM THE PI CARD (root-authenticated)
    if not K.verify(p, sig, pi_pubkey):
        return Verdict(False, "bad PI signature")
    if r := _temporal_reason(p, now, skew):
        return Verdict(False, r)
    # the PI card must have been valid at the moment the member card was issued
    try:
        issued = _parse(p["issued_at"])
    except Exception:  # noqa: BLE001
        return Verdict(False, "bad member timestamps")
    if _temporal_reason(pi_payload, issued, timedelta(0)):
        return Verdict(False, "PI card not valid at member card's issue time")
    if require_crl:
        ok, revoked, reason = _check_crl(crl, root_pub, now, centre or p.get("centre"))
        if not ok:
            return Verdict(False, reason)
        if p["card_id"] in revoked or p["subject"]["fingerprint"] in revoked:
            return Verdict(False, "revoked")
    subj = p["subject"]
    return Verdict(True, "ok", handle=subj["handle"], group=p.get("group"),
                   fingerprint=subj["fingerprint"], pubkey=subj["pubkey"],
                   kind="member", roles=tuple(p.get("roles") or ()))


def verify_project_lead_card(lead_card, pi_card, *, root_pub, now=None,
                             skew_seconds=DEFAULT_SKEW_SECONDS, crl=None,
                             centre=None, require_crl=True) -> Verdict:
    """Verify a project-lead delegation card: root → PI → lead.

    Mirrors :func:`verify_member_card` except the mid card is ``kind ==
    "project_lead"``. The lead card's pubkey (root→PI-authenticated) is what
    later verifies the project cards this lead signed."""
    now = now or _now()
    skew = timedelta(seconds=skew_seconds)
    if require_crl:
        ok, _revoked, reason = _check_crl(crl, root_pub, now, centre)
        if not ok:
            return Verdict(False, reason)
    pv = verify_pi_card(pi_card, root_pub=root_pub, now=now,
                        skew_seconds=skew_seconds, crl=crl, centre=centre,
                        require_crl=require_crl)
    if not pv.ok:
        return Verdict(False, f"PI card invalid: {pv.reason}")
    pi_payload = pi_card["payload"]
    pi_pubkey = pi_payload["subject"]["pubkey"]
    pi_fpr = pi_payload["subject"]["fingerprint"]

    if not isinstance(lead_card, dict):
        return Verdict(False, "malformed lead card")
    p, sig = lead_card.get("payload"), lead_card.get("signature")
    if not isinstance(p, dict) or not sig:
        return Verdict(False, "malformed lead card")
    if p.get("version") != SIGNED_CARD_VERSION:
        return Verdict(False, "unsupported card version")
    if p.get("kind") != "project_lead":
        return Verdict(False, "not a project-lead card")
    if centre and p.get("centre") != centre:
        return Verdict(False, "wrong centre")
    if p.get("centre") != pi_payload.get("centre"):
        return Verdict(False, "centre mismatch across chain")
    if (p.get("issuer") or {}).get("fingerprint") != pi_fpr:
        return Verdict(False, "issuer/PI mismatch")
    # signature checked with the PI key FROM THE PI CARD (root-authenticated)
    if not K.verify(p, sig, pi_pubkey):
        return Verdict(False, "bad PI signature")
    if r := _temporal_reason(p, now, skew):
        return Verdict(False, r)
    # the PI card must have been valid at the moment the lead card was issued
    try:
        issued = _parse(p["issued_at"])
    except Exception:  # noqa: BLE001
        return Verdict(False, "bad lead timestamps")
    if _temporal_reason(pi_payload, issued, timedelta(0)):
        return Verdict(False, "PI card not valid at lead card's issue time")
    if require_crl:
        ok, revoked, reason = _check_crl(crl, root_pub, now, centre or p.get("centre"))
        if not ok:
            return Verdict(False, reason)
        if p["card_id"] in revoked or p["subject"]["fingerprint"] in revoked:
            return Verdict(False, "lead card revoked")
    subj = p["subject"]
    return Verdict(True, "ok", handle=subj["handle"], group=p.get("group"),
                   fingerprint=subj["fingerprint"], pubkey=subj["pubkey"],
                   kind="project_lead", roles=tuple(p.get("roles") or ()))


def verify_project_card(project_card, lead_card, pi_card, *, root_pub, now=None,
                        skew_seconds=DEFAULT_SKEW_SECONDS, crl=None,
                        centre=None, require_crl=True) -> Verdict:
    """Verify a project-membership card by walking root → PI → lead → member.

    1. the lead card verifies as a delegation credential (which itself walks
       root → PI, both against the fail-closed CRL);
    2. the project card verifies against the lead pubkey *from the lead card*
       (never from the leaf), the issuer fingerprints match, the leaf is
       ``kind == "member"`` with a ``project_member`` role, its ``group``
       equals the lead card's ``group`` (the delegation is scoped to exactly
       one project), it is temporally valid, and the lead card was valid at
       the leaf's issue time;
    3. the leaf is not on the (fail-closed) CRL.

    Revoking the lead card therefore invalidates every project card it signed
    — step 1 fails — with no extra machinery."""
    now = now or _now()
    skew = timedelta(seconds=skew_seconds)
    if require_crl:
        ok, _revoked, reason = _check_crl(crl, root_pub, now, centre)
        if not ok:
            return Verdict(False, reason)
    lv = verify_project_lead_card(lead_card, pi_card, root_pub=root_pub,
                                  now=now, skew_seconds=skew_seconds, crl=crl,
                                  centre=centre, require_crl=require_crl)
    if not lv.ok:
        return Verdict(False, f"lead card invalid: {lv.reason}")
    lead_payload = lead_card["payload"]
    lead_pubkey = lead_payload["subject"]["pubkey"]
    lead_fpr = lead_payload["subject"]["fingerprint"]

    if not isinstance(project_card, dict):
        return Verdict(False, "malformed project card")
    p, sig = project_card.get("payload"), project_card.get("signature")
    if not isinstance(p, dict) or not sig:
        return Verdict(False, "malformed project card")
    if p.get("version") != SIGNED_CARD_VERSION:
        return Verdict(False, "unsupported card version")
    if p.get("kind") != "member":                     # leaf-only enforcement
        return Verdict(False, "not a member card")
    if not any((r or {}).get("kind") == "project_member"
               for r in (p.get("roles") or [])):
        return Verdict(False, "no project_member role")
    if centre and p.get("centre") != centre:
        return Verdict(False, "wrong centre")
    if p.get("centre") != lead_payload.get("centre"):
        return Verdict(False, "centre mismatch across chain")
    # the delegation is scoped: the lead may sign for THE project it was
    # delegated, nothing else
    if p.get("group") != lead_payload.get("group"):
        return Verdict(False, "project/lead group mismatch")
    if (p.get("issuer") or {}).get("fingerprint") != lead_fpr:
        return Verdict(False, "issuer/lead mismatch")
    # signature checked with the lead key FROM THE LEAD CARD (chain-authenticated)
    if not K.verify(p, sig, lead_pubkey):
        return Verdict(False, "bad lead signature")
    if r := _temporal_reason(p, now, skew):
        return Verdict(False, r)
    # the lead card must have been valid at the moment the leaf was issued
    try:
        issued = _parse(p["issued_at"])
    except Exception:  # noqa: BLE001
        return Verdict(False, "bad project-card timestamps")
    if _temporal_reason(lead_payload, issued, timedelta(0)):
        return Verdict(False, "lead card not valid at project card's issue time")
    if require_crl:
        ok, revoked, reason = _check_crl(crl, root_pub, now, centre or p.get("centre"))
        if not ok:
            return Verdict(False, reason)
        if p["card_id"] in revoked or p["subject"]["fingerprint"] in revoked:
            return Verdict(False, "revoked")
    subj = p["subject"]
    return Verdict(True, "ok", handle=subj["handle"], group=p.get("group"),
                   fingerprint=subj["fingerprint"], pubkey=subj["pubkey"],
                   kind="member", roles=tuple(p.get("roles") or ()))


# ---------------------------------------------------------------------------
# Proof-of-possession (issuance-time)
# ---------------------------------------------------------------------------

def make_enrollment_request(handle, *, priv: Ed25519PrivateKey, nonce,
                            centre="", group="", email="", github="", slack="",
                            name="", official_handle="") -> dict:
    """Subject-side: sign a fresh ``nonce`` challenge proving control of the key.

    The issuer verifies this BEFORE binding ``fingerprint(pubkey)`` into a card,
    so the card's fingerprint binding actually means "this human holds this key."
    ``email`` + ``github`` + ``slack`` are self-asserted contact info the issuer
    records on the roster (they're inside the signed payload, so they can't be
    altered in flight). ``slack`` is the member's Slack username or member ID; it
    lets the PI DM the signed card straight back to them even when their Slack
    account email differs from the ``email`` above."""
    payload = {
        "purpose": "enrollment",
        "handle": _norm(handle),
        "name": name or "",
        "centre": centre or "",
        "group": group or "",
        "email": email or "",
        "github": (github or "").lstrip("@"),
        "slack": (slack or "").lstrip("@"),
        "official_handle": (official_handle or "").lstrip("@"),
        "nonce": str(nonce),
        "pubkey": K.encode_public(priv.public_key()),
    }
    return {"payload": payload, "signature": K.sign(payload, priv)}


def verify_enrollment(request, *, expected_fingerprint=None,
                      expected_nonce=None) -> bool:
    """Issuer-side: verify the enrollment request self-signature (+ optional
    nonce / fingerprint expectations). Any failure → False."""
    if not isinstance(request, dict):
        return False
    p, sig = request.get("payload"), request.get("signature")
    if not isinstance(p, dict) or not sig:
        return False
    pub = p.get("pubkey")
    if not pub or not K.verify(p, sig, pub):
        return False
    if expected_nonce is not None and p.get("nonce") != str(expected_nonce):
        return False
    if expected_fingerprint is not None and K.fingerprint(pub) != expected_fingerprint:
        return False
    return True


# ---------------------------------------------------------------------------
# Trust-anchor pinning (TOFU; mismatch fails closed)
# ---------------------------------------------------------------------------

def trust_dir() -> Path:
    return _home() / "trust"


def _anchor_path(centre: str) -> Path:
    safe = "".join(c if (c.isalnum() or c in "-_") else "_" for c in str(centre))
    return trust_dir() / f"{safe}.root"


def pin_root(centre: str, root_pubkey) -> str:
    """Pin ``centre``'s root public key locally. Returns the pinned string."""
    d = trust_dir()
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    enc = root_pubkey if (isinstance(root_pubkey, str)
                          and root_pubkey.startswith("ed25519:")) \
        else K.encode_public(_as_pub(root_pubkey) if isinstance(root_pubkey, str)
                              else root_pubkey)
    _anchor_path(centre).write_text(enc + "\n", encoding="utf-8")
    return enc


def load_pinned_root(centre: str) -> str | None:
    p = _anchor_path(centre)
    if not p.is_file():
        return None
    return p.read_text(encoding="utf-8").strip()


def verify_or_pin_root(centre: str, root_pubkey) -> tuple[bool, str]:
    """TOFU: pin on first sight; on a later mismatch, FAIL CLOSED.

    Returns (ok, reason). ``ok`` is True when the key was freshly pinned or
    matches the pin; False (with a reason) when it contradicts the pin."""
    incoming = root_pubkey if (isinstance(root_pubkey, str)
                               and root_pubkey.startswith("ed25519:")) \
        else K.encode_public(root_pubkey)
    pinned = load_pinned_root(centre)
    if pinned is None:
        pin_root(centre, incoming)
        return (True, "pinned (first use)")
    if pinned == incoming:
        return (True, "matches pinned root")
    return (False, "pinned root mismatch — refusing (possible key substitution)")


__all__ = [
    "Verdict", "SIGNED_CARD_VERSION", "DEFAULT_TTL_DAYS", "CRL_MAX_AGE_DAYS",
    "issue_pi_card", "issue_member_card",
    "issue_project_lead_card", "issue_project_card_by_lead",
    "verify_pi_card", "verify_member_card",
    "verify_project_lead_card", "verify_project_card",
    "build_crl", "make_enrollment_request", "verify_enrollment",
    "pin_root", "load_pinned_root", "verify_or_pin_root", "trust_dir",
    "dumps", "loads",
]
