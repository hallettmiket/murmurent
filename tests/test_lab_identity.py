"""
Tests for core/lab_identity.py — unifying a member's handle / email / Slack uid /
GitHub login. Slack resolution is injected, so no token is needed.
"""

from __future__ import annotations

import pytest

from murmurent.core import lab_identity as LI


@pytest.fixture
def lab(monkeypatch, tmp_path):
    root = tmp_path / "lab-mgmt"
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(root))
    (root / "members").mkdir(parents=True)
    (root / "lab.md").write_text("---\nlab: lab_mh\npi: '@mhallet'\n---\n", encoding="utf-8")

    def add(handle, *, email="", github="", status="active"):
        (root / "members" / f"{handle}.md").write_text(
            f"---\nhandle: '@{handle}'\nfull_name: {handle.title()}\nrole: postdoc\n"
            f"status: {status}\nemail: {email}\ngithub: {github}\n---\n", encoding="utf-8")
    return add


def _resolver(mapping):
    return lambda email: mapping.get(email)


def test_member_identity_unifies_all_ids(lab):
    lab("m1", email="m1@x.edu", github="m1gh")
    ident = LI.member_identity("m1", slack_resolver=_resolver({"m1@x.edu": "U111"}))
    assert ident == {"handle": "m1", "email": "m1@x.edu", "github": "m1gh",
                     "slack_uid": "U111", "in_workspace": True}


def test_member_identity_not_in_workspace(lab):
    lab("m2", email="m2@x.edu", github="m2gh")
    ident = LI.member_identity("m2", slack_resolver=_resolver({}))  # lookup misses
    assert ident["slack_uid"] is None and ident["in_workspace"] is False
    assert ident["email"] == "m2@x.edu" and ident["github"] == "m2gh"


def test_member_identity_skips_slack_lookup_without_email(lab):
    lab("m3", email="", github="m3gh")
    calls = []
    ident = LI.member_identity("m3", slack_resolver=lambda e: calls.append(e))
    assert ident["email"] == "" and ident["slack_uid"] is None
    assert calls == []                      # resolver not called when there's no email


def test_member_identity_none_for_unknown(lab):
    assert LI.member_identity("ghost", slack_resolver=_resolver({})) is None


def test_iter_lab_identities_active_only_by_default(lab):
    lab("m1", email="m1@x.edu", github="m1gh")
    lab("m2", email="m2@x.edu", github="m2gh")
    lab("old", email="old@x.edu", status="inactive")
    r = _resolver({"m1@x.edu": "U1", "m2@x.edu": "U2"})
    active = {i["handle"] for i in LI.iter_lab_identities(slack_resolver=r)}
    assert active == {"m1", "m2"}           # inactive excluded
    allh = {i["handle"] for i in LI.iter_lab_identities(slack_resolver=r, active_only=False)}
    assert "old" in allh
