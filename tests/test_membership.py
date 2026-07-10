"""Tests for the Phase-13 group-membership roster.

Covers:
  - core.membership: add / set_status / is_active / iter_members
  - PI cannot deactivate themselves
  - HTTP endpoints: POST /api/members + /api/members/{handle}/{action}
  - Active-check blocks inactive actors at action endpoints
"""

from __future__ import annotations

import datetime as _dt

import pytest

from murmurent.commands import project_cmd
from murmurent.core import membership as M


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setenv("MURMURENT_PROJECTS_ROOT", str(tmp_path / "repos"))
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("MURMURENT_LAB_VM_ROOT", str(tmp_path / "lab_vm"))
    monkeypatch.setenv("MURMURENT_USER", "mhallet")
    # Redirect decommission reports into tmp_path so set_status(INACTIVE)
    # doesn't pollute the real ~/.murmurent/decommissions/.
    monkeypatch.setenv("MURMURENT_DECOMMISSION_DIR", str(tmp_path / "decommissions"))
    (tmp_path / "lab-mgmt" / "members").mkdir(parents=True)
    (tmp_path / "lab-mgmt" / "projects").mkdir(parents=True)
    (tmp_path / "lab-mgmt" / "lab.md").write_text(
        "---\nlab: hallett\nname: 'Hallett Lab'\npi: '@mhallet'\n---\n",
        encoding="utf-8",
    )
    # Seed the PI member file (otherwise CannotDeactivatePI doesn't trigger
    # since there's nothing to deactivate).
    M.add(handle="mhallet", full_name="Mike Hallett", role="pi")
    return tmp_path


# ---------------------------------------------------------------------------
# core.membership
# ---------------------------------------------------------------------------


def test_add_creates_active_member(world):
    rec = M.add(handle="bob", full_name="Bob Yamazaki", role="postdoc")
    assert rec.status == M.ACTIVE
    assert rec.handle == "bob"
    assert rec.path.is_file()


def test_add_strips_at_sign(world):
    rec = M.add(handle="@cassie", full_name="Cassie Okello", role="student")
    assert rec.handle == "cassie"


def test_add_refuses_existing_handle(world):
    with pytest.raises(M.MemberAlreadyExists):
        M.add(handle="mhallet", full_name="x", role="pi")


def test_add_validates_role(world):
    with pytest.raises(M.MembershipError):
        M.add(handle="x", full_name="X", role="emperor")


def test_set_status_flips(world):
    M.add(handle="bob", full_name="B", role="postdoc")
    rec = M.set_status("bob", M.INACTIVE)
    assert rec.status == M.INACTIVE
    assert rec.deactivated_at  # ISO date stamped
    rec2 = M.set_status("bob", M.ACTIVE)
    assert rec2.status == M.ACTIVE
    assert rec2.deactivated_at is None  # cleared on reactivation


def test_set_status_pi_protected(world):
    with pytest.raises(M.CannotDeactivatePI):
        M.set_status("mhallet", M.INACTIVE)


def test_set_status_unknown_handle(world):
    with pytest.raises(M.MemberNotFound):
        M.set_status("nope", M.INACTIVE)


def test_is_active_unknown_returns_false(world):
    assert M.is_active("ghost") is False


def test_is_active_inactive_returns_false(world):
    M.add(handle="bob", full_name="B", role="postdoc")
    assert M.is_active("bob") is True
    M.set_status("bob", M.INACTIVE)
    assert M.is_active("bob") is False


def test_iter_members_filters(world):
    M.add(handle="a", full_name="A", role="postdoc")
    M.add(handle="b", full_name="B", role="student")
    M.set_status("b", M.INACTIVE)
    all_handles = {r.handle for r in M.iter_members()}
    active = {r.handle for r in M.iter_members(include_inactive=False)}
    assert all_handles == {"mhallet", "a", "b"}
    assert active == {"mhallet", "a"}


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------


def _client():
    from fastapi.testclient import TestClient
    from murmurent.dashboard.server import create_app
    return TestClient(create_app())


def test_endpoint_add_member_pi_only(world):
    M.add(handle="allie", full_name="Allie", role="postdoc")  # member exists for the test
    client = _client()
    body = {"handle": "newbie", "full_name": "Newbie X", "role": "student"}
    res_member = client.post("/api/members?user=allie", json=body)
    assert res_member.status_code == 403
    res_pi = client.post("/api/members?user=mhallet", json=body)
    assert res_pi.status_code == 200
    assert res_pi.json()["member"]["handle"] == "newbie"


def test_endpoint_add_member_409_for_existing(world):
    M.add(handle="allie", full_name="Allie", role="postdoc")
    client = _client()
    res = client.post(
        "/api/members?user=mhallet",
        json={"handle": "allie", "full_name": "Dup", "role": "postdoc"},
    )
    assert res.status_code == 409


def test_endpoint_deactivate_then_activate(world):
    M.add(handle="bob", full_name="B", role="postdoc")
    client = _client()
    res = client.post("/api/members/bob/deactivate?user=mhallet")
    assert res.status_code == 200
    assert res.json()["status"] == "inactive"
    res2 = client.post("/api/members/bob/activate?user=mhallet")
    assert res2.status_code == 200
    assert res2.json()["status"] == "active"


def test_endpoint_cannot_deactivate_pi(world):
    client = _client()
    res = client.post("/api/members/mhallet/deactivate?user=mhallet")
    assert res.status_code == 409


def test_endpoint_404_for_missing_member(world):
    client = _client()
    res = client.post("/api/members/ghost/deactivate?user=mhallet")
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Active-check blocks inactive actors
# ---------------------------------------------------------------------------


def test_inactive_member_cannot_run_sea_action(world, monkeypatch):
    """Once @bob is deactivated, his POSTs to action endpoints get 403."""
    M.add(handle="bob", full_name="B", role="postdoc")
    M.add(handle="allie", full_name="A", role="postdoc")
    project_cmd.cmd_new(
        "p_act", charter_path=None, members_csv="@mhallet,@allie,@bob",
        description="x", sensitivity="standard", lead="@allie",
        skip_github=True,
    )
    # File a SEA so bob has something to act on.
    from murmurent.commands import sea_cmd
    sea_cmd.cmd_request(
        project_name="p_act", to_target="@bob", kind="analysis",
        description="x", from_handle="@allie",
    )
    # While bob is active, claim works.
    client = _client()
    M.set_status("bob", M.INACTIVE)
    res = client.post("/api/sea/p_act/1/claim?user=bob", json={})
    assert res.status_code == 403
    assert "inactive" in res.json()["detail"].lower()


def test_inactive_member_visible_in_pi_group_panel(world):
    """PI sees inactive members in the group panel (with status=inactive)."""
    M.add(handle="bob", full_name="B", role="postdoc")
    M.set_status("bob", M.INACTIVE)
    from murmurent.dashboard import snapshot
    resp = snapshot.build_response("mhallet", today=_dt.date(2026, 5, 8))
    bob = next((p for p in resp.peers if p.handle == "bob"), None)
    assert bob is not None
    assert bob.status == "inactive"
