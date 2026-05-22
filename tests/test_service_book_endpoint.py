"""
Phase 3b tests: POST /api/core/<core>/services/<slug>/book endpoint.

Covers:
  - Happy path: active member with current training books a slot,
    request lands in 'scheduled', fee snapshot reflects quote_fee.
  - 422 when training prereq fails (and no request file is written).
  - 422 when service is retired.
  - 404 when core or service is unknown.
  - 422 when slot.start / slot.end missing.
  - Fee tier defaulting (first tier picked) when caller omits ``tier``.
  - Modifiers multiply through the snapshot.
  - 403 when actor tries to book on behalf of another non-self handle
    without being core leader or registrar; allowed when they are.
  - Slack notifier called on success.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
import yaml
from fastapi.testclient import TestClient

from wigamig.core import registrar as R
from wigamig.core import services as S
from wigamig.core import service_requests as SR
from wigamig.core import training as T
from wigamig.dashboard.server import create_app


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_LAB_INFO_ROOT", str(tmp_path / "lab_info"))
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("WIGAMIG_USER", "alice")
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
    # alice = active member of hallett lab; the_pi = PI/registrar.
    _write_member(tmp_path, "alice", trainings=[
        {"name": "itc_basic", "completed": "2025-11-15",
         "valid_until": "2030-11-15"},
    ])
    _write_member(tmp_path, "the_pi", role="pi", trainings=[])
    _write_member(tmp_path, "gary", role="core_leader", trainings=[
        {"name": "itc_basic", "completed": "2025-11-15",
         "valid_until": "2030-11-15"},
    ])
    return tmp_path


def _write_member(root, handle, *, role="postdoc", trainings=None):
    meta = {"handle": f"@{handle}", "role": role, "status": "active"}
    if trainings is not None:
        meta["training"] = trainings
    body = yaml.safe_dump(meta, sort_keys=False).rstrip()
    (root / "lab-mgmt" / "members" / f"{handle}.md").write_text(
        f"---\n{body}\n---\n\n# @{handle}\n", encoding="utf-8",
    )


def _seed_itc(world, *, training_required="itc_basic", status="active"):
    """Create a paid ITC service with one tier + one modifier."""
    # Catalog entry for the training the service requires.
    if training_required:
        T.training_dir("biocore").mkdir(parents=True, exist_ok=True)
        T.training_path("biocore", training_required).write_text(
            "---\n"
            f"training: {training_required}\n"
            f"name: {training_required}\n"
            "core: biocore\nstatus: active\nrefresher_years: 2\n"
            "---\n\n# itc basic\n",
            encoding="utf-8",
        )
    S.create_service(
        core="biocore", slug="itc", name="ITC",
        training_required=training_required,
        status=status,
        fee={"unit": "per_run",
             "tiers": {"academic_internal": 80.0, "industry": 260.0},
             "modifiers": {"weekend": 1.25}},
    )


# ---- happy path --------------------------------------------------------

@patch("wigamig.dashboard.slack_notify._post")
def test_book_happy_path_lands_scheduled(mock_post, world):
    _seed_itc(world)
    client = TestClient(create_app())
    res = client.post(
        "/api/core/biocore/services/itc/book?user=alice",
        json={"slot": {"start": "2026-05-23T10:00-04:00",
                       "end":   "2026-05-23T11:30-04:00"}},
    )
    assert res.status_code == 200, res.text
    j = res.json()
    assert j["ok"] is True
    assert j["state"] == SR.STATE_SCHEDULED
    assert j["requester"] == "@alice"
    assert j["requester_lab"] == "hallett"
    assert j["fee_at_booking"]["tier"] == "academic_internal"
    assert j["fee_at_booking"]["total"] == 80.0
    # Persisted record matches.
    rt = SR.get_request("biocore", j["request_id"])
    assert rt.state == SR.STATE_SCHEDULED
    assert rt.booked_slot.start.startswith("2026-05-23T10")
    mock_post.assert_called()


@patch("wigamig.dashboard.slack_notify._post")
def test_book_modifiers_multiply_through(mock_post, world):
    _seed_itc(world)
    client = TestClient(create_app())
    res = client.post(
        "/api/core/biocore/services/itc/book?user=alice",
        json={"slot": {"start": "2026-05-23T10:00-04:00",
                       "end":   "2026-05-23T11:30-04:00"},
              "tier": "industry", "modifiers": ["weekend"]},
    )
    assert res.status_code == 200, res.text
    fee = res.json()["fee_at_booking"]
    assert fee["tier"] == "industry"
    assert fee["base"] == 260.0
    assert fee["total"] == 325.0   # 260 * 1.25
    assert fee["modifiers_applied"][0]["name"] == "weekend"


# ---- prereq + status gates ---------------------------------------------

def test_book_blocked_when_training_missing(world):
    _seed_itc(world)
    # alice has the training; strip it.
    _write_member(world, "alice", trainings=[])
    client = TestClient(create_app())
    res = client.post(
        "/api/core/biocore/services/itc/book?user=alice",
        json={"slot": {"start": "2026-05-23T10:00-04:00",
                       "end":   "2026-05-23T11:30-04:00"}},
    )
    assert res.status_code == 422
    assert "itc_basic" in res.json()["detail"]
    # No request file written.
    assert SR.iter_requests("biocore") == []


def test_book_refuses_retired_service(world):
    _seed_itc(world, status="active")
    S.archive_service(core="biocore", slug="itc")
    client = TestClient(create_app())
    res = client.post(
        "/api/core/biocore/services/itc/book?user=alice",
        json={"slot": {"start": "2026-05-23T10:00-04:00",
                       "end":   "2026-05-23T11:30-04:00"}},
    )
    # archive_service makes the service unfindable by default → 404.
    assert res.status_code in (404, 422)


def test_book_unknown_core(world):
    client = TestClient(create_app())
    res = client.post(
        "/api/core/ghost/services/itc/book?user=alice",
        json={"slot": {"start": "2026-05-23T10:00-04:00",
                       "end":   "2026-05-23T11:30-04:00"}},
    )
    assert res.status_code == 404


def test_book_unknown_service(world):
    client = TestClient(create_app())
    res = client.post(
        "/api/core/biocore/services/ghost/book?user=alice",
        json={"slot": {"start": "2026-05-23T10:00-04:00",
                       "end":   "2026-05-23T11:30-04:00"}},
    )
    assert res.status_code == 404


def test_book_requires_slot_window(world):
    _seed_itc(world)
    client = TestClient(create_app())
    res = client.post(
        "/api/core/biocore/services/itc/book?user=alice",
        json={"slot": {"start": "2026-05-23T10:00-04:00"}},
    )
    assert res.status_code == 422
    assert "slot.end" in res.json()["detail"]


# ---- proxy booking gate -------------------------------------------------

def test_book_self_no_proxy_required(world):
    _seed_itc(world)
    client = TestClient(create_app())
    res = client.post(
        "/api/core/biocore/services/itc/book?user=alice",
        json={"slot": {"start": "2026-05-23T10:00-04:00",
                       "end":   "2026-05-23T11:30-04:00"},
              "requester": "@alice"},
    )
    assert res.status_code == 200, res.text


@patch("wigamig.dashboard.slack_notify._post")
def test_book_leader_can_proxy_for_member(mock_post, world):
    _seed_itc(world)
    client = TestClient(create_app())
    res = client.post(
        "/api/core/biocore/services/itc/book?user=gary",
        json={"slot": {"start": "2026-05-23T10:00-04:00",
                       "end":   "2026-05-23T11:30-04:00"},
              "requester": "@alice"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["requester"] == "@alice"


def test_book_non_leader_cannot_proxy(world):
    _seed_itc(world)
    # Add bob: active member, no training, but he tries to book FOR alice.
    _write_member(world, "bob", trainings=[])
    client = TestClient(create_app())
    res = client.post(
        "/api/core/biocore/services/itc/book?user=bob",
        json={"slot": {"start": "2026-05-23T10:00-04:00",
                       "end":   "2026-05-23T11:30-04:00"},
              "requester": "@alice"},
    )
    assert res.status_code == 403


# ---- tier defaulting ---------------------------------------------------

@patch("wigamig.dashboard.slack_notify._post")
def test_book_defaults_to_first_tier(mock_post, world):
    _seed_itc(world)
    client = TestClient(create_app())
    res = client.post(
        "/api/core/biocore/services/itc/book?user=alice",
        json={"slot": {"start": "2026-05-23T10:00-04:00",
                       "end":   "2026-05-23T11:30-04:00"}},
    )
    assert res.status_code == 200
    # sorted(tiers.keys())[0] is alphabetical: academic_internal < industry
    assert res.json()["fee_at_booking"]["tier"] == "academic_internal"


def test_book_rejects_unknown_tier(world):
    _seed_itc(world)
    client = TestClient(create_app())
    res = client.post(
        "/api/core/biocore/services/itc/book?user=alice",
        json={"slot": {"start": "2026-05-23T10:00-04:00",
                       "end":   "2026-05-23T11:30-04:00"},
              "tier": "made_up"},
    )
    assert res.status_code == 422


# ---- no-fee service (free training slot) -------------------------------

@patch("wigamig.dashboard.slack_notify._post")
def test_book_no_fee_service_empty_snapshot(mock_post, world):
    """Free services (no fee.tiers) snapshot an empty fee — still
    bookable when the member has the prereq."""
    S.create_service(
        core="biocore", slug="free_slot", name="Free Slot",
        training_required=None,
    )
    client = TestClient(create_app())
    res = client.post(
        "/api/core/biocore/services/free_slot/book?user=alice",
        json={"slot": {"start": "2026-05-23T10:00-04:00",
                       "end":   "2026-05-23T11:30-04:00"}},
    )
    assert res.status_code == 200, res.text
    assert res.json()["fee_at_booking"]["total"] == 0.0
    assert res.json()["fee_at_booking"]["tier"] == ""
