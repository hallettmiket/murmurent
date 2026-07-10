"""
Phase 3d tests: lifecycle endpoints — advance, cancel, reschedule.

Covers:
  - advance: scheduled→in_progress→completed (auto-pick forward state)
  - advance: explicit to_state honored
  - advance: requester forbidden (admin-only); leader + registrar pass
  - cancel: requester, leader, registrar all succeed
  - cancel: outsider forbidden
  - cancel: calendar event deletion attempted only when connected
  - cancel: calendar errors swallowed; request still cancelled
  - cancel: terminal-state refusal
  - reschedule: requester succeeds; slot replaced; old calendar event
    deleted + new one created (best-effort)
  - reschedule: terminal-state refusal
  - reschedule: missing slot fields → 422
  - reschedule: state unchanged
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
import yaml
from fastapi.testclient import TestClient

from murmurent.core import calendar_google as CAL
from murmurent.core import registrar as R
from murmurent.core import service_requests as SR
from murmurent.core import services as S
from murmurent.dashboard.server import create_app


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_LAB_INFO_ROOT", str(tmp_path / "lab_info"))
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("WIGAMIG_HOME", str(tmp_path / "wigamig_home"))
    monkeypatch.setenv("WIGAMIG_USER", "alice")
    (tmp_path / "lab-mgmt" / "members").mkdir(parents=True)
    (tmp_path / "lab-mgmt" / "lab.md").write_text(
        "---\nlab: hallett\npi: '@the_pi'\n---\n", encoding="utf-8",
    )
    (tmp_path / "lab_info").mkdir(parents=True)
    (tmp_path / "lab_info" / "registrar").write_text("the_pi\n", encoding="utf-8")
    R.create_core(name="biocore", display_name="BioCORE", leader_handle="@gary")
    for handle, role in [("alice", "postdoc"), ("bob", "postdoc"),
                         ("the_pi", "pi"), ("gary", "core_leader")]:
        _write_member(tmp_path, handle, role=role)
    S.create_service(
        core="biocore", slug="itc", name="ITC",
        training_required=None,
    )
    return tmp_path


def _write_member(root, handle, *, role="postdoc"):
    meta = {"handle": f"@{handle}", "role": role, "status": "active"}
    (root / "lab-mgmt" / "members" / f"{handle}.md").write_text(
        f"---\n{yaml.safe_dump(meta, sort_keys=False).rstrip()}\n---\n",
        encoding="utf-8",
    )


def _book(client, *, user="alice", with_event_id=""):
    res = client.post(
        f"/api/core/biocore/services/itc/book?user={user}",
        json={"slot": {"start": "2026-05-23T10:00-04:00",
                       "end":   "2026-05-23T11:00-04:00",
                       "calendar_event_id": with_event_id}},
    )
    assert res.status_code == 200, res.text
    return res.json()["request_id"]


# ---- advance -----------------------------------------------------------

@patch("murmurent.dashboard.slack_notify._post")
def test_advance_auto_picks_forward_state(mock_post, world):
    client = TestClient(create_app())
    rid = _book(client)
    res = client.post(
        f"/api/core/biocore/requests/{rid}/advance?user=gary",
    )
    assert res.status_code == 200, res.text
    assert res.json()["state"] == SR.STATE_IN_PROGRESS
    # Advance again -> completed.
    res = client.post(
        f"/api/core/biocore/requests/{rid}/advance?user=gary",
    )
    assert res.status_code == 200, res.text
    assert res.json()["state"] == SR.STATE_COMPLETED


@patch("murmurent.dashboard.slack_notify._post")
def test_advance_explicit_to_state(mock_post, world):
    client = TestClient(create_app())
    rid = _book(client)
    res = client.post(
        f"/api/core/biocore/requests/{rid}/advance?user=gary",
        json={"to_state": "in_progress", "note": "instrument warm"},
    )
    assert res.status_code == 200
    rt = SR.get_request("biocore", rid)
    assert rt.state == SR.STATE_IN_PROGRESS
    assert "instrument warm" in rt.path.read_text(encoding="utf-8")


def test_advance_requester_forbidden(world):
    client = TestClient(create_app())
    rid = _book(client)
    # alice is the requester but NOT the core leader.
    res = client.post(
        f"/api/core/biocore/requests/{rid}/advance?user=alice",
    )
    assert res.status_code == 403


@patch("murmurent.dashboard.slack_notify._post")
def test_advance_registrar_passes(mock_post, world):
    client = TestClient(create_app())
    rid = _book(client)
    res = client.post(
        f"/api/core/biocore/requests/{rid}/advance?user=the_pi",  # registrar
    )
    assert res.status_code == 200


@patch("murmurent.dashboard.slack_notify._post")
def test_advance_terminal_state_refuses(mock_post, world):
    client = TestClient(create_app())
    rid = _book(client)
    # Drive to completed.
    client.post(f"/api/core/biocore/requests/{rid}/advance?user=gary")
    client.post(f"/api/core/biocore/requests/{rid}/advance?user=gary")
    res = client.post(
        f"/api/core/biocore/requests/{rid}/advance?user=gary",
    )
    assert res.status_code == 422


def test_advance_unknown_request(world):
    client = TestClient(create_app())
    res = client.post(
        "/api/core/biocore/requests/ghost-id/advance?user=gary",
    )
    assert res.status_code == 404


# ---- cancel ------------------------------------------------------------

@patch("murmurent.dashboard.slack_notify._post")
def test_cancel_by_requester(mock_post, world):
    client = TestClient(create_app())
    rid = _book(client)
    res = client.post(
        f"/api/core/biocore/requests/{rid}/cancel?user=alice",
    )
    assert res.status_code == 200, res.text
    assert res.json()["state"] == SR.STATE_CANCELLED


@patch("murmurent.dashboard.slack_notify._post")
def test_cancel_by_leader(mock_post, world):
    client = TestClient(create_app())
    rid = _book(client)
    res = client.post(
        f"/api/core/biocore/requests/{rid}/cancel?user=gary",
        json={"note": "instrument down"},
    )
    assert res.status_code == 200
    rt = SR.get_request("biocore", rid)
    assert rt.state == SR.STATE_CANCELLED
    assert "instrument down" in rt.path.read_text(encoding="utf-8")


def test_cancel_by_outsider_forbidden(world):
    client = TestClient(create_app())
    rid = _book(client)
    res = client.post(
        f"/api/core/biocore/requests/{rid}/cancel?user=bob",
    )
    assert res.status_code == 403


@patch("murmurent.dashboard.slack_notify._post")
@patch("murmurent.core.calendar_google.delete_event")
def test_cancel_deletes_calendar_event_when_connected(
    mock_delete, mock_post, world,
):
    # Plant token file so is_connected is True.
    CAL.creds_path("biocore").parent.mkdir(parents=True, exist_ok=True)
    CAL.creds_path("biocore").write_text("{}", encoding="utf-8")
    client = TestClient(create_app())
    rid = _book(client, with_event_id="evt-xyz")
    res = client.post(
        f"/api/core/biocore/requests/{rid}/cancel?user=alice",
    )
    assert res.status_code == 200
    mock_delete.assert_called_once_with("biocore", "evt-xyz")
    assert res.json()["calendar"]["deleted_event_id"] == "evt-xyz"


@patch("murmurent.dashboard.slack_notify._post")
def test_cancel_skips_calendar_when_not_connected(mock_post, world):
    client = TestClient(create_app())
    rid = _book(client, with_event_id="evt-xyz")
    # No creds file: is_connected is False; cancel should still succeed.
    res = client.post(
        f"/api/core/biocore/requests/{rid}/cancel?user=alice",
    )
    assert res.status_code == 200
    assert res.json()["calendar"]["warning"] == ""


@patch("murmurent.dashboard.slack_notify._post")
@patch("murmurent.core.calendar_google.delete_event",
       side_effect=CAL.CalendarError("API 500"))
def test_cancel_swallows_calendar_error(mock_delete, mock_post, world):
    CAL.creds_path("biocore").parent.mkdir(parents=True, exist_ok=True)
    CAL.creds_path("biocore").write_text("{}", encoding="utf-8")
    client = TestClient(create_app())
    rid = _book(client, with_event_id="evt-xyz")
    res = client.post(
        f"/api/core/biocore/requests/{rid}/cancel?user=alice",
    )
    assert res.status_code == 200
    assert "API 500" in res.json()["calendar"]["warning"]
    assert SR.get_request("biocore", rid).state == SR.STATE_CANCELLED


# ---- reschedule --------------------------------------------------------

@patch("murmurent.dashboard.slack_notify._post")
def test_reschedule_replaces_slot_state_unchanged(mock_post, world):
    client = TestClient(create_app())
    rid = _book(client)
    res = client.post(
        f"/api/core/biocore/requests/{rid}/reschedule?user=alice",
        json={"slot": {"start": "2026-05-24T14:00-04:00",
                       "end":   "2026-05-24T15:30-04:00"}},
    )
    assert res.status_code == 200, res.text
    rt = SR.get_request("biocore", rid)
    assert rt.booked_slot.start.startswith("2026-05-24T14")
    assert rt.state == SR.STATE_SCHEDULED


def test_reschedule_missing_slot_fields(world):
    client = TestClient(create_app())
    rid = _book(client)
    res = client.post(
        f"/api/core/biocore/requests/{rid}/reschedule?user=alice",
        json={"slot": {"start": "2026-05-24T14:00-04:00"}},
    )
    assert res.status_code == 422


@patch("murmurent.dashboard.slack_notify._post")
def test_reschedule_refuses_terminal_state(mock_post, world):
    client = TestClient(create_app())
    rid = _book(client)
    client.post(f"/api/core/biocore/requests/{rid}/cancel?user=alice")
    res = client.post(
        f"/api/core/biocore/requests/{rid}/reschedule?user=alice",
        json={"slot": {"start": "2026-05-24T14:00-04:00",
                       "end":   "2026-05-24T15:30-04:00"}},
    )
    assert res.status_code == 422


@patch("murmurent.dashboard.slack_notify._post")
@patch("murmurent.core.calendar_google.create_event")
@patch("murmurent.core.calendar_google.delete_event")
def test_reschedule_rotates_calendar_event(
    mock_delete, mock_create, mock_post, world,
):
    CAL.creds_path("biocore").parent.mkdir(parents=True, exist_ok=True)
    CAL.creds_path("biocore").write_text("{}", encoding="utf-8")
    mock_create.return_value = CAL.CalendarEvent(
        id="evt-new", html_link="https://x/evt-new",
        start="2026-05-24T14:00-04:00", end="2026-05-24T15:30-04:00",
    )
    client = TestClient(create_app())
    rid = _book(client, with_event_id="evt-old")
    res = client.post(
        f"/api/core/biocore/requests/{rid}/reschedule?user=alice",
        json={"slot": {"start": "2026-05-24T14:00-04:00",
                       "end":   "2026-05-24T15:30-04:00"}},
    )
    assert res.status_code == 200, res.text
    mock_delete.assert_called_once_with("biocore", "evt-old")
    mock_create.assert_called_once()
    rt = SR.get_request("biocore", rid)
    assert rt.booked_slot.calendar_event_id == "evt-new"


def test_reschedule_outsider_forbidden(world):
    client = TestClient(create_app())
    rid = _book(client)
    res = client.post(
        f"/api/core/biocore/requests/{rid}/reschedule?user=bob",
        json={"slot": {"start": "2026-05-24T14:00-04:00",
                       "end":   "2026-05-24T15:30-04:00"}},
    )
    assert res.status_code == 403
