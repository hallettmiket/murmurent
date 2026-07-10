"""
Tests for core/idcert.py — the root→PI→member certificate chain.

Beyond the happy path these encode the attack matrix the design reviews required:
forgery / tamper, wrong-signer, chain/kind confusion, expiry + not-yet-valid,
PI-not-valid-at-issue-time, fail-closed CRL (missing / stale / wrong-key /
revoked), trust-anchor pinning mismatch, downgrade, wrong-centre, and PoP.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from murmurent.core import idcert as C
from murmurent.core import idkeys as K


T0 = datetime(2026, 7, 8, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _home(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_HOME", str(tmp_path / "wig"))


@pytest.fixture
def world():
    """A centre root, a PI, a member — three independent keypairs, plus a fresh
    empty CRL and the pinned root pubkey."""
    root = Ed25519PrivateKey.generate()
    pi = Ed25519PrivateKey.generate()
    member = Ed25519PrivateKey.generate()
    root_pub = K.encode_public(root.public_key())
    crl = C.build_crl(centre="qa", revoked=[], root_priv=root, serial=1, issued_at=T0)
    pi_card = C.issue_pi_card(handle="@yxia266", pi_pubkey=pi.public_key(),
                              centre="qa", root_priv=root, issuer_handle="@tbrowne5",
                              issued_at=T0)
    member_card = C.issue_member_card(handle="@allie",
                                      member_pubkey=member.public_key(),
                                      group="yxia_lab", centre="qa", pi_priv=pi,
                                      pi_handle="@yxia266", issued_at=T0)
    return dict(root=root, pi=pi, member=member, root_pub=root_pub, crl=crl,
                pi_card=pi_card, member_card=member_card)


def _v(world, **kw):
    """verify_member_card with the world's defaults, at T0 unless overridden."""
    kw.setdefault("root_pub", world["root_pub"])
    kw.setdefault("now", T0)
    kw.setdefault("crl", world["crl"])
    kw.setdefault("centre", "qa")
    return C.verify_member_card(world["member_card"], world["pi_card"], **kw)


# ---- happy path -------------------------------------------------------------

def test_full_chain_verifies(world):
    v = _v(world)
    assert v.ok and v.reason == "ok"
    assert v.handle == "@allie" and v.group == "yxia_lab" and v.kind == "member"
    assert v.fingerprint == K.fingerprint(world["member"].public_key())


def test_pi_card_verifies_against_root(world):
    v = C.verify_pi_card(world["pi_card"], root_pub=world["root_pub"], now=T0,
                         crl=world["crl"], centre="qa")
    assert v.ok and v.handle == "@yxia266" and v.kind == "pi"


def test_card_json_round_trips_and_still_verifies(world):
    reparsed = C.loads(C.dumps(world["member_card"]))
    v = C.verify_member_card(reparsed, world["pi_card"], root_pub=world["root_pub"],
                             now=T0, crl=world["crl"], centre="qa")
    assert v.ok


# ---- forgery / tamper -------------------------------------------------------

def test_tampered_member_payload_rejected(world):
    world["member_card"]["payload"]["group"] = "some_other_lab"
    assert not _v(world)  # signature no longer matches


def test_privilege_escalation_via_roles_rejected(world):
    world["member_card"]["payload"]["roles"] = [{"kind": "lab_pi"}]
    assert _v(world).reason == "bad PI signature"


def test_attacker_signed_member_card_rejected(world):
    """An attacker with their OWN key mints a member card; the legit PI card is
    presented. Verification uses the PI key from the PI card → bad signature."""
    attacker = Ed25519PrivateKey.generate()
    forged = C.issue_member_card(handle="@allie",
                                 member_pubkey=world["member"].public_key(),
                                 group="yxia_lab", centre="qa", pi_priv=attacker,
                                 pi_handle="@yxia266", issued_at=T0)
    v = C.verify_member_card(forged, world["pi_card"], root_pub=world["root_pub"],
                             now=T0, crl=world["crl"], centre="qa")
    # issuer fingerprint won't match the PI card's fingerprint
    assert not v.ok and v.reason in ("issuer/PI mismatch", "bad PI signature")


def test_forged_pi_card_not_signed_by_root_rejected(world):
    impostor_root = Ed25519PrivateKey.generate()
    fake_pi = C.issue_pi_card(handle="@yxia266", pi_pubkey=world["pi"].public_key(),
                              centre="qa", root_priv=impostor_root, issued_at=T0)
    v = C.verify_pi_card(fake_pi, root_pub=world["root_pub"], now=T0,
                         crl=world["crl"], centre="qa")
    assert not v.ok and v.reason == "bad root signature"


# ---- chain / kind confusion -------------------------------------------------

def test_member_card_cannot_pose_as_pi_card(world):
    v = C.verify_pi_card(world["member_card"], root_pub=world["root_pub"], now=T0,
                         crl=world["crl"], centre="qa")
    assert not v.ok and v.reason == "not a PI card"


def test_pi_card_cannot_pose_as_member_leaf(world):
    # feed the PI card where a member card is expected → kind check refuses
    v = C.verify_member_card(world["pi_card"], world["pi_card"],
                             root_pub=world["root_pub"], now=T0, crl=world["crl"],
                             centre="qa")
    assert not v.ok and v.reason == "not a member card"


def test_member_card_from_a_different_pi_rejected(world):
    """A member card issued by PI-A presented with PI-B's card must fail."""
    other_pi = Ed25519PrivateKey.generate()
    other_pi_card = C.issue_pi_card(handle="@other", pi_pubkey=other_pi.public_key(),
                                    centre="qa", root_priv=world["root"], issued_at=T0)
    v = C.verify_member_card(world["member_card"], other_pi_card,
                             root_pub=world["root_pub"], now=T0, crl=world["crl"],
                             centre="qa")
    assert not v.ok and v.reason == "issuer/PI mismatch"


# ---- temporal ---------------------------------------------------------------

def test_expired_member_card_rejected(world):
    # short-lived member card, PI card still valid → only the member card expires
    short = C.issue_member_card(handle="@allie",
                               member_pubkey=world["member"].public_key(),
                               group="yxia_lab", centre="qa", pi_priv=world["pi"],
                               pi_handle="@yxia266", issued_at=T0, ttl_days=1)
    fresh = C.build_crl(centre="qa", revoked=[], root_priv=world["root"],
                        serial=5, issued_at=T0 + timedelta(days=2))
    v = C.verify_member_card(short, world["pi_card"], root_pub=world["root_pub"],
                             now=T0 + timedelta(days=2), crl=fresh, centre="qa")
    assert v.reason == "expired"


def test_not_yet_valid_rejected(world):
    # member card issued in the future, PI card already valid
    future = C.issue_member_card(handle="@allie",
                                member_pubkey=world["member"].public_key(),
                                group="yxia_lab", centre="qa", pi_priv=world["pi"],
                                pi_handle="@yxia266",
                                issued_at=T0 + timedelta(days=10))
    v = C.verify_member_card(future, world["pi_card"], root_pub=world["root_pub"],
                             now=T0 + timedelta(days=1), crl=world["crl"],
                             centre="qa")
    assert v.reason == "not yet valid"


def test_expired_pi_card_fails_the_chain(world):
    short_pi = C.issue_pi_card(handle="@yxia266", pi_pubkey=world["pi"].public_key(),
                               centre="qa", root_priv=world["root"], issued_at=T0,
                               ttl_days=1)
    v = C.verify_member_card(world["member_card"], short_pi,
                             root_pub=world["root_pub"], now=T0 + timedelta(days=2),
                             crl=world["crl"], centre="qa")
    assert not v.ok and v.reason.startswith("PI card invalid")


def test_pi_card_must_be_valid_at_member_issue_time(world):
    """PI card valid now, but the member card claims to have been issued before
    the PI card existed → chain must reject."""
    late_pi = C.issue_pi_card(handle="@yxia266", pi_pubkey=world["pi"].public_key(),
                              centre="qa", root_priv=world["root"],
                              issued_at=T0 + timedelta(days=10))
    fresh = C.build_crl(centre="qa", revoked=[], root_priv=world["root"],
                        serial=6, issued_at=T0 + timedelta(days=11))
    # member card issued at T0, i.e. before the PI card's not_before
    v = C.verify_member_card(world["member_card"], late_pi,
                             root_pub=world["root_pub"],
                             now=T0 + timedelta(days=11), crl=fresh, centre="qa")
    assert not v.ok and v.reason == "PI card not valid at member card's issue time"


# ---- CRL (fail-closed) ------------------------------------------------------

def test_missing_crl_fails_closed(world):
    assert _v(world, crl=None).reason == "no CRL supplied (fail-closed)"


def test_stale_crl_fails_closed(world):
    old_crl = C.build_crl(centre="qa", revoked=[], root_priv=world["root"],
                          serial=1, issued_at=T0 - timedelta(days=30))
    assert _v(world, crl=old_crl).reason == "stale CRL (fail-closed)"


def test_crl_signed_by_wrong_key_fails_closed(world):
    evil = Ed25519PrivateKey.generate()
    bad_crl = C.build_crl(centre="qa", revoked=[], root_priv=evil, serial=99,
                          issued_at=T0)
    assert _v(world, crl=bad_crl).reason == "unverifiable CRL (bad root signature)"


def test_revoked_by_card_id(world):
    cid = world["member_card"]["payload"]["card_id"]
    crl = C.build_crl(centre="qa", revoked=[cid], root_priv=world["root"],
                      serial=2, issued_at=T0)
    assert _v(world, crl=crl).reason == "revoked"


def test_revoked_by_fingerprint(world):
    fpr = K.fingerprint(world["member"].public_key())
    crl = C.build_crl(centre="qa", revoked=[fpr], root_priv=world["root"],
                      serial=3, issued_at=T0)
    assert _v(world, crl=crl).reason == "revoked"


def test_revoked_pi_kills_whole_group(world):
    """Revoking the PI's card invalidates every member card under it."""
    pi_cid = world["pi_card"]["payload"]["card_id"]
    crl = C.build_crl(centre="qa", revoked=[pi_cid], root_priv=world["root"],
                      serial=4, issued_at=T0)
    v = _v(world, crl=crl)
    assert not v.ok and v.reason.startswith("PI card invalid")


# ---- downgrade / centre -----------------------------------------------------

def test_version_downgrade_rejected(world):
    world["member_card"]["payload"]["version"] = 0
    assert _v(world).reason in ("unsupported card version", "bad PI signature")


def test_wrong_centre_rejected(world):
    assert not _v(world, centre="different-centre").ok


# ---- trust-anchor pinning ---------------------------------------------------

def test_pin_root_tofu_then_match(world):
    ok, _ = C.verify_or_pin_root("qa", world["root_pub"])
    assert ok  # first use → pins
    ok2, _ = C.verify_or_pin_root("qa", world["root_pub"])
    assert ok2  # same key matches


def test_pin_root_mismatch_fails_closed(world):
    C.verify_or_pin_root("qa", world["root_pub"])
    other = K.encode_public(Ed25519PrivateKey.generate().public_key())
    ok, reason = C.verify_or_pin_root("qa", other)
    assert not ok and "mismatch" in reason


# ---- proof-of-possession ----------------------------------------------------

def test_enrollment_pop_round_trip(world):
    req = C.make_enrollment_request("@allie", priv=world["member"], nonce="n-123",
                                    centre="qa", group="yxia_lab")
    fpr = K.fingerprint(world["member"].public_key())
    assert C.verify_enrollment(req, expected_fingerprint=fpr, expected_nonce="n-123")


def test_enrollment_wrong_nonce_rejected(world):
    req = C.make_enrollment_request("@allie", priv=world["member"], nonce="n-123")
    assert not C.verify_enrollment(req, expected_nonce="different")


def test_enrollment_fingerprint_binding(world):
    """A request signed by key A cannot pass as proof for key B's fingerprint."""
    req = C.make_enrollment_request("@allie", priv=world["member"], nonce="n-1")
    other_fpr = K.fingerprint(Ed25519PrivateKey.generate().public_key())
    assert not C.verify_enrollment(req, expected_fingerprint=other_fpr)


def test_enrollment_tampered_payload_rejected(world):
    req = C.make_enrollment_request("@allie", priv=world["member"], nonce="n-1")
    req["payload"]["handle"] = "@someone_else"
    assert not C.verify_enrollment(req)
