"""
Tests for opt-in dashboard session auth (Option A: shared secret → cookie).

Two layers:
  - core token logic in dashboard/auth.py (mint/verify/tamper/expiry, secret
    resolution, the mutating-request gate predicate)
  - end-to-end through the FastAPI app with a TestClient: with no secret the
    dashboard behaves exactly as before (backward compat); with a secret a
    mutating request 401s without a session, succeeds after login, and the
    public allowlist (login, join submit) stays open.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from wigamig.dashboard import auth as A
from wigamig.dashboard.server import create_app


@pytest.fixture(autouse=True)
def isolate_secret(monkeypatch, tmp_path):
    """Never read a real ~/.wigamig/dashboard_secret; start with auth OFF."""
    monkeypatch.setattr(A, "SECRET_FILE", tmp_path / "dashboard_secret")
    monkeypatch.delenv(A.ENV_VAR, raising=False)


# ---- token logic -------------------------------------------------------

def test_token_roundtrip():
    t = A.mint_token("tbrowne", "registrar", "sekret", now=1000)
    payload = A.verify_token(t, "sekret", now=1500)
    assert payload and payload["h"] == "tbrowne" and payload["r"] == "registrar"


def test_token_rejects_wrong_secret():
    t = A.mint_token("tbrowne", "registrar", "sekret", now=1000)
    assert A.verify_token(t, "different", now=1500) is None


def test_token_rejects_tamper():
    t = A.mint_token("tbrowne", "registrar", "sekret", now=1000)
    assert A.verify_token(t[:-1] + ("x" if t[-1] != "x" else "y"),
                          "sekret", now=1500) is None


def test_token_expires():
    t = A.mint_token("tbrowne", "registrar", "sekret", now=1000)
    assert A.verify_token(t, "sekret", now=1000 + A.DEFAULT_TTL + 1) is None


def test_secret_from_env_and_file(monkeypatch, tmp_path):
    assert A.configured_secret() is None and A.auth_enabled() is False
    monkeypatch.setenv(A.ENV_VAR, "  envtok  ")
    assert A.configured_secret() == "envtok"          # trimmed
    monkeypatch.delenv(A.ENV_VAR)
    A.SECRET_FILE.write_text("filetok\n", encoding="utf-8")
    assert A.configured_secret() == "filetok"
    assert A.check_secret("filetok") and not A.check_secret("nope")


@pytest.mark.parametrize("method,path,gated", [
    ("POST", "/api/registrar/join_request/1/approve", True),
    ("PATCH", "/api/centre/profile", True),
    ("DELETE", "/api/hosts/x", True),
    ("GET", "/api/registrar/join_request/1/approve", False),  # reads never gated
    ("POST", "/api/login/authenticate", False),               # allowlist
    ("POST", "/api/centre/init", False),                      # bootstrap
    ("POST", "/api/centre/join_requests", False),            # public join form
])
def test_gate_predicate(method, path, gated):
    assert A.request_needs_session(method, path) is gated


# ---- end-to-end via the app -------------------------------------------

@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_LAB_INFO_ROOT", str(tmp_path / "lab_info"))
    return TestClient(create_app())


def test_no_secret_is_backward_compatible(client):
    """With no secret, a mutating endpoint is reachable (no 401 gate).

    It may fail its own validation (e.g. 404/400), but it must NOT be
    blocked by auth."""
    r = client.post("/api/login/logout")   # a harmless mutating endpoint
    assert r.status_code == 200            # not 401 — auth is off


def test_mutation_blocked_without_session_when_secret_set(client, monkeypatch):
    monkeypatch.setenv(A.ENV_VAR, "topsecret")
    r = client.post("/api/registrar/join_request/1/approve?user=tbrowne")
    assert r.status_code == 401
    assert "authentication required" in r.json()["detail"].lower()


def test_login_then_mutation_allowed(client, monkeypatch):
    monkeypatch.setenv(A.ENV_VAR, "topsecret")
    # Wrong secret → 401.
    bad = client.post("/api/login/authenticate",
                      json={"handle": "tbrowne", "secret": "wrong"})
    assert bad.status_code == 401
    # Correct secret → sets the session cookie.
    ok = client.post("/api/login/authenticate",
                     json={"handle": "tbrowne", "secret": "topsecret"})
    assert ok.status_code == 200
    assert A.COOKIE_NAME in ok.cookies or A.COOKIE_NAME in client.cookies
    # Now the gate lets the mutating request through to the handler (it may
    # 404 on the missing request, but it is NOT a 401).
    r = client.post("/api/registrar/join_request/1/approve?user=tbrowne")
    assert r.status_code != 401


def test_public_allowlist_open_when_secret_set(client, monkeypatch):
    """The public join form must work with a secret set + no session."""
    monkeypatch.setenv(A.ENV_VAR, "topsecret")
    r = client.post("/api/centre/join_requests", json={
        "kind": "pi", "requester_email": "x@y.edu",
        "proposed_name": "vis", "proposed_pi": "@vis",
    })
    assert r.status_code != 401


def test_auth_status_endpoint(client, monkeypatch):
    assert client.get("/api/login/auth-status").json()["auth_enabled"] is False
    monkeypatch.setenv(A.ENV_VAR, "topsecret")
    assert client.get("/api/login/auth-status").json()["auth_enabled"] is True
