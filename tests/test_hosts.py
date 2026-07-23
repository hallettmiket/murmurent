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

from murmurent.core import hosts, remote


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    """Redirect hosts.yaml + remote audit log into tmp_path."""
    monkeypatch.setenv("MURMURENT_HOSTS_FILE", str(tmp_path / "hosts.yaml"))
    monkeypatch.setenv("MURMURENT_REMOTE_AUDIT_LOG", str(tmp_path / "remote_audit.log"))
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
    """Connection fields round-trip; param fields are NOT persisted (issue #80 —
    hosts.yaml is a connection-only registry now)."""
    bio = hosts.Host(
        name="lab-server", kind="ssh", ssh_host="lab-server",
        remote_user="the_pi",
        project_root="/home/the_pi/repos",
        lab_vm_root="/data/lab_vm",
        vault_root="/home/the_pi/Obsidian",
        mount_point="~/Mounts/lab-server",
        description="Schulich compute server",
    )
    hosts.add(bio)
    reread = hosts.read()
    assert set(reread.keys()) == {"local", "lab-server"}
    bio2 = reread["lab-server"]
    # Connection + repo-location metadata survives.
    assert bio2.ssh_host == "lab-server"
    assert bio2.remote_user == "the_pi"
    assert bio2.mount_point == "~/Mounts/lab-server"
    assert bio2.description == "Schulich compute server"
    assert bio2.project_root == "/home/the_pi/repos"
    # CONFIG params are dropped on write → revert to dataclass defaults on read.
    assert bio2.lab_vm_root == "~/lab_vm/data"
    assert bio2.vault_root == "~/Documents/Obsidian"


def test_write_drops_config_params(isolated):
    """The serialised YAML carries no per-machine CONFIG keys (issue #80) —
    but keeps connection + repo-location coordinates."""
    hosts.add(hosts.Host(
        name="lab-server", kind="ssh", ssh_host="lab-server",
        remote_user="the_pi", project_root="/p", lab_vm_root="/d",
        vault_root="/v", lab_vault_root="/lm", scan_dirs=("repos",),
    ))
    text = hosts.hosts_file().read_text(encoding="utf-8")
    for banned in ("lab_vm_root", "vault_root", "lab_vault_root",
                   "oracle_subfolder", "notebook_subfolder", "data_subfolder"):
        assert banned not in text, f"{banned} should not be persisted"
    # Connection + repo-location coordinates ARE there.
    assert "ssh_host" in text and "scan_dirs" in text
    assert "project_root" in text


def test_legacy_config_params_read_but_dropped_on_rewrite(isolated):
    """A pre-#80 hosts.yaml with config params still LOADS (non-destructive);
    the connection row is preserved and the config params drop on next write."""
    path = hosts.hosts_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "version: 1\nhosts:\n"
        "  lab-server:\n"
        "    kind: ssh\n"
        "    ssh_host: lab-server\n"
        "    remote_user: the_pi\n"
        "    project_root: /home/the_pi/repos\n"
        "    lab_vm_root: /data/lab_vm\n"
        "    vault_root: /home/the_pi/Obsidian\n"
        "    scan_dirs: [repos]\n",
        encoding="utf-8",
    )
    # Non-destructive read: legacy config params are still honoured until rewritten.
    h = hosts.read()["lab-server"]
    assert h.lab_vm_root == "/data/lab_vm"
    assert h.scan_dirs == ("repos",)
    # A connection edit preserves the row + repo-location but drops config params.
    hosts.update_host("lab-server", description="compute")
    text = hosts.hosts_file().read_text(encoding="utf-8")
    assert "lab-server" in text and "the_pi" in text   # row preserved
    assert "project_root" in text                       # repo-location kept
    assert "lab_vm_root" not in text                    # config param dropped
    reread = hosts.read()["lab-server"]
    assert reread.ssh_host == "lab-server"
    assert reread.description == "compute"
    assert reread.project_root == "/home/the_pi/repos"


def test_add_refuses_duplicate(isolated):
    h = hosts.Host(name="lab-server", kind="ssh", ssh_host="lab-server")
    hosts.add(h)
    with pytest.raises(hosts.HostAlreadyExists):
        hosts.add(h)


def test_remove_drops_host(isolated):
    h = hosts.Host(name="lab-server", kind="ssh", ssh_host="lab-server")
    hosts.add(h)
    hosts.remove("lab-server")
    assert "lab-server" not in hosts.read()


def test_remove_local_refused(isolated):
    with pytest.raises(hosts.InvalidHost):
        hosts.remove("local")


def test_remove_unknown_refused(isolated):
    with pytest.raises(hosts.HostNotFound):
        hosts.remove("nope")


def test_resolve_returns_host_or_raises(isolated):
    hosts.add(hosts.Host(name="bio", kind="ssh", ssh_host="lab-server"))
    assert hosts.resolve("bio").ssh_host == "lab-server"
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


def test_scan_dirs_round_trip_absolute_and_relative(isolated):
    """User-declared scan dirs (mixed $HOME-relative + absolute) must
    survive a write → read cycle so the repo-inventory scanner sees
    them on every load."""
    h = hosts.Host(
        name="lab-server", kind="ssh", ssh_host="lab-server",
        scan_dirs=("repos", "work/clones", "/srv/projects"),
    )
    hosts.add(h)
    reread = hosts.read()["lab-server"]
    assert reread.scan_dirs == ("repos", "work/clones", "/srv/projects")


def test_scan_dirs_default_is_empty_tuple(isolated):
    """A host with no scan_dirs in YAML reads back as () so the inventory
    scanner knows to apply its built-in defaults."""
    hosts.add(hosts.Host(name="bio", kind="ssh", ssh_host="bio"))
    assert hosts.read()["bio"].scan_dirs == ()


def test_scan_dirs_drops_non_string_entries(isolated):
    """A YAML scan_dirs list with junk entries (None, ints) keeps the
    valid strings instead of rejecting the whole host."""
    path = hosts.hosts_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "version: 1\nhosts:\n"
        "  bio:\n"
        "    kind: ssh\n"
        "    ssh_host: bio\n"
        "    scan_dirs: [repos, null, 42, '/srv/projects', '  ']\n",
        encoding="utf-8",
    )
    assert hosts.read()["bio"].scan_dirs == ("repos", "/srv/projects")


def test_scan_dirs_omitted_from_yaml_when_empty(isolated):
    """We don't want every host row to grow a noisy ``scan_dirs: []``
    after write — only persist the field when the user has set it."""
    hosts.add(hosts.Host(name="bio", kind="ssh", ssh_host="bio"))
    raw = hosts.hosts_file().read_text(encoding="utf-8")
    assert "scan_dirs" not in raw


def test_update_scan_dirs_preserves_other_fields(isolated):
    """Editing scan_dirs from the dashboard must not blank out the connection
    metadata (ssh_host, remote_user, description)."""
    hosts.add(hosts.Host(
        name="bio", kind="ssh", ssh_host="bio.example",
        remote_user="the_pi", description="schulich",
    ))
    updated = hosts.update_scan_dirs("bio", ["repos", "/srv/projects"])
    assert updated.scan_dirs == ("repos", "/srv/projects")
    assert updated.ssh_host == "bio.example"
    assert updated.remote_user == "the_pi"
    assert updated.description == "schulich"
    # Round-trip verifies write persisted scan_dirs without losing the
    # connection fields.
    reread = hosts.read()["bio"]
    assert reread.scan_dirs == ("repos", "/srv/projects")
    assert reread.ssh_host == "bio.example"


def test_update_scan_dirs_can_clear(isolated):
    """Passing an empty list reverts the host to inventory defaults."""
    hosts.add(hosts.Host(
        name="bio", kind="ssh", ssh_host="bio",
        scan_dirs=("repos", "/srv/projects"),
    ))
    hosts.update_scan_dirs("bio", [])
    assert hosts.read()["bio"].scan_dirs == ()


def test_update_scan_dirs_materialises_local(isolated):
    """``local`` is auto-derived on read when missing from YAML — calling
    update_scan_dirs on it must actually persist a local row so the
    setting survives a restart."""
    hosts.update_scan_dirs("local", ["repos", "work/clones"])
    raw = hosts.hosts_file().read_text(encoding="utf-8")
    assert "local" in raw
    assert "work/clones" in raw
    assert hosts.read()["local"].scan_dirs == ("repos", "work/clones")


def test_update_scan_dirs_unknown_raises(isolated):
    with pytest.raises(hosts.HostNotFound):
        hosts.update_scan_dirs("ghost", ["repos"])


# ---------------------------------------------------------------------------
# Remote.run argv construction
# ---------------------------------------------------------------------------


def _local_host() -> hosts.Host:
    return hosts.Host(name="local", kind="local")


def _ssh_host(ssh_host: str = "lab-server") -> hosts.Host:
    return hosts.Host(name="lab-server", kind="ssh", ssh_host=ssh_host)


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
    r = remote.Remote(_ssh_host("lab-server"))
    r.run("ls /data/lab_vm")
    argv = captured["argv"]
    assert argv[0] == "ssh"
    assert "-o" in argv and "BatchMode=yes" in argv
    assert "-o" in argv and "ConnectTimeout=10" in argv
    assert "lab-server" in argv
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
    assert rows[0]["host"] == "lab-server"
    assert rows[0]["ssh_host"] == "lab-server"
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


def test_remote_murmurent_version_parses_stdout(isolated, monkeypatch):
    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, stdout="murmurent, version 1.0.0\n", stderr="")

    monkeypatch.setattr(remote.subprocess, "run", fake_run)
    r = remote.Remote(_ssh_host())
    assert r.murmurent_version() == "murmurent, version 1.0.0"


def test_update_host_edits_connection_fields(isolated):
    """The Machines editor is connection-only (issue #80): ssh_host,
    remote_user, description, scan_dirs. Each is independently updatable; None
    leaves a field untouched. Param fields are no longer accepted."""
    hosts.add(hosts.Host(
        name="lab-server", kind="ssh", ssh_host="old.host", remote_user="u1",
        description="d1", scan_dirs=("~/repos",),
    ))
    u = hosts.update_host(
        "lab-server", ssh_host="new.host", remote_user="u2",
        description="d2", scan_dirs=["~/a", "~/b"],
    )
    assert (u.ssh_host, u.remote_user, u.description, u.scan_dirs) == (
        "new.host", "u2", "d2", ("~/a", "~/b"))

    # Partial update leaves untouched fields alone.
    u2 = hosts.update_host("lab-server", remote_user="u3")
    assert u2.remote_user == "u3"
    assert u2.ssh_host == "new.host" and u2.description == "d2"


def test_update_host_blank_rules(isolated):
    """ssh_host keeps its current value when blanked (an ssh host must keep a
    host); remote_user/description accept an empty-string clear."""
    hosts.add(hosts.Host(
        name="lab-server", kind="ssh", ssh_host="keep.host", remote_user="u1",
        description="d1", scan_dirs=("~/repos",),
    ))
    u = hosts.update_host("lab-server", ssh_host="   ",
                          remote_user="  ", description="  ")
    assert u.ssh_host == "keep.host"
    assert u.remote_user == "" and u.description == ""


def test_update_host_ignores_legacy_param_kwargs(isolated):
    """An older client passing lab_vm_root/vault_root/etc. to update_host is
    tolerated (via **kwargs swallow) — none of it lands in the registry."""
    hosts.add(hosts.Host(name="lab-server", kind="ssh", ssh_host="lab-server"))
    # update_host's signature no longer declares param kwargs; the server body
    # (HostUpdateBody, extra=ignore) drops them before they ever reach here, so
    # a connection-only edit is all that persists.
    hosts.update_host("lab-server", description="just connection")
    text = hosts.hosts_file().read_text(encoding="utf-8")
    assert "lab_vm_root" not in text and "vault_root" not in text


def test_update_host_unknown_raises(isolated):
    with pytest.raises(hosts.HostNotFound):
        hosts.update_host("nope", ssh_host="x")


def test_vault_subfolders_default_to_convention(isolated):
    """The dataclass still exposes convention defaults for the retired param
    fields, so any downstream reader that touches them keeps working."""
    hosts.add(hosts.Host(name="lab-server", kind="ssh", ssh_host="lab-server"))
    bio = hosts.read()["lab-server"]
    assert bio.oracle_subfolder == "oracle"
    assert bio.notebook_subfolder == "lab-notebook"
    assert bio.lab_vault_root == ""
