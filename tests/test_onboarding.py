"""
Tests for core.onboarding — the PI onboarding tracker + run_onboard_check.

Covers: the join detection state machine (waiting -> joined -> onboarded), the
persisted marker (no double-reporting), and that every Slack touch goes through
injectable seams so the token-less suite never hits the wire.
"""

from __future__ import annotations

import pytest

from murmurent.core import centre_init as CI
from murmurent.core import join_requests as JR
from murmurent.core import onboarding as OB
from murmurent.core import registrar as R


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(tmp_path / "lab_info"))
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "wigamig_home"))
    monkeypatch.setenv("MURMURENT_USER", "tbrowne")
    (tmp_path / "lab-mgmt" / "members").mkdir(parents=True)
    (tmp_path / "lab-mgmt" / "lab.md").write_text(
        "---\nlab: hallett\npi: '@the_pi'\n---\n", encoding="utf-8")
    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(R, "REGISTRAR_SENTINEL", fake_home / ".murmurent" / "registrar")
    CI.init_centre(name="Serenity", institution="U", founding_mayor="@tbrowne",
                   slack_workspace="T0X", github_org="centre-x",
                   data_server="lab-server", write_sentinel=False)
    return tmp_path


def _make_lab(name="mh", pi="@the_pi", email="pi@x.edu"):
    """File + approve a lab so it lands in the registry with the PI's email on
    the member record (token-less → Slack/GitHub provisioning no-ops)."""
    req = JR.file_request(kind="lab", requester_email=email,
                          proposed_name=name, proposed_pi=pi,
                          institution_affiliation="Western")
    JR.approve(req_id=req.id, actor="@tbrowne")


# ---- state marker ------------------------------------------------------

def test_marker_roundtrip(world):
    assert OB.is_pi_onboarded("mh") is False
    OB.mark_pi_onboarded("mh", when="2026-07-06T00:00:00+00:00")
    assert OB.is_pi_onboarded("mh") is True


# ---- run_onboard_check with injected seams -----------------------------

def test_waiting_when_pi_not_in_workspace(world):
    _make_lab()
    res = OB.run_onboard_check("mh",
                               workspace_checker=lambda e: False,
                               channel_adder=lambda g, h, e: True,
                               dm_sender=lambda g, e: True)
    assert len(res) == 1
    r = res[0]
    assert r.joined is False
    assert "waiting" in r.note
    assert OB.is_pi_onboarded("mh") is False   # not marked while waiting


def test_lookup_unavailable_is_distinct_from_waiting(world):
    _make_lab()
    res = OB.run_onboard_check("mh", workspace_checker=lambda e: None,
                               channel_adder=lambda g, h, e: True,
                               dm_sender=lambda g, e: True)
    assert res[0].joined is False
    assert "unavailable" in res[0].note
    assert OB.is_pi_onboarded("mh") is False


def test_onboards_when_pi_present(world):
    _make_lab()
    calls = {"channel": [], "dm": []}
    res = OB.run_onboard_check(
        "mh",
        workspace_checker=lambda e: True,
        channel_adder=lambda g, h, e: calls["channel"].append((g, h, e)) or True,
        dm_sender=lambda g, e: calls["dm"].append((g, e)) or True)
    r = res[0]
    assert r.joined and r.added_to_channel and r.dmed
    assert calls["channel"] == [("mh", "@the_pi", "pi@x.edu")]
    assert calls["dm"] == [("mh", "pi@x.edu")]
    assert OB.is_pi_onboarded("mh") is True          # marked so it won't repeat


def test_second_run_skips_already_onboarded(world):
    _make_lab()
    seams = dict(workspace_checker=lambda e: True,
                 channel_adder=lambda g, h, e: True,
                 dm_sender=lambda g, e: True)
    OB.run_onboard_check("mh", **seams)
    dm_calls = []
    res = OB.run_onboard_check("mh", workspace_checker=lambda e: True,
                               channel_adder=lambda g, h, e: True,
                               dm_sender=lambda g, e: dm_calls.append(1) or True)
    assert res[0].note == "already onboarded"
    assert dm_calls == []                            # no second DM


def test_all_groups_when_no_arg(world):
    _make_lab(name="mh", pi="@the_pi", email="a@x.edu")
    _make_lab(name="core_seq", pi="@leader", email="b@x.edu")
    res = OB.run_onboard_check(workspace_checker=lambda e: False,
                               channel_adder=lambda g, h, e: True,
                               dm_sender=lambda g, e: True)
    assert {r.group for r in res} == {"mh", "core_seq"}


def test_no_email_reported(world, monkeypatch):
    _make_lab()
    monkeypatch.setattr(OB, "_pi_email", lambda *a, **k: "")
    res = OB.run_onboard_check("mh", workspace_checker=lambda e: True,
                               channel_adder=lambda g, h, e: True,
                               dm_sender=lambda g, e: True)
    assert res[0].joined is False
    assert "no PI email" in res[0].note
