"""Tests for core.member_audit — classifying each roster member's identity
certificate standing from the PI's own local records (roster + issuance ledger
+ CRL), plus the /api/members/audit dashboard endpoints.

The whole point of this feature: the dashboard's old free-form "add member"
created roster entries with no certificate. The audit finds them.
"""

from __future__ import annotations

import datetime as _dt

import pytest

from murmurent.core import member_audit as MA
from murmurent.core import membership as M
from murmurent.core import revocation as R

CENTRE = "testcentre"


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("MURMURENT_USER", "the_pi")
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "dot"))  # ledger + CRL land here
    (tmp_path / "lab-mgmt" / "members").mkdir(parents=True)
    (tmp_path / "lab-mgmt" / "lab.md").write_text(
        "---\nlab: hallett\nname: 'Hallett Lab'\npi: '@the_pi'\n---\n", encoding="utf-8")
    M.add(handle="the_pi", full_name="Mike Hallett", role="pi")
    return tmp_path


def _statuses(**kw):
    return {s.handle: s.cert for s in MA.audit(centre=CENTRE, **kw)}


def test_uncertified_member_is_flagged(world):
    # A member added with no card (the legacy free-form add) → uncertified.
    M.add(handle="jdoe", full_name="Jane Doe", role="postdoc")
    st = _statuses()
    assert st["jdoe"] == MA.UNCERTIFIED
    # The PI always reads valid (they hold a PI card, can't be removed).
    assert st["the_pi"] == MA.VALID
    flagged = MA.findings(centre=CENTRE)
    assert [f.handle for f in flagged] == ["jdoe"]
    assert "no identity certificate" in flagged[0].detail


def test_carded_member_is_valid(world):
    # Simulate issuance: stamp the roster + record the ledger entry.
    M.upsert_member("asmith", full_name="Al Smith", card_fingerprint="fp_a", card_id="cid_a")
    R.record_issued(CENTRE, handle="asmith", card_id="cid_a", fingerprint="fp_a",
                    kind="member", issued_at="2026-07-01T00:00:00",
                    valid_until="2099-01-01T00:00:00")
    assert _statuses()["asmith"] == MA.VALID
    assert [f.handle for f in MA.findings(centre=CENTRE)] == []


def test_revoked_card_is_flagged(world):
    M.upsert_member("bob", full_name="Bob", card_fingerprint="fp_b", card_id="cid_b")
    R.record_issued(CENTRE, handle="bob", card_id="cid_b", fingerprint="fp_b",
                    kind="member", valid_until="2099-01-01T00:00:00")
    R._add(CENTRE, ["cid_b"])                     # put the card on the revocation set
    st = MA.audit(centre=CENTRE)
    bob = next(s for s in st if s.handle == "bob")
    assert bob.cert == MA.REVOKED


def test_expired_card_is_flagged(world):
    M.upsert_member("carol", full_name="Carol", card_fingerprint="fp_c", card_id="cid_c")
    R.record_issued(CENTRE, handle="carol", card_id="cid_c", fingerprint="fp_c",
                    kind="member", valid_until="2000-01-01T00:00:00")  # long past
    st = {s.handle: s.cert for s in MA.audit(centre=CENTRE)}
    assert st["carol"] == MA.EXPIRED


def test_fingerprint_mismatch_is_flagged(world):
    # Roster stamped with a different fingerprint than the PI actually issued.
    M.upsert_member("dana", full_name="Dana", card_fingerprint="fp_TAMPERED", card_id="cid_d")
    R.record_issued(CENTRE, handle="dana", card_id="cid_d", fingerprint="fp_real",
                    kind="member", valid_until="2099-01-01T00:00:00")
    st = {s.handle: s.cert for s in MA.audit(centre=CENTRE)}
    assert st["dana"] == MA.MISMATCH


def test_status_map_and_inactive_default(world):
    M.add(handle="ghost", full_name="Ghost", role="staff")
    M.set_status("ghost", M.INACTIVE)
    # include_inactive defaults False → inactive member not audited.
    assert "ghost" not in _statuses()
    assert "ghost" in _statuses(include_inactive=True)


# ---------------------------------------------------------------------------
# Endpoints — the cert-gated add + audit, end to end
# ---------------------------------------------------------------------------


def _client():
    from fastapi.testclient import TestClient
    from murmurent.dashboard.server import create_app
    return TestClient(create_app())


@pytest.fixture
def pi_world(monkeypatch, tmp_path):
    """A standalone PI machine with a real identity key + self-issued PI card,
    so the issue-card endpoint can actually sign a member card."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: F401
    from murmurent.core import idkeys as K
    from murmurent.core import issuance as ISS
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(tmp_path / "li"))
    monkeypatch.setenv("MURMURENT_USER", "the_pi")
    (tmp_path / "lab-mgmt" / "members").mkdir(parents=True)
    (tmp_path / "lab-mgmt" / "lab.md").write_text(
        "---\nlab: lab_mh\nname: lab_mh\npi: '@the_pi'\n---\n", encoding="utf-8")
    K.generate_keypair()
    ISS.self_issue_pi_card("@the_pi", "lab_mh")   # PI card + registers lab + PI member
    return tmp_path


def test_issue_card_endpoint_certifies_and_audit_sees_valid(pi_world):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from murmurent.core import idcert as C

    allie = Ed25519PrivateKey.generate()
    enrollment = C.make_enrollment_request("@allie", priv=allie, nonce="a1",
                                           group="lab_mh", email="allie@x.edu")
    client = _client()

    # non-PI is refused
    assert client.post("/api/members/issue-card?user=someone",
                       json={"enrollment": enrollment, "group": "lab_mh", "dm": False}
                       ).status_code == 403

    res = client.post("/api/members/issue-card?user=the_pi",
                      json={"enrollment": enrollment, "group": "lab_mh", "dm": False})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["handle"] == "allie" and body["group"] == "lab_mh"
    assert body["fingerprint"] and body["bundle"]["member_card"]["payload"]["kind"] == "member"

    # The roster now carries a real card for allie (not a bare name).
    rec = M.get("allie")
    assert rec.card_fingerprint and rec.card_id

    # And the audit endpoint reports her as valid, 0 flagged.
    audit = client.get("/api/members/audit?user=the_pi").json()
    by = {m["handle"]: m["cert"] for m in audit["members"]}
    assert by["allie"] == "valid"
    assert audit["counts"]["flagged"] == 0


def test_issue_card_rejects_bad_proof(pi_world):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from murmurent.core import idcert as C

    allie = Ed25519PrivateKey.generate()
    enrollment = C.make_enrollment_request("@allie", priv=allie, nonce="a1", group="lab_mh")
    enrollment["signature"] = "tampered"          # break the proof-of-possession
    client = _client()
    res = client.post("/api/members/issue-card?user=the_pi",
                      json={"enrollment": enrollment, "group": "lab_mh", "dm": False})
    assert res.status_code == 422
    assert "proof-of-possession" in res.json()["detail"].lower()
    # nobody got added
    with pytest.raises(M.MemberNotFound):
        M.get("allie")
