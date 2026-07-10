"""
Phase 4d tests: GET /api/lab/<lab>/core_charges aggregator.

Covers:
  - returns one row per core that has billed this lab in the month
  - excludes cores with no lines (or only OTHER labs' lines)
  - total sums subtotals; unconfirmed counts flagged lines
  - month defaults to current YYYY-MM
  - bad month -> 422
"""

from __future__ import annotations

import datetime as _dt

import pytest
import yaml
from fastapi.testclient import TestClient

from murmurent.core import registrar as R
from murmurent.core import service_requests as SR
from murmurent.core import services as S
from murmurent.dashboard.server import create_app


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(tmp_path / "lab_info"))
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("MURMURENT_USER", "mhallet")
    (tmp_path / "lab-mgmt" / "members").mkdir(parents=True)
    (tmp_path / "lab-mgmt" / "lab.md").write_text(
        "---\nlab: hallett\npi: '@mhallet'\n---\n", encoding="utf-8",
    )
    (tmp_path / "lab_info").mkdir(parents=True)
    (tmp_path / "lab_info" / "registrar").write_text("mhallet\n", encoding="utf-8")
    R.create_core(name="biocore", display_name="BioCORE", leader_handle="@gary")
    R.create_core(name="genomics", display_name="Genomics", leader_handle="@sam")
    S.create_service(core="biocore", slug="itc", name="ITC")
    S.create_service(core="genomics", slug="seq", name="Sequencing")
    return tmp_path


def _bill(core, lab, total, confirmed=True,
           start="2026-05-23T10:00-04:00", service="itc"):
    req = SR.create_request(
        core=core, service=service, requester="@alice", requester_lab=lab,
        booked_slot=SR.BookingSlot(start=start,
                                     end=start.replace("10:00", "11:00")),
        fee_at_booking=SR.FeeSnapshot(tier="academic_internal",
                                        unit="per_run",
                                        base=total, total=total),
    )
    SR.transition_request(core=core, request_id=req.request_id,
                            to_state=SR.STATE_IN_PROGRESS)
    SR.transition_request(core=core, request_id=req.request_id,
                            to_state=SR.STATE_COMPLETED)
    if confirmed:
        SR.set_actual_charge(
            core=core, request_id=req.request_id,
            charge=SR.FeeSnapshot(tier="academic_internal", unit="per_run",
                                    base=total, total=total),
            confirmed_by="@gary",
        )


def test_aggregates_across_cores(world):
    _bill("biocore",  "hallett", 100.0)
    _bill("genomics", "hallett", 500.0, service="seq")
    _bill("biocore",  "castellani", 80.0)   # different lab; excluded
    client = TestClient(create_app())
    res = client.get("/api/lab/hallett/core_charges?month=2026-05")
    assert res.status_code == 200, res.text
    j = res.json()
    cores = {c["core"]: c for c in j["cores"]}
    assert sorted(cores) == ["biocore", "genomics"]
    assert cores["genomics"]["subtotal"] == 500.0
    assert j["total"] == 600.0


def test_empty_when_lab_has_no_charges(world):
    _bill("biocore", "castellani", 80.0)
    client = TestClient(create_app())
    res = client.get("/api/lab/hallett/core_charges?month=2026-05")
    assert res.status_code == 200
    assert res.json()["cores"] == []
    assert res.json()["total"] == 0.0


def test_unconfirmed_count_propagates(world):
    _bill("biocore", "hallett", 80.0, confirmed=False)
    client = TestClient(create_app())
    res = client.get("/api/lab/hallett/core_charges?month=2026-05")
    assert res.json()["unconfirmed"] == 1
    assert res.json()["cores"][0]["unconfirmed"] == 1


def test_default_month_is_current(world):
    """Without ?month=, the endpoint returns today's YYYY-MM."""
    client = TestClient(create_app())
    res = client.get("/api/lab/hallett/core_charges")
    assert res.status_code == 200
    now = _dt.datetime.now(_dt.timezone.utc)
    assert res.json()["month"] == f"{now.year:04d}-{now.month:02d}"


def test_bad_month_returns_422(world):
    client = TestClient(create_app())
    res = client.get("/api/lab/hallett/core_charges?month=2026-13")
    assert res.status_code == 422
