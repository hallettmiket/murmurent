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


# ---- GitHub provisioning ----------------------------------------------------

def _seed_project_with_github():
    MEM.upsert_member("@allie", github="allie-gh", role="postdoc")
    MEM.upsert_member("@bob", github="bobgh", role="student")
    MEM.upsert_member("@nogh", role="student")               # no github login
    CP.upsert("rna_atlas", lab="lab_mh", member="@allie",
              cert={"fingerprint": "fa", "card_id": "cA"})
    CP.upsert("rna_atlas", lab="lab_mh", member="@bob",
              cert={"fingerprint": "fb", "card_id": "cB"})
    CP.upsert("rna_atlas", lab="lab_mh", member="@nogh",
              cert={"fingerprint": "fx", "card_id": "cX"})


def test_member_github_map_from_roster():
    _seed_project_with_github()
    assert CPROV.member_github_map(["@allie", "bob", "nogh"]) == {
        "allie": "allie-gh", "bob": "bobgh"}


def test_provision_github_creates_repo_and_adds_collaborators():
    _seed_project_with_github()
    made = {"collabs": []}

    def repo_creator(org, name):
        made["repo"] = f"{org}/{name}"
        return (True, "created")

    def collaborator(org, name, login):
        made["collabs"].append(login)
        return (True, "invited")

    out = CPROV.provision_github("rna_atlas", org="hallettmiket",
                                 repo_creator=repo_creator, collaborator=collaborator)
    assert out["ok"] and out["repo"] == "hallettmiket/rna_atlas"
    assert made["repo"] == "hallettmiket/rna_atlas"
    assert set(made["collabs"]) == {"allie-gh", "bobgh"}      # nogh skipped
    assert CP.get("rna_atlas").github_repo == "hallettmiket/rna_atlas"
    statuses = {c["handle"]: c["status"] for c in out["collaborators"]}
    assert statuses == {"allie": "ok", "bob": "ok", "nogh": "no_github"}


def test_provision_github_needs_an_org():
    _seed_project_with_github()
    out = CPROV.provision_github("rna_atlas", org="",
                                 repo_creator=lambda o, n: (True, "x"))
    # no org passed and no lab.md github_org → clean no_github_org report
    assert out["ok"] is False and out["error"] == "no_github_org"


def test_provision_github_repo_create_failure_is_clean():
    _seed_project_with_github()
    out = CPROV.provision_github("rna_atlas", org="hallettmiket",
                                 repo_creator=lambda o, n: (False, "gh CLI not installed"))
    assert out["ok"] is False and out["error"] == "repo_create_failed"
    assert CP.get("rna_atlas").github_repo == ""             # nothing stamped
