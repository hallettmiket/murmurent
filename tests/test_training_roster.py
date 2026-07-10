"""
Tests for the per-core training roster (Phase 6++: training authority
moved from the member's lab file to the core's own records).

Covers:
  - record_training writes <lab_info>/cores/<c>/lab-mgmt/training_roster/<h>.md
  - record_training is idempotent (same slug replaces, new slug appends)
  - list_core_member_trainings reads back the records
  - has_completed_on_core respects valid_until
  - GET /api/core/<c>/training_roster (leader/registrar only)
  - POST /api/core/<c>/training/<slug>/record:
    - leader writes successfully
    - non-leader/non-registrar refused
    - 422 on missing member or completed date
    - 404 on unknown training catalog entry
    - valid_until auto-computed from refresher_years when omitted
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
import yaml
from fastapi.testclient import TestClient

from murmurent.core import registrar as R
from murmurent.core import training as T
from murmurent.dashboard.server import create_app


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(tmp_path / "lab_info"))
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("MURMURENT_USER", "the_pi")
    (tmp_path / "lab-mgmt" / "members").mkdir(parents=True)
    (tmp_path / "lab-mgmt" / "lab.md").write_text(
        "---\nlab: hallett\npi: '@the_pi'\n---\n", encoding="utf-8",
    )
    (tmp_path / "lab_info").mkdir(parents=True)
    (tmp_path / "lab_info" / "registrar").write_text("the_pi\n", encoding="utf-8")
    R.create_core(name="biocore", display_name="BioCORE", leader_handle="@gary")
    for h in ("alice", "the_pi", "gary", "bob"):
        (tmp_path / "lab-mgmt" / "members" / f"{h}.md").write_text(
            f"---\n{yaml.safe_dump({'handle': f'@{h}', 'role': 'postdoc', 'status': 'active'}, sort_keys=False).rstrip()}\n---\n",
            encoding="utf-8",
        )
    # Catalog entry so the record endpoint can resolve refresher_years.
    T.training_dir("biocore").mkdir(parents=True, exist_ok=True)
    T.training_path("biocore", "itc_basic").write_text(
        "---\ntraining: itc_basic\nname: ITC basic\ncore: biocore\n"
        "status: active\nrefresher_years: 2\ntrainers: ['@gary']\n"
        "location: Room 100\n---\n\n# itc basic\n",
        encoding="utf-8",
    )
    return tmp_path


# ---- helper -------------------------------------------------------------

def test_record_training_writes_roster_file(world):
    p = T.record_training(
        core="biocore", handle="@alice", training_slug="itc_basic",
        completed="2026-05-22", by="@gary", valid_until="2028-05-22",
    )
    assert p.is_file()
    assert p.parent.name == "training_roster"
    # File has the expected schema.
    parsed = yaml.safe_load(p.read_text(encoding="utf-8").split("---")[1])
    assert parsed["member"] == "@alice"
    assert parsed["core"] == "biocore"
    assert parsed["training"][0]["name"] == "itc_basic"


def test_record_training_idempotent_replace(world):
    T.record_training(
        core="biocore", handle="@alice", training_slug="itc_basic",
        completed="2020-01-01", by="@gary", valid_until="2022-01-01",
    )
    T.record_training(
        core="biocore", handle="@alice", training_slug="itc_basic",
        completed="2026-05-22", by="@gary", valid_until="2028-05-22",
    )
    rows = T.list_core_member_trainings("biocore", "alice")
    assert len(rows) == 1
    assert rows[0].completed == "2026-05-22"


def test_record_training_multiple_slugs_coexist(world):
    T.record_training(
        core="biocore", handle="@alice", training_slug="itc_basic",
        completed="2026-05-22", by="@gary",
    )
    T.record_training(
        core="biocore", handle="@alice", training_slug="centrifuge_basic",
        completed="2026-05-23", by="@gary",
    )
    names = sorted(r.name for r in T.list_core_member_trainings("biocore", "alice"))
    assert names == ["centrifuge_basic", "itc_basic"]


def test_has_completed_on_core_respects_expiry(world):
    T.record_training(
        core="biocore", handle="@alice", training_slug="itc_basic",
        completed="2020-01-01", by="@gary", valid_until="2022-01-01",
    )
    import datetime as _dt
    assert T.has_completed_on_core(
        "biocore", "@alice", "itc_basic",
        today=_dt.date(2026, 5, 23),
    ) is False


def test_list_core_member_trainings_missing_member(world):
    assert T.list_core_member_trainings("biocore", "ghost") == []


# ---- HTTP endpoints -----------------------------------------------------

def test_http_record_leader_passes(world):
    client = TestClient(create_app())
    res = client.post(
        "/api/core/biocore/training/itc_basic/record?user=gary",
        json={"member": "@alice", "completed": "2026-05-22"},
    )
    assert res.status_code == 200, res.text
    j = res.json()
    assert j["member"] == "alice"
    # valid_until auto-computed: completed + refresher_years (2) = 2028-05-22.
    assert j["valid_until"] == "2028-05-22"


def test_http_record_registrar_passes(world):
    client = TestClient(create_app())
    res = client.post(
        "/api/core/biocore/training/itc_basic/record?user=the_pi",
        json={"member": "@alice", "completed": "2026-05-22"},
    )
    assert res.status_code == 200


def test_http_record_outsider_forbidden(world):
    client = TestClient(create_app())
    res = client.post(
        "/api/core/biocore/training/itc_basic/record?user=alice",
        json={"member": "@bob", "completed": "2026-05-22"},
    )
    assert res.status_code == 403


def test_http_record_missing_fields(world):
    client = TestClient(create_app())
    res = client.post(
        "/api/core/biocore/training/itc_basic/record?user=gary",
        json={"member": "@alice"},   # no completed
    )
    assert res.status_code == 422


def test_http_record_unknown_training(world):
    client = TestClient(create_app())
    res = client.post(
        "/api/core/biocore/training/ghost/record?user=gary",
        json={"member": "@alice", "completed": "2026-05-22"},
    )
    assert res.status_code == 404


def test_http_record_explicit_valid_until(world):
    client = TestClient(create_app())
    res = client.post(
        "/api/core/biocore/training/itc_basic/record?user=gary",
        json={"member": "@alice", "completed": "2026-05-22",
              "valid_until": "2027-05-22", "notes": "passed quiz"},
    )
    assert res.json()["valid_until"] == "2027-05-22"


def test_http_roster_leader_lists_members(world):
    T.record_training(
        core="biocore", handle="@alice", training_slug="itc_basic",
        completed="2026-05-22", by="@gary", valid_until="2028-05-22",
    )
    T.record_training(
        core="biocore", handle="@bob", training_slug="itc_basic",
        completed="2025-01-15", by="@gary", valid_until="2027-01-15",
    )
    client = TestClient(create_app())
    res = client.get("/api/core/biocore/training_roster?user=gary")
    assert res.status_code == 200
    rows = {r["handle"]: r for r in res.json()["members"]}
    assert "@alice" in rows and "@bob" in rows
    assert rows["@alice"]["trainings"][0]["is_current"] is True


def test_http_roster_outsider_forbidden(world):
    client = TestClient(create_app())
    res = client.get("/api/core/biocore/training_roster?user=alice")
    assert res.status_code == 403


def test_http_roster_unknown_core_404(world):
    client = TestClient(create_app())
    res = client.get("/api/core/ghost/training_roster?user=gary")
    assert res.status_code == 404
