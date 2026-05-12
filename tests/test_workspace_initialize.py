"""Tests for the install wizard endpoint + snapshot loader.

Covers:
  - POST /api/workspace/initialize creates raw/refined dirs and writes the manifest
  - The manifest round-trips through ``_installations`` into the contract
  - Member persona sees only their own row; PI sees all rows on this machine
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from wigamig.dashboard import snapshot as snap_mod
from wigamig.dashboard.contract import InstallationRow
from wigamig.dashboard.server import create_app


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    """Point projects, lab_vm, and the installations dir at a tmp filesystem."""
    repos = tmp_path / "repos"
    lab_vm = tmp_path / "lab_vm"
    lab_mgmt = tmp_path / "lab-mgmt"
    installs = tmp_path / "wigamig" / "installations"

    monkeypatch.setenv("WIGAMIG_PROJECTS_ROOT", str(repos))
    monkeypatch.setenv("WIGAMIG_LAB_VM_ROOT", str(lab_vm))
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(lab_mgmt))
    monkeypatch.setenv("WIGAMIG_USER", "the_pi")
    monkeypatch.setattr(snap_mod, "INSTALLATIONS_DIR", installs)

    # A bare project dir is enough for the endpoint's existence check.
    (repos / "demo").mkdir(parents=True)
    # Seed a minimal lab-mgmt so _require_active doesn't blow up.
    (lab_mgmt / "members").mkdir(parents=True)
    (lab_mgmt / "lab.md").write_text(
        "---\nlab: hallett\nname: 'Hallett Lab'\npi: '@the_pi'\n---\n",
        encoding="utf-8",
    )
    (lab_mgmt / "members" / "the_pi.md").write_text(
        "---\nhandle: '@the_pi'\nfull_name: 'Mike Hallett'\nrole: pi\nstatus: active\n---\n",
        encoding="utf-8",
    )

    return {
        "tmp": tmp_path,
        "repos": repos,
        "lab_vm": lab_vm,
        "installs": installs,
    }


def _initialize_body(**overrides) -> dict:
    body = {
        "member": "@the_pi",
        "project": "demo",
        "machine_type": "laptop",
        "hostname": None,
        "username": "mth",
        "has_direct_access": True,
        "lab_base": "/tmp/lab_vm",
        "raw_path": "/tmp/lab_vm/raw",
        "refined_path": "/tmp/lab_vm/refined",
        "notebook_path": "/tmp/lab_vm/lab-notebook",
        "ssh_remote": None,
        "mount_point": None,
        "infra_components": ["git", "vscode"],
        "agents": ["oracle", "blacksmith"],
    }
    body.update(overrides)
    return body


def test_initialize_creates_dirs_and_manifest(isolated, tmp_path):
    client = TestClient(create_app())
    raw_root = tmp_path / "lab_vm_target" / "raw"
    refined_root = tmp_path / "lab_vm_target" / "refined"
    body = _initialize_body(
        raw_path=str(raw_root), refined_path=str(refined_root)
    )

    res = client.post("/api/workspace/initialize", json=body)
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["ok"] is True

    # Project subdirs created under raw/ and refined/.
    assert (raw_root / "demo").is_dir()
    assert (refined_root / "demo").is_dir()

    # Manifest exists at the configured INSTALLATIONS_DIR.
    manifest = isolated["installs"] / "demo.yaml"
    assert manifest.is_file()
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    assert data["project"] == "demo"
    assert data["member"] == "@the_pi"
    assert data["machine_type"] == "laptop"
    assert data["status"] == "active"
    assert data["components"] == ["git", "vscode"]
    assert data["agents"] == ["oracle", "blacksmith"]


def test_initialize_rejects_unknown_project(isolated):
    client = TestClient(create_app())
    res = client.post("/api/workspace/initialize", json=_initialize_body(project="nope"))
    assert res.status_code == 404


def test_initialize_is_idempotent(isolated, tmp_path):
    """Re-running the wizard for the same project should not error."""
    client = TestClient(create_app())
    body = _initialize_body(
        raw_path=str(tmp_path / "lv" / "raw"),
        refined_path=str(tmp_path / "lv" / "refined"),
    )
    r1 = client.post("/api/workspace/initialize", json=body)
    r2 = client.post("/api/workspace/initialize", json=body)
    assert r1.status_code == 200
    assert r2.status_code == 200


def test_installations_loader_filters_for_member(isolated):
    """A non-PI viewer only sees their own installations."""
    installs = isolated["installs"]
    installs.mkdir(parents=True, exist_ok=True)
    (installs / "demo.yaml").write_text(
        yaml.safe_dump({
            "member": "@bob", "project": "demo",
            "machine_type": "laptop", "username": "bob",
        }),
        encoding="utf-8",
    )
    (installs / "other.yaml").write_text(
        yaml.safe_dump({
            "member": "@the_pi", "project": "other",
            "machine_type": "laptop", "username": "mth",
        }),
        encoding="utf-8",
    )

    member_view = snap_mod._installations("the_pi", persona="member")
    pi_view = snap_mod._installations("the_pi", persona="pi")

    assert [r.project for r in member_view] == ["other"]
    assert sorted(r.project for r in pi_view) == ["demo", "other"]


def test_installations_loader_skips_bad_manifest(isolated):
    """One malformed manifest must not break the whole loader."""
    installs = isolated["installs"]
    installs.mkdir(parents=True, exist_ok=True)
    (installs / "broken.yaml").write_text(": : :\n", encoding="utf-8")
    (installs / "good.yaml").write_text(
        yaml.safe_dump({
            "member": "@the_pi", "project": "demo",
            "machine_type": "laptop", "username": "mth",
        }),
        encoding="utf-8",
    )
    rows = snap_mod._installations("the_pi", persona="pi")
    assert [r.project for r in rows] == ["demo"]


def test_installations_loader_returns_empty_when_dir_missing(isolated):
    """No installations dir is the fresh-machine case; must not crash."""
    # `isolated` already points INSTALLATIONS_DIR at a tmp path that doesn't
    # exist yet (no install has happened).
    rows = snap_mod._installations("the_pi", persona="pi")
    assert rows == []
