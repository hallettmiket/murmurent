"""
Phase 3f tests: GET /api/core/<core>/requests inbox endpoint.

Covers:
  - 403 when actor is neither leader nor registrar
  - 200 for leader (gary)
  - 200 for registrar (mhallet)
  - 404 for unknown core
  - state filter narrows the result
  - include_terminal=false hides completed/cancelled
  - Ordering: live first by slot.start asc, terminal by updated desc
  - counts block reports live/terminal split
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
import yaml
from fastapi.testclient import TestClient

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
    for h in ("alice", "bob", "mhallet", "gary"):
        (tmp_path / "lab-mgmt" / "members" / f"{h}.md").write_text(
            f"---\n{yaml.safe_dump({'handle': f'@{h}', 'role': 'postdoc', 'status': 'active'}, sort_keys=False).rstrip()}\n---\n",
            encoding="utf-8",
        )
    S.create_service(core="biocore", slug="itc", name="ITC")
    return tmp_path


@patch("murmurent.dashboard.slack_notify._post")
def _seed_bookings(mock_post, client):
    """Three back-to-back hour slots: alice@10-11 (live), bob@11-12
    (cancelled), alice@12-13 (completed)."""
    for user, start, end, terminal in [
        ("alice", "2026-05-23T10:00-04:00", "2026-05-23T11:00-04:00", None),
        ("bob",   "2026-05-23T11:00-04:00", "2026-05-23T12:00-04:00", "cancel"),
        ("alice", "2026-05-23T12:00-04:00", "2026-05-23T13:00-04:00", "complete"),
    ]:
        res = client.post(
            f"/api/core/biocore/services/itc/book?user={user}",
            json={"slot": {"start": start, "end": end}},
        )
        rid = res.json()["request_id"]
        if terminal == "cancel":
            client.post(f"/api/core/biocore/requests/{rid}/cancel?user={user}")
        elif terminal == "complete":
            client.post(f"/api/core/biocore/requests/{rid}/advance?user=gary")
            client.post(f"/api/core/biocore/requests/{rid}/advance?user=gary")


# ---- permission ---------------------------------------------------------

def test_inbox_forbidden_for_outsider(world):
    client = TestClient(create_app())
    res = client.get("/api/core/biocore/requests?user=alice")
    assert res.status_code == 403


def test_inbox_404_for_unknown_core(world):
    client = TestClient(create_app())
    res = client.get("/api/core/ghost/requests?user=gary")
    assert res.status_code == 404


def test_inbox_ok_for_leader(world):
    client = TestClient(create_app())
    res = client.get("/api/core/biocore/requests?user=gary")
    assert res.status_code == 200
    assert res.json()["requests"] == []
    assert res.json()["counts"] == {"live": 0, "terminal": 0}


@patch("murmurent.dashboard.slack_notify._post")
def test_inbox_ok_for_registrar(mock_post, world):
    client = TestClient(create_app())
    res = client.get("/api/core/biocore/requests?user=mhallet")
    assert res.status_code == 200


# ---- listing / filtering ------------------------------------------------

@patch("murmurent.dashboard.slack_notify._post")
def test_inbox_orders_live_first_then_terminal(mock_post, world):
    client = TestClient(create_app())
    _seed_bookings.__wrapped__(mock_post, client)
    res = client.get("/api/core/biocore/requests?user=gary")
    rows = res.json()["requests"]
    assert len(rows) == 3
    assert rows[0]["state"] == "scheduled"
    # Terminal rows trail (cancelled + completed, order by updated desc).
    assert {rows[1]["state"], rows[2]["state"]} == {"cancelled", "completed"}
    counts = res.json()["counts"]
    assert counts == {"live": 1, "terminal": 2}


@patch("murmurent.dashboard.slack_notify._post")
def test_inbox_include_terminal_false_hides_them(mock_post, world):
    client = TestClient(create_app())
    _seed_bookings.__wrapped__(mock_post, client)
    res = client.get(
        "/api/core/biocore/requests?user=gary&include_terminal=false",
    )
    rows = res.json()["requests"]
    assert [r["state"] for r in rows] == ["scheduled"]


@patch("murmurent.dashboard.slack_notify._post")
def test_inbox_state_filter(mock_post, world):
    client = TestClient(create_app())
    _seed_bookings.__wrapped__(mock_post, client)
    res = client.get(
        "/api/core/biocore/requests?user=gary&state=cancelled",
    )
    rows = res.json()["requests"]
    assert len(rows) == 1 and rows[0]["state"] == "cancelled"
