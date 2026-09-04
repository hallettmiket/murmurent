"""
Purpose: wire the murmurent commons into ~/.claude/ (agents, rules, skills,
         CLAUDE.md) from a clone OR from the installed package.
Author: Mike Hallett (with Claude Code)
Date: 2026-09-01
Input: the commons (see core.commons.commons_root)
Output: symlinks under ~/.claude/; a per-item report

This is the Python half of ``scripts/setup.sh``. The shell script still exists
and is what a clone-based install runs; this exists so that
``uv tool install murmurent`` is a COMPLETE install, with no clone and no
``curl | bash``.

Both write the same symlinks with the same rules, and both are idempotent:

* an existing symlink is re-pointed (so an upgrade moves it to the new source);
* a REGULAR FILE is never touched. A member who wrote their own
  ``~/.claude/agents/oracle.md`` keeps it, and is told it was preserved. Silently
  overwriting someone's own agent would be the worst thing this command could do.

Symlinks rather than copies, so an edit in the clone takes effect immediately
and an upgrade of the package does not leave stale copies behind.
"""

from __future__ import annotations

from pathlib import Path

import click

from ..core.commons import commons_root, commons_source


def _cc_dir() -> Path:
    import os

    override = os.environ.get("MURMURENT_CC_DIR")
    return Path(override).expanduser() if override else Path.home() / ".claude"


def _link_dir(src_dir: Path, dest_dir: Path, pattern: str, kind: str) -> tuple[int, int, int]:
    """Link every ``pattern`` under ``src_dir`` into ``dest_dir``.

    Returns (created, repointed, preserved).
    """
    created = repointed = preserved = 0
    if not src_dir.is_dir():
        return (0, 0, 0)
    dest_dir.mkdir(parents=True, exist_ok=True)
    for src in sorted(src_dir.glob(pattern)):
        dest = dest_dir / src.name
        if dest.is_symlink():
            dest.unlink()
            dest.symlink_to(src)
            repointed += 1
        elif dest.exists():
            click.echo(f"  ! preserved your own {kind}/{src.name} (not a symlink)")
            preserved += 1
        else:
            dest.symlink_to(src)
            click.echo(f"  + {kind}/{src.name}")
            created += 1
    return (created, repointed, preserved)


def _prune_dangling(dest_dir: Path, root: Path, kind: str) -> int:
    """Remove symlinks in ``dest_dir`` that point INTO the commons at a file
    that is gone: an agent retired from the commons, a rule renamed.

    Only links into the commons are candidates. A link into someone's personal
    vault, or anywhere else, is theirs and stays whatever it points at. Returns
    the number removed.
    """
    removed = 0
    if not dest_dir.is_dir():
        return 0
    root_s = str(root)
    for p in sorted(dest_dir.iterdir()):
        if not p.is_symlink() or p.exists():
            continue
        import os

        target = os.readlink(p)
        if target.startswith(root_s):
            p.unlink()
            click.echo(f"  - removed dangling {kind}/{p.name} (it left the commons)")
            removed += 1
    return removed


def cmd_setup(*, force: bool = False, show_next_step: bool = True) -> int:
    """Wire agents, rules, skills and CLAUDE.md into ~/.claude/.

    ``show_next_step`` is False when called from ``murmurent install``, which
    registers the hooks itself a moment later. Telling someone to run a command
    that has already run is how a working install gets reported as broken.
    """
    root = commons_root()
    source = commons_source()
    cc = _cc_dir()

    click.echo(f"Wiring the murmurent commons from the {source}:")
    click.echo(f"  {root}")
    click.echo(f"into {cc}\n")

    if not (root / "agents").is_dir():
        click.echo(
            "  x no commons found.\n"
            "    Either reinstall the package, or set MURMURENT_REPO_ROOT to your "
            "murmurent clone.",
            err=True,
        )
        return 1

    totals = [0, 0, 0]
    for sub, pattern, kind in (
        ("agents", "*.md", "agents"),
        ("rules", "*.md", "rules"),
    ):
        c, r, p = _link_dir(root / sub, cc / sub, pattern, kind)
        totals = [totals[0] + c, totals[1] + r, totals[2] + p]

    # Deployment-specific rules, when the commons came from a clone that has
    # them. A package install has no rules/local by construction.
    c, r, p = _link_dir(root / "rules" / "local", cc / "rules", "*.md", "rules")
    totals = [totals[0] + c, totals[1] + r, totals[2] + p]

    # Skills are directories, not files.
    skills_src = root / "skills"
    if skills_src.is_dir():
        (cc / "skills").mkdir(parents=True, exist_ok=True)
        for src in sorted(d for d in skills_src.iterdir() if d.is_dir()):
            dest = cc / "skills" / src.name
            if dest.is_symlink():
                dest.unlink()
                dest.symlink_to(src)
                totals[1] += 1
            elif dest.exists():
                click.echo(f"  ! preserved your own skills/{src.name} (not a symlink)")
                totals[2] += 1
            else:
                dest.symlink_to(src)
                click.echo(f"  + skills/{src.name}")
                totals[0] += 1

    # CLAUDE.md sits beside the commons in a clone, and one level up from the
    # packaged commons dir; ship it from wherever it actually is.
    for candidate in (root / "CLAUDE.md", root.parent / "CLAUDE.md"):
        if candidate.is_file():
            dest = cc / "CLAUDE.md"
            if dest.is_symlink() or not dest.exists():
                if dest.is_symlink():
                    dest.unlink()
                dest.symlink_to(candidate)
                click.echo("  + CLAUDE.md")
            else:
                click.echo("  ! preserved your own CLAUDE.md (not a symlink)")
            break

    pruned = sum(_prune_dangling(cc / sub, root, sub) for sub in ("agents", "rules", "skills"))

    created, repointed, preserved = totals
    click.echo(
        f"\n{created} created, {repointed} re-pointed, {pruned} dangling removed, "
        f"{preserved} of your own files left alone."
    )
    if show_next_step:
        click.echo("\nNext: murmurent install --hooks   (registers hooks + MCP servers)")
    return 0
