"""Tests for the Item-3 R1 host registry + SSH chokepoint.

Covers:
  - hosts.yaml round-trip: read → write → read with mixed local/ssh hosts
  - Built-in ``local`` host is always present, never overwritten on read
  - Schema validation rejects bad payloads but doesn't blank the file
  - ``Remote`` builds the right argv for local vs ssh hosts (bash -lc on
    both sides; ssh adds BatchMode + ConnectTimeout)
  - ``Remote.run`` appends one row per call to the remote_audit.log
  - ``Remote.run(check=True)`` raises ``RemoteError`` on non-zero exit
  - ``Remote.run(timeout=...)`` raises ``RemoteError`` with rc=124 on timeout
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from wigamig.core import hosts, remote


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    """Redirect hosts.yaml + remote audit log into tmp_path."""
    monkeypatch.setenv("WIGAMIG_HOSTS_FILE", str(tmp_path / "hosts.yaml"))
    monkeypatch.setenv("WIGAMIG_REMOTE_AUDIT_LOG", str(tmp_path / "remote_audit.log"))
    return tmp_path


# ---------------------------------------------------------------------------
# hosts.yaml
# ---------------------------------------------------------------------------


def test_read_local_only_when_file_missing(isolated):
    registry = hosts.read()
    assert list(registry.keys()) == ["local"]
    assert registry["local"].kind == "local"
    assert registry["local"].project_root == "~/repos"


def test_round_trip_with_ssh_host(isolated):
    bio = hosts.Host(
        name="biodatsci", kind="ssh", ssh_host="biodatsci",
        remote_user="mhallet",
        project_root="/home/mhallet/repos",
        lab_vm_root="/data/lab_vm",
        vault_root="/home/mhallet/Obsidian",
        mount_point="~/Mounts/biodatsci",
        description="Schulich compute server",
    )
    hosts.add(bio)
    reread = hosts.read()
    assert set(reread.keys()) == {"local", "biodatsci"}
    bio2 = reread["biodatsci"]
    assert bio2.ssh_host == "biodatsci"
    assert bio2.remote_user == "mhallet"
    assert bio2.lab_vm_root == "/data/lab_vm"
    assert bio2.mount_point == "~/Mounts/biodatsci"


def test_add_refuses_duplicate(isolated):
    h = hosts.Host(name="biodatsci", kind="ssh", ssh_host="biodatsci")
    hosts.add(h)
    with pytest.raises(hosts.HostAlreadyExists):
        hosts.add(h)


def test_remove_drops_host(isolated):
    h = hosts.Host(name="biodatsci", kind="ssh", ssh_host="biodatsci")
    hosts.add(h)
    hosts.remove("biodatsci")
    assert "biodatsci" not in hosts.read()


def test_remove_local_refused(isolated):
    with pytest.raises(hosts.InvalidHost):
        hosts.remove("local")


def test_remove_unknown_refused(isolated):
    with pytest.raises(hosts.HostNotFound):
        hosts.remove("nope")


def test_resolve_returns_host_or_raises(isolated):
    hosts.add(hosts.Host(name="bio", kind="ssh", ssh_host="biodatsci"))
    assert hosts.resolve("bio").ssh_host == "biodatsci"
    with pytest.raises(hosts.HostNotFound):
        hosts.resolve("ghost")


def test_ssh_kind_requires_ssh_host(isolated):
    """An ssh-kind row missing ssh_host is silently dropped on read."""
    path = hosts.hosts_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "version: 1\nhosts:\n"
        "  broken: { kind: ssh }\n"
        "  ok:     { kind: ssh, ssh_host: foo }\n",
        encoding="utf-8",
    )
    registry = hosts.read()
    assert "broken" not in registry
    assert registry["ok"].ssh_host == "foo"


def test_invalid_kind_dropped(isolated):
    path = hosts.hosts_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "version: 1\nhosts:\n  weird: { kind: ftp }\n",
        encoding="utf-8",
    )
    assert "weird" not in hosts.read()


def test_malformed_yaml_falls_back_to_local_only(isolated):
    path = hosts.hosts_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(": : :\n", encoding="utf-8")
    assert list(hosts.read().keys()) == ["local"]


# ---------------------------------------------------------------------------
# Remote.run argv construction
# ---------------------------------------------------------------------------


def _local_host() -> hosts.Host:
    return hosts.Host(name="local", kind="local")


def _ssh_host(ssh_host: str = "biodatsci") -> hosts.Host:
    return hosts.Host(name="biodatsci", kind="ssh", ssh_host=ssh_host)


def test_remote_argv_for_local_host(isolated, monkeypatch):
    captured: dict = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(remote.subprocess, "run", fake_run)
    r = remote.Remote(_local_host())
    res = r.run("echo hi")
    assert res.ok
    assert captured["argv"] == ["bash", "-lc", "echo hi"]


def test_remote_argv_for_ssh_host(isolated, monkeypatch):
    captured: dict = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(remote.subprocess, "run", fake_run)
    r = remote.Remote(_ssh_host("biodatsci"))
    r.run("ls /data/lab_vm")
    argv = captured["argv"]
    assert argv[0] == "ssh"
    assert "-o" in argv and "BatchMode=yes" in argv
    assert "-o" in argv and "ConnectTimeout=10" in argv
    assert "biodatsci" in argv
    # Last token wraps the command in bash -lc
    assert argv[-1].startswith("bash -lc ")
    # The literal command should appear quoted inside that wrapping.
    assert "ls /data/lab_vm" in argv[-1]


def test_remote_argv_unknown_kind_raises(isolated):
    h = hosts.Host(name="weird", kind="local")
    object.__setattr__(h, "kind", "ftp")
    with pytest.raises(ValueError):
        remote.Remote(h)._build_argv("true")


# ---------------------------------------------------------------------------
# Remote.run side effects: audit log + error handling
# ---------------------------------------------------------------------------


def test_remote_run_appends_audit(isolated, monkeypatch):
    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(remote.subprocess, "run", fake_run)
    r = remote.Remote(_ssh_host())
    r.run("ls /tmp")
    log_path = remote._audit_path()  # noqa: SLF001
    assert log_path.is_file()
    rows = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
    assert len(rows) == 1
    assert rows[0]["host"] == "biodatsci"
    assert rows[0]["ssh_host"] == "biodatsci"
    assert rows[0]["command"] == "ls /tmp"
    assert rows[0]["returncode"] == 0


def test_remote_run_nonzero_raises_when_check_true(isolated, monkeypatch):
    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 2, stdout="", stderr="boom")

    monkeypatch.setattr(remote.subprocess, "run", fake_run)
    r = remote.Remote(_ssh_host())
    with pytest.raises(remote.RemoteError) as exc_info:
        r.run("false")
    assert exc_info.value.returncode == 2
    assert "boom" in exc_info.value.stderr


def test_remote_run_nonzero_returns_when_check_false(isolated, monkeypatch):
    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 5, stdout="", stderr="nope")

    monkeypatch.setattr(remote.subprocess, "run", fake_run)
    r = remote.Remote(_ssh_host())
    res = r.run("false", check=False)
    assert res.ok is False
    assert res.returncode == 5


def test_remote_run_timeout_raises_remote_error(isolated, monkeypatch):
    def fake_run(argv, **kwargs):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=kwargs.get("timeout", 1))

    monkeypatch.setattr(remote.subprocess, "run", fake_run)
    r = remote.Remote(_ssh_host())
    with pytest.raises(remote.RemoteError) as exc_info:
        r.run("sleep 999", timeout=1)
    assert exc_info.value.returncode == 124


def test_remote_run_empty_command_raises(isolated):
    r = remote.Remote(_ssh_host())
    with pytest.raises(ValueError):
        r.run("")


def test_remote_probe_uses_true(isolated, monkeypatch):
    seen: dict = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(remote.subprocess, "run", fake_run)
    r = remote.Remote(_ssh_host())
    res = r.probe()
    assert res.ok
    assert "true" in seen["argv"][-1]


def test_remote_wigamig_version_parses_stdout(isolated, monkeypatch):
    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, stdout="wigamig, version 1.0.0\n", stderr="")

    monkeypatch.setattr(remote.subprocess, "run", fake_run)
    r = remote.Remote(_ssh_host())
    assert r.wigamig_version() == "wigamig, version 1.0.0"
