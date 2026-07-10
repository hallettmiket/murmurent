"""
Phase 4c tests: HTTP invoice preview + generate endpoints.

Covers:
  - preview: leader/registrar OK; outsider 403; unknown core 404
  - preview: bad month -> 422
  - preview: returns per-lab rows + total + unconfirmed count
  - generate: writes the expected files; returns paths
  - generate: empty month returns ok with empty written list
  - finalised toggle propagates to gather_invoices
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
import yaml
from fastapi.testclient import TestClient

from murmurent.core import invoices as INV
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
    for h in ("alice", "bob", "the_pi", "gary"):
        (tmp_path / "lab-mgmt" / "members" / f"{h}.md").write_text(
            f"---\n{yaml.safe_dump({'handle': f'@{h}', 'role': 'postdoc', 'status': 'active'}, sort_keys=False).rstrip()}\n---\n",
            encoding="utf-8",
        )
    S.create_service(core="biocore", slug="itc", name="ITC")
    return tmp_path


def _seed():
    """One confirmed line + one unconfirmed line in 2026-05."""
    for actual in (100.0, None):
        req = SR.create_request(
            core="biocore", service="itc",
            requester="@alice", requester_lab="hallett",
            booked_slot=SR.BookingSlot(
                start="2026-05-23T10:00-04:00",
                end="2026-05-23T11:00-04:00",
            ),
            fee_at_booking=SR.FeeSnapshot(
                tier="academic_internal", unit="per_run",
                base=80.0, total=80.0,
            ),
        )
        SR.transition_request(core="biocore", request_id=req.request_id,
                                to_state=SR.STATE_IN_PROGRESS)
        SR.transition_request(core="biocore", request_id=req.request_id,
                                to_state=SR.STATE_COMPLETED)
        if actual is not None:
            SR.set_actual_charge(
                core="biocore", request_id=req.request_id,
                charge=SR.FeeSnapshot(tier="academic_internal", unit="per_run",
                                        base=80.0, total=actual),
                confirmed_by="@gary",
            )


# ---- preview ------------------------------------------------------------

def test_preview_outsider_forbidden(world):
    _seed()
    client = TestClient(create_app())
    res = client.get(
        "/api/core/biocore/invoices/2026-05/preview?user=alice",
    )
    assert res.status_code == 403


def test_preview_unknown_core(world):
    client = TestClient(create_app())
    res = client.get(
        "/api/core/ghost/invoices/2026-05/preview?user=gary",
    )
    assert res.status_code == 404


def test_preview_bad_month(world):
    client = TestClient(create_app())
    res = client.get(
        "/api/core/biocore/invoices/2026-13/preview?user=gary",
    )
    assert res.status_code == 422


def test_preview_summary(world):
    _seed()
    client = TestClient(create_app())
    res = client.get(
        "/api/core/biocore/invoices/2026-05/preview?user=gary",
    )
    assert res.status_code == 200, res.text
    j = res.json()
    assert len(j["labs"]) == 1
    assert j["labs"][0]["lab"] == "hallett"
    assert j["labs"][0]["lines"] == 2
    assert j["labs"][0]["unconfirmed"] == 1
    assert j["total"] == 180.0   # 100 (confirmed) + 80 (booked fallback)
    assert j["unconfirmed"] == 1


def test_preview_finalised_drops_unconfirmed(world):
    _seed()
    client = TestClient(create_app())
    res = client.get(
        "/api/core/biocore/invoices/2026-05/preview?user=gary&finalised=true",
    )
    assert res.json()["total"] == 100.0
    assert res.json()["unconfirmed"] == 0


# ---- generate -----------------------------------------------------------

def test_generate_writes_files(world):
    _seed()
    client = TestClient(create_app())
    res = client.post(
        "/api/core/biocore/invoices/2026-05/generate?user=gary",
    )
    assert res.status_code == 200, res.text
    j = res.json()
    assert j["labs"] == ["hallett"]
    assert any(p.endswith("hallett.csv") for p in j["written"])
    assert any(p.endswith("summary.md") for p in j["written"])
    base = INV.invoices_dir("biocore") / "2026-05"
    assert (base / "hallett.md").is_file()


def test_generate_empty_month_ok(world):
    client = TestClient(create_app())
    res = client.post(
        "/api/core/biocore/invoices/2026-05/generate?user=gary",
    )
    assert res.status_code == 200
    assert res.json()["written"] == []


def test_generate_outsider_forbidden(world):
    _seed()
    client = TestClient(create_app())
    res = client.post(
        "/api/core/biocore/invoices/2026-05/generate?user=alice",
    )
    assert res.status_code == 403


def test_generate_finalised_only(world):
    _seed()
    client = TestClient(create_app())
    res = client.post(
        "/api/core/biocore/invoices/2026-05/generate?user=gary",
        json={"finalised": True},
    )
    assert res.json()["total"] == 100.0
