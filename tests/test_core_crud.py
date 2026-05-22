"""
Tests for Phase 1d core CRUD: add/remove members + rotate leader.

Covers both the core.registrar helpers (add_core_member,
remove_core_member, rotate_core_leader) and their HTTP endpoints
(/api/registrar/core/<name>/members[/...], /leader).

Slack notification calls in the endpoints are mocked because the
test environment doesn't have a SLACK_BOT_TOKEN set.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from wigamig.core import registrar as R
from wigamig.core.frontmatter import parse_file
from wigamig.dashboard.server import create_app


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_LAB_INFO_ROOT", str(tmp_path / "lab_info"))
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("WIGAMIG_USER", "mhallet")
    (tmp_path / "lab-mgmt" / "members").mkdir(parents=True)
    (tmp_path / "lab-mgmt" / "lab.md").write_text(
        "---\nlab: hallett\npi: '@mhallet'\n---\n",
        encoding="utf-8",
    )
    (tmp_path / "lab_info").mkdir(parents=True)
    (tmp_path / "lab_info" / "registrar").write_text("mhallet\n", encoding="utf-8")
    R.create_core(
        name="biocore", display_name="BioCORE",
        leader_handle="@gary",
        leader_full_name="Gary (placeholder)",
    )
    return tmp_path


def _members_dir(core="biocore") -> Path:
    reg = R.read_registry()
    entry = next(c for c in reg.cores if c.name == core)
    return Path(entry.lab_mgmt_path) / "members"


# ---- add_core_member -----------------------------------------------------

def test_add_core_member_writes_file(world):
    path = R.add_core_member(
        core_name="biocore", handle="@alice",
        full_name="Alice Apt", role="staff",
    )
    assert path.is_file()
    meta = parse_file(path).meta or {}
    assert meta["handle"] == "@alice"
    assert meta["full_name"] == "Alice Apt"
    assert meta["role"] == "staff"
    assert meta["status"] == "active"
    assert meta["lab"] == "biocore"


def test_add_core_member_is_idempotent(world):
    p1 = R.add_core_member(core_name="biocore", handle="alice")
    p2 = R.add_core_member(core_name="biocore", handle="alice", role="ignored")
    assert p1 == p2
    # First-write role wins; idempotent re-add doesn't clobber.
    meta = parse_file(p1).meta or {}
    assert meta["role"] == "staff"


def test_add_core_member_unknown_core(world):
    with pytest.raises(R.LabNotFound):
        R.add_core_member(core_name="ghost", handle="alice")


def test_add_core_member_empty_handle(world):
    from wigamig.core.membership import MembershipError
    with pytest.raises(MembershipError):
        R.add_core_member(core_name="biocore", handle="@")


# ---- remove_core_member --------------------------------------------------

def test_remove_core_member_marks_inactive(world):
    R.add_core_member(core_name="biocore", handle="alice")
    changed = R.remove_core_member(core_name="biocore", handle="alice")
    assert changed is True
    meta = parse_file(_members_dir() / "alice.md").meta or {}
    assert meta["status"] == "inactive"


def test_remove_core_member_idempotent(world):
    R.add_core_member(core_name="biocore", handle="alice")
    R.remove_core_member(core_name="biocore", handle="alice")
    # Second remove is a no-op (already inactive).
    assert R.remove_core_member(core_name="biocore", handle="alice") is False


def test_remove_core_member_returns_false_when_missing(world):
    assert R.remove_core_member(core_name="biocore", handle="never_existed") is False


def test_remove_core_leader_refuses(world):
    with pytest.raises(R.PIAlreadyLeadsAnother):
        R.remove_core_member(core_name="biocore", handle="gary")
    # File untouched.
    meta = parse_file(_members_dir() / "gary.md").meta or {}
    assert meta["status"] == "active"


# ---- rotate_core_leader --------------------------------------------------

def test_rotate_core_leader_updates_registry_and_lab_md(world):
    R.add_core_member(core_name="biocore", handle="bob", full_name="Bob Y")
    entry = R.rotate_core_leader(
        core_name="biocore", new_handle="@bob", new_full_name="Bob Y",
    )
    assert entry.pi == "@bob"
    # Registry persisted.
    reg = R.read_registry()
    refreshed = next(c for c in reg.cores if c.name == "biocore")
    assert refreshed.pi == "@bob"
    # lab.md frontmatter updated.
    lab_md = Path(refreshed.lab_mgmt_path) / "lab.md"
    assert "pi: '@bob'" in lab_md.read_text(encoding="utf-8")


def test_rotate_core_leader_promotes_new_member_role(world):
    R.add_core_member(core_name="biocore", handle="bob", role="staff")
    R.rotate_core_leader(core_name="biocore", new_handle="bob")
    meta = parse_file(_members_dir() / "bob.md").meta or {}
    assert meta["role"] == "core_leader"


def test_rotate_core_leader_demotes_old_leader_to_staff(world):
    R.add_core_member(core_name="biocore", handle="bob")
    R.rotate_core_leader(core_name="biocore", new_handle="bob")
    meta = parse_file(_members_dir() / "gary.md").meta or {}
    assert meta["role"] == "staff"
    assert meta["status"] == "active"   # NOT auto-deactivated


def test_rotate_core_leader_creates_member_file_if_absent(world):
    """New leader doesn't need to be an existing member — the rotation
    creates their member file as well."""
    R.rotate_core_leader(
        core_name="biocore", new_handle="@brand_new",
        new_full_name="Brand New",
    )
    new_path = _members_dir() / "brand_new.md"
    assert new_path.is_file()
    meta = parse_file(new_path).meta or {}
    assert meta["role"] == "core_leader"


def test_rotate_core_leader_noop_when_same(world):
    entry = R.rotate_core_leader(core_name="biocore", new_handle="@gary")
    assert entry.pi == "@gary"


def test_rotate_core_leader_refuses_when_new_leads_another_active_core(world):
    R.create_core(name="genomics", display_name="Genomics",
                  leader_handle="@gpi")
    with pytest.raises(R.PIAlreadyLeadsAnother):
        R.rotate_core_leader(core_name="biocore", new_handle="@gpi")


# ---- HTTP endpoints ------------------------------------------------------

@patch("wigamig.dashboard.slack_notify._post")
def test_http_add_member(mock_post, world):
    client = TestClient(create_app())
    res = client.post(
        "/api/registrar/core/biocore/members?user=mhallet",
        json={"handle": "alice", "full_name": "Alice Apt", "role": "staff"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["ok"] is True
    mock_post.assert_called()  # slack notification fired


@patch("wigamig.dashboard.slack_notify._post")
def test_http_remove_member(mock_post, world):
    R.add_core_member(core_name="biocore", handle="alice")
    client = TestClient(create_app())
    res = client.post(
        "/api/registrar/core/biocore/members/alice/remove?user=mhallet",
    )
    assert res.status_code == 200, res.text
    assert res.json()["changed"] is True
    mock_post.assert_called()


@patch("wigamig.dashboard.slack_notify._post")
def test_http_rotate_leader(mock_post, world):
    R.add_core_member(core_name="biocore", handle="bob")
    client = TestClient(create_app())
    res = client.post(
        "/api/registrar/core/biocore/leader?user=mhallet",
        json={"handle": "bob", "full_name": "Bob Y"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["leader"] == "@bob"
    mock_post.assert_called()


def test_http_endpoints_reject_non_registrar(world):
    client = TestClient(create_app())
    res = client.post(
        "/api/registrar/core/biocore/members?user=alice",
        json={"handle": "bob"},
    )
    assert res.status_code in (401, 403)


def test_http_remove_leader_refuses(world):
    client = TestClient(create_app())
    res = client.post(
        "/api/registrar/core/biocore/members/gary/remove?user=mhallet",
    )
    assert res.status_code == 409


def test_http_unknown_core_returns_404(world):
    client = TestClient(create_app())
    res = client.post(
        "/api/registrar/core/ghost/members?user=mhallet",
        json={"handle": "alice"},
    )
    assert res.status_code == 404
