"""
Purpose: Implementations of ``murmurent dashboard`` (Streamlit launcher,
         markdown snapshot, terminal-friendly outstanding summary).
Author: Mike Hallett (with Claude Code)
Date: 2026-05-07
Input: CLI flags from :mod:`murmurent.cli`.
Output: Side effects on ``lab-mgmt/dashboards/`` or stdout.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import click

from ..core import dashboard
from ..core.identity import resolve as resolve_identity
from ..core.repo import lab_mgmt_repo_root


def cmd_dashboard(
    *,
    pi_view: bool,
    snapshot: bool,
    outstanding: bool,
    hifi: bool = False,
    host: str = "127.0.0.1",
    port: int = 8770,
    tunnel: str = "",
    tunnel_port: int | None = None,
) -> int:
    """``murmurent dashboard`` — open Streamlit, print the snapshot, or print outstanding."""
    # Tunnel mode: no local server at all — forward a remote machine's
    # dashboard (bound to its own 127.0.0.1) to this laptop over SSH.
    if tunnel:
        return _launch_tunnel(target=tunnel, port=port, local_port=tunnel_port)

    identity = resolve_identity(allow_unknown=True)
    handle = identity.handle if identity.source != "unknown" else ""

    # Hi-fi (FastAPI) launcher: phase-0 lives alongside Streamlit until the
    # panels finish porting.
    if hifi:
        return _launch_hifi(host=host, port=port)

    # Streamlit-only mode: handle may be empty; the app shows a login sidebar.
    if not (snapshot or outstanding):
        return _launch_streamlit(handle)

    if not handle:
        raise click.ClickException(
            "No member identity resolved. Set $MURMURENT_USER or write your handle to "
            "~/.murmurent/user (e.g. `echo the_pi > ~/.murmurent/user`)."
        )

    snap = dashboard.build_snapshot(handle)

    if pi_view and not snap.is_pi:
        raise click.ClickException(
            "--pi requires MURMURENT_USER=the_pi (or PI gh handle); v1 hardcodes PI to @the_pi."
        )

    if outstanding:
        click.echo(dashboard.render_outstanding(snap), nl=False)
        return 0

    target = lab_mgmt_repo_root() / "dashboards" / f"{snap.member}.md"
    if target.is_file():
        click.echo(target.read_text(encoding="utf-8"), nl=False)
    else:
        click.echo(dashboard.render_markdown(snap), nl=False)
    return 0


def _launch_hifi(*, host: str, port: int) -> int:
    """Launch the FastAPI hi-fi server (uvicorn) in the foreground."""
    try:
        from ..dashboard import server as hifi_server  # noqa: F401
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise click.ClickException(
            "hi-fi dashboard deps missing (fastapi/uvicorn). Reinstall murmurent "
            "editable from the clone (the deps are hard deps, so this is all it "
            "takes):\n"
            "    cd ~/repos/murmurent && uv tool install --force --python 3.12 -e .\n"
            "Or run the /murmurent-reset skill at --level install."
        ) from exc

    click.echo(f"Hi-fi dashboard: http://{host}:{port}/")
    click.echo(f"  Data contract:   http://{host}:{port}/api/dashboard")

    # Guardrail: if the dashboard is bound to a non-loopback address it is
    # reachable off-machine — refuse to run wide-open unless a dashboard
    # secret is configured (or the operator explicitly accepts the risk).
    from ..dashboard import auth as _auth
    loopback = host in ("127.0.0.1", "localhost", "::1", "")
    if not loopback and not _auth.auth_enabled():
        click.secho(
            f"  ⚠ Exposed on {host}:{port} with NO dashboard auth — anyone who "
            f"can reach it can act as registrar.",
            fg="red", err=True,
        )
        click.secho(
            f"    Set ${_auth.ENV_VAR} (or write {_auth.SECRET_FILE}) to require a "
            f"login, then front it with TLS. See docs/setup.md.",
            fg="yellow", err=True,
        )
    click.echo("  Ctrl+C to stop.")
    import uvicorn

    uvicorn.run(
        "murmurent.dashboard.server:app",
        host=host,
        port=port,
        log_level="info",
        reload=False,
    )
    return 0


# ---------------------------------------------------------------------------
# SSH tunnel to a remote machine's dashboard (issue #80, remote-dashboard phase)
# ---------------------------------------------------------------------------


def resolve_tunnel_destination(target: str) -> str:
    """Turn ``target`` into an ssh destination string.

    If ``target`` names an ssh-kind host in ``~/.murmurent/hosts.yaml``,
    its ``ssh_host`` (prefixed with ``remote_user@`` when set and not
    already embedded) is used. A registry hit of kind ``local`` is an
    error (there is nothing to tunnel to on this machine). Any name not
    in the registry is passed to ssh verbatim, so plain ``you@host``
    destinations and ``~/.ssh/config`` aliases keep working.
    """
    from ..core import hosts as _hosts

    try:
        entry = _hosts.resolve(target)
    except _hosts.HostNotFound:
        return target
    if not entry.is_remote():
        raise click.ClickException(
            f"host {target!r} is this machine (kind: local) — nothing to "
            f"tunnel to. Run `murmurent dashboard --hifi` instead."
        )
    dest = entry.ssh_host
    if entry.remote_user and "@" not in dest:
        dest = f"{entry.remote_user}@{dest}"
    return dest


def build_tunnel_argv(ssh_dest: str, *, remote_port: int, local_port: int) -> list[str]:
    """Fixed-list ssh argv for the local port-forward (no shell involved)."""
    return [
        "ssh",
        "-N",
        "-L",
        f"{local_port}:localhost:{remote_port}",
        ssh_dest,
    ]


def _launch_tunnel(*, target: str, port: int, local_port: int | None) -> int:
    """Forward ``localhost:<local_port>`` to ``target``'s dashboard port.

    The remote dashboard stays bound to its own 127.0.0.1; the forward is
    the only way in, which is the point. Blocks until interrupted.
    """
    if shutil.which("ssh") is None:
        raise click.ClickException(
            "ssh not found on PATH. Install an OpenSSH client to use "
            "--tunnel (macOS/Linux ship one; on Windows enable the "
            "'OpenSSH Client' optional feature)."
        )
    ssh_dest = resolve_tunnel_destination(target)
    lport = local_port if local_port is not None else port
    argv = build_tunnel_argv(ssh_dest, remote_port=port, local_port=lport)
    click.echo(
        f"Open http://localhost:{lport} on this machine — you're viewing "
        f"{target}'s dashboard"
    )
    click.echo(f"  Forwarding via: {' '.join(argv)}")
    click.echo("  Ctrl+C to stop.")
    try:
        rc = subprocess.call(argv)
    except KeyboardInterrupt:
        return 0
    if rc == 130:  # ssh killed by the user's Ctrl+C — a clean stop
        return 0
    if rc != 0:
        raise click.ClickException(
            f"ssh exited with status {rc} (destination: {ssh_dest}). Check "
            f"that the host is reachable and that `murmurent dashboard "
            f"--hifi` is running there."
        )
    return 0


def _launch_streamlit(handle: str) -> int:
    """Launch the Streamlit app via ``streamlit run``."""
    if shutil.which("streamlit") is None:
        raise click.ClickException(
            "streamlit is not installed. `uv pip install streamlit` (already in "
            "the project's optional 'dashboard' extras) or run with --snapshot."
        )
    app_path = Path(__file__).resolve().parent.parent / "dashboard" / "app.py"
    if not app_path.is_file():
        raise click.ClickException(f"streamlit app not found at {app_path}")
    cmd = [
        "streamlit",
        "run",
        str(app_path),
        "--server.headless",
        "false",
        "--",
        f"--user={handle}",
    ]
    click.echo(f"Launching: {' '.join(cmd)}")
    return subprocess.call(cmd)


def cmd_generate_all() -> list[Path]:
    """Generate snapshots for every member listed in lab-mgmt/members/."""
    members_dir = lab_mgmt_repo_root() / "members"
    targets: list[Path] = []
    if not members_dir.is_dir():
        return targets
    for path in sorted(members_dir.glob("*.md")):
        handle = path.stem
        targets.append(dashboard.write_member_dashboard(handle))
    return targets
