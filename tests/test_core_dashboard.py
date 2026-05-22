"""
Tests for the Phase 1 Core Dashboard route + endpoint.

Covers:
  - GET /core HTML route serves core.html
  - GET /api/core/dashboard returns the core entry + member list
  - Unknown core id -> 404
  - login resolver returns is_core_leader=true for a core's leader
  - core_leader role lands the user at /core?core=<id> after select
  - VALID_ROLES includes "core_leader"
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from wigamig.core import registrar as R
from wigamig.core import role_audit
from wigamig.dashboard.server import create_app


@pytest.fixture
def world(monkeypatch, tmp_path):
    # Centre registrar + audit log live here so the tests don't touch
    # the real ~/.wigamig/.
    monkeypatch.setenv("WIGAMIG_LAB_INFO_ROOT", str(tmp_path / "lab_info"))
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("WIGAMIG_USER", "mhallet")
    monkeypatch.setenv(role_audit.ENV_VAR, str(tmp_path / "role_audit.log"))

    # Minimal lab.md so the resolver's PI check doesn't blow up.
    (tmp_path / "lab-mgmt" / "members").mkdir(parents=True)
    (tmp_path / "lab-mgmt" / "lab.md").write_text(
        "---\nlab: hallett\npi: '@mhallet'\n---\n",
        encoding="utf-8",
    )

    # Seed the centre registrar so is_registrar(mhallet) is true.
    (tmp_path / "lab_info").mkdir(parents=True)
    (tmp_path / "lab_info" / "registrar").write_text("mhallet\n", encoding="utf-8")

    return tmp_path


def _seed_core(name="biocore", display="BioCORE", leader="@biocore_leader"):
    R.create_core(
        name=name,
        display_name=display,
        leader_handle=leader,
        leader_full_name=f"{leader.lstrip('@')} (placeholder)",
        institution="Western University",
        department="Biochemistry",
    )


# ---- VALID_ROLES ----------------------------------------------------------

def test_valid_roles_includes_core_leader():
    assert "core_leader" in role_audit.VALID_ROLES


# ---- /core HTML route -----------------------------------------------------

def test_core_route_returns_html(world):
    _seed_core()
    client = TestClient(create_app())
    res = client.get("/core?core=biocore&user=mhallet")
    assert res.status_code == 200
    assert "CORE DASHBOARD" in res.text
    assert "/api/core/dashboard" in res.text  # the JS that fetches the data


# ---- /api/core/dashboard --------------------------------------------------

def test_core_dashboard_endpoint_returns_core_and_members(world):
    _seed_core()
    client = TestClient(create_app())
    res = client.get("/api/core/dashboard?core=biocore&user=mhallet")
    assert res.status_code == 200
    d = res.json()
    assert d["ok"] is True
    assert d["core"]["name"] == "biocore"
    assert d["core"]["display_name"] == "BioCORE"
    assert d["core"]["leader"] == "@biocore_leader"
    assert d["core"]["status"] == "active"
    assert d["core"]["kind"] == "core"
    # create_core scaffolds the leader as a member of the core too.
    handles = [m["handle"] for m in d["members"]]
    assert "biocore_leader" in handles


def test_core_dashboard_404_on_unknown_core(world):
    client = TestClient(create_app())
    res = client.get("/api/core/dashboard?core=ghost_core")
    assert res.status_code == 404


def test_core_dashboard_marks_leader_can_admin(world):
    _seed_core()
    client = TestClient(create_app())
    res = client.get("/api/core/dashboard?core=biocore&user=biocore_leader")
    v = res.json()["viewer"]
    assert v["is_leader"] is True
    assert v["can_admin"] is True


def test_core_dashboard_registrar_can_admin_other_cores(world):
    _seed_core()
    client = TestClient(create_app())
    res = client.get("/api/core/dashboard?core=biocore&user=mhallet")
    v = res.json()["viewer"]
    assert v["is_leader"] is False
    assert v["is_registrar"] is True
    assert v["can_admin"] is True   # registrar gets implicit admin


# ---- login resolver -------------------------------------------------------

def test_login_resolve_flags_core_leader(world):
    _seed_core()
    client = TestClient(create_app())
    res = client.get("/api/login/resolve?user=biocore_leader")
    d = res.json()
    assert d["is_core_leader"] is True
    assert d["core_leader_of"] == ["biocore"]


def test_login_resolve_non_leader_has_core_leader_false(world):
    _seed_core()
    client = TestClient(create_app())
    res = client.get("/api/login/resolve?user=mhallet")
    d = res.json()
    assert d["is_core_leader"] is False
    assert d["core_leader_of"] == []


def test_login_select_core_leader_routes_to_core_dashboard(world):
    _seed_core()
    client = TestClient(create_app())
    res = client.post("/api/login/select", json={
        "handle": "biocore_leader",
        "role": "core_leader",
        "remember_user": False,
    })
    assert res.status_code == 200, res.text
    d = res.json()
    assert d["ok"] is True
    assert d["role"] == "core_leader"
    assert d["next"] == "/core?core=biocore&user=biocore_leader"


def test_login_select_rejects_core_leader_for_non_leader(world):
    _seed_core()
    client = TestClient(create_app())
    res = client.post("/api/login/select", json={
        "handle": "mhallet",   # not a core leader
        "role": "core_leader",
        "remember_user": False,
    })
    assert res.status_code == 403
