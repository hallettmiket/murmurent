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

from murmurent.core import registrar as R
from murmurent.core import role_audit
from murmurent.dashboard.server import create_app


@pytest.fixture
def world(monkeypatch, tmp_path):
    # Centre registrar + audit log live here so the tests don't touch
    # the real ~/.murmurent/.
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(tmp_path / "lab_info"))
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("MURMURENT_USER", "the_pi")
    monkeypatch.setenv(role_audit.ENV_VAR, str(tmp_path / "role_audit.log"))

    # Minimal lab.md so the resolver's PI check doesn't blow up.
    (tmp_path / "lab-mgmt" / "members").mkdir(parents=True)
    (tmp_path / "lab-mgmt" / "lab.md").write_text(
        "---\nlab: hallett\npi: '@the_pi'\n---\n",
        encoding="utf-8",
    )

    # Seed the centre registrar so is_registrar(the_pi) is true.
    (tmp_path / "lab_info").mkdir(parents=True)
    (tmp_path / "lab_info" / "registrar").write_text("the_pi\n", encoding="utf-8")

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

def test_valid_roles_has_three_lenses_only():
    """A PI leads either a lab or a core — one PI lens for both (issue
    #18). core_leader is retired as a login role; core-leader AUTHORITY
    (can_admin on /api/core/dashboard etc.) is unaffected."""
    assert role_audit.VALID_ROLES == {"member", "pi", "registrar"}


# ---- /core HTML route -----------------------------------------------------

def test_core_route_returns_html(world):
    _seed_core()
    client = TestClient(create_app())
    res = client.get("/core?core=biocore&user=the_pi")
    assert res.status_code == 200
    assert "CORE DASHBOARD" in res.text
    assert "/api/core/dashboard" in res.text  # the JS that fetches the data


# ---- /api/core/dashboard --------------------------------------------------

def test_core_dashboard_endpoint_returns_core_and_members(world):
    _seed_core()
    client = TestClient(create_app())
    res = client.get("/api/core/dashboard?core=biocore&user=the_pi")
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
    res = client.get("/api/core/dashboard?core=biocore&user=the_pi")
    v = res.json()["viewer"]
    assert v["is_leader"] is False
    assert v["is_registrar"] is True
    assert v["can_admin"] is True   # registrar gets implicit admin


# ---- login resolver -------------------------------------------------------

def test_login_resolve_core_leader_is_pi(world):
    """The leader of a core resolves as a PI — same lens as a lab PI
    (issue #18). The retired core_leader fields are gone from the
    payload entirely."""
    _seed_core()
    client = TestClient(create_app())
    res = client.get("/api/login/resolve?user=biocore_leader")
    d = res.json()
    assert d["is_pi"] is True
    assert d["pi_lab"] == "biocore"
    assert d["default_role"] == "pi"
    assert "is_core_leader" not in d
    assert "core_leader_of" not in d


def test_login_resolve_outsider_is_plain_member(world):
    """A handle that leads nothing and isn't a registrar gets only the
    member lens."""
    _seed_core()
    client = TestClient(create_app())
    d = client.get("/api/login/resolve?user=random_outsider").json()
    assert d["is_pi"] is False
    assert d["is_registrar"] is False
    assert d["default_role"] == "member"


def test_login_select_core_leader_role_is_rejected(world):
    """core_leader is no longer a valid login role — even for the actual
    core leader, who signs in as PI instead."""
    _seed_core()
    client = TestClient(create_app())
    res = client.post("/api/login/select", json={
        "handle": "biocore_leader",
        "role": "core_leader",
        "remember_user": False,
    })
    assert res.status_code == 400


def test_login_select_routes_core_pi_to_dashboard(world):
    _seed_core()
    client = TestClient(create_app())
    res = client.post("/api/login/select", json={
        "handle": "biocore_leader",
        "role": "pi",
        "remember_user": False,
    })
    assert res.status_code == 200, res.text
    d = res.json()
    assert d["ok"] is True and d["role"] == "pi"
    assert d["next"] == "/dashboard?user=biocore_leader&persona=pi"


def test_core_services_list_empty(world):
    """A freshly-registered core with no services returns an empty list."""
    _seed_core()
    client = TestClient(create_app())
    res = client.get("/api/core/biocore/services?user=the_pi")
    assert res.status_code == 200, res.text
    d = res.json()
    assert d["ok"] is True
    assert d["core"] == "biocore"
    assert d["count"] == 0
    assert d["services"] == []


def test_core_services_list_returns_catalog(world):
    """A core with services in lab-mgmt/services/ surfaces them in the
    Phase 2b list endpoint. Schema mirrors the ServiceSummary dataclass."""
    _seed_core()
    from murmurent.core import services as _svc
    sdir = _svc.services_dir("biocore")
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "demo.md").write_text(
        "---\n"
        "service: demo\n"
        "name: Demo Service\n"
        "core: biocore\n"
        "capability: structure_function_interaction\n"
        "fee:\n  unit: per_run\n  tiers:\n    academic_internal: 80.0\n"
        "status: active\n"
        "---\n# Demo\n",
        encoding="utf-8",
    )
    client = TestClient(create_app())
    res = client.get("/api/core/biocore/services?user=the_pi")
    d = res.json()
    assert d["count"] == 1
    s = d["services"][0]
    assert s["slug"] == "demo"
    assert s["name"] == "Demo Service"
    assert s["fee"]["tiers"]["academic_internal"] == 80.0


def test_core_services_list_unknown_core_404(world):
    client = TestClient(create_app())
    res = client.get("/api/core/ghost/services")
    assert res.status_code == 404


def test_registrar_signs_in_as_registrar_not_core_leader(world):
    """Registrars keep implicit ADMIN over every core (can_admin on the
    core endpoints, pinned above) but sign in through the registrar
    lens — the core_leader login shortcut is retired with the role."""
    _seed_core(name="biocore")
    R.create_core(
        name="genomics", display_name="Genomics Core",
        leader_handle="@genomics_leader",
    )
    client = TestClient(create_app())
    res = client.post("/api/login/select", json={
        "handle": "the_pi", "role": "core_leader", "remember_user": False,
    })
    assert res.status_code == 400
    res = client.post("/api/login/select", json={
        "handle": "the_pi", "role": "registrar", "remember_user": False,
    })
    assert res.status_code == 200, res.text
    assert res.json()["next"] == "/registrar?user=the_pi"


def test_core_pi_dashboard_is_the_core_dashboard(world):
    """One dashboard per group (issue #18): a core's PI signing in as PI
    lands directly on their core's dashboard — no separate destination
    to know about. A non-core viewer still gets the lab UI."""
    _seed_core()
    client = TestClient(create_app())
    res = client.get("/dashboard?user=biocore_leader&persona=pi",
                     follow_redirects=False)
    assert res.status_code == 307
    assert res.headers["location"] == "/core?core=biocore&user=biocore_leader"
    # Following through serves the core dashboard page.
    res = client.get("/dashboard?user=biocore_leader&persona=pi")
    assert res.status_code == 200 and "CORE DASHBOARD" in res.text
    # A handle that leads no core gets the ordinary lab UI.
    res = client.get("/dashboard?user=random_member", follow_redirects=False)
    assert res.status_code == 200


def test_api_route_miss_404_explains_version_skew(world):
    """Issue #19: a browser newer than the server process (JSX is read
    fresh from disk, Python routes are not) hits routes that don't exist
    and got a bare "Not Found". The rewritten detail says to restart.
    Endpoint-raised 404s keep their own detail; non-API misses are
    untouched."""
    client = TestClient(create_app())
    res = client.get("/api/definitely/not/a/route")
    assert res.status_code == 404
    assert "restart" in res.json()["detail"].lower()
    # An endpoint's own 404 detail passes through unchanged.
    res = client.get("/api/core/dashboard?core=ghost_core")
    assert res.status_code == 404
    assert "restart" not in res.json()["detail"].lower()
