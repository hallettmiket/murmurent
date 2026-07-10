"""
Purpose: ed25519 key management + canonical signing primitives — the crypto
foundation under the murmurent identity-card certificate chain (``core/idcert.py``).

Everything a signed identity card needs at the byte level lives here: generate /
load a keypair, compute a stable public-key *fingerprint* (a member's unique ID),
and sign / verify an EXACT canonical serialization of a payload.

Design constraints baked in (from the adversary + security_guard design reviews):

  - **Fixed algorithm.** ed25519, full stop. There is no in-band algorithm field
    and callers never negotiate one. Verifiers ignore anything a card claims about
    its own algorithm — this closes the ``alg:none`` / algorithm-confusion class.
  - **Sign exact canonical bytes.** :func:`canonical_bytes` is a frozen,
    deterministic serialization (sorted-key, compact, UTF-8 JSON). Signer and
    verifier both go through it, so there is no re-serialization ambiguity and no
    unsigned-field wiggle room — the caller decides exactly which fields are in
    the signed payload and only those bytes are signed.
  - **Perms at generation time.** The private key is written under
    ``~/.wigamig/keys/`` with ``0700`` dir / ``0600`` file perms enforced *as it
    is created* (``os.open`` with mode, then an explicit ``chmod``), never by
    downstream convention, and never into a repo working tree.
  - **No private material leaves this module** in a card, log, or wire message —
    only public keys (:func:`encode_public`) and signatures travel.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

_KEY_NAME = "id_ed25519"
_PUB_PREFIX = "ed25519:"


# ---------------------------------------------------------------------------
# Paths (honour WIGAMIG_HOME so tests + non-default installs are isolated)
# ---------------------------------------------------------------------------

def _home() -> Path:
    return Path(os.environ.get("WIGAMIG_HOME", str(Path.home() / ".wigamig")))


def keys_dir() -> Path:
    return _home() / "keys"


def private_key_path() -> Path:
    return keys_dir() / _KEY_NAME


def public_key_path() -> Path:
    return keys_dir() / f"{_KEY_NAME}.pub"


def _pub_for(priv_path: Path) -> Path:
    """The ``.pub`` companion of a private-key path."""
    return Path(str(priv_path) + ".pub")


# ---------------------------------------------------------------------------
# Canonicalization — the single definition of "the bytes we sign"
# ---------------------------------------------------------------------------

def canonical_bytes(payload: dict) -> bytes:
    """Deterministic serialization of ``payload`` → the exact bytes to sign.

    Sorted keys + compact separators + UTF-8. Because signer and verifier both
    route through this, key ordering / whitespace can never desynchronize them,
    and only the fields the caller put in ``payload`` are covered (no trailing
    unsigned data). Reject non-dict input loudly rather than signing garbage.
    """
    if not isinstance(payload, dict):
        raise TypeError("canonical_bytes expects a dict payload")
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


# ---------------------------------------------------------------------------
# Public-key encoding + fingerprint
# ---------------------------------------------------------------------------

def _raw_public(pub: Ed25519PublicKey) -> bytes:
    return pub.public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )


def encode_public(pub: Ed25519PublicKey | bytes) -> str:
    """Public key → a compact, publishable ``ed25519:<base64>`` string.

    This is the ONLY representation that ever leaves the machine (cards, the
    installations table). Private keys are never encoded for transport."""
    raw = bytes(pub) if isinstance(pub, (bytes, bytearray)) else _raw_public(pub)
    return _PUB_PREFIX + base64.b64encode(raw).decode("ascii")


def decode_public(text: str) -> Ed25519PublicKey:
    """Parse an ``ed25519:<base64>`` (or bare base64) public key string."""
    s = text.strip()
    if s.startswith(_PUB_PREFIX):
        s = s[len(_PUB_PREFIX):]
    raw = base64.b64decode(s)
    return Ed25519PublicKey.from_public_bytes(raw)


def fingerprint(pub: Ed25519PublicKey | bytes | str) -> str:
    """Stable SHA-256 fingerprint of a public key — a member's unique ID.

    Format mirrors OpenSSH: ``SHA256:<unpadded-base64>``. Accepts a key object,
    raw bytes, or an ``ed25519:<base64>`` string so callers can fingerprint a
    published key without first decoding it into an object.
    """
    if isinstance(pub, str):
        raw = _raw_public(decode_public(pub))
    elif isinstance(pub, (bytes, bytearray)):
        raw = bytes(pub)
    else:
        raw = _raw_public(pub)
    digest = hashlib.sha256(raw).digest()
    return "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")


# ---------------------------------------------------------------------------
# Keypair generation + loading
# ---------------------------------------------------------------------------

def have_keys(path: Path | None = None) -> bool:
    return (path or private_key_path()).is_file()


def generate_keypair(*, overwrite: bool = False, path: Path | None = None) -> str:
    """Create an ed25519 keypair (default: this machine's key under
    ``~/.wigamig/keys/``; ``path`` selects a different key, e.g. the centre root).

    Idempotent: if a private key already exists at ``path`` and ``overwrite`` is
    false, the existing key is kept and its fingerprint returned (so a "first run
    after clone" trigger can call this unconditionally). Returns the fingerprint.

    Perms are set as the files are created — dir ``0700``, private key ``0600``,
    public key ``0644`` — not left to a later chmod that a racing reader could
    beat.
    """
    priv_p = path or private_key_path()
    d = priv_p.parent
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)

    if priv_p.is_file() and not overwrite:
        return fingerprint(load_public(priv_p))

    priv = Ed25519PrivateKey.generate()
    pem = priv.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    # Create the private key file 0600 atomically (mode applies at open()).
    fd = os.open(str(priv_p), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, pem)
    finally:
        os.close(fd)
    os.chmod(priv_p, 0o600)  # belt-and-suspenders vs a permissive umask

    pub = priv.public_key()
    pub_p = _pub_for(priv_p)
    pub_p.write_text(encode_public(pub) + "\n", encoding="utf-8")
    os.chmod(pub_p, 0o644)
    return fingerprint(pub)


def load_private(path: Path | None = None) -> Ed25519PrivateKey:
    data = (path or private_key_path()).read_bytes()
    key = serialization.load_pem_private_key(data, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("not an ed25519 private key")
    return key


def load_public(path: Path | None = None) -> Ed25519PublicKey:
    """The public key for ``path`` — from the ``.pub`` file, else derived."""
    priv_p = path or private_key_path()
    pub_p = _pub_for(priv_p)
    if pub_p.is_file():
        return decode_public(pub_p.read_text(encoding="utf-8"))
    return load_private(priv_p).public_key()


def local_fingerprint(path: Path | None = None) -> str | None:
    """Fingerprint of the key at ``path`` (default: this machine's), or None if
    no keypair exists there yet."""
    if not have_keys(path):
        return None
    return fingerprint(load_public(path))


# ---------------------------------------------------------------------------
# Sign / verify
# ---------------------------------------------------------------------------

def sign(payload: dict, priv: Ed25519PrivateKey | None = None) -> str:
    """Sign the canonical bytes of ``payload``; return base64 signature.

    Uses this machine's private key unless one is passed (the mayor/PI signing
    with a specific loaded key)."""
    priv = priv or load_private()
    sig = priv.sign(canonical_bytes(payload))
    return base64.b64encode(sig).decode("ascii")


def verify(payload: dict, signature: str, pub: Ed25519PublicKey | str) -> bool:
    """True iff ``signature`` is a valid ed25519 sig over ``payload``'s canonical
    bytes under ``pub``. Fixed algorithm — the caller supplies the trusted key
    (from the chain), never the card. Any failure → False, never an exception."""
    if isinstance(pub, str):
        try:
            pub = decode_public(pub)
        except Exception:  # noqa: BLE001 — malformed key is just "invalid"
            return False
    try:
        pub.verify(base64.b64decode(signature), canonical_bytes(payload))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


__all__ = [
    "canonical_bytes",
    "encode_public",
    "decode_public",
    "fingerprint",
    "have_keys",
    "generate_keypair",
    "load_private",
    "load_public",
    "local_fingerprint",
    "sign",
    "verify",
    "keys_dir",
    "private_key_path",
    "public_key_path",
]
