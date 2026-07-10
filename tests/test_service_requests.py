"""
Phase 3a tests: per-core service-request records + state machine.

Covers core.service_requests:
  - new_request_id (date prefix, requester slug, service slug, NNN suffix)
  - create_request (writes file, auto-detects state from booked_slot)
  - get_request / iter_requests (filters: state, requester, requester_lab,
    include_terminal)
  - transition_request (allowed + illegal transitions; terminal refusal)
  - update_booking_slot (reschedule)
  - request_id collision avoidance on same day
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pytest

from murmurent.core import registrar as R
from murmurent.core import service_requests as SR


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_LAB_INFO_ROOT", str(tmp_path / "lab_info"))
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("WIGAMIG_USER", "the_pi")
    (tmp_path / "lab-mgmt" / "members").mkdir(parents=True)
    (tmp_path / "lab-mgmt" / "lab.md").write_text(
        "---\nlab: hallett\npi: '@the_pi'\n---\n",
        encoding="utf-8",
    )
    (tmp_path / "lab_info").mkdir(parents=True)
    (tmp_path / "lab_info" / "registrar").write_text("the_pi\n", encoding="utf-8")
    R.create_core(
        name="biocore", display_name="BioCORE",
        leader_handle="@gary",
    )
    return tmp_path


# ---- new_request_id -----------------------------------------------------

def test_new_request_id_shape(world):
    rid = SR.new_request_id(
        core="biocore", requester="alice", service="itc_microcal_peaq",
        today=_dt.date(2026, 5, 23),
    )
    assert rid == "2026-05-23-alice-itc_microcal_peaq-001"


def test_new_request_id_strips_at_sign(world):
    rid = SR.new_request_id(
        core="biocore", requester="@alice", service="x_svc",
        today=_dt.date(2026, 5, 23),
    )
    assert rid.startswith("2026-05-23-alice-x_svc")


def test_new_request_id_avoids_collisions(world):
    """Two bookings same day/same requester/same service => 001, 002."""
    today = _dt.date(2026, 5, 23)
    r1 = SR.create_request(
        core="biocore", service="itc", requester="@alice",
        requester_lab="hallett", today=today,
    )
    r2 = SR.create_request(
        core="biocore", service="itc", requester="@alice",
        requester_lab="hallett", today=today,
    )
    assert r1.request_id.endswith("-001")
    assert r2.request_id.endswith("-002")


# ---- create_request -----------------------------------------------------

def test_create_request_no_slot_starts_requested(world):
    req = SR.create_request(
        core="biocore", service="itc", requester="@alice",
        requester_lab="hallett",
    )
    assert req.state == SR.STATE_REQUESTED
    assert req.path.is_file()
    assert req.job_id == req.request_id


def test_create_request_with_slot_starts_scheduled(world):
    slot = SR.BookingSlot(
        start="2026-05-23T10:00-04:00", end="2026-05-23T11:30-04:00",
    )
    req = SR.create_request(
        core="biocore", service="itc", requester="@alice",
        requester_lab="hallett", booked_slot=slot,
    )
    assert req.state == SR.STATE_SCHEDULED
    assert req.booked_slot.start.startswith("2026-05-23T10")


def test_create_request_unknown_core_raises(world):
    with pytest.raises(R.LabNotFound):
        SR.create_request(
            core="ghost", service="x", requester="@alice",
            requester_lab="hallett",
        )


def test_create_request_persists_fee_snapshot(world):
    fee = SR.FeeSnapshot(tier="academic_internal", unit="per_run",
                          base=80.0, total=100.0,
                          modifiers_applied=[{"name": "weekend",
                                              "factor": 1.25}])
    req = SR.create_request(
        core="biocore", service="itc", requester="@alice",
        requester_lab="hallett", fee_at_booking=fee,
    )
    roundtrip = SR.get_request("biocore", req.request_id)
    assert roundtrip.fee_at_booking.total == 100.0
    assert roundtrip.fee_at_booking.modifiers_applied[0]["name"] == "weekend"


def test_create_request_writes_to_requests_dir(world):
    req = SR.create_request(
        core="biocore", service="itc", requester="@alice",
        requester_lab="hallett",
    )
    expected = SR.requests_dir("biocore") / f"{req.request_id}.md"
    assert req.path == expected


# ---- iter_requests filters ---------------------------------------------

def _seed_three(world):
    """Three requests in known states for filtering tests."""
    r1 = SR.create_request(core="biocore", service="itc",
                            requester="@alice", requester_lab="hallett")
    r2 = SR.create_request(
        core="biocore", service="centrifuge",
        requester="@bob", requester_lab="castellani",
        booked_slot=SR.BookingSlot(start="2026-05-23T10:00-04:00",
                                    end="2026-05-23T11:00-04:00"),
    )
    SR.transition_request(core="biocore", request_id=r2.request_id,
                           to_state=SR.STATE_IN_PROGRESS)
    SR.transition_request(core="biocore", request_id=r2.request_id,
                           to_state=SR.STATE_COMPLETED)
    r3 = SR.create_request(core="biocore", service="cd",
                            requester="@alice", requester_lab="hallett")
    SR.transition_request(core="biocore", request_id=r3.request_id,
                           to_state=SR.STATE_CANCELLED)
    return r1, r2, r3


def test_iter_requests_all(world):
    _seed_three(world)
    assert len(SR.iter_requests("biocore")) == 3


def test_iter_requests_filters_by_state(world):
    _seed_three(world)
    out = SR.iter_requests("biocore", state=SR.STATE_REQUESTED)
    assert len(out) == 1
    assert out[0].service == "itc"


def test_iter_requests_filters_by_requester(world):
    _seed_three(world)
    out = SR.iter_requests("biocore", requester="@alice")
    assert sorted(r.service for r in out) == ["cd", "itc"]


def test_iter_requests_filters_by_requester_lab(world):
    _seed_three(world)
    out = SR.iter_requests("biocore", requester_lab="castellani")
    assert len(out) == 1 and out[0].service == "centrifuge"


def test_iter_requests_exclude_terminal(world):
    _seed_three(world)
    out = SR.iter_requests("biocore", include_terminal=False)
    # itc (requested) is the only non-terminal; centrifuge (completed)
    # and cd (cancelled) drop out.
    assert [r.service for r in out] == ["itc"]


def test_iter_requests_unknown_core_empty(world):
    assert SR.iter_requests("ghost") == []


# ---- transition_request -------------------------------------------------

@pytest.mark.parametrize("path", [
    [SR.STATE_SCHEDULED],
    [SR.STATE_SCHEDULED, SR.STATE_IN_PROGRESS],
    [SR.STATE_SCHEDULED, SR.STATE_IN_PROGRESS, SR.STATE_COMPLETED],
    [SR.STATE_SCHEDULED, SR.STATE_CANCELLED],
    [SR.STATE_CANCELLED],   # straight cancel from requested
])
def test_transition_request_legal_paths(world, path):
    req = SR.create_request(core="biocore", service="itc",
                             requester="@alice", requester_lab="hallett")
    current = req
    for to in path:
        current = SR.transition_request(
            core="biocore", request_id=req.request_id, to_state=to,
        )
        assert current.state == to


def test_transition_request_illegal_from_requested(world):
    req = SR.create_request(core="biocore", service="itc",
                             requester="@alice", requester_lab="hallett")
    with pytest.raises(SR.RequestError, match="illegal transition"):
        SR.transition_request(core="biocore", request_id=req.request_id,
                                to_state=SR.STATE_COMPLETED)


def test_transition_request_refuses_from_terminal(world):
    req = SR.create_request(core="biocore", service="itc",
                             requester="@alice", requester_lab="hallett")
    SR.transition_request(core="biocore", request_id=req.request_id,
                           to_state=SR.STATE_CANCELLED)
    with pytest.raises(SR.RequestError):
        SR.transition_request(core="biocore", request_id=req.request_id,
                                to_state=SR.STATE_SCHEDULED)


def test_transition_request_unknown_state_raises(world):
    req = SR.create_request(core="biocore", service="itc",
                             requester="@alice", requester_lab="hallett")
    with pytest.raises(SR.RequestError, match="unknown state"):
        SR.transition_request(core="biocore", request_id=req.request_id,
                                to_state="approved")


def test_transition_request_missing_id_raises(world):
    with pytest.raises(SR.RequestError, match="request not found"):
        SR.transition_request(core="biocore", request_id="ghost",
                                to_state=SR.STATE_CANCELLED)


def test_transition_request_appends_note_to_body(world):
    req = SR.create_request(core="biocore", service="itc",
                             requester="@alice", requester_lab="hallett",
                             notes="initial brief")
    SR.transition_request(core="biocore", request_id=req.request_id,
                           to_state=SR.STATE_CANCELLED,
                           note="alice cancelled — schedule conflict")
    body = req.path.read_text(encoding="utf-8")
    assert "alice cancelled" in body
    assert "→ cancelled" in body


# ---- update_booking_slot ------------------------------------------------

def test_update_booking_slot_replaces_window(world):
    req = SR.create_request(
        core="biocore", service="itc",
        requester="@alice", requester_lab="hallett",
        booked_slot=SR.BookingSlot(start="2026-05-23T10:00-04:00",
                                    end="2026-05-23T11:00-04:00"),
    )
    new_slot = SR.BookingSlot(start="2026-05-24T14:00-04:00",
                                end="2026-05-24T15:30-04:00",
                                calendar_event_id="abc123")
    SR.update_booking_slot(core="biocore", request_id=req.request_id,
                             booked_slot=new_slot)
    rt = SR.get_request("biocore", req.request_id)
    assert rt.booked_slot.start.startswith("2026-05-24T14")
    assert rt.booked_slot.calendar_event_id == "abc123"
    # State unchanged (still scheduled).
    assert rt.state == SR.STATE_SCHEDULED


def test_update_booking_slot_unknown_request(world):
    with pytest.raises(SR.RequestError):
        SR.update_booking_slot(core="biocore", request_id="ghost",
                                 booked_slot=SR.BookingSlot())
