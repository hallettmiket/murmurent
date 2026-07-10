"""
Tests for member removal — the inverse of onboarding.

Covers registrar.read_group_member / remove_group_member (roster) and
centre_provision.deprovision_member_from_group (Slack kick + GitHub collaborator
removal + roster mark), all through injectable seams so no live calls happen.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from murmurent.core import centre_init as CI
from murmurent.core import centre_provision as CP
from murmurent.core import registrar as R


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_LAB_INFO_ROOT", str(tmp_path / "lab_info"))
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("WIGAMIG_USER", "tbrowne")
    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(R, "REGISTRAR_SENTINEL", fake_home / ".wigamig" / "registrar")
    CI.init_centre(name="C", institution="U", founding_mayor="@tbrowne",
                   slack_workspace="T0X", github_org="centre-x", write_sentinel=False)
    R.create_lab(name="mh", display_name="MH", pi_handle="@the_pi",
                 pi_email="pi@x.edu")
    # A member with an email + a resolvable GitHub login.
    lab_mgmt = Path(R.read_registry().labs[0].lab_mgmt_path).expanduser()
    (lab_mgmt / "members").mkdir(parents=True, exist_ok=True)
    (lab_mgmt / "members" / "twu.md").write_text(
        "---\nhandle: '@twu'\nfull_name: Tim Wu\nrole: member\nstatus: active\n"
        "lab: mh\nemail: twu@x.edu\ngit_logins:\n  github: twu-gh\n---\n\n# @twu\n",
        encoding="utf-8")
    R.set_group_slack_channel("mh", "C0CHAN")
    R.update_group_profile("mh", {"github": "org/mh_repo"})
    return tmp_path


# ---- registrar roster ops ---------------------------------------------

def test_read_group_member(world):
    info = R.read_group_member("mh", "@twu")
    assert info["handle"] == "twu"
    assert info["email"] == "twu@x.edu"
    assert info["github"] == "twu-gh"
    assert info["status"] == "active"


def test_read_group_member_absent(world):
    assert R.read_group_member("mh", "nobody") is None


def test_remove_group_member_marks_removed(world):
    assert R.remove_group_member("mh", "twu") is True
    info = R.read_group_member("mh", "twu")
    assert info["status"] == "removed"          # file kept, status flipped


def test_remove_group_member_delete(world):
    assert R.remove_group_member("mh", "twu", delete=True) is True
    assert R.read_group_member("mh", "twu") is None   # file gone


# ---- full deprovision orchestration -----------------------------------

def test_deprovision_kicks_removes_and_marks(world):
    calls = {"kick": [], "gh": []}
    probes = CP.deprovision_member_from_group(
        "mh", handle="@twu",
        kicker=lambda cid, em: calls["kick"].append((cid, em)) or (True, "kicked"),
        collaborator_remover=lambda r, l: calls["gh"].append((r, l)) or (True, "removed"))
    by = {p.name: p for p in probes}
    # Slack kick targeted the group's channel + the member's email.
    assert calls["kick"] == [("C0CHAN", "twu@x.edu")]
    assert by["slack-channel"].status == "ok"
    # GitHub collaborator removed by login on the group's repo.
    assert calls["gh"] == [("org/mh_repo", "twu-gh")]
    assert by["github-repo"].status == "ok"
    # Roster marked removed.
    assert by["roster"].status == "ok"
    assert R.read_group_member("mh", "twu")["status"] == "removed"


def test_deprovision_unknown_member_is_noop(world):
    probes = CP.deprovision_member_from_group(
        "mh", handle="ghost",
        kicker=lambda *a: (True, ""), collaborator_remover=lambda *a: (True, ""))
    assert len(probes) == 1
    assert probes[0].name == "member" and probes[0].status == "warn"


def test_deprovision_warns_without_channel_or_repo(world):
    # Clear the channel id + repo so those steps have nothing to act on.
    R.set_group_slack_channel("mh", "")
    R.update_group_profile("mh", {"github": ""})
    probes = CP.deprovision_member_from_group(
        "mh", handle="twu",
        kicker=lambda *a: (True, ""), collaborator_remover=lambda *a: (True, ""))
    by = {p.name: p for p in probes}
    assert by["slack-channel"].status == "warn"
    assert by["github-repo"].status == "warn"
    assert by["roster"].status == "ok"          # roster removal still happens
