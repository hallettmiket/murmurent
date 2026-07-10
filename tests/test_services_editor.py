"""
Phase 2c tests: service catalog write helpers + HTTP editor endpoints.

Covers:
  - create_service / update_service / archive_service helpers
  - Slug validation (rejects bad chars, uppercase, leading dash)
  - Duplicate slug refused
  - Unknown core refused
  - update_service replaces top-level keys; missing slug refused
  - archive_service flips status to retired
  - HTTP endpoints (POST/PATCH/POST .../archive)
  - Permission gate: core leader OR registrar passes; others 403
  - Slack notifications fire on each mutation
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from murmurent.core import registrar as R
from murmurent.core import services as S
from murmurent.dashboard.server import create_app


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(tmp_path / "lab_info"))
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("MURMURENT_USER", "the_pi")
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


# ---- create_service helper -----------------------------------------------

def test_create_service_writes_file_and_commits(world):
    path = S.create_service(
        core="biocore", slug="itc_demo", name="ITC Demo",
        capability="structure_function_interaction",
        fee={"unit": "per_run",
             "tiers": {"academic_internal": 80.0, "industry": 260.0}},
    )
    assert path.is_file()
    out = S.iter_services("biocore")
    assert len(out) == 1 and out[0].slug == "itc_demo"
    assert out[0].fee.tiers["academic_internal"] == 80.0


def test_create_service_refuses_duplicate_slug(world):
    S.create_service(core="biocore", slug="dup", name="First")
    with pytest.raises(S.ServiceError, match="already exists"):
        S.create_service(core="biocore", slug="dup", name="Second")


def test_create_service_refuses_unknown_core(world):
    with pytest.raises(R.LabNotFound):
        S.create_service(core="ghost", slug="valid_slug", name="X")


@pytest.mark.parametrize("bad", [
    "_leading",       # leading underscore
    "-dash",          # dash not allowed
    "with space",     # space
    "",               # empty
    "a",              # too short (min 2 chars)
])
def test_create_service_rejects_bad_slugs(world, bad):
    with pytest.raises(S.ServiceError, match="slug must match"):
        S.create_service(core="biocore", slug=bad, name="X")


def test_create_service_auto_lowercases_slug(world):
    """UPPERCASE -> lowercase is a friendly normalisation, not an error."""
    p = S.create_service(core="biocore", slug="MIXED_Case", name="X")
    assert p.name == "mixed_case.md"


def test_create_service_rejects_bad_status(world):
    with pytest.raises(S.ServiceError, match="status must be one of"):
        S.create_service(core="biocore", slug="x1", name="X",
                          status="zombie")


# ---- update_service helper -----------------------------------------------

def test_update_service_merges_top_level_fields(world):
    S.create_service(core="biocore", slug="abc", name="Original")
    S.update_service(core="biocore", slug="abc",
                     patch={"name": "Renamed", "description": "new"})
    out = S.get_service("biocore", "abc")
    assert out.name == "Renamed"
    assert out.description == "new"


def test_update_service_replaces_fee_block_wholesale(world):
    S.create_service(core="biocore", slug="abc", name="X",
                     fee={"unit": "per_run",
                          "tiers": {"academic_internal": 80.0}})
    S.update_service(core="biocore", slug="abc",
                     patch={"fee": {"unit": "per_hour",
                                    "tiers": {"industry": 200.0}}})
    out = S.get_service("biocore", "abc")
    assert out.fee.unit == "per_hour"
    assert "academic_internal" not in out.fee.tiers


def test_update_service_unknown_slug_refused(world):
    with pytest.raises(S.ServiceError, match="not found"):
        S.update_service(core="biocore", slug="ghost", patch={"name": "x"})


def test_update_service_validates_status(world):
    S.create_service(core="biocore", slug="abc", name="X")
    with pytest.raises(S.ServiceError, match="status must be one of"):
        S.update_service(core="biocore", slug="abc",
                          patch={"status": "deleted"})


# ---- archive_service -----------------------------------------------------

def test_archive_service_flips_status(world):
    S.create_service(core="biocore", slug="abc", name="X")
    S.archive_service(core="biocore", slug="abc")
    # Now hidden from default list.
    assert S.iter_services("biocore") == []
    # But still findable with include_retired.
    out = S.iter_services("biocore", include_retired=True)
    assert len(out) == 1 and out[0].status == "retired"


# ---- HTTP endpoints ------------------------------------------------------

@patch("murmurent.dashboard.slack_notify._post")
def test_http_create_as_registrar(mock_post, world):
    client = TestClient(create_app())
    res = client.post(
        "/api/core/biocore/services?user=the_pi",
        json={"slug": "x1", "name": "X1",
              "fee": {"unit": "per_run", "tiers": {"academic_internal": 50}}},
    )
    assert res.status_code == 200, res.text
    assert res.json()["ok"] is True
    mock_post.assert_called()


@patch("murmurent.dashboard.slack_notify._post")
def test_http_create_as_core_leader(mock_post, world):
    client = TestClient(create_app())
    res = client.post(
        "/api/core/biocore/services?user=gary",  # gary is the bioCORE leader
        json={"slug": "x2", "name": "X2"},
    )
    assert res.status_code == 200, res.text
    mock_post.assert_called()


def test_http_create_rejects_other_handle(world):
    client = TestClient(create_app())
    res = client.post(
        "/api/core/biocore/services?user=random_user",
        json={"slug": "x3", "name": "X3"},
    )
    assert res.status_code == 403


def test_http_create_missing_required_fields(world):
    client = TestClient(create_app())
    res = client.post(
        "/api/core/biocore/services?user=the_pi",
        json={"slug": "ok"},   # no name
    )
    assert res.status_code == 422


def test_http_create_unknown_core(world):
    client = TestClient(create_app())
    res = client.post(
        "/api/core/ghost/services?user=the_pi",
        json={"slug": "x", "name": "X"},
    )
    assert res.status_code == 404


@patch("murmurent.dashboard.slack_notify._post")
def test_http_update_patches_field(mock_post, world):
    S.create_service(core="biocore", slug="abc", name="Original")
    client = TestClient(create_app())
    res = client.patch(
        "/api/core/biocore/services/abc?user=the_pi",
        json={"description": "edited"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["fields_changed"] == ["description"]
    mock_post.assert_called()
    s = S.get_service("biocore", "abc")
    assert s.description == "edited"


@patch("murmurent.dashboard.slack_notify._post")
def test_http_archive_endpoint(mock_post, world):
    S.create_service(core="biocore", slug="abc", name="X")
    client = TestClient(create_app())
    res = client.post(
        "/api/core/biocore/services/abc/archive?user=the_pi",
    )
    assert res.status_code == 200
    assert res.json()["status"] == "retired"
    mock_post.assert_called()
    # No longer visible in default list.
    assert S.iter_services("biocore") == []
