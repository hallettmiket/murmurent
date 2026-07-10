"""
Purpose: the CENTRE ROOT signing key — the certificate-authority root of a
murmurent centre, held ONLY by the mayor. Distinct from a member's per-machine key
(``core/idkeys.py`` machine key): the root signs PI cards (``core/idcert.py``)
and self-certifies the centre's published public keys.

Blast radius: whoever holds this key **is** the centre. It is generated once at
centre bootstrap, used rarely (PI-card issuance + the CRL), and MUST be backed up
offline, encrypted, off the laptop. It must NEVER be wired into an automated / CI
signing path. See ``docs/centre_root_key.md`` — the rotation runbook — which by
policy exists *before* the key does.

The centre publishes TWO public keys in the ``murmurent_public`` installations
table (Phase 6): the **age** recipient (joiners encrypt requests to it) and the
**signing** recipient (anyone verifies a card chains to this centre with it). The
installation entry is **self-signed by the root** so a substituted pubkey can't
produce a valid signature — but self-signature only proves internal consistency;
the real trust anchor is the locally *pinned* root fingerprint (TOFU), confirmed
out-of-band on rotation. See ``idcert.verify_or_pin_root``.
"""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from . import idcert as _cert
from . import idkeys as K

ROOT_KEY_NAME = "centre_root_ed25519"


def _home() -> Path:
    return Path(os.environ.get("WIGAMIG_HOME", str(Path.home() / ".wigamig")))


def root_key_path() -> Path:
    return _home() / "keys" / ROOT_KEY_NAME


# ---------------------------------------------------------------------------
# Key lifecycle
# ---------------------------------------------------------------------------

def have_root_key() -> bool:
    return K.have_keys(root_key_path())


def generate_root_key(*, overwrite: bool = False) -> str:
    """Mint the centre root key (idempotent unless ``overwrite``). Returns its
    fingerprint. ``overwrite=True`` is a ROTATION — every card signed by the old
    key is stale and must be re-issued (see the runbook)."""
    return K.generate_keypair(overwrite=overwrite, path=root_key_path())


def load_root_private() -> Ed25519PrivateKey:
    return K.load_private(root_key_path())


def root_public() -> str | None:
    """The published ``ed25519:<base64>`` signing recipient, or None."""
    if not have_root_key():
        return None
    return K.encode_public(K.load_public(root_key_path()))


def root_fingerprint() -> str | None:
    return K.local_fingerprint(root_key_path())


def bootstrap_root(unique_name: str) -> dict:
    """Generate the centre root key if absent and pin its own fingerprint as this
    machine's trust anchor for ``unique_name``. Idempotent. Returns
    ``{fingerprint, public}``.

    The mayor pins their OWN root so their machine verifies cards through the
    same anchor everyone else will; members pin the same key on first import."""
    fp = generate_root_key()
    pub = root_public()
    if unique_name and pub:
        _cert.pin_root(unique_name, pub)
    return {"fingerprint": fp, "public": pub}


# ---------------------------------------------------------------------------
# Self-signed installation entry (what gets published to murmurent_public)
# ---------------------------------------------------------------------------

def build_installation_entry(*, unique_name: str, institution: str, name: str,
                             join_email: str = "", age_recipient: str = "") -> dict:
    """The centre's public directory row, **self-signed by the root key**.

    Defeats the "swap just the pubkey, keep the old signature" attack: a changed
    ``signing_pubkey`` invalidates the self-signature. It does NOT prove this is
    the authentic centre (an attacker could swap pubkey AND re-sign with their
    own key) — that protection is the out-of-band pinned fingerprint. Requires
    the root key to exist."""
    root = load_root_private()
    signing_pub = K.encode_public(root.public_key())
    payload = {
        "unique_name": unique_name,
        "institution": institution,
        "name": name,
        "join_email": join_email,
        "age_pubkey": age_recipient,          # encrypt join requests to this
        "signing_pubkey": signing_pub,        # verify card chains with this
        "root_fingerprint": K.fingerprint(root.public_key()),
    }
    return {"payload": payload, "signature": K.sign(payload, root)}


def verify_installation_entry(entry: dict) -> bool:
    """True iff the entry is self-signed by the ``signing_pubkey`` it advertises
    and that pubkey matches the stated ``root_fingerprint``. Any failure → False."""
    if not isinstance(entry, dict):
        return False
    p, sig = entry.get("payload"), entry.get("signature")
    if not isinstance(p, dict) or not sig:
        return False
    pub = p.get("signing_pubkey")
    if not pub or K.fingerprint(pub) != p.get("root_fingerprint"):
        return False
    return K.verify(p, sig, pub)


__all__ = [
    "ROOT_KEY_NAME", "root_key_path",
    "have_root_key", "generate_root_key", "load_root_private",
    "root_public", "root_fingerprint", "bootstrap_root",
    "build_installation_entry", "verify_installation_entry",
]
