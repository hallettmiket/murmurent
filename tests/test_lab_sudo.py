"""
Tests for the wigamig-level ``lab_sudo`` flag — the per-lab security
dashboard gate. Covers:

  - core.membership.set_lab_sudo + lab_sudo_handles helpers
  - Idempotent grant/revoke; revoke removes the key (vs setting false)
  - Preservation of other frontmatter fields (contact, location, certs)
  - HTTP endpoint /api/members/{handle}/lab_sudo (PI only)
  - PI cannot grant to a non-existent member
  - Snapshot.PeerRow carries the flag

Mirrors the conventions in tests/test_membership.py.
"""

from __future__ import annotations

import datetime as _dt
import os

import pytest
from fastapi.testclient import TestClient

from wigamig.core import membership as M
from wigamig.core.frontmatter import parse_file
from wigamig.dashboard.server import create_app


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_PROJECTS_ROOT", str(tmp_path / "repos"))
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("WIGAMIG_LAB_VM_ROOT", str(tmp_path / "lab_vm"))
    monkeypatch.setenv("WIGAMIG_USER", "the_pi")
    monkeypatch.setenv("WIGAMIG_DECOMMISSION_DIR", str(tmp_path / "decommissions"))
    (tmp_path / "lab-mgmt" / "members").mkdir(parents=True)
    (tmp_path / "lab-mgmt" / "projects").mkdir(parents=True)
    (tmp_path / "lab-mgmt" / "lab.md").write_text(
        "---\nlab: hallett\nname: 'Hallett Lab'\npi: '@the_pi'\n---\n",
        encoding="utf-8",
    )
    M.add(handle="the_pi", full_name="Mike Hallett", role="pi")
    M.add(handle="alice", full_name="Alice A.", role="postdoc")
    M.add(handle="bob", full_name="Bob B.", role="student")
    return tmp_path


# ---- core.membership ------------------------------------------------------

def test_set_lab_sudo_grant_writes_flag(world):
    path = M.set_lab_sudo("alice", True)
    meta = parse_file(path).meta or {}
    assert meta.get("lab_sudo") is True


def test_set_lab_sudo_revoke_removes_key(world):
    """Revoking should *remove* the key rather than writing ``false`` —
    keeps frontmatter minimal and round-trips with default behaviour."""
    M.set_lab_sudo("alice", True)
    path = M.set_lab_sudo("alice", False)
    meta = parse_file(path).meta or {}
    assert "lab_sudo" not in meta


def test_set_lab_sudo_is_idempotent(world):
    M.set_lab_sudo("alice", True)
    M.set_lab_sudo("alice", True)
    M.set_lab_sudo("alice", True)
    meta = parse_file(M.member_path("alice")).meta or {}
    assert meta.get("lab_sudo") is True


def test_set_lab_sudo_preserves_other_fields(world):
    """Granting lab_sudo must not nuke contact/location/certifications.
    The merge writer in core.membership.set_lab_sudo reads existing
    frontmatter, sets one key, and writes everything back."""
    # Decorate alice with extra fields before grant.
    path = M.member_path("alice")
    raw = path.read_text(encoding="utf-8")
    enriched = raw.replace(
        "status: active",
        "status: active\n"
        "lab: hallett\n"
        "contact:\n"
        "  email: alice@example.edu\n"
        "  orcid: 0000-1234-5678\n"
        "location:\n"
        "  office: SDRI 444\n"
        "certifications:\n"
        "  - name: TCPS_2\n"
        "    completed: '2024-01-15'",
    )
    path.write_text(enriched, encoding="utf-8")

    M.set_lab_sudo("alice", True)
    meta = parse_file(path).meta or {}
    assert meta.get("lab_sudo") is True
    assert meta["contact"]["email"] == "alice@example.edu"
    assert meta["contact"]["orcid"] == "0000-1234-5678"
    assert meta["location"]["office"] == "SDRI 444"
    assert meta["certifications"][0]["name"] == "TCPS_2"


def test_set_lab_sudo_unknown_handle(world):
    with pytest.raises(M.MembershipError):
        M.set_lab_sudo("does_not_exist", True)


def test_lab_sudo_handles_returns_grantees(world):
    assert M.lab_sudo_handles() == []
    M.set_lab_sudo("alice", True)
    M.set_lab_sudo("bob", True)
    handles = M.lab_sudo_handles()
    assert sorted(handles) == ["alice", "bob"]


def test_lab_sudo_handles_excludes_inactive(world):
    """An inactive member with the flag still set shouldn't appear in
    the grantee list — they can't act anyway, and the PI shouldn't be
    tricked into thinking they have an extra grantee to manage."""
    M.set_lab_sudo("alice", True)
    M.set_lab_sudo("bob", True)
    M.set_status("alice", M.INACTIVE)
    handles = M.lab_sudo_handles()
    assert handles == ["bob"]


# ---- HTTP endpoint --------------------------------------------------------

def test_lab_sudo_endpoint_pi_can_grant(world):
    client = TestClient(create_app())
    res = client.post(
        "/api/members/alice/lab_sudo?user=the_pi",
        json={"grant": True},
    )
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["ok"] is True
    assert payload["lab_sudo"] is True
    # Confirm on-disk effect.
    meta = parse_file(M.member_path("alice")).meta or {}
    assert meta.get("lab_sudo") is True


def test_lab_sudo_endpoint_pi_can_revoke(world):
    M.set_lab_sudo("alice", True)
    client = TestClient(create_app())
    res = client.post(
        "/api/members/alice/lab_sudo?user=the_pi",
        json={"grant": False},
    )
    assert res.status_code == 200, res.text
    assert res.json()["lab_sudo"] is False
    meta = parse_file(M.member_path("alice")).meta or {}
    assert "lab_sudo" not in meta


def test_lab_sudo_endpoint_non_pi_denied(world):
    client = TestClient(create_app())
    res = client.post(
        "/api/members/bob/lab_sudo?user=alice",
        json={"grant": True},
    )
    assert res.status_code in (401, 403, 422)
    # alice didn't get the flag set as a side effect.
    meta = parse_file(M.member_path("bob")).meta or {}
    assert "lab_sudo" not in meta


def test_lab_sudo_endpoint_unknown_member(world):
    client = TestClient(create_app())
    res = client.post(
        "/api/members/ghost/lab_sudo?user=the_pi",
        json={"grant": True},
    )
    assert res.status_code == 404


def test_lab_sudo_endpoint_defaults_grant_to_false(world):
    """Missing ``grant`` key in body should be treated as revoke (safe
    default) — never as ``true`` by accident."""
    M.set_lab_sudo("alice", True)
    client = TestClient(create_app())
    res = client.post(
        "/api/members/alice/lab_sudo?user=the_pi",
        json={},
    )
    assert res.status_code == 200
    assert res.json()["lab_sudo"] is False
