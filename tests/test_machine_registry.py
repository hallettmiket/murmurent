"""Tests for the machine-config simplification (issue #80).

Covers the four moving parts of the "machine-config" phase:

  1. ``POST`` / ``PATCH /api/hosts`` no longer accept or persist a foreign
     machine's param fields (data-root / vault / project / lab-vault paths /
     subfolders) — they are ignored, and only connection info survives.
  2. Saving THIS machine's settings mirrors its own entry to
     ``<vault>/machines/<machine_id>.yaml``.
  3. ``"machines"`` is in the vault tracked-folder allowlist so the mirror
     syncs via GitHub.
  4. The read-only cross-machine view reads every ``<vault>/machines/*.yaml``.
  5. ``environment_this_machine`` exposes the friendly name + id that feed the
     header identity badge.

All state is confined to ``tmp_path`` + monkeypatched env — no real vault or
``~/.murmurent`` is touched.
"""

from __future__ import annotations

import pytest
import yaml
from fastapi.testclient import TestClient

from murmurent.core import hosts as _hosts
from murmurent.core import machine_registry as _mr
from murmurent.core import vault_provision as _vp
from murmurent.dashboard import contract as C
from murmurent.dashboard import machine_settings as _ms
from murmurent.dashboard.server import create_app


@pytest.fixture
def env(monkeypatch, tmp_path):
    """Isolate hosts.yaml, machine.yaml, and the vault machines dir."""
    hosts_file = tmp_path / "hosts.yaml"
    machine_file = tmp_path / "machine.yaml"
    vault = tmp_path / "murmurent_vault"
    machines_dir = vault / "machines"
    monkeypatch.setenv("MURMURENT_HOSTS_FILE", str(hosts_file))
    monkeypatch.setattr(_ms, "MACHINE_FILE", machine_file)
    monkeypatch.setenv(_mr.ENV_MACHINES_DIR, str(machines_dir))
    return {"tmp": tmp_path, "vault": vault, "machines_dir": machines_dir}


# ---------------------------------------------------------------------------
# 1. Foreign-machine param editing is retired
# ---------------------------------------------------------------------------


def test_post_host_ignores_param_fields(env):
    """A POST that still sends the retired param fields succeeds but persists
    only the connection info — no data-root / vault / project keys land."""
    client = TestClient(create_app())
    res = client.post("/api/hosts", json={
        "name": "lab-server", "ssh_host": "lab-server", "remote_user": "the_pi",
        "scan_dirs": ["repos"],
        # Retired param fields an older client might still send:
        "lab_vm_root": "/data/lab_vm", "wigamig_base": "/data/lab_vm",
        "vault_root": "/home/the_pi/Obsidian", "project_root": "/home/the_pi/repos",
        "lab_vault_root": "/home/the_pi/lab_mgmt", "oracle_subfolder": "orc",
    })
    assert res.status_code == 200, res.text
    text = (env["tmp"] / "hosts.yaml").read_text(encoding="utf-8")
    for banned in ("lab_vm_root", "vault_root", "project_root",
                   "lab_vault_root", "oracle_subfolder"):
        assert banned not in text, f"{banned} should not be persisted"
    h = _hosts.resolve("lab-server")
    assert h.ssh_host == "lab-server" and h.remote_user == "the_pi"
    assert h.scan_dirs == ("repos",)


def test_patch_host_ignores_param_fields(env):
    """PATCH is connection-only: it edits ssh_host/remote_user/description/
    scan_dirs and ignores any param fields."""
    _hosts.add(_hosts.Host(name="lab-server", kind="ssh", ssh_host="old"))
    client = TestClient(create_app())
    res = client.patch("/api/hosts/lab-server", json={
        "ssh_host": "new", "remote_user": "u2", "description": "compute",
        "scan_dirs": ["repos", "/srv/x"],
        # Ignored:
        "lab_vm_root": "/data", "vault_root": "/v", "lab_vault_root": "/lm",
    })
    assert res.status_code == 200, res.text
    h = _hosts.resolve("lab-server")
    assert h.ssh_host == "new" and h.remote_user == "u2"
    assert h.description == "compute" and h.scan_dirs == ("repos", "/srv/x")
    text = (env["tmp"] / "hosts.yaml").read_text(encoding="utf-8")
    assert "lab_vm_root" not in text and "vault_root" not in text


def test_repo_inventory_scan_still_reads_connection_fields(env):
    """The connection registry still carries exactly what the repo_inventory
    SSH scan needs: ssh_host + scan_dirs."""
    _hosts.add(_hosts.Host(
        name="lab-server", kind="ssh", ssh_host="lab-server.edu",
        scan_dirs=("repos", "/srv/projects"),
    ))
    h = _hosts.resolve("lab-server")
    assert h.ssh_host == "lab-server.edu"
    assert h.scan_dirs == ("repos", "/srv/projects")


# ---------------------------------------------------------------------------
# 2 + 3. Save mirrors this machine; "machines" is tracked
# ---------------------------------------------------------------------------


def test_machines_folder_is_tracked_by_allowlist():
    assert "machines" in _vp.MURMURENT_TRACKED_FOLDERS
    assert "machines" in _vp.VAULT_SUBDIRS
    # And the generated allowlist .gitignore re-includes it.
    assert "!/machines/" in _vp._allowlist_gitignore_lines()


def test_save_machine_settings_mirrors_to_vault(env):
    """POST /api/machine/settings writes machine.yaml AND mirrors this
    machine's own entry to <vault>/machines/<machine_id>.yaml."""
    client = TestClient(create_app())
    res = client.post("/api/machine/settings", json={
        "machine_name": "mike-laptop",
        "wigamig_base": str(env["tmp"] / "wig"),
        "obsidian_vault_path": str(env["vault"]),
        "oracle_subfolder": "oracle",
        "notebook_subfolder": "lab-notebook",
    })
    assert res.status_code == 200, res.text
    mirror = env["machines_dir"] / "mike-laptop.yaml"
    assert mirror.is_file(), "mirror file should exist"
    data = yaml.safe_load(mirror.read_text(encoding="utf-8"))
    assert data["machine_id"] == "mike-laptop"
    assert data["machine_name"] == "mike-laptop"
    assert data["obsidian_vault_path"] == str(env["vault"])
    assert "updated" in data


def test_mirror_is_single_file_per_machine(env):
    """Re-saving the same machine overwrites its own file (single-writer);
    it never creates a second file."""
    s = C.MachineSettings(machine_name="box-a",
                          obsidian_vault_path=str(env["vault"]))
    _mr.mirror_this_machine(s)
    _mr.mirror_this_machine(s)
    files = sorted(p.name for p in env["machines_dir"].glob("*.yaml"))
    assert files == ["box-a.yaml"]


def test_mirror_is_noop_without_vault(monkeypatch, tmp_path):
    """No registered vault → the mirror is a graceful no-op (badge still works
    from machine.yaml/hostname)."""
    monkeypatch.delenv(_mr.ENV_MACHINES_DIR, raising=False)
    # personal_vault_root returns None when obsidian_vault_path is unset.
    monkeypatch.setattr(_mr, "vault_machines_dir", lambda: None)
    assert _mr.mirror_this_machine(
        C.MachineSettings(machine_name="x")) is None


def test_machine_id_prefers_name_then_hostname(env, monkeypatch):
    assert _mr.machine_id(C.MachineSettings(machine_name="My Laptop!!")) == "my-laptop"
    monkeypatch.setattr(_mr, "_short_hostname", lambda: "biodatsci.uwo.ca".split(".")[0])
    assert _mr.machine_id(C.MachineSettings(machine_name="")) == "biodatsci"


# ---------------------------------------------------------------------------
# 4. Read-only cross-machine view reads multiple files
# ---------------------------------------------------------------------------


def test_read_registry_reads_multiple_machine_files(env):
    env["machines_dir"].mkdir(parents=True, exist_ok=True)
    (env["machines_dir"] / "laptop.yaml").write_text(
        yaml.safe_dump({"machine_id": "laptop", "machine_name": "laptop",
                        "updated": "2026-07-01T00:00:00Z"}), encoding="utf-8")
    (env["machines_dir"] / "server.yaml").write_text(
        yaml.safe_dump({"machine_id": "server", "machine_name": "server",
                        "updated": "2026-07-20T00:00:00Z"}), encoding="utf-8")
    reg = _mr.read_registry()
    ids = [m["machine_id"] for m in reg]
    assert set(ids) == {"laptop", "server"}
    # Newest first.
    assert ids[0] == "server"


def test_machines_registry_endpoint(env):
    """GET /api/machines/registry returns the mirrored entries + this id."""
    # Save this machine, which mirrors itself.
    client = TestClient(create_app())
    client.post("/api/machine/settings", json={
        "machine_name": "this-box", "obsidian_vault_path": str(env["vault"]),
    })
    # Add a second machine's mirror by hand (as if synced from another box).
    (env["machines_dir"] / "other-box.yaml").write_text(
        yaml.safe_dump({"machine_id": "other-box", "machine_name": "other-box",
                        "updated": "2026-06-01T00:00:00Z"}), encoding="utf-8")
    body = client.get("/api/machines/registry").json()
    ids = {m["machine_id"] for m in body["machines"]}
    assert {"this-box", "other-box"} <= ids
    assert body["this_machine_id"] == "this-box"


def test_registry_endpoint_empty_without_vault(monkeypatch, tmp_path):
    monkeypatch.setenv("MURMURENT_HOSTS_FILE", str(tmp_path / "hosts.yaml"))
    monkeypatch.setattr(_ms, "MACHINE_FILE", tmp_path / "machine.yaml")
    monkeypatch.setattr(_mr, "vault_machines_dir", lambda: None)
    client = TestClient(create_app())
    body = client.get("/api/machines/registry").json()
    assert body["machines"] == []


# ---------------------------------------------------------------------------
# 5. environment_this_machine feeds the identity badge
# ---------------------------------------------------------------------------


def test_environment_this_machine_exposes_badge_fields(env):
    """The badge needs a friendly machine name + a stable id from machine.yaml."""
    client = TestClient(create_app())
    client.post("/api/machine/settings", json={
        "machine_name": "Mike Laptop", "obsidian_vault_path": str(env["vault"]),
    })
    body = client.get("/api/environment/this_machine").json()
    assert body["machine_name"] == "Mike Laptop"
    assert body["machine_id"] == "mike-laptop"
    assert "hostname" in body and "platform" in body
