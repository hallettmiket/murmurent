"""Tests for the Item-3 R3 dashboard surface (hosts endpoint, ProjectRow.host,
create-project request roundtrip with --host).

Covers:
  - ``GET /api/hosts`` returns at minimum ``{name: "local"}`` and surfaces any
    custom hosts the user registered in ~/.murmurent/hosts.yaml
  - ``ProjectRow.host`` / ``remote_path`` / ``remote_ssh_host`` are populated
    for remote-pointer dirs and stay empty for plain local projects
  - ``POST /api/request/create-project`` accepts ``host: biodatsci`` and the
    JoinRequest persists it in frontmatter
  - On approval, a request with ``host: biodatsci`` routes to
    ``cmd_new_remote`` (verified by patching project_cmd)
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from murmurent.core import hosts as _hosts
from murmurent.core import projects as _projects
from murmurent.core import requests as req_core
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
    monkeypatch.setenv("MURMURENT_ROLE_AUDIT_LOG", str(tmp_path / "role_audit.log"))
    monkeypatch.setenv("MURMURENT_USER", "mhallet")
    (lab_mgmt / "projects").mkdir(parents=True)
    (lab_mgmt / "members").mkdir(parents=True)
    (lab_mgmt / "requests").mkdir(parents=True)
    (lab_mgmt / "lab.md").write_text(
        "---\nlab: hallett\nname: 'Hallett Lab'\npi: '@mhallet'\n---\n",
        encoding="utf-8",
    )
    (lab_mgmt / "members" / "mhallet.md").write_text(
        "---\nhandle: '@mhallet'\nfull_name: 'Mike Hallett'\nrole: pi\nstatus: active\nlab: hallett\n---\n",
        encoding="utf-8",
    )
    return {"tmp": tmp_path, "repos": repos, "lab_mgmt": lab_mgmt}


# ---------------------------------------------------------------------------
# /api/hosts
# ---------------------------------------------------------------------------


def test_hosts_endpoint_always_has_local(world):
    client = TestClient(create_app())
    res = client.get("/api/hosts")
    assert res.status_code == 200
    body = res.json()
    names = {h["name"] for h in body["hosts"]}
    assert "local" in names


def test_hosts_endpoint_includes_registered_ssh_hosts(world):
    _hosts.add(_hosts.Host(
        name="biodatsci", kind="ssh", ssh_host="biodatsci",
        remote_user="mhallet",
        project_root="/home/mhallet/repos",
        lab_vm_root="/data/lab_vm",
    ))
    client = TestClient(create_app())
    res = client.get("/api/hosts")
    body = res.json()
    by_name = {h["name"]: h for h in body["hosts"]}
    assert "biodatsci" in by_name
    assert by_name["biodatsci"]["is_remote"] is True
    assert by_name["biodatsci"]["ssh_host"] == "biodatsci"


def test_hosts_endpoint_includes_scan_dirs(world):
    """``GET /api/hosts`` must surface ``scan_dirs`` so the Machines panel
    can render per-host repo locations and the Repo Inventory knows which
    dirs each host was scanned with."""
    _hosts.add(_hosts.Host(
        name="biodatsci", kind="ssh", ssh_host="biodatsci",
        scan_dirs=("repos", "/srv/projects"),
    ))
    client = TestClient(create_app())
    body = client.get("/api/hosts").json()
    by_name = {h["name"]: h for h in body["hosts"]}
    assert by_name["biodatsci"]["scan_dirs"] == ["repos", "/srv/projects"]
    # Hosts with no scan_dirs round-trip as an empty list (not missing key).
    assert by_name["local"]["scan_dirs"] == []


def test_post_host_accepts_scan_dirs(world):
    """``POST /api/hosts`` must accept ``scan_dirs`` so the Add-Machine
    form can register a host with custom repo locations in one round-trip."""
    client = TestClient(create_app())
    res = client.post("/api/hosts", json={
        "name": "biodatsci", "ssh_host": "biodatsci",
        "scan_dirs": ["repos", "/srv/projects"],
    })
    assert res.status_code == 200, res.text
    # And the value really did land in hosts.yaml.
    assert _hosts.resolve("biodatsci").scan_dirs == ("repos", "/srv/projects")


def test_patch_host_scan_dirs_round_trip(world):
    """``PATCH /api/hosts/{name}/scan-dirs`` must replace the list and
    persist it. Existing fields (ssh_host, remote_user, …) must survive
    untouched — this is the only way to edit a registered host today."""
    _hosts.add(_hosts.Host(
        name="biodatsci", kind="ssh", ssh_host="biodatsci",
        remote_user="mhallet", description="lab server",
    ))
    client = TestClient(create_app())
    res = client.patch("/api/hosts/biodatsci/scan-dirs", json={
        "scan_dirs": ["repos", "/srv/projects"],
    })
    assert res.status_code == 200, res.text
    assert res.json()["host"]["scan_dirs"] == ["repos", "/srv/projects"]
    h = _hosts.resolve("biodatsci")
    assert h.scan_dirs == ("repos", "/srv/projects")
    # Unrelated fields preserved.
    assert h.remote_user == "mhallet"
    assert h.description == "lab server"


def test_patch_host_scan_dirs_unknown_host_404s(world):
    """Touching an unregistered host returns 404, not a silent success."""
    client = TestClient(create_app())
    res = client.patch("/api/hosts/ghost/scan-dirs", json={"scan_dirs": ["x"]})
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Remote-pointer detection in snapshot.ProjectRow
# ---------------------------------------------------------------------------


def _seed_local_project(repos: Path, lab_mgmt: Path, name: str = "loc") -> None:
    """Make a tiny local project so the dashboard has something to walk."""
    p = repos / name
    (p / "exp").mkdir(parents=True)
    p.joinpath("CHARTER.md").write_text(
        "---\n"
        f"project: {name}\n"
        "sensitivity: standard\n"
        "lead: '@mhallet'\n"
        "created: 2026-05-13\n"
        "members:\n  - '@mhallet'\n"
        "---\n# loc\n",
        encoding="utf-8",
    )
    lab_mgmt.joinpath("projects", f"{name}.md").write_text(
        "---\n"
        f"project: {name}\n"
        f"path: {p}\n"
        "sensitivity: standard\n"
        "lead: '@mhallet'\n"
        "created: 2026-05-13\n"
        "members:\n  - '@mhallet'\n"
        "---\n",
        encoding="utf-8",
    )


def _seed_remote_pointer(repos: Path, lab_mgmt: Path, name: str = "rem") -> None:
    """Make a remote-pointer project pointing at biodatsci."""
    p = repos / name
    p.mkdir(parents=True)
    p.joinpath(".murmurent-remote-pointer").write_text("", encoding="utf-8")
    p.joinpath("CHARTER.md").write_text(
        "---\n"
        f"project: {name}\n"
        "sensitivity: standard\n"
        "lead: '@mhallet'\n"
        "created: 2026-05-13\n"
        "host: biodatsci\n"
        f"remote_path: /home/mhallet/repos/{name}\n"
        "members:\n  - '@mhallet'\n"
        "---\n# rem\n",
        encoding="utf-8",
    )
    lab_mgmt.joinpath("projects", f"{name}.md").write_text(
        "---\n"
        f"project: {name}\n"
        f"path: {p}\n"
        "sensitivity: standard\n"
        "lead: '@mhallet'\n"
        "host: biodatsci\n"
        f"remote_path: /home/mhallet/repos/{name}\n"
        "created: 2026-05-13\n"
        "members:\n  - '@mhallet'\n"
        "---\n",
        encoding="utf-8",
    )


def test_project_row_marks_local_project_as_host_local(world):
    _seed_local_project(world["repos"], world["lab_mgmt"])
    client = TestClient(create_app())
    res = client.get("/api/dashboard?user=mhallet&persona=pi")
    assert res.status_code == 200, res.text
    rows = res.json()["projects"]
    loc = next(r for r in rows if r["name"] == "loc")
    assert loc["host"] == "local"
    assert loc["remote_path"] is None
    assert loc["remote_ssh_host"] is None


def test_project_row_marks_remote_pointer(world):
    _hosts.add(_hosts.Host(
        name="biodatsci", kind="ssh", ssh_host="biodatsci",
        project_root="/home/mhallet/repos",
    ))
    _seed_remote_pointer(world["repos"], world["lab_mgmt"])
    client = TestClient(create_app())
    res = client.get("/api/dashboard?user=mhallet&persona=pi")
    rows = res.json()["projects"]
    rem = next(r for r in rows if r["name"] == "rem")
    assert rem["host"] == "biodatsci"
    assert rem["remote_path"] == "/home/mhallet/repos/rem"
    assert rem["remote_ssh_host"] == "biodatsci"


def test_project_row_remote_pointer_falls_back_to_host_name(world):
    """When the host isn't registered in hosts.yaml, remote_ssh_host
    falls back to the host name so the UI still shows something useful."""
    # NOTE: do not register biodatsci this time.
    _seed_remote_pointer(world["repos"], world["lab_mgmt"])
    client = TestClient(create_app())
    res = client.get("/api/dashboard?user=mhallet&persona=pi")
    rows = res.json()["projects"]
    rem = next(r for r in rows if r["name"] == "rem")
    assert rem["host"] == "biodatsci"
    assert rem["remote_ssh_host"] == "biodatsci"


# ---------------------------------------------------------------------------
# Create-project request with host
# ---------------------------------------------------------------------------


def test_create_project_request_persists_host(world):
    client = TestClient(create_app())
    res = client.post("/api/request/create-project", json={
        "project": "newproj",
        "proposed_members": ["@mhallet"],
        "sensitivity": "standard",
        "justification": "scratching an itch",
        "host": "biodatsci",
    })
    assert res.status_code == 200, res.text
    body = res.json()
    req_id = body["request"]["id"]
    # Read the request back from disk and confirm host persisted.
    req = req_core.parse_request(req_core.request_path(req_id))
    assert req.host == "biodatsci"
    assert req.kind == "project-create"


def test_create_project_request_default_host_is_local(world):
    client = TestClient(create_app())
    res = client.post("/api/request/create-project", json={
        "project": "deflocal",
        "proposed_members": ["@mhallet"],
        "sensitivity": "standard",
        "justification": "",
    })
    assert res.status_code == 200, res.text
    req = req_core.parse_request(req_core.request_path(res.json()["request"]["id"]))
    assert req.host in (None, "local")


def test_approve_routes_remote_to_cmd_new_remote(world, monkeypatch):
    """An approved project-create with host=biodatsci must call
    cmd_new_remote, not cmd_new."""
    from murmurent.commands import project_cmd as _project_cmd
    seen: dict = {}

    def fake_cmd_new(*a, **kw):
        seen["local"] = True

    def fake_cmd_new_remote(name, **kw):
        seen["remote"] = True
        seen["remote_kw"] = kw
        return "/home/mhallet/repos/" + name

    monkeypatch.setattr(_project_cmd, "cmd_new", fake_cmd_new)
    monkeypatch.setattr(_project_cmd, "cmd_new_remote", fake_cmd_new_remote)
    _hosts.add(_hosts.Host(
        name="biodatsci", kind="ssh", ssh_host="biodatsci",
        project_root="/home/mhallet/repos",
    ))

    client = TestClient(create_app())
    res = client.post("/api/request/create-project", json={
        "project": "remoteproj",
        "proposed_members": ["@mhallet"],
        "sensitivity": "standard",
        "host": "biodatsci",
    })
    req_id = res.json()["request"]["id"]
    # PI approves.
    res2 = client.post(f"/api/request/{req_id}/approve")
    assert res2.status_code == 200, res2.text
    assert seen.get("remote") is True
    assert seen.get("local") is None
    assert seen["remote_kw"]["host_name"] == "biodatsci"
