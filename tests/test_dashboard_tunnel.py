"""Tests for ``murmurent dashboard --tunnel`` (issue #80, remote-dashboard phase).

Covers:
  - ``build_tunnel_argv`` produces the fixed-list ssh argv (no shell string)
  - ``--port`` moves both sides of the forward; ``--tunnel-port`` moves only
    the local side
  - ``resolve_tunnel_destination`` maps a hosts.yaml ssh host (with
    ``remote_user``) to ``user@host``, passes unknown names through verbatim,
    and refuses a local-kind host
  - ssh missing from PATH raises a clear ClickException
  - a nonzero ssh exit is surfaced; 130 (Ctrl+C) is a clean stop
  - CLI wiring: ``murmurent dashboard --tunnel`` reaches subprocess.call with
    the expected argv and prints the open-this-URL line

No test opens a real SSH connection: ``subprocess.call`` is monkeypatched
throughout.
"""

from __future__ import annotations

import click
import pytest
from click.testing import CliRunner

from murmurent.cli import cli
from murmurent.commands import dashboard_cmd as mod
from murmurent.core import hosts as _hosts


# ---------------------------------------------------------------------------
# argv construction
# ---------------------------------------------------------------------------


def test_argv_default_port() -> None:
    argv = mod.build_tunnel_argv("you@host", remote_port=8770, local_port=8770)
    assert argv == ["ssh", "-N", "-L", "8770:localhost:8770", "you@host"]


def test_argv_port_moves_both_sides() -> None:
    argv = mod.build_tunnel_argv("you@host", remote_port=9000, local_port=9000)
    assert argv == ["ssh", "-N", "-L", "9000:localhost:9000", "you@host"]


def test_argv_tunnel_port_moves_local_side_only() -> None:
    argv = mod.build_tunnel_argv("you@host", remote_port=8770, local_port=8899)
    assert argv == ["ssh", "-N", "-L", "8899:localhost:8770", "you@host"]


def test_argv_is_a_fixed_list() -> None:
    """Hostile-looking destinations stay a single argv element (no shell)."""
    dest = "you@host; rm -rf /"
    argv = mod.build_tunnel_argv(dest, remote_port=8770, local_port=8770)
    assert argv[-1] == dest
    assert all(isinstance(a, str) for a in argv)


# ---------------------------------------------------------------------------
# hosts.yaml resolution
# ---------------------------------------------------------------------------


@pytest.fixture
def hosts_yaml(tmp_path, monkeypatch):
    path = tmp_path / "hosts.yaml"
    monkeypatch.setenv(_hosts.ENV_VAR, str(path))
    _hosts.add(
        _hosts.Host(
            name="lab-server",
            kind="ssh",
            ssh_host="lab-server.internal",
            remote_user="you",
        )
    )
    _hosts.add(
        _hosts.Host(name="bare-server", kind="ssh", ssh_host="you@bare.internal")
    )
    return path


def test_resolve_registry_host_prefixes_remote_user(hosts_yaml) -> None:
    assert mod.resolve_tunnel_destination("lab-server") == "you@lab-server.internal"


def test_resolve_registry_host_keeps_embedded_user(hosts_yaml) -> None:
    assert mod.resolve_tunnel_destination("bare-server") == "you@bare.internal"


def test_resolve_unknown_name_passes_through(hosts_yaml) -> None:
    assert mod.resolve_tunnel_destination("you@elsewhere") == "you@elsewhere"


def test_resolve_local_kind_refused(hosts_yaml) -> None:
    with pytest.raises(click.ClickException, match="local"):
        mod.resolve_tunnel_destination("local")


# ---------------------------------------------------------------------------
# _launch_tunnel behaviour (subprocess.call monkeypatched)
# ---------------------------------------------------------------------------


def test_ssh_missing_is_a_clear_error(monkeypatch) -> None:
    monkeypatch.setattr(mod.shutil, "which", lambda _: None)
    with pytest.raises(click.ClickException, match="ssh not found"):
        mod._launch_tunnel(target="you@host", port=8770, local_port=None)


def test_nonzero_ssh_exit_is_surfaced(monkeypatch) -> None:
    monkeypatch.setattr(mod.shutil, "which", lambda _: "/usr/bin/ssh")
    monkeypatch.setattr(mod.subprocess, "call", lambda argv: 255)
    with pytest.raises(click.ClickException, match="status 255"):
        mod._launch_tunnel(target="you@host", port=8770, local_port=None)


def test_sigint_exit_130_is_clean(monkeypatch) -> None:
    monkeypatch.setattr(mod.shutil, "which", lambda _: "/usr/bin/ssh")
    monkeypatch.setattr(mod.subprocess, "call", lambda argv: 130)
    assert mod._launch_tunnel(target="you@host", port=8770, local_port=None) == 0


def test_keyboard_interrupt_is_clean(monkeypatch) -> None:
    monkeypatch.setattr(mod.shutil, "which", lambda _: "/usr/bin/ssh")

    def _boom(argv):
        raise KeyboardInterrupt

    monkeypatch.setattr(mod.subprocess, "call", _boom)
    assert mod._launch_tunnel(target="you@host", port=8770, local_port=None) == 0


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------


def _capture_call(monkeypatch):
    calls: list[list[str]] = []

    def _fake(argv):
        calls.append(list(argv))
        return 0

    monkeypatch.setattr(mod.shutil, "which", lambda _: "/usr/bin/ssh")
    monkeypatch.setattr(mod.subprocess, "call", _fake)
    return calls


def test_cli_tunnel_literal_destination(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv(_hosts.ENV_VAR, str(tmp_path / "hosts.yaml"))
    calls = _capture_call(monkeypatch)
    result = CliRunner().invoke(cli, ["dashboard", "--tunnel", "you@host"])
    assert result.exit_code == 0, result.output
    assert calls == [["ssh", "-N", "-L", "8770:localhost:8770", "you@host"]]
    assert (
        "Open http://localhost:8770 on this machine — you're viewing "
        "you@host's dashboard" in result.output
    )


def test_cli_tunnel_port_and_tunnel_port(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv(_hosts.ENV_VAR, str(tmp_path / "hosts.yaml"))
    calls = _capture_call(monkeypatch)
    result = CliRunner().invoke(
        cli,
        ["dashboard", "--tunnel", "you@host", "--port", "9000", "--tunnel-port", "9001"],
    )
    assert result.exit_code == 0, result.output
    assert calls == [["ssh", "-N", "-L", "9001:localhost:9000", "you@host"]]
    assert "http://localhost:9001" in result.output


def test_cli_tunnel_resolves_registry_host(monkeypatch, hosts_yaml) -> None:
    calls = _capture_call(monkeypatch)
    result = CliRunner().invoke(cli, ["dashboard", "--tunnel", "lab-server"])
    assert result.exit_code == 0, result.output
    assert calls == [
        ["ssh", "-N", "-L", "8770:localhost:8770", "you@lab-server.internal"]
    ]
