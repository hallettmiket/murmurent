"""
Phase 3c tests: Google Calendar wiring for the booking endpoint.

Covers:
  - calendar_google.is_connected / creds_path under WIGAMIG_HOME
  - Booking endpoint creates a calendar event synchronously when
    connected, populates calendar_event_id + html_link in the
    response AND the persisted request file.
  - Booking endpoint surfaces a friendly 'not connected' warning when
    no token file exists; the request is still created in 'scheduled'
    (calendar must never block the booking).
  - Booking endpoint surfaces the CalendarError message when the API
    call fails; the request is still created with event_id="".
  - Caller-supplied calendar_event_id is preserved verbatim (used by
    Phase 3d cancel + re-book flows).
  - create_event refuses to import google libs when not installed
    (CalendarError with install hint).

We patch ``calendar_google.create_event`` at the boundary rather than
mocking the actual Google client — that's a black-box contract; the
client wrapper itself is exercised manually by Gary's one-time OAuth.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from fastapi.testclient import TestClient

from murmurent.core import calendar_google as CAL
from murmurent.core import registrar as R
from murmurent.core import services as S
from murmurent.core import service_requests as SR
from murmurent.dashboard.server import create_app


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_LAB_INFO_ROOT", str(tmp_path / "lab_info"))
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("WIGAMIG_HOME", str(tmp_path / "wigamig_home"))
    monkeypatch.setenv("WIGAMIG_USER", "alice")
    (tmp_path / "lab-mgmt" / "members").mkdir(parents=True)
    (tmp_path / "lab-mgmt" / "lab.md").write_text(
        "---\nlab: hallett\npi: '@mhallet'\n---\n", encoding="utf-8",
    )
    (tmp_path / "lab_info").mkdir(parents=True)
    (tmp_path / "lab_info" / "registrar").write_text("mhallet\n", encoding="utf-8")
    R.create_core(name="biocore", display_name="BioCORE", leader_handle="@gary")
    _write_member(tmp_path, "alice", trainings=[
        {"name": "itc_basic", "completed": "2025-11-15",
         "valid_until": "2030-11-15"},
    ])
    _write_member(tmp_path, "mhallet", role="pi")
    _write_member(tmp_path, "gary", role="core_leader")
    S.create_service(
        core="biocore", slug="itc", name="ITC",
        training_required=None,        # tests focus on calendar, not prereqs
        fee={"unit": "per_run",
             "tiers": {"academic_internal": 80.0}},
    )
    return tmp_path


def _write_member(root, handle, *, role="postdoc", trainings=None):
    meta = {"handle": f"@{handle}", "role": role, "status": "active"}
    if trainings is not None:
        meta["training"] = trainings
    (root / "lab-mgmt" / "members" / f"{handle}.md").write_text(
        f"---\n{yaml.safe_dump(meta, sort_keys=False).rstrip()}\n---\n", encoding="utf-8",
    )


# ---- path helpers ------------------------------------------------------

def test_creds_path_respects_wigamig_home(world):
    assert CAL.creds_path("biocore") == (
        world / "wigamig_home" / "cores" / "biocore" / "google_calendar.json"
    )


def test_is_connected_false_when_token_absent(world):
    assert CAL.is_connected("biocore") is False


def test_is_connected_true_when_token_present(world):
    p = CAL.creds_path("biocore")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{}", encoding="utf-8")
    assert CAL.is_connected("biocore") is True


# ---- booking endpoint integration --------------------------------------

@patch("murmurent.dashboard.slack_notify._post")
def test_book_no_calendar_returns_warning_not_blocked(mock_post, world):
    """No token file → request still lands scheduled; warning surfaced."""
    client = TestClient(create_app())
    res = client.post(
        "/api/core/biocore/services/itc/book?user=alice",
        json={"slot": {"start": "2026-05-23T10:00-04:00",
                       "end":   "2026-05-23T11:00-04:00"}},
    )
    assert res.status_code == 200, res.text
    j = res.json()
    assert j["state"] == SR.STATE_SCHEDULED
    assert j["calendar"]["event_id"] == ""
    assert "calendar not connected" in j["calendar"]["warning"]
    assert "core-calendar-auth" in j["calendar"]["warning"]


@patch("murmurent.dashboard.slack_notify._post")
@patch("murmurent.core.calendar_google.create_event")
def test_book_creates_event_when_connected(mock_create, mock_post, world):
    """Token file present → endpoint calls calendar_google.create_event
    and stitches the returned id + html_link into both the response
    and the persisted request file."""
    # Plant a fake token file so is_connected() returns True.
    p = CAL.creds_path("biocore")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{}", encoding="utf-8")
    mock_create.return_value = CAL.CalendarEvent(
        id="evt-abc123",
        html_link="https://calendar.google.com/event?eid=evt-abc123",
        start="2026-05-23T10:00-04:00",
        end="2026-05-23T11:00-04:00",
        summary="ITC — @alice",
    )
    client = TestClient(create_app())
    res = client.post(
        "/api/core/biocore/services/itc/book?user=alice",
        json={"slot": {"start": "2026-05-23T10:00-04:00",
                       "end":   "2026-05-23T11:00-04:00"},
              "notes": "ITC run for project dcis"},
    )
    assert res.status_code == 200, res.text
    j = res.json()
    assert j["slot"]["calendar_event_id"] == "evt-abc123"
    assert j["calendar"]["event_id"] == "evt-abc123"
    assert j["calendar"]["html_link"].endswith("evt-abc123")
    assert j["calendar"]["warning"] == ""
    # Verify the create_event was called with the right shape.
    kwargs = mock_create.call_args.kwargs
    assert kwargs["core"] == "biocore"
    assert "@alice" in kwargs["summary"]
    assert "dcis" in kwargs["description"]
    # Persisted file carries the event_id.
    rt = SR.get_request("biocore", j["request_id"])
    assert rt.booked_slot.calendar_event_id == "evt-abc123"


@patch("murmurent.dashboard.slack_notify._post")
@patch("murmurent.core.calendar_google.create_event")
def test_book_swallows_calendar_error_and_warns(mock_create, mock_post, world):
    """API failure → request still created, event_id="", warning carries
    the error message so the leader can see what went wrong."""
    p = CAL.creds_path("biocore")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{}", encoding="utf-8")
    mock_create.side_effect = CAL.CalendarError("HTTP 500: quota exceeded")
    client = TestClient(create_app())
    res = client.post(
        "/api/core/biocore/services/itc/book?user=alice",
        json={"slot": {"start": "2026-05-23T10:00-04:00",
                       "end":   "2026-05-23T11:00-04:00"}},
    )
    assert res.status_code == 200, res.text
    j = res.json()
    assert j["state"] == SR.STATE_SCHEDULED
    assert j["calendar"]["event_id"] == ""
    assert "quota exceeded" in j["calendar"]["warning"]


@patch("murmurent.dashboard.slack_notify._post")
@patch("murmurent.core.calendar_google.create_event")
def test_book_caller_supplied_event_id_skips_create(mock_create, mock_post, world):
    """If the caller already has a calendar_event_id (re-book / proxy
    flows), the server uses it verbatim and does NOT call create_event."""
    client = TestClient(create_app())
    res = client.post(
        "/api/core/biocore/services/itc/book?user=alice",
        json={"slot": {"start": "2026-05-23T10:00-04:00",
                       "end":   "2026-05-23T11:00-04:00",
                       "calendar_event_id": "pre-existing-id"}},
    )
    assert res.status_code == 200, res.text
    j = res.json()
    assert j["slot"]["calendar_event_id"] == "pre-existing-id"
    assert mock_create.called is False


# ---- lazy-import guards ------------------------------------------------

def test_run_oauth_flow_clear_error_when_libs_missing(world, monkeypatch):
    """If google-auth-oauthlib isn't importable, run_oauth_flow raises
    CalendarError with an install hint (not ImportError)."""
    import builtins
    real_import = builtins.__import__
    def blocked(name, *a, **kw):
        if name.startswith("google_auth_oauthlib"):
            raise ImportError("blocked for test")
        return real_import(name, *a, **kw)
    monkeypatch.setattr(builtins, "__import__", blocked)
    with pytest.raises(CAL.CalendarError, match="gcal"):
        CAL.run_oauth_flow("biocore")


def test_run_oauth_flow_complains_when_client_secret_missing(world):
    """No oauth client_secret.json → CalendarError tells the leader
    exactly where to drop the file."""
    with pytest.raises(CAL.CalendarError, match="missing OAuth client"):
        # google-auth-oauthlib may or may not be installed; either way
        # the missing-client check fires before the flow runs.
        try:
            CAL.run_oauth_flow("biocore")
        except CAL.CalendarError as e:
            if "google-auth-oauthlib" in str(e):
                pytest.skip("gcal extras not installed")
            raise
