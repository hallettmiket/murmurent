"""Tests for project-join requests (Phase 8).

Three layers:
  - core.requests   — file/approve/decline + persistence + member add
  - request_actions — auth wrapper + audit logging
  - HTTP endpoint   — POST /api/request/join + /{id}/{action}
"""

from __future__ import annotations

import datetime as _dt

import pytest

from murmurent.commands import project_cmd
from murmurent.core import requests as req_core
from murmurent.dashboard import audit_log, request_actions, snapshot


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setenv("MURMURENT_PROJECTS_ROOT", str(tmp_path / "repos"))
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("MURMURENT_LAB_VM_ROOT", str(tmp_path / "lab_vm"))
    monkeypatch.setenv("MURMURENT_USER", "diego")
    (tmp_path / "lab-mgmt" / "members").mkdir(parents=True)
    (tmp_path / "lab-mgmt" / "projects").mkdir(parents=True)
    # Set the PI via lab.md (so request_actions can authorise approve/decline).
    (tmp_path / "lab-mgmt" / "lab.md").write_text(
        "---\nlab: hallett\nname: 'Hallett Lab'\npi: '@the_pi'\n---\n", encoding="utf-8"
    )

    project_cmd.cmd_new(
        "p_request",
        charter_path=None,
        members_csv="@the_pi,@allie",  # diego is NOT a member
        description="x", sensitivity="standard", lead="@allie",
        skip_github=True,
    )
    return tmp_path


# ---------------------------------------------------------------------------
# core.requests
# ---------------------------------------------------------------------------


def test_file_request_creates_pending(world):
    req = req_core.file_request(
        requester="diego", project="p_request",
        justification="want to help with imaging",
    )
    assert req.id == 1
    assert req.state == "pending"
    assert req.requester == "@diego"
    assert req.project == "p_request"
    assert req.created_at  # ISO date


def test_file_request_refuses_existing_member(world):
    with pytest.raises(req_core.RequestError) as ei:
        req_core.file_request(requester="allie", project="p_request")
    assert "already a member" in str(ei.value).lower()


def test_file_request_refuses_duplicate_pending(world):
    req_core.file_request(requester="diego", project="p_request")
    with pytest.raises(req_core.RequestError) as ei:
        req_core.file_request(requester="diego", project="p_request")
    assert "pending" in str(ei.value).lower()


def test_file_request_unknown_project(world):
    with pytest.raises(req_core.RequestError) as ei:
        req_core.file_request(requester="diego", project="nope")
    assert "not found" in str(ei.value).lower()


def test_approve_adds_to_members(world):
    req = req_core.file_request(requester="diego", project="p_request")
    req_core.approve(req, approver="the_pi")
    req_core.write_request(req)

    assert req.state == "approved"
    assert req.resolved_by == "@the_pi"

    # Check the project's MEMBERS file got updated.
    members_path = world / "repos" / "p_request" / "MEMBERS"
    text = members_path.read_text()
    assert "@diego" in text


def test_approve_is_idempotent_for_member_add(world):
    """Approving twice would fail at the state machine, but the underlying
    membership-add helper should be safe even if called repeatedly."""
    req_core._add_to_project_members("p_request", "@diego")
    req_core._add_to_project_members("p_request", "@diego")
    members_path = world / "repos" / "p_request" / "MEMBERS"
    occurrences = members_path.read_text().count("@diego")
    assert occurrences == 1


def test_decline_requires_reason(world):
    req = req_core.file_request(requester="diego", project="p_request")
    with pytest.raises(req_core.RequestError):
        req_core.decline(req, decliner="the_pi", reason="")


def test_decline_persists_reason(world):
    req = req_core.file_request(requester="diego", project="p_request")
    req_core.decline(req, decliner="the_pi", reason="not a clinical project member")
    req_core.write_request(req)
    reloaded = req_core.parse_request(req.path)
    assert reloaded.state == "declined"
    assert reloaded.decline_reason == "not a clinical project member"


def test_cannot_re_approve_terminal(world):
    req = req_core.file_request(requester="diego", project="p_request")
    req_core.approve(req, approver="the_pi")
    req_core.write_request(req)
    with pytest.raises(req_core.RequestStateError):
        req_core.approve(req, approver="the_pi")


# ---------------------------------------------------------------------------
# request_actions (auth + audit)
# ---------------------------------------------------------------------------


def test_action_layer_only_pi_can_approve(world):
    req = req_core.file_request(requester="diego", project="p_request")
    with pytest.raises(request_actions.RequestForbidden):
        request_actions.apply_action(
            request_id=req.id, action="approve", actor="diego"
        )


def test_action_layer_pi_approve_works_and_audits(world):
    req = req_core.file_request(requester="diego", project="p_request")
    request_actions.apply_action(
        request_id=req.id, action="approve", actor="the_pi"
    )
    events = audit_log.read_recent()
    kinds = {e.kind for e in events}
    # File event was logged via the file_join_request path; approve here.
    # We only ran apply_action (not file_join_request), so just check approve.
    assert "request.approve" in kinds


def test_action_layer_unknown_action_is_bad_request(world):
    req = req_core.file_request(requester="diego", project="p_request")
    with pytest.raises(request_actions.RequestBadRequest):
        request_actions.apply_action(
            request_id=req.id, action="haxxor", actor="the_pi"
        )


def test_action_layer_decline_requires_reason(world):
    req = req_core.file_request(requester="diego", project="p_request")
    with pytest.raises(request_actions.RequestBadRequest):
        request_actions.apply_action(
            request_id=req.id, action="decline", actor="the_pi"
        )


# ---------------------------------------------------------------------------
# Snapshot integration
# ---------------------------------------------------------------------------


def test_snapshot_member_sees_only_own_pending(world):
    """A member's dashboard shows only THEIR pending requests."""
    req_core.file_request(requester="diego", project="p_request", justification="hi")
    resp = snapshot.build_response("diego", today=_dt.date(2026, 5, 8))
    assert len(resp.requests_pending) == 1
    assert resp.requests_pending[0].requester == "@diego"


def test_snapshot_pi_sees_all_pending(world):
    req_core.file_request(requester="diego", project="p_request", justification="hi")
    resp = snapshot.build_response(
        "the_pi", persona="pi", today=_dt.date(2026, 5, 8)
    )
    assert len(resp.requests_pending) == 1


def test_snapshot_member_does_not_see_others_pending(world):
    """A non-PI member should not see requests from other people."""
    req_core.file_request(requester="diego", project="p_request", justification="hi")
    resp = snapshot.build_response("allie", today=_dt.date(2026, 5, 8))
    # Allie didn't file anything, so requests_pending is empty for her.
    assert resp.requests_pending == []


def test_requests_mine_shows_resolved_too(world):
    req = req_core.file_request(requester="diego", project="p_request", justification="hi")
    request_actions.apply_action(
        request_id=req.id, action="decline", actor="the_pi",
        reason="clinical compliance gap",
    )
    resp = snapshot.build_response("diego", today=_dt.date(2026, 5, 8))
    states = {r.state for r in resp.requests_mine}
    assert "declined" in states


# ---------------------------------------------------------------------------
# HTTP endpoint
# ---------------------------------------------------------------------------


def _client():
    from fastapi.testclient import TestClient
    from murmurent.dashboard.server import create_app
    return TestClient(create_app())


def test_endpoint_file_join_happy_path(world):
    client = _client()
    res = client.post(
        "/api/request/join?user=diego",
        json={"project": "p_request", "justification": "imaging help"},
    )
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["ok"] is True
    assert payload["request"]["state"] == "pending"


def test_endpoint_file_join_409_for_existing_member(world):
    client = _client()
    res = client.post(
        "/api/request/join?user=allie", json={"project": "p_request"}
    )
    assert res.status_code == 409


def test_endpoint_file_join_404_for_unknown_project(world):
    client = _client()
    res = client.post(
        "/api/request/join?user=diego", json={"project": "nonsense"}
    )
    assert res.status_code == 404


def test_endpoint_approve_pi_only(world):
    client = _client()
    client.post("/api/request/join?user=diego", json={"project": "p_request"})
    res_diego = client.post("/api/request/1/approve?user=diego", json={})
    assert res_diego.status_code == 403
    res_pi = client.post("/api/request/1/approve?user=the_pi", json={})
    assert res_pi.status_code == 200
    assert res_pi.json()["request"]["state"] == "approved"


def test_endpoint_decline_requires_reason(world):
    client = _client()
    client.post("/api/request/join?user=diego", json={"project": "p_request"})
    res = client.post("/api/request/1/decline?user=the_pi", json={})
    assert res.status_code == 422


def test_endpoint_decline_persists(world):
    client = _client()
    client.post("/api/request/join?user=diego", json={"project": "p_request"})
    res = client.post(
        "/api/request/1/decline?user=the_pi",
        json={"reason": "wait until next quarter"},
    )
    assert res.status_code == 200
    assert res.json()["request"]["decline_reason"] == "wait until next quarter"


def test_endpoint_unknown_action_is_422(world):
    client = _client()
    client.post("/api/request/join?user=diego", json={"project": "p_request"})
    res = client.post("/api/request/1/explode?user=the_pi", json={})
    assert res.status_code == 422


def test_endpoint_404_for_missing_request(world):
    client = _client()
    res = client.post("/api/request/999/approve?user=the_pi", json={})
    assert res.status_code == 404
