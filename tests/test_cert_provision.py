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
    MEM.upsert_member("@allie", email="allie@example.edu", role="postdoc")
    MEM.upsert_member("@bob", email="bob@example.edu", role="student")
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
    assert m == {"allie": "allie@example.edu", "bob": "bob@example.edu"}   # nomail excluded


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
    assert seen["emails"] == {"allie": "allie@example.edu", "bob": "bob@example.edu"}
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


# ---- teardown ---------------------------------------------------------------

def test_teardown_archives_channel_and_removes_collaborators():
    _seed_project_with_github()
    CP.upsert("rna_atlas", lab="lab_mh", slack_channel_id="C777",
              github_repo="hallettmiket/rna_atlas")
    done = {"removed": []}

    def archiver(channel_id):
        done["archived"] = channel_id
        return (True, "archived")

    def remover(org, name, login):
        done["removed"].append(f"{org}/{name}:{login}")
        return (True, "removed")

    out = CPROV.teardown("rna_atlas", channel_archiver=archiver, collab_remover=remover)
    assert done["archived"] == "C777"
    assert out["channel_archived"]["ok"] is True
    assert set(done["removed"]) == {"hallettmiket/rna_atlas:allie-gh",
                                    "hallettmiket/rna_atlas:bobgh"}   # nogh skipped
    assert {c["login"] for c in out["collaborators_removed"]} == {"allie-gh", "bobgh"}


def test_teardown_unprovisioned_is_noop():
    _seed_project_with_github()   # no slack_channel_id / github_repo set
    out = CPROV.teardown("rna_atlas",
                         channel_archiver=lambda c: (True, "x"),
                         collab_remover=lambda o, n, l: (True, "x"))
    assert out["channel_archived"] is None and out["collaborators_removed"] == []


# ---- reconcile --------------------------------------------------------------

def test_reconcile_slack_invites_missing_and_kicks_extras():
    _seed_project_with_members()          # certified: allie, bob, nomail
    CP.upsert("rna_atlas", lab="lab_mh", slack_channel_id="C1")
    acted = {"invited": None, "kicked": []}

    # channel currently holds allie (U1), a bot, and an interloper (Uextra)
    def ids_fetcher(channel_id):
        return {"U1", "Ubot", "Uextra"}

    # certified members resolve: allie→U1 (present), bob→U3 (missing), nomail→None
    def uid_resolver(handles, email_map):
        return {"allie": "U1", "bob": "U3", "nomail": None}

    def inviter(channel_id, handles, *, member_email_map):
        acted["invited"] = list(handles)
        return {"invited": handles, "already_in": [], "unresolved": [], "error": None}

    def kicker(channel_id, uid):
        acted["kicked"].append(uid)
        return (True, "kicked")

    out = CPROV.reconcile_slack("rna_atlas", ids_fetcher=ids_fetcher,
                                uid_resolver=uid_resolver, inviter=inviter,
                                kicker=kicker, bot_uid="Ubot")
    assert out["to_invite"] == ["bob"] and acted["invited"] == ["bob"]
    assert out["to_kick"] == ["Uextra"] and acted["kicked"] == ["Uextra"]  # bot kept
    assert out["unresolved"] == ["nomail"] and out["in_sync"] is False


def test_reconcile_slack_check_only_makes_no_changes():
    _seed_project_with_members()
    CP.upsert("rna_atlas", lab="lab_mh", slack_channel_id="C1")
    calls = {"kick": 0, "invite": 0}
    out = CPROV.reconcile_slack(
        "rna_atlas", apply=False,
        ids_fetcher=lambda c: {"Uextra"},
        uid_resolver=lambda h, e: {"allie": "U1", "bob": "U3", "nomail": "U4"},
        inviter=lambda *a, **k: calls.__setitem__("invite", calls["invite"] + 1),
        kicker=lambda *a, **k: calls.__setitem__("kick", calls["kick"] + 1),
        bot_uid=None)
    assert calls == {"kick": 0, "invite": 0}          # apply=False → no side effects
    assert set(out["to_invite"]) == {"allie", "bob", "nomail"}
    assert out["to_kick"] == ["Uextra"] and out["invited"] == [] and out["kicked"] == []


def test_reconcile_slack_not_provisioned():
    _seed_project_with_members()          # no slack_channel_id
    out = CPROV.reconcile_slack("rna_atlas")
    assert out["ok"] is False and out["error"] == "not_provisioned"


def test_reconcile_github_adds_and_removes():
    _seed_project_with_github()           # certified logins: allie-gh, bobgh (nogh none)
    CP.upsert("rna_atlas", lab="lab_mh", github_repo="hallettmiket/rna_atlas")
    acted = {"added": [], "removed": []}

    # repo currently has bobgh + a stale collaborator "ex-member" + the owner
    def fetcher(org, name):
        return {"bobgh", "ex-member", "the_pi"}

    def adder(org, name, login):
        acted["added"].append(login)
        return (True, "added")

    def remover(org, name, login):
        acted["removed"].append(login)
        return (True, "removed")

    out = CPROV.reconcile_github("rna_atlas", collaborators_fetcher=fetcher,
                                 adder=adder, remover=remover,
                                 owner_logins=["the_pi"])
    assert out["to_add"] == ["allie-gh"] and acted["added"] == ["allie-gh"]
    assert out["to_remove"] == ["ex-member"] and acted["removed"] == ["ex-member"]
    assert out["in_sync"] is False        # owner protected, not removed


def test_reconcile_github_not_provisioned():
    _seed_project_with_github()
    out = CPROV.reconcile_github("rna_atlas")
    assert out["ok"] is False and out["error"] == "not_provisioned"


# ---- workspace check --------------------------------------------------------

def test_workspace_check_splits_in_missing_and_no_email():
    _seed_project_with_members()          # allie+bob have emails, nomail doesn't

    # allie is in the workspace, bob is not
    def resolver(email):
        return "U_allie" if email == "allie@example.edu" else None

    out = CPROV.workspace_check("rna_atlas", slack_resolver=resolver)
    assert [r["handle"] for r in out["in_workspace"]] == ["allie"]
    assert [r["handle"] for r in out["missing"]] == ["bob"]
    assert out["no_email"] == ["nomail"]
    assert out["in_workspace"][0]["slack_uid"] == "U_allie"


def test_workspace_check_no_resolver_marks_all_missing():
    _seed_project_with_members()
    # a resolver that always fails (no token) → emailed members can't be confirmed
    out = CPROV.workspace_check("rna_atlas", slack_resolver=lambda e: None)
    assert {r["handle"] for r in out["missing"]} == {"allie", "bob"}
    assert out["in_workspace"] == [] and out["no_email"] == ["nomail"]


def test_workspace_check_unknown_project_raises():
    with pytest.raises(CPROV.CertProvisionError, match="no cert-project"):
        CPROV.workspace_check("ghost")
