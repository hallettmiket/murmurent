"""Tests for Item 3 R4 — dashboard host registry + remote workspace launch.

Covers:
  - DELETE /api/hosts/{name} removes; 403 non-PI; 400 on 'local'; 404 unknown
  - PATCH /api/hosts/{name} is connection-only (ignores vault CONFIG params)
  - POST /api/workspace/launch for a remote-pointer project returns a
    vscode-remote URL (and doesn't invoke start_workspace.sh)
  - POST /api/workspace/launch for a local project uses open_murmurent.sh

Issue #94: ``POST /api/hosts`` (register a foreign SSH host) and
``POST /api/hosts/{name}/test`` (connectivity probes) were removed with the
retired "add machine / SSH repo scan" flow. Foreign hosts are no longer added
from the UI; the DELETE / PATCH endpoints still operate on pre-existing
``hosts.yaml`` entries, so those tests seed rows directly via ``core.hosts.add``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from murmurent.core import hosts as _hosts
from murmurent.dashboard.server import create_app


@pytest.fixture
def world(monkeypatch, tmp_path):
    repos = tmp_path / "repos"
    lab_mgmt = tmp_path / "lab-mgmt"
    lab_vm = tmp_path / "lab_vm"
    monkeypatch.setenv("MURMURENT_PROJECTS_ROOT", str(repos))
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(lab_mgmt))
    monkeypatch.setenv("MURMURENT_LAB_VM_ROOT", str(lab_vm))
    monkeypatch.setenv("MURMURENT_HOSTS_FILE", str(tmp_path / "hosts.yaml"))
    monkeypatch.setenv("MURMURENT_REMOTE_AUDIT_LOG", str(tmp_path / "remote_audit.log"))
    monkeypatch.setenv("MURMURENT_USER", "the_pi")
    (lab_mgmt / "projects").mkdir(parents=True)
    (lab_mgmt / "members").mkdir(parents=True)
    (lab_mgmt / "requests").mkdir(parents=True)
    (lab_mgmt / "lab.md").write_text(
        "---\nlab: hallett\nname: 'Hallett Lab'\npi: '@the_pi'\n---\n",
        encoding="utf-8",
    )
    (lab_mgmt / "members" / "the_pi.md").write_text(
        "---\nhandle: '@the_pi'\nfull_name: 'Mike Hallett'\nrole: pi\nstatus: active\nlab: hallett\n---\n",
        encoding="utf-8",
    )
    return {"tmp": tmp_path, "repos": repos, "lab_mgmt": lab_mgmt}


# ---------------------------------------------------------------------------
# Host registry endpoints (issue #94)
#
# POST /api/hosts (add a foreign SSH host) and POST /api/hosts/{name}/test
# (connectivity probes) were removed with the retired "add machine / SSH repo
# scan" flow. Foreign hosts are seeded directly via core.hosts.add — the same
# pre-existing hosts.yaml rows that --tunnel / DELETE / PATCH still operate on.
# ---------------------------------------------------------------------------


def _seed_host(name: str = "lab-server", **kw) -> None:
    """Write a foreign ssh host straight into the registry (the UI no longer
    adds these; #94)."""
    _hosts.add(_hosts.Host(name=name, kind="ssh",
                           ssh_host=kw.pop("ssh_host", name), **kw))


def test_patch_host_ignores_vault_config_params(world):
    """Issue #80: PATCH /api/hosts is connection-only — the retired vault CONFIG
    fields are ignored, never persisted. (The this-machine editor uses this
    endpoint for the local row; here we exercise a pre-existing foreign row.)"""
    _seed_host("lab-server")
    client = TestClient(create_app())
    res = client.patch("/api/hosts/lab-server", json={
        "description": "compute node",
        "vault_root": "/srv/murmurent_vault",
        "oracle_subfolder": "oracle2",
        "notebook_subfolder": "notebook2",
        "lab_vault_root": "/srv/murmurent_lab_mgmt_mh",
    })
    assert res.status_code == 200, res.text
    row = next(r for r in client.get("/api/hosts").json()["hosts"]
               if r["name"] == "lab-server")
    # The connection-only edit landed; the config params did not.
    assert row["description"] == "compute node"
    assert row["lab_vault_root"] == ""
    assert row["vault_root"] != "/srv/murmurent_vault"


# ---------------------------------------------------------------------------
# DELETE /api/hosts/{name} — kept; operates on pre-existing entries
# ---------------------------------------------------------------------------


def test_delete_host_removes(world):
    _seed_host("lab-server")
    client = TestClient(create_app())
    res = client.delete("/api/hosts/lab-server")
    assert res.status_code == 200
    listing = client.get("/api/hosts").json()
    assert "lab-server" not in {h["name"] for h in listing["hosts"]}


def test_delete_host_requires_pi(world, monkeypatch):
    """Decommissioning a host is destructive → PI only. A non-PI actor is
    refused and the host survives (regression for the missing-auth gap that was
    silently writing '@unknown' decommission reports)."""
    monkeypatch.delenv("MURMURENT_USER", raising=False)   # no PI fallback
    _seed_host("lab-server")
    client = TestClient(create_app())
    res = client.delete("/api/hosts/lab-server?user=intruder")
    assert res.status_code == 403
    listing = client.get("/api/hosts").json()
    assert "lab-server" in {h["name"] for h in listing["hosts"]}   # not removed


def test_delete_local_refused(world):
    client = TestClient(create_app())
    res = client.delete("/api/hosts/local")
    assert res.status_code == 400


def test_delete_unknown_404(world):
    client = TestClient(create_app())
    res = client.delete("/api/hosts/nope")
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Workspace launch for remote project
# ---------------------------------------------------------------------------


def _seed_remote_pointer(repos: Path, lab_mgmt: Path, name: str = "candi") -> None:
    p = repos / name
    p.mkdir(parents=True)
    p.joinpath(".murmurent-remote-pointer").write_text("", encoding="utf-8")
    p.joinpath("CHARTER.md").write_text(
        "---\n"
        f"project: {name}\n"
        "sensitivity: standard\n"
        "lead: '@the_pi'\n"
        "created: 2026-05-13\n"
        "host: lab-server\n"
        f"remote_path: /home/the_pi/repos/{name}\n"
        "members:\n  - '@the_pi'\n"
        "---\n",
        encoding="utf-8",
    )
    lab_mgmt.joinpath("projects", f"{name}.md").write_text(
        "---\n"
        f"project: {name}\n"
        f"path: {p}\n"
        "sensitivity: standard\n"
        "lead: '@the_pi'\n"
        "host: lab-server\n"
        f"remote_path: /home/the_pi/repos/{name}\n"
        "created: 2026-05-13\n"
        "members:\n  - '@the_pi'\n"
        "---\n",
        encoding="utf-8",
    )


def _seed_local_for_launch(repos: Path, lab_mgmt: Path, name: str = "loc") -> None:
    """Minimal local project so workspace_launch finds it via find_project."""
    p = repos / name
    p.mkdir(parents=True)
    p.joinpath("CHARTER.md").write_text(
        "---\n"
        f"project: {name}\nsensitivity: standard\nlead: '@the_pi'\n"
        "created: 2026-05-13\nmembers:\n  - '@the_pi'\n"
        "---\n# loc\n",
        encoding="utf-8",
    )
    lab_mgmt.joinpath("projects", f"{name}.md").write_text(
        "---\n"
        f"project: {name}\npath: {p}\nsensitivity: standard\nlead: '@the_pi'\n"
        "created: 2026-05-13\nmembers:\n  - '@the_pi'\n---\n",
        encoding="utf-8",
    )


def test_workspace_launch_local_uses_open_wigamig_sh(world, monkeypatch):
    """The dashboard's local-project launch now invokes
    scripts/open_murmurent.sh — the 80%-window launcher with monitor
    detection — instead of the older scripts/start_workspace.sh that
    spawned a VSCode + iTerm 65/35 split. The agent-log role moved
    into VSCode's BR pane via the murmurent hook, so iTerm windows are
    no longer needed for the local flow.
    """
    _seed_local_for_launch(world["repos"], world["lab_mgmt"])
    launched = {"argv": None}

    def fake_popen(argv, **kwargs):
        launched["argv"] = list(argv)
        class _Stub:
            pass
        return _Stub()

    monkeypatch.setattr("subprocess.Popen", fake_popen)

    client = TestClient(create_app())
    res = client.post("/api/workspace/launch?user=the_pi", json={
        "project": "loc",
        # Local launch no longer requires an agent pick — the launcher
        # opens the repo and CC hooks do their thing per-project.
        "agents": [],
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["launcher"].endswith("/open_murmurent.sh")
    # First argv element is the launcher; second is the project dir.
    assert launched["argv"] is not None
    assert launched["argv"][0].endswith("/open_murmurent.sh")
    assert launched["argv"][1].endswith("/loc")


def test_workspace_launch_remote_returns_vscode_url(world, monkeypatch):
    _hosts.add(_hosts.Host(
        name="lab-server", kind="ssh", ssh_host="lab-server",
        project_root="/home/the_pi/repos",
    ))
    _seed_remote_pointer(world["repos"], world["lab_mgmt"])
    launched = {"argv": None}

    def fake_popen(argv, **kwargs):
        launched["argv"] = argv
        class _Stub:
            pass
        return _Stub()

    monkeypatch.setattr("subprocess.Popen", fake_popen)

    client = TestClient(create_app())
    res = client.post("/api/workspace/launch?user=the_pi", json={
        "project": "candi",
        "agents": [],  # agents irrelevant for remote
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["host"] == "lab-server"
    assert body["remote_path"] == "/home/the_pi/repos/candi"
    assert body["vscode_url"] == "vscode-remote://ssh-remote+lab-server/home/the_pi/repos/candi"
    # Two acceptable launchers (2026-05-15 refactor): the ``code`` CLI
    # invoked with ``--folder-uri`` (preferred — works without macOS
    # LaunchServices registering the vscode-remote scheme), or ``open``
    # as a fallback. Either way the URL must be present in argv.
    if launched["argv"] is not None:
        argv0 = launched["argv"][0]
        if argv0 == "open":
            assert launched["argv"][1] == body["vscode_url"]
        else:
            assert argv0.endswith("/code")
            assert "--folder-uri" in launched["argv"]
            assert body["vscode_url"] in launched["argv"]


def test_workspace_launch_remote_falls_back_when_open_fails(world, monkeypatch):
    """If `open` isn't available (Linux dev box), we still return the URL."""
    _hosts.add(_hosts.Host(name="lab-server", kind="ssh", ssh_host="lab-server"))
    _seed_remote_pointer(world["repos"], world["lab_mgmt"])

    def fake_popen(argv, **kwargs):
        raise OSError("no open command")
    monkeypatch.setattr("subprocess.Popen", fake_popen)

    client = TestClient(create_app())
    body = client.post("/api/workspace/launch?user=the_pi", json={
        "project": "candi", "agents": [],
    }).json()
    assert body["launched"] is False
    assert body["vscode_url"].startswith("vscode-remote://ssh-remote+lab-server")


def test_workspace_launch_unknown_project_404(world):
    client = TestClient(create_app())
    res = client.post("/api/workspace/launch?user=the_pi", json={
        "project": "ghost", "agents": ["blacksmith"],
    })
    assert res.status_code == 404
