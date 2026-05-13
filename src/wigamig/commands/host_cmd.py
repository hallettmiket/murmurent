"""
Purpose: CLI handlers for ``wigamig host {list, add, remove, test}``.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-13
Input: Arguments from the click subcommand layer.
Output: Stdout messages + side effects on ~/.wigamig/hosts.yaml.

The ``host`` command tree lets a user register a remote machine
(typically lab-server.example.edu) so the dashboard can offer it as
an install target for new projects. The full SSH plumbing lives in
:mod:`core.remote`; this module is just the CLI surface + diagnostics.
"""

from __future__ import annotations

import click

from ..core import hosts as _hosts
from ..core import remote as _remote


def cmd_list() -> int:
    """Print every registered host with its kind and key paths."""
    registry = _hosts.read()
    if not registry:
        click.echo("(no hosts registered — 'local' is always available)")
        return 0
    name_w = max(len(n) for n in registry) + 1
    for name, host in registry.items():
        target = host.ssh_host if host.is_remote() else "(this laptop)"
        click.echo(
            f"{name:<{name_w}}  {host.kind:<5}  {target:<28}  "
            f"project_root={host.project_root}"
        )
    return 0


def cmd_add(
    *,
    name: str,
    ssh_host: str | None,
    remote_user: str,
    project_root: str,
    lab_vm_root: str,
    vault_root: str,
    mount_point: str,
    description: str,
) -> int:
    """Register a new SSH host. Refuses on duplicate name."""
    kind = "ssh" if ssh_host else "local"
    host = _hosts.Host(
        name=name,
        kind=kind,
        ssh_host=ssh_host or "",
        remote_user=remote_user,
        project_root=project_root,
        lab_vm_root=lab_vm_root,
        vault_root=vault_root,
        mount_point=mount_point,
        description=description,
    )
    try:
        _hosts.add(host)
    except _hosts.HostError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Registered host {name!r} ({kind}).")
    if kind == "ssh":
        click.echo(f"  ssh_host:     {ssh_host}")
        click.echo(f"  remote_user:  {remote_user or '(use ssh_config default)'}")
        click.echo(f"  project_root: {project_root}")
        click.echo(f"  lab_vm_root:  {lab_vm_root}")
        click.echo("Next: run `wigamig host test " + name + "` to verify connectivity.")
    return 0


def cmd_remove(name: str) -> int:
    try:
        _hosts.remove(name)
    except _hosts.HostError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Removed host {name!r}.")
    return 0


def cmd_test(name: str) -> int:
    """Run a chain of probes against ``name``. Each probe prints ✓ or ✗.

    Returns 0 on overall success (all required probes pass), 1 on
    failure. The full set of probes:

      1. ssh connectivity        (required for ssh hosts)
      2. wigamig --version       (required)
      3. /data/lab_vm/{raw,refined} accessibility  (warn-only)
      4. gh auth status          (warn-only)
    """
    try:
        host = _hosts.resolve(name)
    except _hosts.HostNotFound as exc:
        raise click.ClickException(str(exc)) from exc

    remote = _remote.Remote(host)
    required_failures = 0

    # Probe 1: connectivity
    if host.is_remote():
        click.echo(f"→ ssh {host.ssh_host}", nl=False)
        res = remote.probe()
        if res.ok:
            click.echo("  ✓")
        else:
            click.echo("  ✗")
            click.echo(f"    {res.stderr.strip() or 'connection failed'}")
            required_failures += 1
            # No point continuing — the rest will all time out.
            return required_failures

    # Probe 2: wigamig --version
    click.echo("→ wigamig --version", nl=False)
    try:
        version = remote.wigamig_version()
        click.echo(f"  ✓  ({version})")
    except _remote.RemoteError as exc:
        click.echo("  ✗")
        click.echo(f"    {exc.stderr.strip() or str(exc)}")
        click.echo("    fix: bash scripts/install_remote.sh " + name)
        required_failures += 1

    # Probe 3: lab_vm dirs (warn-only)
    click.echo(f"→ {host.lab_vm_root}/{{raw,refined}}", nl=False)
    try:
        remote.run(
            f"test -d {host.lab_vm_root}/raw && test -d {host.lab_vm_root}/refined",
            check=False,
        )
    except _remote.RemoteError:
        pass
    else:
        # We used check=False above; re-run to learn the rc.
        res = remote.run(
            f"test -d {host.lab_vm_root}/raw && test -d {host.lab_vm_root}/refined",
            check=False,
        )
        if res.ok:
            click.echo("  ✓")
        else:
            click.echo("  ⚠ (missing — wigamig will create on first project)")

    # Probe 4: gh auth status (warn-only)
    click.echo("→ gh auth status", nl=False)
    res = remote.run(
        "command -v gh >/dev/null 2>&1 && gh auth status",
        check=False,
    )
    if res.ok:
        click.echo("  ✓")
    else:
        click.echo("  ⚠ (run `gh auth login` on the host before --repo-kind github)")

    if required_failures:
        click.echo(f"\n{required_failures} required check(s) failed.")
        return 1
    click.echo("\nAll required checks passed.")
    return 0
