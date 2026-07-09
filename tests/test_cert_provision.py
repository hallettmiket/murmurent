"""
Tests for core/cert_provision.py — Slack channel provisioning for cert-projects
with membership synced to the certified members. Uses injectable creator/inviter
seams so no live Slack token is needed.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from wigamig.core import cert_projects as CP
from wigamig.core import cert_provision as CPROV
from wigamig.core import membership as MEM


@pytest.fixture(autouse=True)
def _lab_mgmt(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(tmp_path / "lab_mgmt"))


def _seed_project_with_members():
    # roster carries the emails the invite engine resolves against
    MEM.upsert_member("@allie", email="allie@uwo.ca", role="postdoc")
    MEM.upsert_member("@bob", email="bob@uwo.ca", role="student")
    MEM.upsert_member("@nomail", role="student")            # no email on record
    CP.upsert("rna_atlas", lab="lab_mh", member="@allie",
              cert={"fingerprint": "fa", "card_id": "cA"})
    CP.upsert("rna_atlas", lab="lab_mh", member="@bob",
              cert={"fingerprint": "fb", "card_id": "cB"})
    CP.upsert("rna_atlas", lab="lab_mh", member="@nomail",
              cert={"fingerprint": "fn", "card_id": "cN"})


def test_slack_channel_name_normalizes():
    assert CPROV.slack_channel_name("RNA_Atlas") == "rna_atlas"     # keeps _
    assert CPROV.slack_channel_name("a b/c") == "a-b-c"
    assert CPROV.slack_channel_name("--x--") == "x"


def test_member_email_map_from_roster():
    _seed_project_with_members()
    m = CPROV.member_email_map(["@allie", "bob", "nomail"])
    assert m == {"allie": "allie@uwo.ca", "bob": "bob@uwo.ca"}   # nomail excluded


def test_provision_creates_channel_and_stamps_id():
    _seed_project_with_members()
    seen = {}

    def creator(name):
        seen["name"] = name
        return SimpleNamespace(ok=True, channel_id="C123", error="", detail="")

    def inviter(channel_id, handles, *, member_email_map):
        seen["channel_id"] = channel_id
        seen["handles"] = list(handles)
        seen["emails"] = dict(member_email_map)
        return {"channel_id": channel_id, "invited": ["allie", "bob"],
                "already_in": [], "unresolved": [{"handle": "nomail",
                                                  "reason": "no email on record"}],
                "error": None}

    out = CPROV.provision_slack("rna_atlas", creator=creator, inviter=inviter)
    assert out["ok"] and out["created"] and out["channel_id"] == "C123"
    assert seen["name"] == "rna_atlas" and seen["channel_id"] == "C123"
    assert set(seen["handles"]) == {"allie", "bob", "nomail"}
    assert seen["emails"] == {"allie": "allie@uwo.ca", "bob": "bob@uwo.ca"}
    # the id is persisted on the record
    assert CP.get("rna_atlas").slack_channel_id == "C123"
    assert out["unresolved"][0]["handle"] == "nomail"


def test_provision_is_idempotent_no_recreate():
    _seed_project_with_members()
    CP.upsert("rna_atlas", lab="lab_mh", slack_channel_id="Cexisting")
    calls = {"create": 0}

    def creator(name):
        calls["create"] += 1
        return SimpleNamespace(ok=True, channel_id="CNEW")

    def inviter(channel_id, handles, *, member_email_map):
        return {"channel_id": channel_id, "invited": [], "already_in": handles,
                "unresolved": [], "error": None}

    out = CPROV.provision_slack("rna_atlas", creator=creator, inviter=inviter)
    assert calls["create"] == 0                       # existing channel reused
    assert out["created"] is False and out["channel_id"] == "Cexisting"


def test_provision_reports_missing_token_gracefully():
    _seed_project_with_members()

    def creator(name):
        return SimpleNamespace(ok=False, channel_id="", error="missing_token",
                               detail="no Slack token")

    out = CPROV.provision_slack("rna_atlas", creator=creator)
    assert out["ok"] is False and out["error"] == "missing_token"
    assert CP.get("rna_atlas").slack_channel_id == ""   # nothing stamped


def test_provision_unknown_project_raises():
    with pytest.raises(CPROV.CertProvisionError, match="no cert-project"):
        CPROV.provision_slack("ghost")
