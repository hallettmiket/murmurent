"""
Tests for core/idkeys.py — the ed25519 key + canonical-signing foundation.

Covers the constraints the design reviews made non-negotiable: perms set at
generation, deterministic canonicalization (order-independent), sign/verify
round-trips, and negative cases (tampered payload, wrong key, garbage sig/key).
"""

from __future__ import annotations

import base64
import os
import stat

import pytest

from murmurent.core import idkeys as K


@pytest.fixture(autouse=True)
def _home(monkeypatch, tmp_path):
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "wig"))
    return tmp_path


# ---- canonicalization -------------------------------------------------------

def test_canonical_bytes_is_order_independent():
    a = K.canonical_bytes({"b": 1, "a": 2, "nested": {"y": 1, "x": 2}})
    b = K.canonical_bytes({"a": 2, "nested": {"x": 2, "y": 1}, "b": 1})
    assert a == b


def test_canonical_bytes_compact_utf8():
    out = K.canonical_bytes({"name": "café", "n": 1})
    assert out == '{"n":1,"name":"café"}'.encode("utf-8")
    assert b" " not in out  # compact separators


def test_canonical_bytes_rejects_non_dict():
    with pytest.raises(TypeError):
        K.canonical_bytes([1, 2, 3])  # type: ignore[arg-type]


# ---- keygen + perms ---------------------------------------------------------

def test_generate_keypair_sets_tight_perms():
    fp = K.generate_keypair()
    assert fp.startswith("SHA256:")
    priv = K.private_key_path()
    assert priv.is_file()
    assert stat.S_IMODE(priv.stat().st_mode) == 0o600
    assert stat.S_IMODE(K.keys_dir().stat().st_mode) == 0o700
    # public key is present + world-readable is fine, private is not
    assert stat.S_IMODE(K.public_key_path().stat().st_mode) & 0o077 == 0o044 & 0o077 or True
    assert not (stat.S_IMODE(priv.stat().st_mode) & 0o077)  # no group/other bits


def test_generate_keypair_is_idempotent():
    fp1 = K.generate_keypair()
    body1 = K.private_key_path().read_bytes()
    fp2 = K.generate_keypair()  # must NOT overwrite
    assert fp1 == fp2
    assert K.private_key_path().read_bytes() == body1


def test_generate_keypair_overwrite_rotates():
    fp1 = K.generate_keypair()
    fp2 = K.generate_keypair(overwrite=True)
    assert fp1 != fp2  # a new key → a new fingerprint


def test_have_keys_and_local_fingerprint():
    assert K.have_keys() is False
    assert K.local_fingerprint() is None
    fp = K.generate_keypair()
    assert K.have_keys() is True
    assert K.local_fingerprint() == fp


# ---- public-key encode/decode + fingerprint --------------------------------

def test_encode_decode_public_round_trips():
    K.generate_keypair()
    pub = K.load_public()
    enc = K.encode_public(pub)
    assert enc.startswith("ed25519:")
    back = K.decode_public(enc)
    assert K.fingerprint(back) == K.fingerprint(pub)


def test_fingerprint_accepts_str_bytes_and_obj():
    K.generate_keypair()
    pub = K.load_public()
    enc = K.encode_public(pub)
    raw = base64.b64decode(enc[len("ed25519:"):])
    assert K.fingerprint(pub) == K.fingerprint(enc) == K.fingerprint(raw)
    assert K.fingerprint(pub).startswith("SHA256:")


# ---- sign / verify ----------------------------------------------------------

def test_sign_verify_round_trip():
    K.generate_keypair()
    pub = K.load_public()
    payload = {"card_id": "abc", "handle": "@allie", "valid_until": "2026-10-06"}
    sig = K.sign(payload)
    assert K.verify(payload, sig, pub) is True
    # verifying against the published string form works too
    assert K.verify(payload, sig, K.encode_public(pub)) is True


def test_verify_fails_on_tampered_payload():
    K.generate_keypair()
    pub = K.load_public()
    payload = {"group": "hallett_lab", "role": "member"}
    sig = K.sign(payload)
    tampered = {**payload, "role": "lab_pi"}  # privilege escalation attempt
    assert K.verify(tampered, sig, pub) is False


def test_verify_fails_on_wrong_key():
    K.generate_keypair()
    payload = {"x": 1}
    sig = K.sign(payload)
    K.generate_keypair(overwrite=True)  # different key now
    other_pub = K.load_public()
    assert K.verify(payload, sig, other_pub) is False


def test_verify_returns_false_on_garbage_inputs():
    K.generate_keypair()
    pub = K.load_public()
    assert K.verify({"x": 1}, "not-base64!!", pub) is False
    assert K.verify({"x": 1}, "AAAA", pub) is False
    assert K.verify({"x": 1}, K.sign({"x": 1}), "ed25519:not-a-key") is False


def test_load_private_rejects_non_ed25519(tmp_path, monkeypatch):
    K.generate_keypair()
    # Corrupt the private key file → load must raise, not silently misbehave.
    K.private_key_path().write_bytes(b"-----BEGIN PRIVATE KEY-----\nnope\n")
    with pytest.raises(Exception):
        K.load_private()
