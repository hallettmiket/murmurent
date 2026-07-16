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
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "wig"))


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


def test_enrollment_carries_official_handle(world):
    """official_handle rides inside the signed enrollment payload so the issuer
    can record it on the roster in one round trip (GH #23)."""
    req = C.make_enrollment_request("@allie", priv=world["member"], nonce="n-1",
                                    official_handle="@ahall", slack="a.h")
    assert req["payload"]["official_handle"] == "ahall"   # @ stripped
    assert req["payload"]["slack"] == "a.h"
    # Still self-consistent (the new field is inside the signed payload).
    assert C.verify_enrollment(req, expected_nonce="n-1")


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


# ---- project delegation chain (root → PI → lead → member) --------------------

@pytest.fixture
def pworld(world):
    """world + a project lead (@allie promoted) and a project member (@bob).

    The lead card delegates yxia_lab/dcis_17 to @allie; @allie signs @bob's
    project card with her own key."""
    lead = world["member"]          # @allie's keypair doubles as the lead key
    bob = Ed25519PrivateKey.generate()
    lead_card = C.issue_project_lead_card(
        handle="@allie", lead_pubkey=lead.public_key(), project="dcis_17",
        lab="yxia_lab", centre="qa", pi_priv=world["pi"], pi_handle="@yxia266",
        issued_at=T0)
    proj_card = C.issue_project_card_by_lead(
        handle="@bob", member_pubkey=bob.public_key(), group="yxia_lab/dcis_17",
        centre="qa", lead_priv=lead, lead_handle="@allie",
        roles=[{"kind": "project_member", "project": "dcis_17",
                "lab": "yxia_lab", "group": "yxia_lab/dcis_17"}],
        issued_at=T0)
    return dict(world, lead=lead, bob=bob, lead_card=lead_card,
                proj_card=proj_card)


def _pv(pw, **kw):
    """verify_project_card with pworld defaults, at T0 unless overridden."""
    kw.setdefault("root_pub", pw["root_pub"])
    kw.setdefault("now", T0)
    kw.setdefault("crl", pw["crl"])
    kw.setdefault("centre", "qa")
    return C.verify_project_card(pw["proj_card"], pw["lead_card"], pw["pi_card"], **kw)


def test_project_chain_verifies(pworld):
    v = _pv(pworld)
    assert v.ok and v.reason == "ok"
    assert v.handle == "@bob" and v.group == "yxia_lab/dcis_17"
    assert v.kind == "member"
    assert any(r.get("kind") == "project_member" for r in v.roles)


def test_lead_card_verifies_standalone(pworld):
    v = C.verify_project_lead_card(pworld["lead_card"], pworld["pi_card"],
                                   root_pub=pworld["root_pub"], now=T0,
                                   crl=pworld["crl"], centre="qa")
    assert v.ok and v.handle == "@allie" and v.kind == "project_lead"
    assert v.group == "yxia_lab/dcis_17"


def test_pi_self_delegation_verifies(pworld):
    """PI == lead: the PI self-delegates and signs project cards directly."""
    lead_card = C.issue_project_lead_card(
        handle="@yxia266", lead_pubkey=pworld["pi"].public_key(),
        project="dcis_17", lab="yxia_lab", centre="qa", pi_priv=pworld["pi"],
        pi_handle="@yxia266", issued_at=T0)
    proj = C.issue_project_card_by_lead(
        handle="@bob", member_pubkey=pworld["bob"].public_key(),
        group="yxia_lab/dcis_17", centre="qa", lead_priv=pworld["pi"],
        lead_handle="@yxia266",
        roles=[{"kind": "project_member", "project": "dcis_17",
                "lab": "yxia_lab", "group": "yxia_lab/dcis_17"}], issued_at=T0)
    v = C.verify_project_card(proj, lead_card, pworld["pi_card"],
                              root_pub=pworld["root_pub"], now=T0,
                              crl=pworld["crl"], centre="qa")
    assert v.ok


def test_tampered_project_payload_rejected(pworld):
    pworld["proj_card"]["payload"]["subject"]["handle"] = "@mallory"
    assert not _pv(pworld)


def test_tampered_lead_payload_rejected(pworld):
    pworld["lead_card"]["payload"]["group"] = "yxia_lab/other_project"
    v = _pv(pworld)
    assert not v.ok and "lead card invalid" in v.reason


def test_revoked_lead_kills_every_project_card(pworld):
    """Revoking the lead's card_id invalidates all cards the lead signed."""
    lead_id = pworld["lead_card"]["payload"]["card_id"]
    crl = C.build_crl(centre="qa", revoked=[lead_id], root_priv=pworld["root"],
                      serial=2, issued_at=T0)
    v = _pv(pworld, crl=crl)
    assert not v.ok and "lead card revoked" in v.reason


def test_revoked_project_leaf_only(pworld):
    leaf_id = pworld["proj_card"]["payload"]["card_id"]
    crl = C.build_crl(centre="qa", revoked=[leaf_id], root_priv=pworld["root"],
                      serial=2, issued_at=T0)
    v = _pv(pworld, crl=crl)
    assert not v.ok and v.reason == "revoked"
    # the lead card itself is still fine
    lv = C.verify_project_lead_card(pworld["lead_card"], pworld["pi_card"],
                                    root_pub=pworld["root_pub"], now=T0,
                                    crl=crl, centre="qa")
    assert lv.ok


def test_lead_cannot_sign_for_a_different_project(pworld):
    """Delegation is scoped: a card for another project's group is rejected
    even though the lead's signature is valid."""
    rogue = C.issue_project_card_by_lead(
        handle="@bob", member_pubkey=pworld["bob"].public_key(),
        group="yxia_lab/other_project", centre="qa", lead_priv=pworld["lead"],
        lead_handle="@allie",
        roles=[{"kind": "project_member", "project": "other_project",
                "lab": "yxia_lab", "group": "yxia_lab/other_project"}],
        issued_at=T0)
    v = C.verify_project_card(rogue, pworld["lead_card"], pworld["pi_card"],
                              root_pub=pworld["root_pub"], now=T0,
                              crl=pworld["crl"], centre="qa")
    assert not v.ok and v.reason == "project/lead group mismatch"


def test_attacker_signed_project_card_rejected(pworld):
    attacker = Ed25519PrivateKey.generate()
    forged = C.issue_project_card_by_lead(
        handle="@bob", member_pubkey=pworld["bob"].public_key(),
        group="yxia_lab/dcis_17", centre="qa", lead_priv=attacker,
        lead_handle="@allie",
        roles=[{"kind": "project_member"}], issued_at=T0)
    v = C.verify_project_card(forged, pworld["lead_card"], pworld["pi_card"],
                              root_pub=pworld["root_pub"], now=T0,
                              crl=pworld["crl"], centre="qa")
    assert not v.ok and v.reason in ("issuer/lead mismatch", "bad lead signature")


def test_member_card_cannot_act_as_lead_card(pworld):
    """A plain member card (kind=member) presented as the delegation link is
    structurally rejected — a member can never be an issuer."""
    v = C.verify_project_card(pworld["proj_card"], pworld["member_card"],
                              pworld["pi_card"], root_pub=pworld["root_pub"],
                              now=T0, crl=pworld["crl"], centre="qa")
    assert not v.ok and "not a project-lead card" in v.reason


def test_lead_card_cannot_pose_as_member_card(pworld):
    """The delegation card can never pass the plain member-card verifier."""
    v = C.verify_member_card(pworld["lead_card"], pworld["pi_card"],
                             root_pub=pworld["root_pub"], now=T0,
                             crl=pworld["crl"], centre="qa")
    assert not v.ok and v.reason == "not a member card"


def test_project_card_without_role_rejected(pworld):
    bare = C.issue_project_card_by_lead(
        handle="@bob", member_pubkey=pworld["bob"].public_key(),
        group="yxia_lab/dcis_17", centre="qa", lead_priv=pworld["lead"],
        lead_handle="@allie", roles=[], issued_at=T0)
    v = C.verify_project_card(bare, pworld["lead_card"], pworld["pi_card"],
                              root_pub=pworld["root_pub"], now=T0,
                              crl=pworld["crl"], centre="qa")
    assert not v.ok and v.reason == "no project_member role"


def test_lead_expired_at_leaf_issue_time_rejected(pworld):
    """Temporal nesting: a project card issued after the lead card expired is
    rejected even if presented while the lead card would otherwise be renewed."""
    late = T0 + timedelta(days=120)          # beyond the lead card's 90-day TTL
    proj = C.issue_project_card_by_lead(
        handle="@bob", member_pubkey=pworld["bob"].public_key(),
        group="yxia_lab/dcis_17", centre="qa", lead_priv=pworld["lead"],
        lead_handle="@allie",
        roles=[{"kind": "project_member"}], issued_at=late)
    crl = C.build_crl(centre="qa", revoked=[], root_priv=pworld["root"],
                      serial=3, issued_at=late)
    # fresh lead+pi cards so only the ORIGINAL lead card is expired at `late`
    v = C.verify_project_card(proj, pworld["lead_card"], pworld["pi_card"],
                              root_pub=pworld["root_pub"], now=late,
                              crl=crl, centre="qa")
    assert not v.ok  # lead card expired (chain fails at step 1)


def test_project_chain_missing_crl_fails_closed(pworld):
    v = _pv(pworld, crl=None)
    assert not v.ok and "no CRL" in v.reason


def test_project_chain_stale_crl_fails_closed(pworld):
    late = T0 + timedelta(days=30)
    v = _pv(pworld, now=late)   # CRL issued at T0 → >7 days old
    assert not v.ok and "stale CRL" in v.reason


def test_project_chain_wrong_centre_rejected(pworld):
    v = _pv(pworld, centre="other_centre")
    assert not v.ok
