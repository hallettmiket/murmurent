"""
Phase 3e tests: cross-core browse + per-member request list endpoints.

Covers:
  - GET /api/cores/services returns one row per active service across
    every core; retired services are excluded.
  - When ?member=<h> provided, each row carries a ``can_book`` block
    matching training.check_service_prereqs (greys the Book button).
  - When ?member omitted, rows lack can_book (anonymous browse).
  - GET /api/member/<h>/requests returns only that member's bookings,
    excludes other members.
  - Live requests sorted by slot.start asc; terminal requests
    suppressed by default, included only with ?include_terminal=true.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
import yaml
from fastapi.testclient import TestClient

from wigamig.core import registrar as R
from wigamig.core import services as S
from wigamig.core import training as T
from wigamig.dashboard.server import create_app


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
    R.create_core(name="biocore", display_name="BioCORE",
                   leader_handle="@gary")
    R.create_core(name="genomics", display_name="Genomics Core",
                   leader_handle="@sam")
    for h in ("alice", "bob", "mhallet", "gary", "sam"):
        _write_member(tmp_path, h)
    # Two active services + one retired.
    T.training_dir("biocore").mkdir(parents=True, exist_ok=True)
    T.training_path("biocore", "itc_basic").write_text(
        "---\ntraining: itc_basic\nname: itc_basic\ncore: biocore\nstatus: active\n---\n",
        encoding="utf-8",
    )
    S.create_service(core="biocore", slug="itc", name="ITC",
                     training_required="itc_basic",
                     fee={"unit": "per_run",
                          "tiers": {"academic_internal": 80.0}})
    S.create_service(core="biocore", slug="cd", name="CD")
    S.create_service(core="biocore", slug="old", name="Old",
                     status="retired")
    S.create_service(core="genomics", slug="seq", name="Sequencing")
    return tmp_path


def _write_member(root, handle, *, trainings=None):
    meta = {"handle": f"@{handle}", "role": "postdoc", "status": "active"}
    if trainings is not None:
        meta["training"] = trainings
    (root / "lab-mgmt" / "members" / f"{handle}.md").write_text(
        f"---\n{yaml.safe_dump(meta, sort_keys=False).rstrip()}\n---\n",
        encoding="utf-8",
    )


# ---- /api/cores/services -----------------------------------------------

def test_list_cores_services_returns_active_only(world):
    client = TestClient(create_app())
    res = client.get("/api/cores/services")
    assert res.status_code == 200
    rows = res.json()["services"]
    slugs = sorted((r["core"], r["slug"]) for r in rows)
    assert slugs == [("biocore", "cd"), ("biocore", "itc"),
                     ("genomics", "seq")]
    # No can_book key when no member.
    assert "can_book" not in rows[0]


def test_list_cores_services_per_member_can_book(world):
    """alice has no training -> itc can_book=false; cd has no requirement
    so can_book=true."""
    client = TestClient(create_app())
    res = client.get("/api/cores/services?member=alice")
    assert res.status_code == 200
    rows = {(r["core"], r["slug"]): r for r in res.json()["services"]}
    assert rows[("biocore", "itc")]["can_book"]["ok"] is False
    assert "itc_basic" in rows[("biocore", "itc")]["can_book"]["reason"]
    assert rows[("biocore", "cd")]["can_book"]["ok"] is True


def test_list_cores_services_member_with_training(world):
    _write_member(world, "carol", trainings=[
        {"name": "itc_basic", "completed": "2025-11-15",
         "valid_until": "2030-11-15"},
    ])
    client = TestClient(create_app())
    res = client.get("/api/cores/services?member=carol")
    rows = {(r["core"], r["slug"]): r for r in res.json()["services"]}
    assert rows[("biocore", "itc")]["can_book"]["ok"] is True


# ---- /api/member/<h>/requests ------------------------------------------

@patch("wigamig.dashboard.slack_notify._post")
def test_member_requests_only_for_that_member(mock_post, world):
    client = TestClient(create_app())
    # alice books cd; bob books cd; alice books seq.
    for user in ("alice", "bob", "alice"):
        client.post(
            f"/api/core/biocore/services/cd/book?user={user}",
            json={"slot": {"start": "2026-05-23T10:00-04:00",
                           "end":   "2026-05-23T11:00-04:00"}},
        )
    client.post(
        "/api/core/genomics/services/seq/book?user=alice",
        json={"slot": {"start": "2026-05-25T10:00-04:00",
                       "end":   "2026-05-25T11:00-04:00"}},
    )
    res = client.get("/api/member/alice/requests")
    assert res.status_code == 200
    rows = res.json()["requests"]
    assert len(rows) == 3
    assert all(r["state"] == "scheduled" for r in rows)
    # Sorted ascending by start: 05-23 entries first, then 05-25.
    assert rows[0]["slot"]["start"].startswith("2026-05-23")
    assert rows[-1]["slot"]["start"].startswith("2026-05-25")
    assert {r["core"] for r in rows} == {"biocore", "genomics"}


@patch("wigamig.dashboard.slack_notify._post")
def test_member_requests_excludes_terminal_by_default(mock_post, world):
    client = TestClient(create_app())
    res_book = client.post(
        "/api/core/biocore/services/cd/book?user=alice",
        json={"slot": {"start": "2026-05-23T10:00-04:00",
                       "end":   "2026-05-23T11:00-04:00"}},
    )
    rid = res_book.json()["request_id"]
    client.post(f"/api/core/biocore/requests/{rid}/cancel?user=alice")
    # Default: terminal hidden.
    rows = client.get("/api/member/alice/requests").json()["requests"]
    assert rows == []
    # include_terminal=true brings it back.
    rows = client.get(
        "/api/member/alice/requests?include_terminal=true"
    ).json()["requests"]
    assert len(rows) == 1
    assert rows[0]["state"] == "cancelled"


def test_member_requests_unknown_member_empty(world):
    client = TestClient(create_app())
    rows = client.get("/api/member/nobody/requests").json()["requests"]
    assert rows == []
