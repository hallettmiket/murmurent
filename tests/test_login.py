"""Tests for the Item-1 login / role-selection layer.

Covers:
  - ``_registry.yaml:registrars:`` round-trip + multi-handle parsing
  - ``is_registrar()`` honours the registry list as authoritative,
    falls back to the legacy sentinel only when the list is empty
  - ``role_audit.record()`` appends JSONL events and round-trips
  - ``GET /api/login/resolve`` returns the right role flags for each
    of: unknown handle, plain member, PI, registrar
  - ``POST /api/login/select`` audits + rejects unheld roles
  - ``GET /`` serves the login landing page (not the hi-fi dashboard)
  - ``GET /dashboard`` serves the hi-fi dashboard at the new route
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wigamig.core import registrar, role_audit
from wigamig.core.registrar import LabEntry, Registry
from wigamig.dashboard.server import create_app


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    """Redirect every login-touched path into tmp_path.

    Mirrors the fixture in ``test_registrar.py`` but also redirects the
    role-audit log + the user-pref file so the test never writes into
    the real ``~/.wigamig/``.
    """
    monkeypatch.setenv("WIGAMIG_LAB_INFO_ROOT", str(tmp_path / "lab_info"))
    monkeypatch.setattr(
        registrar, "REGISTRAR_SENTINEL", tmp_path / "registrar_sentinel"
    )
    monkeypatch.setenv("WIGAMIG_ROLE_AUDIT_LOG", str(tmp_path / "role_audit.log"))
    # Redirect Path.home() so the remember-me write also lands in tmp.
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setenv("WIGAMIG_USER", "")  # don't leak the real user
    return tmp_path


def _seed_lab_mgmt(root: Path, *, lab_id: str, pi: str, members: list[tuple[str, str]]) -> Path:
    """Scaffold a fake lab-mgmt repo with lab.md + members/."""
    lab_dir = root / f"{lab_id}-lab-mgmt"
    (lab_dir / "members").mkdir(parents=True)
    (lab_dir / "lab.md").write_text(
        "---\n"
        f"lab: {lab_id}\n"
        f"name: {lab_id.title()} Lab\n"
        f"pi: '@{pi}'\n"
        "institution: Western University\n"
        "created: 2026-01-01\n"
        "---\n",
        encoding="utf-8",
    )
    for handle, role in members:
        (lab_dir / "members" / f"{handle}.md").write_text(
            "---\n"
            f"handle: '@{handle}'\n"
            f"full_name: {handle.title()}\n"
            f"role: {role}\n"
            "status: active\n"
            "---\n",
            encoding="utf-8",
        )
    return lab_dir


# ---------------------------------------------------------------------------
# Registry: multi-registrar list
# ---------------------------------------------------------------------------


def test_registry_round_trip_with_registrars(isolated):
    original = Registry(
        labs=[LabEntry(name="hallett", pi="@the_pi", lab_mgmt_path="/tmp/x")],
        registrars=["the_pi", "alice"],
    )
    registrar.write_registry(original)
    reread = registrar.read_registry()
    assert reread.registrars == ["the_pi", "alice"]


def test_registrars_normalises_and_dedups(isolated):
    # @-prefixed, mixed case, duplicates → normalised list
    registrar.registry_path().parent.mkdir(parents=True)
    registrar.registry_path().write_text(
        "version: 1\nregistrars: ['@MHallet', 'alice', '@the_pi']\nlabs: {}\n",
        encoding="utf-8",
    )
    assert registrar.registrars() == ["the_pi", "alice"]


def test_is_registrar_prefers_registry_list_over_sentinel(isolated):
    # Sentinel says the_pi; registry list says alice. Registry wins.
    registrar.REGISTRAR_SENTINEL.write_text("the_pi\n", encoding="utf-8")
    registrar.write_registry(Registry(registrars=["alice"]))
    assert registrar.is_registrar("alice") is True
    assert registrar.is_registrar("the_pi") is False


def test_is_registrar_falls_back_to_sentinel_when_list_empty(isolated):
    # Legacy single-registrar install: no registry list, sentinel honoured.
    registrar.REGISTRAR_SENTINEL.write_text("the_pi\n", encoding="utf-8")
    # Write an empty-registrars registry on disk.
    registrar.write_registry(Registry(registrars=[]))
    assert registrar.is_registrar("the_pi") is True
    assert registrar.is_registrar("alice") is False


def test_is_registrar_multiple_centres(isolated):
    """Multi-registrar centre: both handles are recognised."""
    registrar.write_registry(Registry(registrars=["the_pi", "alice"]))
    assert registrar.is_registrar("the_pi") is True
    assert registrar.is_registrar("@Alice") is True
    assert registrar.is_registrar("bob") is False


# ---------------------------------------------------------------------------
# Role audit log
# ---------------------------------------------------------------------------


def test_role_audit_record_appends_jsonl(isolated):
    role_audit.record(handle="the_pi", role="pi", source="127.0.0.1", allowed=True)
    role_audit.record(handle="bob", role="registrar", source="127.0.0.1",
                      allowed=False, reason="not_registrar")
    path = role_audit.log_path()
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["handle"] == "the_pi"
    assert first["role"] == "pi"
    assert first["allowed"] is True
    second = json.loads(lines[1])
    assert second["allowed"] is False
    assert second["reason"] == "not_registrar"


def test_role_audit_read_all_round_trip(isolated):
    now = _dt.datetime(2026, 5, 13, 12, 0, tzinfo=_dt.timezone.utc)
    role_audit.record(handle="the_pi", role="pi", source="127.0.0.1",
                      allowed=True, now=now)
    events = role_audit.read_all()
    assert len(events) == 1
    assert events[0].handle == "the_pi"
    assert events[0].role == "pi"
    assert events[0].ts == now


def test_role_audit_recent_for_filters_handle(isolated):
    role_audit.record(handle="the_pi", role="pi", source="127.0.0.1", allowed=True)
    role_audit.record(handle="alice", role="member", source="127.0.0.1", allowed=True)
    role_audit.record(handle="the_pi", role="registrar", source="127.0.0.1", allowed=True)
    rows = role_audit.recent_for("the_pi")
    assert [r.role for r in rows] == ["registrar", "pi"]  # newest first


# ---------------------------------------------------------------------------
# /api/login/resolve
# ---------------------------------------------------------------------------


def test_login_resolve_unknown_handle(isolated):
    client = TestClient(create_app())
    res = client.get("/api/login/resolve?user=ghost")
    assert res.status_code == 200
    body = res.json()
    assert body["handle"] == "ghost"
    assert body["is_member"] is False
    assert body["is_pi"] is False
    assert body["is_registrar"] is False
    assert body["default_role"] == "member"


def test_login_resolve_member_only(isolated, tmp_path, monkeypatch):
    lab_dir = _seed_lab_mgmt(tmp_path, lab_id="hallett", pi="the_pi",
                             members=[("the_pi", "pi"), ("bob", "postdoc")])
    registrar.bootstrap_from_existing_lab_mgmt(lab_mgmt_path=lab_dir)
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(lab_dir))
    client = TestClient(create_app())
    res = client.get("/api/login/resolve?user=bob")
    body = res.json()
    assert body["is_member"] is True
    assert body["is_pi"] is False
    assert body["is_registrar"] is False
    assert body["default_role"] == "member"


def test_login_resolve_pi(isolated, tmp_path, monkeypatch):
    lab_dir = _seed_lab_mgmt(tmp_path, lab_id="hallett", pi="the_pi",
                             members=[("the_pi", "pi")])
    registrar.bootstrap_from_existing_lab_mgmt(lab_mgmt_path=lab_dir)
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(lab_dir))
    client = TestClient(create_app())
    res = client.get("/api/login/resolve?user=the_pi")
    body = res.json()
    assert body["is_pi"] is True
    assert body["default_role"] == "pi"


def test_login_resolve_registrar_from_registry(isolated, tmp_path, monkeypatch):
    lab_dir = _seed_lab_mgmt(tmp_path, lab_id="hallett", pi="the_pi",
                             members=[("the_pi", "pi")])
    registrar.bootstrap_from_existing_lab_mgmt(lab_mgmt_path=lab_dir)
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(lab_dir))
    # Add a second registrar via the registry.
    reg = registrar.read_registry()
    registrar.write_registry(Registry(
        labs=reg.labs, cores=reg.cores, collaborations=reg.collaborations,
        registrars=["the_pi", "alice"],
    ))
    client = TestClient(create_app())
    res = client.get("/api/login/resolve?user=alice")
    body = res.json()
    assert body["is_registrar"] is True
    assert body["default_role"] == "registrar"
    # Both registrars surfaced.
    assert "the_pi" in body["registrar_centres"]
    assert "alice" in body["registrar_centres"]


def test_login_resolve_core_leader_is_not_a_lab_pi(isolated, tmp_path, monkeypatch):
    """A core LEADER must resolve as core_leader, NOT as a lab PI. Cores reuse
    the ``pi:`` field internally for their leader, which used to make the
    resolver read it as a lab PI (emucaki showing PI view but no core view)."""
    from wigamig.core.registrar import CoreEntry
    core_dir = _seed_lab_mgmt(tmp_path, lab_id="biocore", pi="emucaki",
                              members=[("emucaki", "lead")])
    registrar.write_registry(Registry(
        cores=[CoreEntry(name="biocore", pi="@emucaki", lab_mgmt_path=str(core_dir))],
    ))
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(core_dir))
    body = TestClient(create_app()).get("/api/login/resolve?user=emucaki").json()
    assert body["is_core_leader"] is True
    assert "biocore" in body["core_leader_of"]
    assert body["is_pi"] is False              # NOT misclassified as a lab PI
    assert body["default_role"] == "core_leader"


def test_dashboard_gate_rejects_unknown_on_multigroup_centre(isolated, tmp_path, monkeypatch):
    """An unknown netname on a centre WITH groups gets 403 — NOT a fabricated
    dashboard under some default ('hallett') lab. The core scoping-leak fix."""
    lab_dir = _seed_lab_mgmt(tmp_path, lab_id="yxia_lab", pi="yxia266",
                             members=[("yxia266", "pi")])
    registrar.bootstrap_from_existing_lab_mgmt(lab_mgmt_path=lab_dir)
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(lab_dir))
    client = TestClient(create_app())
    res = client.get("/api/dashboard?user=totally_made_up_netname")
    assert res.status_code == 403
    assert "not registered" in res.json()["detail"].lower()


# ---------------------------------------------------------------------------
# /api/login/select
# ---------------------------------------------------------------------------


def test_login_select_member_always_allowed(isolated):
    client = TestClient(create_app())
    res = client.post("/api/login/select", json={
        "handle": "ghost", "role": "member", "remember_user": False,
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["next"] == "/dashboard?user=ghost&persona=member"
    # Audited as allowed.
    events = role_audit.read_all()
    assert any(e.handle == "ghost" and e.role == "member" and e.allowed for e in events)


def test_login_select_pi_rejected_for_non_pi(isolated, tmp_path, monkeypatch):
    lab_dir = _seed_lab_mgmt(tmp_path, lab_id="hallett", pi="the_pi",
                             members=[("bob", "postdoc")])
    registrar.bootstrap_from_existing_lab_mgmt(lab_mgmt_path=lab_dir)
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(lab_dir))
    client = TestClient(create_app())
    res = client.post("/api/login/select", json={
        "handle": "bob", "role": "pi", "remember_user": False,
    })
    assert res.status_code == 403
    events = role_audit.read_all()
    assert any(e.handle == "bob" and e.role == "pi" and not e.allowed for e in events)


def test_login_select_registrar_allowed(isolated, tmp_path, monkeypatch):
    lab_dir = _seed_lab_mgmt(tmp_path, lab_id="hallett", pi="the_pi",
                             members=[("the_pi", "pi")])
    registrar.bootstrap_from_existing_lab_mgmt(lab_mgmt_path=lab_dir)
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(lab_dir))
    reg = registrar.read_registry()
    registrar.write_registry(Registry(
        labs=reg.labs, registrars=["the_pi"],
    ))
    client = TestClient(create_app())
    res = client.post("/api/login/select", json={
        "handle": "the_pi", "role": "registrar", "remember_user": False,
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["next"] == "/registrar?user=the_pi"


def test_login_select_remember_user_writes_pref(isolated):
    client = TestClient(create_app())
    client.post("/api/login/select", json={
        "handle": "ghost", "role": "member", "remember_user": True,
    })
    pref = isolated / ".wigamig" / "user"
    assert pref.is_file()
    assert pref.read_text(encoding="utf-8").strip() == "ghost"


def test_login_select_bad_role_400(isolated):
    client = TestClient(create_app())
    res = client.post("/api/login/select", json={
        "handle": "ghost", "role": "owner", "remember_user": False,
    })
    assert res.status_code == 400


# ---------------------------------------------------------------------------
# Routing: / serves login, /dashboard serves hi-fi
# ---------------------------------------------------------------------------


def test_root_serves_login_page(isolated):
    client = TestClient(create_app())
    res = client.get("/")
    assert res.status_code == 200
    assert "Sign in" in res.text or "login" in res.text.lower()
    # The hi-fi dashboard's distinct marker shouldn't be on the login page.
    assert "hifi-app.jsx" not in res.text


def test_dashboard_route_serves_hifi(isolated):
    client = TestClient(create_app())
    res = client.get("/dashboard")
    assert res.status_code == 200
    assert "hifi-app.jsx" in res.text


# ---------------------------------------------------------------------------
# Cache headers — required so that returning users see the new ``/`` (login)
# instead of a stale cached dashboard, which makes the "↺ switch" link and
# the registrar's "→ Lab dashboard" link appear to do nothing.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/", "/dashboard", "/registrar"])
def test_html_routes_set_no_cache(isolated, path):
    """Every HTML route must tell browsers to revalidate.

    Without this, the launcher's existing browser tab keeps showing the
    pre-Phase-F dashboard (which used to live at ``/``) and clicking the
    new "↺ switch" link silently returns the stale page from disk cache
    — the symptom that prompted this fix.
    """
    client = TestClient(create_app())
    res = client.get(path)
    cache_control = res.headers.get("cache-control", "")
    assert "no-cache" in cache_control, f"{path} sent cache-control={cache_control!r}"
