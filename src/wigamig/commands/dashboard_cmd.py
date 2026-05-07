"""
Purpose: Implementations of ``wigamig dashboard`` (Streamlit launcher,
         markdown snapshot, terminal-friendly outstanding summary).
Author: Mike Hallett (with Claude Code)
Date: 2026-05-07
Input: CLI flags from :mod:`wigamig.cli`.
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
) -> int:
    """``wigamig dashboard`` — open Streamlit, print the snapshot, or print outstanding."""
    identity = resolve_identity(allow_unknown=True)
    handle = identity.handle
    snap = dashboard.build_snapshot(handle)

    if pi_view and not snap.is_pi:
        raise click.ClickException(
            "--pi requires WIGAMIG_USER=mike (or PI gh handle); v1 hardcodes PI to @mike."
        )

    if outstanding:
        click.echo(dashboard.render_outstanding(snap), nl=False)
        return 0

    if snapshot:
        target = lab_mgmt_repo_root() / "dashboards" / f"{snap.member}.md"
        if target.is_file():
            click.echo(target.read_text(encoding="utf-8"), nl=False)
        else:
            click.echo(dashboard.render_markdown(snap), nl=False)
        return 0

    return _launch_streamlit(handle)


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
