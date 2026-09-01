"""
Purpose: Implementation of ``murmurent data ...`` subcommands — the data-tree
         maintenance verbs. Currently: ``data migrate``, which renames the
         legacy ``raw/`` -> ``immutable/`` and ``refined/`` -> ``append_only/``
         directories under the data root (the 2026-07 dual-name transition).
Author: Mike Hallett (with Claude Code)
Date: 2026-07-20
Input: CLI arguments forwarded from :mod:`murmurent.cli` (optional ``--root``
       and ``--dry-run``).
Output: Renames on the data-root filesystem; a per-directory report on stdout.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import click

from ..core import lab_vm

# (legacy name, new name) pairs, in display order.
_RENAMES: tuple[tuple[str, str], ...] = (
    (lab_vm.LEGACY_IMMUTABLE_SUBDIR, lab_vm.IMMUTABLE_SUBDIR),
    (lab_vm.LEGACY_APPEND_ONLY_SUBDIR, lab_vm.APPEND_ONLY_SUBDIR),
)


@dataclass(frozen=True)
class MigrationAction:
    """One planned (or performed) rename under the data root."""

    legacy: Path
    new: Path
    status: str  # "rename" | "skip-absent" | "skip-migrated" | "conflict"
    detail: str


def plan_migration(root: Path) -> list[MigrationAction]:
    """Compute the rename actions for ``root`` without touching the filesystem.

    - legacy present, new absent  → ``rename``
    - legacy absent               → ``skip-absent`` (nothing to move; idempotent)
    - legacy absent, new present  → ``skip-migrated`` (already done; idempotent)
    - legacy present, new present → ``conflict`` (refuse — destination exists)
    """
    actions: list[MigrationAction] = []
    for legacy_name, new_name in _RENAMES:
        legacy = root / legacy_name
        new = root / new_name
        legacy_here = legacy.exists()
        new_here = new.exists()
        if legacy_here and new_here:
            actions.append(MigrationAction(
                legacy, new, "conflict",
                f"both {legacy_name}/ and {new_name}/ exist — refusing to merge",
            ))
        elif legacy_here and not new_here:
            actions.append(MigrationAction(
                legacy, new, "rename", f"{legacy_name}/ -> {new_name}/",
            ))
        elif not legacy_here and new_here:
            actions.append(MigrationAction(
                legacy, new, "skip-migrated", f"{new_name}/ already present",
            ))
        else:
            actions.append(MigrationAction(
                legacy, new, "skip-absent", f"no {legacy_name}/ to migrate",
            ))
    return actions


def cmd_migrate(root: str | None, *, dry_run: bool) -> int:
    """``murmurent data migrate`` — rename legacy raw/refined dirs to the new names.

    Idempotent (re-running after a successful migrate is a no-op). Refuses when a
    destination already exists alongside its legacy source. ``--dry-run`` previews.
    """
    data_root = Path(root).expanduser() if root else lab_vm.data_root()
    click.echo(f"Data root: {data_root}")

    actions = plan_migration(data_root)

    conflicts = [a for a in actions if a.status == "conflict"]
    if conflicts:
        for a in conflicts:
            click.echo(f"  CONFLICT  {a.detail}")
        raise click.ClickException(
            "refusing to migrate: a destination directory already exists. "
            "Reconcile the two directories by hand, then re-run."
        )

    renamed = 0
    for a in actions:
        if a.status == "rename":
            if dry_run:
                click.echo(f"  [dry-run] would rename {a.detail}")
            else:
                a.legacy.rename(a.new)
                click.echo(f"  renamed   {a.detail}")
                renamed += 1
        elif a.status == "skip-migrated":
            click.echo(f"  ok        {a.detail}")
        else:  # skip-absent
            click.echo(f"  skip      {a.detail}")

    if dry_run:
        pending = sum(1 for a in actions if a.status == "rename")
        click.echo(f"[dry-run] {pending} directory rename(s) pending; nothing changed.")
    else:
        click.echo(f"Done: {renamed} directory rename(s) applied.")
    return 0
