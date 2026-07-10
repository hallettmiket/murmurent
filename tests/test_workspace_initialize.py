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

from murmurent.dashboard import snapshot as snap_mod
from murmurent.dashboard.contract import InstallationRow
from murmurent.dashboard.server import create_app


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    """Point projects, lab_vm, and the installations dir at a tmp filesystem."""
    repos = tmp_path / "repos"
    lab_vm = tmp_path / "lab_vm"
    lab_mgmt = tmp_path / "lab-mgmt"
    installs = tmp_path / "murmurent" / "installations"

    monkeypatch.setenv("WIGAMIG_PROJECTS_ROOT", str(repos))
    monkeypatch.setenv("WIGAMIG_LAB_VM_ROOT", str(lab_vm))
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(lab_mgmt))
    monkeypatch.setenv("WIGAMIG_USER", "mhallet")
    monkeypatch.setattr(snap_mod, "INSTALLATIONS_DIR", installs)

    # A bare project dir is enough for the endpoint's existence check.
    (repos / "demo").mkdir(parents=True)
    # Seed a minimal lab-mgmt so _require_active doesn't blow up.
    (lab_mgmt / "members").mkdir(parents=True)
    (lab_mgmt / "lab.md").write_text(
        # github_org is set explicitly so github-kind installs derive a
        # real org (the fallback is now empty = unconfigured).
        "---\nlab: hallett\nname: 'Hallett Lab'\npi: '@mhallet'\n"
        "github_org: hallettmiket\n---\n",
        encoding="utf-8",
    )
    (lab_mgmt / "members" / "mhallet.md").write_text(
        "---\nhandle: '@mhallet'\nfull_name: 'Mike Hallett'\nrole: pi\nstatus: active\n---\n",
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
        "member": "@mhallet",
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
    assert data["member"] == "@mhallet"
    assert data["machine_type"] == "laptop"
    assert data["status"] == "active"
    assert data["components"] == ["git", "vscode"]
    assert data["agents"] == ["oracle", "blacksmith"]


def test_initialize_writes_charter_for_bare_clone(isolated, tmp_path, monkeypatch):
    """A clone with no CHARTER.md must become a murmurent project end-to-end
    when installed: CHARTER appears, the lab_mgmt registry gets an entry,
    and the installation manifest is written. Before the projectize
    refactor this would 404 on bare clones — only project-new'd repos
    could be installed."""
    # Point murmurent commons at a fake so bootstrap_local has agents to symlink.
    commons = tmp_path / "wigamig_commons"
    (commons / "agents").mkdir(parents=True)
    (commons / "agents" / "oracle.md").write_text("# oracle\n")
    (commons / "agents" / "blacksmith.md").write_text("# blacksmith\n")
    monkeypatch.setenv("WIGAMIG_REPO_ROOT", str(commons))
    # Make the demo dir a git working tree so projectize sees a real clone.
    (isolated["repos"] / "demo" / ".git").mkdir()

    client = TestClient(create_app())
    body = _initialize_body(
        raw_path=str(tmp_path / "lv2" / "raw"),
        refined_path=str(tmp_path / "lv2" / "refined"),
    )
    res = client.post("/api/workspace/initialize", json=body)
    assert res.status_code == 200, res.text

    # CHARTER materialised with lead=member, sensitivity=standard.
    charter = (isolated["repos"] / "demo" / "CHARTER.md").read_text()
    assert "project: demo" in charter
    assert "@mhallet" in charter
    # Lab-mgmt registry entry too.
    assert (isolated["tmp"] / "lab-mgmt" / "cert_projects" / "demo.md").is_file()
    # Manifest as before.
    assert (isolated["installs"] / "demo.yaml").is_file()


def test_initialize_ssh_install_on_bare_repo_no_local_dir(isolated, tmp_path, monkeypatch):
    """SSH install of a repo with no local presence at all — the
    closes-the-loop case for #9: click `+ install` for biodatsci on a
    GitHub repo you've never had locally and it ends up wigamig-ready
    on biodatsci, in the Projects list, and in the Installations list.

    Before this change, the 404 at line 1218 blocked any install
    where the local ~/repos/<name> dir didn't exist, even though the
    whole point of an SSH install is that the working tree lives on
    the remote.
    """
    import murmurent.core.remote as _remote_mod
    from murmurent.core import hosts as _hosts

    # Register an SSH host so workspace_initialize can resolve it.
    monkeypatch.setenv("WIGAMIG_HOSTS_FILE", str(tmp_path / "hosts.yaml"))
    _hosts.add(_hosts.Host(
        name="biodatsci", kind="ssh", ssh_host="biodatsci",
        remote_user="mhallet", project_root="/home/UWO/mhallet/repos",
        lab_vm_root="/data/lab_vm/wigamig",
    ))

    # Mock every Remote.run so we don't actually SSH anywhere. Two
    # round trips happen: the install probe (murmurent binary / clone)
    # and the projectize-driven remote_adopt CHARTER write.
    def fake_run(self, command, *, check=True, timeout=60):
        if "murmurent --version" in command:
            stdout = "murmurent 1.0.0\n"
        elif "raw:" in command or "refined:" in command or "notebook:" in command:
            stdout = "\n".join([
                "murmurent:ok:1.0.0",
                "homedir:ok:/home/UWO/mhallet",
                "raw:ok:created /data/lab_vm/wigamig/raw",
                "refined:ok:created /data/lab_vm/wigamig/refined",
                "notebook:ok:created /data/lab_vm/wigamig/lab_notebooks",
                "repo:ok:cloned git@github.com:hallettmiket/freshrepo.git into /home/UWO/mhallet/repos/freshrepo",
                "cc_agent:ok:blacksmith -> wigamig/agents/blacksmith.md",
                "cc_claude_md:ok:created /home/UWO/mhallet/repos/freshrepo/CLAUDE.md",
            ]) + "\n"
        else:
            # The adopt_remote_clone script, identifiable by `DEST=` +
            # the CHARTER heredoc marker.
            stdout = "\n".join([
                "charter:ok:wrote /home/UWO/mhallet/repos/freshrepo/CHARTER.md",
                "cc_agent:ok:blacksmith -> wigamig/agents/blacksmith.md",
                "cc_claude_md:ok:already exists at /home/UWO/mhallet/repos/freshrepo/CLAUDE.md",
            ]) + "\n"
        return _remote_mod.RemoteResult(
            host="biodatsci", command=command, returncode=0,
            stdout=stdout, stderr="",
        )
    monkeypatch.setattr(_remote_mod.Remote, "run", fake_run)

    client = TestClient(create_app())
    body = _initialize_body(
        project="freshrepo",
        ssh_remote="biodatsci",
        has_direct_access=False,
        raw_path="/data/lab_vm/wigamig/raw",
        refined_path="/data/lab_vm/wigamig/refined",
        notebook_path="/data/lab_vm/wigamig/lab_notebooks",
    )
    # Note: ~/repos/freshrepo does NOT exist locally — that's the test.
    assert not (isolated["repos"] / "freshrepo").exists()

    res = client.post("/api/workspace/initialize", json=body)
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["ok"] is True

    # Lab-mgmt registry entry exists with the remote-host fields.
    reg = isolated["tmp"] / "lab-mgmt" / "cert_projects" / "freshrepo.md"
    assert reg.is_file()
    reg_text = reg.read_text()
    assert "host: biodatsci" in reg_text
    assert "/home/UWO/mhallet/repos/freshrepo" in reg_text

    # Installation manifest reflects the SSH install.
    manifest_p = isolated["installs"] / "freshrepo.yaml"
    assert manifest_p.is_file()
    m = yaml.safe_load(manifest_p.read_text())
    assert m["ssh_remote"] == "biodatsci"
    assert m["access"] == "ssh"
    # And the CHARTER write fired remotely (visible in the probes).
    probe_names = [p["name"] for p in payload["probes"]]
    assert "charter" in probe_names


def test_initialize_rejects_unknown_project(isolated):
    client = TestClient(create_app())
    res = client.post("/api/workspace/initialize", json=_initialize_body(project="nope"))
    assert res.status_code == 404


def test_initialize_clone_if_missing_runs_git_clone(isolated, tmp_path, monkeypatch):
    """One-shot clone+adopt+install: Repos-panel + install on a brand-new
    repo. Server should git-clone, then projectize. No 404."""
    # Provide a local bare repo as the "GitHub" origin so git clone works
    # without network. Also set up commons so bootstrap_local doesn't bail.
    commons = tmp_path / "wigamig_commons"
    (commons / "agents").mkdir(parents=True)
    (commons / "agents" / "oracle.md").write_text("# oracle\n")
    monkeypatch.setenv("WIGAMIG_REPO_ROOT", str(commons))

    import subprocess
    origin = tmp_path / "origin" / "newcoin.git"
    origin.parent.mkdir(parents=True)
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
    # Seed the bare repo with one commit so `git clone` produces a working tree.
    seed = tmp_path / "seed"
    subprocess.run(["git", "init", str(seed)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(seed), "config", "user.email", "t@t"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(seed), "config", "user.name", "t"], check=True, capture_output=True)
    (seed / "README.md").write_text("seed\n")
    subprocess.run(["git", "-C", str(seed), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(seed), "commit", "-m", "init"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(seed), "remote", "add", "origin", str(origin)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(seed), "push", "origin", "HEAD:refs/heads/main"], check=True, capture_output=True)

    body = _initialize_body(
        project="newcoin",
        agents=["oracle"],
        raw_path=str(tmp_path / "lv" / "raw"),
        refined_path=str(tmp_path / "lv" / "refined"),
    )
    body["clone_if_missing"] = True
    body["repo_url"] = str(origin)

    client = TestClient(create_app())
    r = client.post("/api/workspace/initialize", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True

    # The clone landed under WIGAMIG_PROJECTS_ROOT/newcoin.
    cloned = isolated["repos"] / "newcoin"
    assert (cloned / ".git").is_dir()
    # CHARTER.md was written by projectize after the clone.
    assert (cloned / "CHARTER.md").is_file()
    # Installation manifest exists.
    assert (isolated["installs"] / "newcoin.yaml").is_file()


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
            "member": "@mhallet", "project": "other",
            "machine_type": "laptop", "username": "mth",
        }),
        encoding="utf-8",
    )

    member_view = snap_mod._installations("mhallet", persona="member")
    pi_view = snap_mod._installations("mhallet", persona="pi")

    assert [r.project for r in member_view] == ["other"]
    assert sorted(r.project for r in pi_view) == ["demo", "other"]


def test_installations_loader_skips_bad_manifest(isolated):
    """One malformed manifest must not break the whole loader."""
    installs = isolated["installs"]
    installs.mkdir(parents=True, exist_ok=True)
    (installs / "broken.yaml").write_text(": : :\n", encoding="utf-8")
    (installs / "good.yaml").write_text(
        yaml.safe_dump({
            "member": "@mhallet", "project": "demo",
            "machine_type": "laptop", "username": "mth",
        }),
        encoding="utf-8",
    )
    rows = snap_mod._installations("mhallet", persona="pi")
    assert [r.project for r in rows] == ["demo"]


def test_installations_loader_returns_empty_when_dir_missing(isolated):
    """No installations dir is the fresh-machine case; must not crash."""
    # `isolated` already points INSTALLATIONS_DIR at a tmp path that doesn't
    # exist yet (no install has happened).
    rows = snap_mod._installations("mhallet", persona="pi")
    assert rows == []
