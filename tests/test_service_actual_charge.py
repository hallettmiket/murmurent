"""
Phase 4a tests: leader confirms post-run actual charge.

Covers:
  - set_actual_charge helper persists FeeSnapshot + confirmed_by/_at
  - get_request roundtrips actual_charge from disk
  - Body appended with audit line
  - PATCH endpoint: leader passes, requester forbidden, outsider 403
  - Endpoint defaults missing tier/unit/base from fee_at_booking
  - Endpoint rejects missing/negative total
  - Endpoint allowed in any state (scheduled, in_progress, completed)
  - Slack notify fires with overtime/refund delta
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
import yaml
from fastapi.testclient import TestClient

from wigamig.core import registrar as R
from wigamig.core import service_requests as SR
from wigamig.core import services as S
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
    R.create_core(name="biocore", display_name="BioCORE", leader_handle="@gary")
    for h in ("alice", "bob", "mhallet", "gary"):
        (tmp_path / "lab-mgmt" / "members" / f"{h}.md").write_text(
            f"---\n{yaml.safe_dump({'handle': f'@{h}', 'role': 'postdoc', 'status': 'active'}, sort_keys=False).rstrip()}\n---\n",
            encoding="utf-8",
        )
    S.create_service(
        core="biocore", slug="itc", name="ITC",
        fee={"unit": "per_run",
             "tiers": {"academic_internal": 80.0}},
    )
    return tmp_path


def _book(client, user="alice"):
    res = client.post(
        f"/api/core/biocore/services/itc/book?user={user}",
        json={"slot": {"start": "2026-05-23T10:00-04:00",
                       "end":   "2026-05-23T11:00-04:00"}},
    )
    return res.json()["request_id"]


# ---- helper -------------------------------------------------------------

@patch("wigamig.dashboard.slack_notify._post")
def test_set_actual_charge_persists_and_audits(mock_post, world):
    client = TestClient(create_app())
    rid = _book(client)
    SR.set_actual_charge(
        core="biocore", request_id=rid,
        charge=SR.FeeSnapshot(tier="academic_internal", unit="per_run",
                                base=80.0, total=100.0),
        confirmed_by="@gary", note="ran 30 min over",
    )
    rt = SR.get_request("biocore", rid)
    assert rt.actual_charge is not None
    assert rt.actual_charge.total == 100.0
    assert rt.actual_charge_confirmed_by == "gary"
    assert rt.actual_charge_confirmed_at  # non-empty ISO
    assert "ran 30 min over" in rt.path.read_text(encoding="utf-8")


def test_set_actual_charge_unknown_request(world):
    with pytest.raises(SR.RequestError):
        SR.set_actual_charge(
            core="biocore", request_id="ghost",
            charge=SR.FeeSnapshot(total=1.0),
            confirmed_by="@gary",
        )


# ---- endpoint -----------------------------------------------------------

@patch("wigamig.dashboard.slack_notify._post")
def test_endpoint_leader_passes(mock_post, world):
    client = TestClient(create_app())
    rid = _book(client)
    res = client.patch(
        f"/api/core/biocore/requests/{rid}/actual_charge?user=gary",
        json={"total": 95.5, "note": "minor overtime"},
    )
    assert res.status_code == 200, res.text
    j = res.json()
    assert j["actual_charge"]["total"] == 95.5
    assert j["actual_charge"]["tier"] == "academic_internal"  # defaulted
    assert j["actual_charge_confirmed_by"] == "gary"
    mock_post.assert_called()


@patch("wigamig.dashboard.slack_notify._post")
def test_endpoint_registrar_passes(mock_post, world):
    client = TestClient(create_app())
    rid = _book(client)
    res = client.patch(
        f"/api/core/biocore/requests/{rid}/actual_charge?user=mhallet",
        json={"total": 80.0},
    )
    assert res.status_code == 200


def test_endpoint_requester_forbidden(world):
    client = TestClient(create_app())
    rid = _book(client)
    res = client.patch(
        f"/api/core/biocore/requests/{rid}/actual_charge?user=alice",
        json={"total": 80.0},
    )
    assert res.status_code == 403


def test_endpoint_outsider_forbidden(world):
    client = TestClient(create_app())
    rid = _book(client)
    res = client.patch(
        f"/api/core/biocore/requests/{rid}/actual_charge?user=bob",
        json={"total": 80.0},
    )
    assert res.status_code == 403


def test_endpoint_unknown_request(world):
    client = TestClient(create_app())
    res = client.patch(
        "/api/core/biocore/requests/ghost/actual_charge?user=gary",
        json={"total": 80.0},
    )
    assert res.status_code == 404


def test_endpoint_requires_total(world):
    client = TestClient(create_app())
    rid = _book(client)
    res = client.patch(
        f"/api/core/biocore/requests/{rid}/actual_charge?user=gary",
        json={"note": "no number"},
    )
    assert res.status_code == 422


@pytest.mark.parametrize("bad", [-1.0, "not a number"])
def test_endpoint_rejects_bad_total(world, bad):
    client = TestClient(create_app())
    rid = _book(client)
    res = client.patch(
        f"/api/core/biocore/requests/{rid}/actual_charge?user=gary",
        json={"total": bad},
    )
    assert res.status_code == 422


@patch("wigamig.dashboard.slack_notify._post")
def test_endpoint_allowed_after_completed(mock_post, world):
    """Charges often confirmed AFTER a run completes; verify state is
    not a barrier."""
    client = TestClient(create_app())
    rid = _book(client)
    client.post(f"/api/core/biocore/requests/{rid}/advance?user=gary")
    client.post(f"/api/core/biocore/requests/{rid}/advance?user=gary")
    assert SR.get_request("biocore", rid).state == SR.STATE_COMPLETED
    res = client.patch(
        f"/api/core/biocore/requests/{rid}/actual_charge?user=gary",
        json={"total": 80.0},
    )
    assert res.status_code == 200


@patch("wigamig.dashboard.slack_notify._post")
def test_endpoint_slack_delta_overtime(mock_post, world):
    client = TestClient(create_app())
    rid = _book(client)
    client.patch(
        f"/api/core/biocore/requests/{rid}/actual_charge?user=gary",
        json={"total": 100.0, "note": "overtime"},
    )
    msg = mock_post.call_args.args[1]
    assert "+$20.00" in msg
    assert "overtime" in msg
