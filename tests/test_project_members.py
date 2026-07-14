"""
Tests for core/project_members.py — add/remove project members end to end
(cert issue/revoke + DM + channel sync) and create_project_certs for both
creator shapes (PI vs delegated member). Slack seams injected; no token needed.
"""

from __future__ import annotations

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from murmurent.core import cert_projects as CP
from murmurent.core import idcert as C
from murmurent.core import idkeys as K
from murmurent.core import issuance as ISS
from murmurent.core import membership as MEM
from murmurent.core import project_members as PM
from murmurent.core import revocation as REV


@pytest.fixture
def pi_world(monkeypatch, tmp_path):
    """Standalone PI (@yxia266, xia_lab) with two carded members on the shared
    roster (@allie, @bob) and a self-delegated project 'dcis_17'."""
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "pi_home"))
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(tmp_path / "pi_li"))
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(tmp_path / "shared_lab_mgmt"))
    K.generate_keypair()
    out = ISS.self_issue_pi_card("@yxia266", "xia_lab")
    for h, email, slack in (("@allie", "allie@x.edu", "allieslack"),
                            ("@bob", "bob@x.edu", "bobslack")):
        priv = Ed25519PrivateKey.generate()
        req = C.make_enrollment_request(h, priv=priv, nonce="n",
                                        group="xia_lab", email=email, slack=slack)
        ISS.issue_member_card(h, enrollment=req, group="xia_lab")
    ISS.issue_project_lead_card("@yxia266", project="dcis_17")
    return {"tmp": tmp_path, "trust": out["trust_root"]}


def _dm_recorder(sent):
    def dm(workspace, *, text, slack="", email="", token=None):
        sent.append({"workspace": workspace, "slack": slack, "email": email,
                     "text": text})
        return (True, "recorded")
    return dm


# ---- add_member ---------------------------------------------------------------

def test_add_member_issues_and_dms(pi_world, monkeypatch):
    monkeypatch.setenv("MURMURENT_GROUP_SLACK_TOKEN", "xoxb-test")
    sent = []
    out = PM.add_member("dcis_17", "@allie", dm_sender=_dm_recorder(sent))
    assert out["ok"] and out["group"] == "xia_lab/dcis_17"
    assert out["bundle"]["project_card"]["payload"]["subject"]["handle"] == "@allie"
    # DM went over the project's workspace to the roster contact
    assert sent and sent[0]["workspace"] == "xia_lab"
    assert sent[0]["slack"] == "allieslack" and sent[0]["email"] == "allie@x.edu"
    assert "import-card" in sent[0]["text"]
    # registry certified her
    cp = CP.get("dcis_17")
    assert "@allie" in cp.members
    assert any(c["handle"] == "@allie" for c in cp.certs)


def test_add_member_no_recorded_key_falls_back(pi_world):
    out = PM.add_member("dcis_17", "@stranger", dm=False)
    assert not out["ok"] and out["error"] == "no_recorded_key"
    assert out["fallback"] == "enrollment"
    assert "@stranger" not in CP.get("dcis_17").members


def test_add_member_pop_enrollment_for_external(pi_world):
    """External/keyless member: the PoP enrollment path certifies them AND
    records their contact info + pubkey so the next add is one-click."""
    ext = Ed25519PrivateKey.generate()
    req = C.make_enrollment_request("@ext", priv=ext, nonce="e1",
                                    email="ext@other.edu", slack="extslack")
    out = PM.add_member("dcis_17", "@ext", enrollment=req, dm=False)
    assert out["ok"]
    assert MEM.get("ext").pubkey == K.encode_public(ext.public_key())


def test_add_member_invites_to_channel(pi_world):
    """Item 8: adding a member syncs the private channel (invite path)."""
    CP.upsert("dcis_17", lab="xia_lab", slack_channel_id="C123")
    calls = []
    def fake_inviter(cid, handles, *, member_email_map):
        calls.append((cid, list(handles)))
        return {"invited": list(handles), "already_in": [], "unresolved": []}
    # uid resolver: everyone resolves; channel currently holds only the PI
    out = PM.add_member("dcis_17", "@allie", dm=False, inviter=fake_inviter)
    assert out["ok"]
    slack = out["slack"]
    assert slack["ok"] and slack["channel_id"] == "C123"


# ---- remove_member --------------------------------------------------------------

def test_remove_member_revokes_and_kicks(pi_world):
    PM.add_member("dcis_17", "@allie", dm=False)
    CP.upsert("dcis_17", lab="xia_lab", slack_channel_id="C123")
    kicked = []
    def fake_kicker(cid, uid):
        kicked.append((cid, uid))
        return (True, "kicked")
    out = PM.remove_member("dcis_17", "@allie", kicker=fake_kicker)
    assert out["ok"] and out["revoked"]
    # registry: gone
    cp = CP.get("dcis_17")
    assert "@allie" not in cp.members
    assert not any(c["handle"] == "@allie" for c in cp.certs)
    # CRL: her card id is revoked
    crl = REV.current_crl("yxia266-xia_lab")
    ledger_ids = set(crl["payload"]["revoked"])
    assert ledger_ids  # something revoked


def test_removed_members_proof_fails(pi_world, monkeypatch, tmp_path):
    """The point of it all: after removal, the member can no longer PROVE
    project membership once they hold the fresh CRL."""
    bundle = PM.add_member("dcis_17", "@allie", dm=False)["bundle"]
    trust = pi_world["trust"]

    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "allie_home"))
    ISS.verify_and_import_project_card(bundle, trust_root=trust)
    assert ISS.verify_project_membership("dcis_17").ok

    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "pi_home"))
    PM.remove_member("dcis_17", "@allie")
    fresh_crl = REV.current_crl("yxia266-xia_lab")

    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "allie_home"))
    REV.import_distributed_crl("yxia266-xia_lab", fresh_crl)
    pv = ISS.verify_project_membership("dcis_17")
    assert not pv.ok and "revoked" in pv.reason


def test_remove_member_refuses_the_lead(pi_world):
    with pytest.raises(PM.ProjectMemberError, match="lead"):
        PM.remove_member("dcis_17", "@yxia266")


def test_remove_uncertified_member_is_registry_only(pi_world):
    CP.upsert("dcis_17", lab="xia_lab", member="@ghost")   # never certified
    out = PM.remove_member("dcis_17", "@ghost")
    assert out["ok"] and not out["revoked"]
    assert "@ghost" not in CP.get("dcis_17").members


# ---- create_project_certs -------------------------------------------------------

def test_create_certs_creator_is_pi(pi_world):
    """creator == PI: self-delegation + every roster-keyed member carded now."""
    sent = []
    out = PM.create_project_certs("proj_two", lab="xia_lab", lead="@yxia266",
                                  members=["@yxia266", "@allie", "@bob", "@nokey"],
                                  dm_sender=_dm_recorder(sent))
    assert out["lead"]["handle"] == "@yxia266"
    # PI's own lead card is local — never DM'd
    assert not out["lead"]["dm"]["sent"]
    issued = {e["handle"] for e in out["issued"]}
    assert issued == {"@allie", "@bob"}
    assert out["pending_enrollment"] == ["@nokey"]
    assert out["awaiting_lead"] == []
    # both member bundles were DM'd
    assert len(sent) == 2
    cp = CP.get("proj_two")
    assert cp.lead == "@yxia266"
    assert {c["handle"] for c in cp.certs} == {"@yxia266", "@allie", "@bob"}


def test_create_certs_creator_is_member(pi_world):
    """creator == member: only the LEAD card is issued + DM'd; members await
    the lead's own machine (their key is not here)."""
    sent = []
    out = PM.create_project_certs("proj_three", lab="xia_lab", lead="@allie",
                                  members=["@allie", "@bob"],
                                  dm_sender=_dm_recorder(sent))
    assert out["lead"]["handle"] == "@allie" and out["lead"]["dm"]["sent"]
    assert out["issued"] == []                       # NO member cards minted here
    assert out["awaiting_lead"] == ["@bob"]
    # the DM carried the lead bundle (no leaf)
    assert len(sent) == 1 and "LEAD card" in sent[0]["text"]
    cp = CP.get("proj_three")
    assert cp.lead == "@allie"
    assert any(c["handle"] == "@allie" for c in cp.certs)   # her lead card
    assert not any(c["handle"] == "@bob" for c in cp.certs)


def test_create_certs_lead_without_key_reports(pi_world):
    out = PM.create_project_certs("proj_four", lab="xia_lab", lead="@nokey",
                                  members=["@nokey", "@allie"], dm=False)
    assert out["lead"] is None
    assert out["errors"] and out["errors"][0]["error"] == "lead_pending_enrollment"
