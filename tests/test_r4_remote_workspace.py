"""Tests for Item 3 R4 — dashboard host CRUD + remote workspace launch.

Covers:
  - POST /api/hosts adds a host; refuses duplicate (409)
  - DELETE /api/hosts/{name} removes; 400 on 'local'; 404 on unknown
  - POST /api/hosts/{name}/test runs probes and returns structured rows
    (mocked SSH so no real network)
  - POST /api/workspace/launch for a remote-pointer project returns a
    vscode-remote URL (and doesn't invoke start_workspace.sh)
  - POST /api/workspace/launch for a local project still requires agents
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from murmurent.core import hosts as _hosts
from murmurent.core import remote as _remote
from murmurent.dashboard.server import create_app


@pytest.fixture
def world(monkeypatch, tmp_path):
    repos = tmp_path / "repos"
    lab_mgmt = tmp_path / "lab-mgmt"
    lab_vm = tmp_path / "lab_vm"
    monkeypatch.setenv("WIGAMIG_PROJECTS_ROOT", str(repos))
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(lab_mgmt))
    monkeypatch.setenv("WIGAMIG_LAB_VM_ROOT", str(lab_vm))
    monkeypatch.setenv("WIGAMIG_HOSTS_FILE", str(tmp_path / "hosts.yaml"))
    monkeypatch.setenv("WIGAMIG_REMOTE_AUDIT_LOG", str(tmp_path / "remote_audit.log"))
    monkeypatch.setenv("WIGAMIG_USER", "the_pi")
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
# POST /api/hosts
# ---------------------------------------------------------------------------


def test_post_host_adds(world):
    client = TestClient(create_app())
    res = client.post("/api/hosts", json={
        "name": "lab-server",
        "ssh_host": "lab-server",
        "remote_user": "the_pi",
        "project_root": "~/repos",
        "lab_vm_root": "/data/lab_vm",
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["host"]["name"] == "lab-server"
    # And it shows up in subsequent GETs.
    listing = client.get("/api/hosts").json()
    names = {h["name"] for h in listing["hosts"]}
    assert {"local", "lab-server"} <= names


def test_post_host_duplicate_409(world):
    client = TestClient(create_app())
    body = {"name": "lab-server", "ssh_host": "lab-server"}
    res1 = client.post("/api/hosts", json=body)
    assert res1.status_code == 200
    res2 = client.post("/api/hosts", json=body)
    assert res2.status_code == 409


def test_post_host_local_is_re_derivable(world):
    """The built-in 'local' row is always re-derivable — posting it again
    is a no-op rather than a 409. This matches the core hosts.add() rule
    that lets read() always synthesise 'local' regardless of what's
    been written to the file."""
    client = TestClient(create_app())
    res = client.post("/api/hosts", json={"name": "local", "ssh_host": ""})
    assert res.status_code == 200


# ---------------------------------------------------------------------------
# DELETE /api/hosts/{name}
# ---------------------------------------------------------------------------


def test_delete_host_removes(world):
    client = TestClient(create_app())
    client.post("/api/hosts", json={"name": "lab-server", "ssh_host": "lab-server"})
    res = client.delete("/api/hosts/lab-server")
    assert res.status_code == 200
    listing = client.get("/api/hosts").json()
    assert "lab-server" not in {h["name"] for h in listing["hosts"]}


def test_delete_host_requires_pi(world, monkeypatch):
    """Decommissioning a host is destructive → PI only. A non-PI actor is
    refused and the host survives (regression for the missing-auth gap that was
    silently writing '@unknown' decommission reports)."""
    monkeypatch.delenv("WIGAMIG_USER", raising=False)   # no PI fallback
    client = TestClient(create_app())
    client.post("/api/hosts", json={"name": "lab-server", "ssh_host": "lab-server"})
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
# POST /api/hosts/{name}/test
# ---------------------------------------------------------------------------


def _ok(stdout: str = "ok") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")


def _fail(rc: int = 1, stderr: str = "boom") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], rc, stdout="", stderr=stderr)


def test_host_test_all_ok(world, monkeypatch):
    client = TestClient(create_app())
    client.post("/api/hosts", json={
        "name": "lab-server", "ssh_host": "lab-server", "lab_vm_root": "/data/lab_vm",
    })

    # Probe sequence: ssh (true), murmurent --version, test -d lab_vm dirs, gh auth status
    sequence = iter([
        _ok(),                            # ssh probe (true)
        _ok("murmurent 1.0.0"),           # murmurent --version
        _ok(),                            # lab_vm test -d
        _ok("Logged in to github.com"),   # gh auth status
    ])
    monkeypatch.setattr(_remote.subprocess, "run", lambda *a, **k: next(sequence))

    res = client.post("/api/hosts/lab-server/test")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["overall"] == "ok"
    statuses = {p["name"]: p["status"] for p in body["probes"]}
    assert statuses == {"ssh": "ok", "murmurent": "ok", "lab_vm": "ok", "gh_auth": "ok"}


def test_host_test_murmurent_missing_fails(world, monkeypatch):
    client = TestClient(create_app())
    client.post("/api/hosts", json={"name": "lab-server", "ssh_host": "lab-server"})
    sequence = iter([
        _ok(),                              # ssh probe
        _fail(127, "murmurent: command not found"),  # murmurent --version
        _ok(),                              # lab_vm
        _fail(1, "not authenticated"),      # gh auth
    ])
    monkeypatch.setattr(_remote.subprocess, "run", lambda *a, **k: next(sequence))

    body = client.post("/api/hosts/lab-server/test").json()
    assert body["overall"] == "fail"
    by_name = {p["name"]: p for p in body["probes"]}
    assert by_name["murmurent"]["status"] == "fail"
    assert by_name["murmurent"]["required"] is True
    assert "install_remote.sh" in by_name["murmurent"]["detail"]
    # lab_vm and gh_auth are warn-only — their failures don't change overall=fail
    # but their statuses are reported correctly.
    assert by_name["gh_auth"]["status"] == "warn"


def test_host_test_ssh_fails_short_circuits(world, monkeypatch):
    client = TestClient(create_app())
    client.post("/api/hosts", json={"name": "lab-server", "ssh_host": "lab-server"})

    call_count = {"n": 0}

    def fake_run(*a, **k):
        call_count["n"] += 1
        return _fail(255, "permission denied (publickey)")

    monkeypatch.setattr(_remote.subprocess, "run", fake_run)
    body = client.post("/api/hosts/lab-server/test").json()
    # Only the ssh probe was issued — no point continuing.
    assert call_count["n"] == 1
    assert body["overall"] == "fail"
    assert body["probes"][0]["name"] == "ssh"
    assert body["probes"][0]["status"] == "fail"


def test_host_test_local_returns_ok_without_ssh_call(world, monkeypatch):
    """The local host has nothing to ssh into, but the test endpoint
    still runs murmurent --version + the lab_vm/gh probes via bash -lc."""
    client = TestClient(create_app())
    sequence = iter([
        _ok("murmurent 1.0.0"),
        _fail(),  # lab_vm missing locally — warn
        _ok("Logged in"),
    ])
    monkeypatch.setattr(_remote.subprocess, "run", lambda *a, **k: next(sequence))

    body = client.post("/api/hosts/local/test").json()
    # No required failure, even though lab_vm is warn — overall ok.
    assert body["overall"] == "ok"
    statuses = {p["name"]: p["status"] for p in body["probes"]}
    assert statuses["ssh"] == "ok"          # synthetic "local host"
    assert statuses["murmurent"] == "ok"
    assert statuses["lab_vm"] == "warn"


# ---------------------------------------------------------------------------
# Workspace launch for remote project
# ---------------------------------------------------------------------------


def _seed_remote_pointer(repos: Path, lab_mgmt: Path, name: str = "candi") -> None:
    p = repos / name
    p.mkdir(parents=True)
    p.joinpath(".wigamig-remote-pointer").write_text("", encoding="utf-8")
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
