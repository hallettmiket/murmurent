"""
Conflict-check on the booking endpoint: refuse a second booking
whose [start, end) overlaps an existing scheduled/in_progress one
for the same service. Overrideable by leader/registrar.

This is the "(c) backend overlap check" half of the conflict-handling
work the PI asked for during smoke testing.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
import yaml
from fastapi.testclient import TestClient

from wigamig.core import registrar as R
from wigamig.core import service_requests as SR
from wigamig.core import services as S
from wigamig.core import training as T
from wigamig.dashboard.server import create_app


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_LAB_INFO_ROOT", str(tmp_path / "lab_info"))
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("WIGAMIG_LAB_VM_ROOT", str(tmp_path / "lab_vm"))
    monkeypatch.setenv("WIGAMIG_HOME", str(tmp_path / "wigamig_home"))
    monkeypatch.setenv("WIGAMIG_USER", "alice")
    (tmp_path / "lab-mgmt" / "members").mkdir(parents=True)
    (tmp_path / "lab-mgmt" / "lab.md").write_text(
        "---\nlab: hallett\npi: '@mhallet'\n---\n", encoding="utf-8",
    )
    (tmp_path / "lab_info").mkdir(parents=True)
    (tmp_path / "lab_info" / "registrar").write_text("mhallet\n", encoding="utf-8")
    R.create_core(name="biocore", display_name="BioCORE", leader_handle="@gary")
    for h in ("alice", "bob", "mhallet", "gary"):
        (tmp_path / "lab-mgmt" / "members" / f"{h}.md").write_text(
            f"---\n{yaml.safe_dump({'handle': f'@{h}', 'role': 'postdoc', 'status': 'active'}, sort_keys=False).rstrip()}\n---\n",
            encoding="utf-8",
        )
    # Two services so we can prove conflict-check is per-service.
    S.create_service(core="biocore", slug="itc", name="ITC",
                      training_required=None)
    S.create_service(core="biocore", slug="cd", name="CD",
                      training_required=None)
    return tmp_path


def _book(client, *, user, service="itc", start="2026-05-23T10:00-04:00",
           end="2026-05-23T11:00-04:00", **extra):
    payload = {"slot": {"start": start, "end": end}, **extra}
    return client.post(
        f"/api/core/biocore/services/{service}/book?user={user}",
        json=payload,
    )


# ---- happy path: no conflict, both succeed ------------------------------

@patch("wigamig.dashboard.slack_notify._post")
def test_non_overlapping_slots_both_book(mock_post, world):
    client = TestClient(create_app())
    r1 = _book(client, user="alice",
                start="2026-05-23T10:00-04:00", end="2026-05-23T11:00-04:00")
    r2 = _book(client, user="bob",
                start="2026-05-23T11:00-04:00", end="2026-05-23T12:00-04:00")
    assert r1.status_code == 200
    assert r2.status_code == 200


# ---- conflict variants --------------------------------------------------

@patch("wigamig.dashboard.slack_notify._post")
def test_exact_overlap_refused(mock_post, world):
    client = TestClient(create_app())
    r1 = _book(client, user="alice")
    assert r1.status_code == 200
    r2 = _book(client, user="bob")
    assert r2.status_code == 409
    assert "conflicts" in r2.json()["detail"]
    assert "@alice" in r2.json()["detail"]


@patch("wigamig.dashboard.slack_notify._post")
def test_partial_overlap_refused(mock_post, world):
    client = TestClient(create_app())
    _book(client, user="alice",
           start="2026-05-23T10:00-04:00", end="2026-05-23T11:00-04:00")
    r = _book(client, user="bob",
               start="2026-05-23T10:30-04:00", end="2026-05-23T11:30-04:00")
    assert r.status_code == 409


@patch("wigamig.dashboard.slack_notify._post")
def test_back_to_back_slots_ok(mock_post, world):
    """end == start of the next is NOT an overlap."""
    client = TestClient(create_app())
    _book(client, user="alice",
           start="2026-05-23T10:00-04:00", end="2026-05-23T11:00-04:00")
    r = _book(client, user="bob",
               start="2026-05-23T11:00-04:00", end="2026-05-23T12:00-04:00")
    assert r.status_code == 200


@patch("wigamig.dashboard.slack_notify._post")
def test_different_service_no_conflict(mock_post, world):
    """ITC slot doesn't block CD slot at the same time."""
    client = TestClient(create_app())
    _book(client, user="alice", service="itc")
    r = _book(client, user="bob", service="cd")
    assert r.status_code == 200


@patch("wigamig.dashboard.slack_notify._post")
def test_cancelled_booking_frees_slot(mock_post, world):
    client = TestClient(create_app())
    r1 = _book(client, user="alice")
    rid = r1.json()["request_id"]
    client.post(f"/api/core/biocore/requests/{rid}/cancel?user=alice")
    # Now bob can take the same slot.
    r2 = _book(client, user="bob")
    assert r2.status_code == 200


# ---- override (leader / registrar only) --------------------------------

@patch("wigamig.dashboard.slack_notify._post")
def test_override_conflict_works_for_leader(mock_post, world):
    """Leader proxy-books on behalf of alice over an existing slot."""
    client = TestClient(create_app())
    _book(client, user="alice")
    r = _book(client, user="gary",
               requester="@alice", override_conflict=True,
               start="2026-05-23T10:00-04:00", end="2026-05-23T11:00-04:00")
    assert r.status_code == 200, r.text


@patch("wigamig.dashboard.slack_notify._post")
def test_override_conflict_works_for_registrar(mock_post, world):
    client = TestClient(create_app())
    _book(client, user="alice")
    r = _book(client, user="mhallet",
               requester="@bob", override_conflict=True)
    assert r.status_code == 200


@patch("wigamig.dashboard.slack_notify._post")
def test_override_conflict_ignored_for_member(mock_post, world):
    """A regular member can't bypass the check by sending the flag."""
    client = TestClient(create_app())
    _book(client, user="alice")
    r = _book(client, user="bob", override_conflict=True)
    assert r.status_code == 409


# ---- bad slot inputs surface early -------------------------------------

@patch("wigamig.dashboard.slack_notify._post")
def test_end_before_start_refused(mock_post, world):
    client = TestClient(create_app())
    r = _book(client, user="alice",
               start="2026-05-23T11:00-04:00", end="2026-05-23T10:00-04:00")
    assert r.status_code == 422
    assert "after slot.start" in r.json()["detail"]


def test_non_iso_slot_refused(world):
    client = TestClient(create_app())
    r = _book(client, user="alice",
               start="tomorrow morning", end="tomorrow noon")
    assert r.status_code == 422
