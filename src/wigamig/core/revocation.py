"""
Purpose: the centre REVOCATION list (CRL) — the mayor-side store that makes
"revoke a card" real, since cards have a long (90-day) TTL. The CRL is signed by
the **centre root key** and lists revoked card-ids / fingerprints; verifiers check
it fail-closed (``idcert.verify_*`` with ``require_crl=True``).

Trust model (Phase 5): the CRL is a centre-wide artifact anchored to the root, so
only the mayor (root-key holder) publishes it. Removing a member pulls their live
access via Slack/GitHub/registry ACLs *immediately* (that is the real
enforcement); adding their card to the CRL is defense-in-depth and is actioned by
the mayor. Distributing the signed CRL to members' machines is Phase 6; until
then, a member's dashboard enforces card **expiry + tamper** but not remote
revocation.

State on disk (under ``~/.wigamig/revocation/``):
  - ``<centre>.state.json``   — ``{serial, revoked: [...]}`` (the unsigned set)
  - ``<centre>.crl.json``     — the last root-signed CRL (published / importable)
  - ``<centre>.issued.json``  — issuance ledger ``{handle: {card_id, fingerprint,
    kind}}`` so a removal can find a card to revoke by handle
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from . import centre_root as _cr
from . import idcert as _cert


class RevocationError(RuntimeError):
    """A revocation operation could not be completed."""


def _home() -> Path:
    return Path(os.environ.get("WIGAMIG_HOME", str(Path.home() / ".wigamig")))


def _dir() -> Path:
    return _home() / "revocation"


def _safe(name: str) -> str:
    return "".join(c if (c.isalnum() or c in "-_") else "_" for c in str(name or ""))


def _norm(handle: str) -> str:
    return str(handle or "").lstrip("@").strip().lower()


def _state_path(centre: str) -> Path:
    return _dir() / f"{_safe(centre)}.state.json"


def _signed_path(centre: str) -> Path:
    return _dir() / f"{_safe(centre)}.crl.json"


def _ledger_path(centre: str) -> Path:
    return _dir() / f"{_safe(centre)}.issued.json"


def _load(p: Path, default):
    if not p.is_file():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _save(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Issuance ledger (so a removal can revoke by handle)
# ---------------------------------------------------------------------------

def record_issued(centre: str, *, handle: str, card_id: str,
                  fingerprint: str, kind: str) -> None:
    """Record an issued card so it can later be revoked by handle. Best-effort;
    called from the issuer's machine at issuance time."""
    led = _load(_ledger_path(centre), {})
    led[_norm(handle)] = {"card_id": card_id, "fingerprint": fingerprint, "kind": kind}
    _save(_ledger_path(centre), led)


def lookup_issued(centre: str, handle: str) -> dict | None:
    return _load(_ledger_path(centre), {}).get(_norm(handle))


# ---------------------------------------------------------------------------
# Revoke + publish (root-key holder only)
# ---------------------------------------------------------------------------

def revoked_ids(centre: str) -> list[str]:
    return list(_load(_state_path(centre), {"serial": 0, "revoked": []}).get("revoked", []))


def _add(centre: str, ids) -> dict:
    st = _load(_state_path(centre), {"serial": 0, "revoked": []})
    cur = set(st.get("revoked", []))
    cur.update(i for i in ids if i)
    st["revoked"] = sorted(cur)
    st["serial"] = int(st.get("serial", 0)) + 1
    _save(_state_path(centre), st)
    return st


def build_fresh_crl(centre: str) -> dict:
    """Root-sign the current revoked set with a fresh ``issued_at`` (so the CRL
    passes the verifier's freshness check). Requires the centre root key."""
    if not _cr.have_root_key():
        raise RevocationError("no centre root key on this machine")
    st = _load(_state_path(centre), {"serial": 0, "revoked": []})
    return _cert.build_crl(centre=centre, revoked=st.get("revoked", []),
                           root_priv=_cr.load_root_private(),
                           serial=int(st.get("serial", 0)))


def publish(centre: str) -> dict:
    """Build + persist a fresh root-signed CRL. Returns it."""
    crl = build_fresh_crl(centre)
    _save(_signed_path(centre), crl)
    return crl


def revoke(centre: str, *, card_id: str | None = None,
           fingerprint: str | None = None) -> dict:
    """Add a card-id and/or fingerprint to the CRL, bump the serial, republish.
    Requires the centre root key (mayor's machine)."""
    if not _cr.have_root_key():
        raise RevocationError(
            "no centre root key; revocation must run on the mayor's machine")
    ids = [i for i in (card_id, fingerprint) if i]
    if not ids:
        raise RevocationError("nothing to revoke (need card_id or fingerprint)")
    _add(centre, ids)
    return publish(centre)


def revoke_member(centre: str, handle: str) -> dict:
    """Revoke a member's card. Reads the fingerprint/id from the **roster** (the
    source of truth) first, then falls back to this machine's issuance ledger."""
    rec = None
    try:
        from . import membership as _mem
        p = _mem.member_path(handle)
        if p.is_file():
            m = _mem.parse_member(p)
            if m.card_fingerprint or m.card_id:
                rec = {"card_id": m.card_id, "fingerprint": m.card_fingerprint}
    except Exception:  # noqa: BLE001
        pass
    if not rec:
        rec = lookup_issued(centre, handle)          # ledger fallback
    if not rec:
        raise RevocationError(
            f"no issued card on record for @{_norm(handle)} — revoke on the "
            "machine that issued it, or pass --fingerprint")
    return revoke(centre, card_id=rec.get("card_id") or None,
                  fingerprint=rec.get("fingerprint") or None)


# ---------------------------------------------------------------------------
# The CRL to hand a verifier
# ---------------------------------------------------------------------------

def current_crl(centre: str) -> dict | None:
    """The CRL a verifier should use: freshly root-signed if we hold the root
    key; otherwise the last imported/distributed signed CRL (may be None)."""
    if _cr.have_root_key():
        try:
            return build_fresh_crl(centre)
        except RevocationError:
            return None
    return _load(_signed_path(centre), None)


def import_distributed_crl(centre: str, crl) -> None:
    """Member side: store a signed CRL fetched from the centre so the local
    dashboard can enforce revocation."""
    _save(_signed_path(centre), crl if isinstance(crl, dict) else json.loads(crl))


__all__ = [
    "RevocationError", "record_issued", "lookup_issued", "revoked_ids",
    "revoke", "revoke_member", "publish", "build_fresh_crl", "current_crl",
    "import_distributed_crl",
]
