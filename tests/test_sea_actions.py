"""Tests for the Phase-4 SEA action layer + ``POST /api/sea/...`` endpoints.

Covers the full lifecycle path (claim → complete → examine → conclude),
authorization (recipient-only for claim/complete/decline; squad for
examine/conclude/reopen), state-machine guards, and HTTP code mapping.
"""

from __future__ import annotations

import pytest

from murmurent.commands import project_cmd, sea_cmd
from murmurent.core import sea as sea_core
from murmurent.dashboard import sea_actions


@pytest.fixture
def world(monkeypatch, tmp_path):
    """Two-project universe with a few SEAs across the lifecycle."""
    monkeypatch.setenv("MURMURENT_PROJECTS_ROOT", str(tmp_path / "repos"))
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("MURMURENT_LAB_VM_ROOT", str(tmp_path / "lab_vm"))
    monkeypatch.setenv("MURMURENT_USER", "allie")
    (tmp_path / "lab-mgmt" / "members").mkdir(parents=True)
    (tmp_path / "lab-mgmt" / "projects").mkdir(parents=True)

    project_cmd.cmd_new(
        "p_test",
        charter_path=None,
        members_csv="@allie,@bob,@cassie",
        description="Action-test fixture project.",
        sensitivity="standard",
        lead="@allie",
        skip_github=True,
    )

    # SEA 1: requested by allie → assigned to bob (will run through full lifecycle).
    sea_cmd.cmd_request(
        project_name="p_test", to_target="@bob", kind="analysis",
        description="lifecycle test", from_handle="@allie",
    )
    return tmp_path


# ---------------------------------------------------------------------------
# core: apply_action()
# ---------------------------------------------------------------------------


def test_claim_succeeds_for_recipient(world):
    result = sea_actions.apply_action(
        project="p_test", sea_id=1, action="claim", actor="bob"
    )
    assert result.sea.state == "claimed"
    assert result.sea.claimed_at  # ISO date stamped


def test_claim_forbidden_for_non_recipient(world):
    with pytest.raises(sea_actions.SeaForbidden):
        sea_actions.apply_action(
            project="p_test", sea_id=1, action="claim", actor="cassie"
        )


def test_claim_conflict_when_already_claimed(world):
    sea_actions.apply_action(project="p_test", sea_id=1, action="claim", actor="bob")
    with pytest.raises(sea_actions.SeaConflict):
        sea_actions.apply_action(
            project="p_test", sea_id=1, action="claim", actor="bob"
        )


def test_complete_requires_delivery(world):
    sea_actions.apply_action(project="p_test", sea_id=1, action="claim", actor="bob")
    with pytest.raises(sea_actions.SeaBadRequest):
        sea_actions.apply_action(
            project="p_test", sea_id=1, action="complete", actor="bob"
        )


def test_complete_persists_delivery(world):
    sea_actions.apply_action(project="p_test", sea_id=1, action="claim", actor="bob")
    result = sea_actions.apply_action(
        project="p_test", sea_id=1, action="complete", actor="bob",
        delivery="findings/x.md",
    )
    assert result.sea.state == "complete"
    assert result.sea.delivery == "findings/x.md"


def test_examine_allowed_for_either_squad_member(world):
    """Either from_handle or to_handle can examine."""
    sea_actions.apply_action(project="p_test", sea_id=1, action="claim", actor="bob")
    sea_actions.apply_action(
        project="p_test", sea_id=1, action="complete", actor="bob",
        delivery="findings/x.md",
    )
    # allie (the from_handle) examines.
    result = sea_actions.apply_action(
        project="p_test", sea_id=1, action="examine", actor="allie"
    )
    assert result.sea.state == "examined"


def test_examine_forbidden_for_non_squad(world):
    sea_actions.apply_action(project="p_test", sea_id=1, action="claim", actor="bob")
    sea_actions.apply_action(
        project="p_test", sea_id=1, action="complete", actor="bob",
        delivery="findings/x.md",
    )
    with pytest.raises(sea_actions.SeaForbidden):
        sea_actions.apply_action(
            project="p_test", sea_id=1, action="examine", actor="cassie"
        )


def test_decline_requires_reason(world):
    with pytest.raises(sea_actions.SeaBadRequest):
        sea_actions.apply_action(
            project="p_test", sea_id=1, action="decline", actor="bob"
        )


def test_decline_marks_terminal(world):
    result = sea_actions.apply_action(
        project="p_test", sea_id=1, action="decline", actor="bob",
        reason="out of scope",
    )
    assert result.sea.state == "declined"
    assert result.sea.decline_reason == "out of scope"


def test_full_lifecycle_claim_to_conclude(world):
    sea_actions.apply_action(project="p_test", sea_id=1, action="claim", actor="bob")
    sea_actions.apply_action(
        project="p_test", sea_id=1, action="complete", actor="bob",
        delivery="findings/x.md",
    )
    sea_actions.apply_action(project="p_test", sea_id=1, action="examine", actor="allie")
    result = sea_actions.apply_action(
        project="p_test", sea_id=1, action="conclude", actor="allie"
    )
    assert result.sea.state == "concluded"
    assert result.sea.concluded_at


def test_unknown_action_is_bad_request(world):
    with pytest.raises(sea_actions.SeaBadRequest):
        sea_actions.apply_action(
            project="p_test", sea_id=1, action="haxxor", actor="bob"
        )


def test_missing_project_is_not_found(world):
    with pytest.raises(sea_actions.SeaNotFound):
        sea_actions.apply_action(
            project="nope", sea_id=1, action="claim", actor="bob"
        )


def test_missing_sea_is_not_found(world):
    with pytest.raises(sea_actions.SeaNotFound):
        sea_actions.apply_action(
            project="p_test", sea_id=999, action="claim", actor="bob"
        )


# ---------------------------------------------------------------------------
# HTTP endpoint: POST /api/sea/{project}/{id}/{action}
# ---------------------------------------------------------------------------


def _client():
    from fastapi.testclient import TestClient
    from murmurent.dashboard.server import create_app
    return TestClient(create_app())


def test_endpoint_claim_happy_path(world):
    client = _client()
    res = client.post("/api/sea/p_test/1/claim?user=bob", json={})
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["ok"] is True
    assert payload["sea"]["state"] == "claimed"


def test_endpoint_claim_forbidden(world):
    client = _client()
    res = client.post("/api/sea/p_test/1/claim?user=cassie", json={})
    assert res.status_code == 403


def test_endpoint_claim_conflict_after_already_claimed(world):
    client = _client()
    client.post("/api/sea/p_test/1/claim?user=bob", json={})
    res = client.post("/api/sea/p_test/1/claim?user=bob", json={})
    assert res.status_code == 409


def test_endpoint_complete_validates_delivery(world):
    client = _client()
    client.post("/api/sea/p_test/1/claim?user=bob", json={})
    res = client.post("/api/sea/p_test/1/complete?user=bob", json={})
    assert res.status_code == 422


def test_endpoint_complete_with_delivery(world):
    client = _client()
    client.post("/api/sea/p_test/1/claim?user=bob", json={})
    res = client.post(
        "/api/sea/p_test/1/complete?user=bob",
        json={"delivery": "findings/x.md"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["sea"]["state"] == "complete"


def test_endpoint_unknown_action_is_422(world):
    client = _client()
    res = client.post("/api/sea/p_test/1/explode?user=bob", json={})
    assert res.status_code == 422


def test_endpoint_missing_sea_is_404(world):
    client = _client()
    res = client.post("/api/sea/p_test/999/claim?user=bob", json={})
    assert res.status_code == 404


def test_endpoint_no_user_is_400(world, monkeypatch, tmp_path):
    from murmurent.core import identity as _identity

    monkeypatch.delenv("MURMURENT_USER", raising=False)
    monkeypatch.setenv("PATH", "")  # block gh fallback
    # Also block the ~/.murmurent/user fallback so the developer's saved
    # Western netname doesn't leak in.
    monkeypatch.setattr(_identity, "USER_FILE", tmp_path / "no_user_here")
    client = _client()
    res = client.post("/api/sea/p_test/1/claim", json={})
    assert res.status_code == 400
