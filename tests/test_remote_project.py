"""Tests for the Item-3 R2 remote project install dispatcher.

Covers:
  - ``cmd_new_remote`` refuses unknown hosts and local-kind hosts
  - ``cmd_new_remote`` shells out via the SSH chokepoint (mocked) and
    constructs the expected remote ``murmurent project new ...`` command
  - On success, a local remote-pointer dir is created at ``~/repos/<name>/``
    with ``.wigamig-remote-pointer`` + a CHARTER.md carrying ``host:`` +
    ``remote_path:`` in its frontmatter
  - The lab-mgmt registry entry includes ``host:`` and ``remote_path:``
  - ``render_registry_entry`` round-trip with host fields
  - ``is_remote_pointer`` / ``read_remote_pointer`` correctly detect the pointer
  - A connection failure (probe returns rc!=0) raises ``click.ClickException``
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import click

from murmurent.commands import project_cmd
from murmurent.core import hosts as _hosts
from murmurent.core import remote as _remote
from murmurent.core import projects as _projects
from murmurent.core.frontmatter import parse_file


@pytest.fixture
def world(monkeypatch, tmp_path):
    """Isolated lab-mgmt + projects root + hosts.yaml + audit logs."""
    repos = tmp_path / "repos"
    lab_mgmt = tmp_path / "lab-mgmt"
    monkeypatch.setenv("WIGAMIG_PROJECTS_ROOT", str(repos))
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(lab_mgmt))
    monkeypatch.setenv("WIGAMIG_HOSTS_FILE", str(tmp_path / "hosts.yaml"))
    monkeypatch.setenv("WIGAMIG_REMOTE_AUDIT_LOG", str(tmp_path / "remote_audit.log"))
    monkeypatch.setenv("WIGAMIG_USER", "the_pi")
    (lab_mgmt / "projects").mkdir(parents=True)
    (lab_mgmt / "members").mkdir(parents=True)
    (lab_mgmt / "lab.md").write_text(
        "---\nlab: hallett\nname: 'Hallett Lab'\npi: '@the_pi'\n---\n",
        encoding="utf-8",
    )
    (lab_mgmt / "members" / "the_pi.md").write_text(
        "---\nhandle: '@the_pi'\nfull_name: 'Mike Hallett'\nrole: pi\nstatus: active\nlab: hallett\n---\n",
        encoding="utf-8",
    )
    return {
        "tmp": tmp_path,
        "repos": repos,
        "lab_mgmt": lab_mgmt,
    }


@pytest.fixture
def fake_ssh(monkeypatch):
    """Replace subprocess.run inside core.remote so no real SSH runs.

    Returns a list ``calls`` capturing every argv. By default every call
    succeeds with stdout="ok"; tests can monkeypatch the side effect to
    simulate failures.
    """
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(_remote.subprocess, "run", fake_run)
    return calls


@pytest.fixture
def lab-server(world):
    """Register a `lab-server` host so cmd_new_remote can resolve it."""
    _hosts.add(_hosts.Host(
        name="lab-server", kind="ssh", ssh_host="lab-server",
        remote_user="the_pi",
        project_root="/home/the_pi/repos",
        lab_vm_root="/data/lab_vm",
    ))


# ---------------------------------------------------------------------------
# render_registry_entry — host fields
# ---------------------------------------------------------------------------


def test_render_registry_entry_local_unchanged(world):
    summary = _projects.ProjectSummary(
        name="x", path=Path("/tmp/x"),
        sensitivity="standard", lead="@the_pi",
        members=("@the_pi",), choreography=None,
    )
    text = _projects.render_registry_entry(summary, today="2026-05-13")
    assert "host:" not in text
    assert "remote_path:" not in text


def test_render_registry_entry_with_host(world):
    summary = _projects.ProjectSummary(
        name="x", path=Path("/tmp/x"),
        sensitivity="standard", lead="@the_pi",
        members=("@the_pi",), choreography=None,
    )
    text = _projects.render_registry_entry(
        summary, today="2026-05-13",
        host_name="lab-server", remote_path="/home/the_pi/repos/x",
    )
    assert "host: lab-server" in text
    assert "remote_path: /home/the_pi/repos/x" in text


def test_render_registry_entry_remote_requires_path(world):
    summary = _projects.ProjectSummary(
        name="x", path=Path("/tmp/x"),
        sensitivity="standard", lead="@the_pi",
        members=("@the_pi",), choreography=None,
    )
    with pytest.raises(ValueError):
        _projects.render_registry_entry(
            summary, today="2026-05-13", host_name="lab-server", remote_path="",
        )


# ---------------------------------------------------------------------------
# is_remote_pointer / read_remote_pointer
# ---------------------------------------------------------------------------


def test_is_remote_pointer_false_for_regular_dir(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    (d / "CHARTER.md").write_text("---\nproject: proj\n---\n", encoding="utf-8")
    assert _projects.is_remote_pointer(d) is False


def test_is_remote_pointer_true_when_marker_present(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    (d / ".wigamig-remote-pointer").write_text("", encoding="utf-8")
    (d / "CHARTER.md").write_text(
        "---\nproject: proj\nhost: lab-server\nremote_path: /home/the_pi/repos/proj\n---\n",
        encoding="utf-8",
    )
    assert _projects.is_remote_pointer(d) is True
    host, path = _projects.read_remote_pointer(d)
    assert host == "lab-server"
    assert path == "/home/the_pi/repos/proj"


def test_read_remote_pointer_none_when_local_host(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    (d / ".wigamig-remote-pointer").write_text("", encoding="utf-8")
    (d / "CHARTER.md").write_text(
        "---\nproject: proj\nhost: local\n---\n", encoding="utf-8",
    )
    assert _projects.read_remote_pointer(d) is None


# ---------------------------------------------------------------------------
# cmd_new_remote — happy path
# ---------------------------------------------------------------------------


def test_cmd_new_remote_writes_pointer_and_registry(world, lab-server, fake_ssh):
    remote_path = project_cmd.cmd_new_remote(
        "myproj",
        host_name="lab-server",
        members_csv="the_pi,alice",
        sensitivity="standard",
        description="a great project",
    )
    assert remote_path == "/home/the_pi/repos/myproj"
    pointer = world["repos"] / "myproj"
    assert pointer.is_dir()
    assert (pointer / ".wigamig-remote-pointer").is_file()
    charter = pointer / "CHARTER.md"
    assert charter.is_file()
    meta = parse_file(charter).meta
    assert meta["host"] == "lab-server"
    assert meta["remote_path"] == "/home/the_pi/repos/myproj"
    # lab-mgmt registry entry has host: + remote_path:
    registry = world["lab_mgmt"] / "cert_projects" / "myproj.md"
    assert registry.is_file()
    text = registry.read_text(encoding="utf-8")
    assert "host: lab-server" in text
    assert "remote_path: /home/the_pi/repos/myproj" in text


def test_cmd_new_remote_sends_expected_command_over_ssh(world, lab-server, fake_ssh):
    project_cmd.cmd_new_remote(
        "myproj",
        host_name="lab-server",
        members_csv="the_pi,alice",
        sensitivity="standard",
    )
    # 1st call is the probe (`true`); subsequent ones are the actual create.
    assert any("true" in (call[-1] if call else "") for call in fake_ssh)
    create_calls = [c for c in fake_ssh if "murmurent project new" in (c[-1] if c else "")]
    assert create_calls, f"no project new call seen; calls={fake_ssh}"
    cmd = create_calls[0][-1]
    assert "murmurent project new myproj" in cmd
    assert "--members" in cmd
    assert "--sensitivity standard" in cmd
    assert "--lead" in cmd


# ---------------------------------------------------------------------------
# cmd_new_remote — refusals
# ---------------------------------------------------------------------------


def test_cmd_new_remote_unknown_host_refused(world):
    with pytest.raises(click.ClickException) as exc_info:
        project_cmd.cmd_new_remote(
            "x", host_name="ghost", members_csv="the_pi", sensitivity="standard",
        )
    assert "Register it first" in str(exc_info.value)


def test_cmd_new_remote_local_host_refused(world):
    with pytest.raises(click.ClickException) as exc_info:
        project_cmd.cmd_new_remote(
            "x", host_name="local", members_csv="the_pi", sensitivity="standard",
        )
    assert "local" in str(exc_info.value)


def test_cmd_new_remote_needs_sensitivity(world, lab-server):
    with pytest.raises(click.ClickException) as exc_info:
        project_cmd.cmd_new_remote(
            "x", host_name="lab-server", members_csv="the_pi", sensitivity=None,
        )
    assert "sensitivity" in str(exc_info.value)


def test_cmd_new_remote_ssh_unreachable_raises(world, lab-server, monkeypatch):
    """When the probe fails (e.g. ssh refuses connection), raise a clear error."""
    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 255, stdout="", stderr="permission denied")

    monkeypatch.setattr(_remote.subprocess, "run", fake_run)
    with pytest.raises(click.ClickException) as exc_info:
        project_cmd.cmd_new_remote(
            "x", host_name="lab-server", members_csv="the_pi", sensitivity="standard",
        )
    assert "cannot reach host" in str(exc_info.value)


def test_cmd_new_remote_remote_failure_propagates(world, lab-server, monkeypatch):
    """When the remote murmurent project new fails, surface stderr to the user."""
    state = {"call": 0}

    def fake_run(argv, **kwargs):
        state["call"] += 1
        if state["call"] == 1:
            # probe
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        # actual create
        return subprocess.CompletedProcess(argv, 2, stdout="", stderr="boom")

    monkeypatch.setattr(_remote.subprocess, "run", fake_run)
    with pytest.raises(click.ClickException) as exc_info:
        project_cmd.cmd_new_remote(
            "x", host_name="lab-server", members_csv="the_pi", sensitivity="standard",
        )
    assert "boom" in str(exc_info.value)


def test_cmd_new_remote_refuses_to_overwrite_non_pointer(world, lab-server, fake_ssh):
    """If ~/repos/<name>/ already exists without the marker, refuse."""
    existing = world["repos"] / "myproj"
    existing.mkdir(parents=True)
    (existing / "CHARTER.md").write_text("---\nproject: myproj\n---\n", encoding="utf-8")
    with pytest.raises(click.ClickException) as exc_info:
        project_cmd.cmd_new_remote(
            "myproj",
            host_name="lab-server",
            members_csv="the_pi",
            sensitivity="standard",
        )
    assert "already exists" in str(exc_info.value)
