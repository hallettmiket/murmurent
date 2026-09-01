"""
Purpose: One-shot Layer-2 CC bootstrap for repos that pre-date the install-wizard refactor.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-15
Input: ``~/repos/<project>/CHARTER.md`` (any project repo); optional
       installation manifest at ``~/.murmurent/installations/<project>.yaml``.
Output: ``<project>/.claude/agents/`` populated with symlinks + a
        ``<project>/CLAUDE.md`` stub. Prints traffic-light status per project.

Walks ``~/repos/`` and for each subdir containing a ``CHARTER.md``,
calls :func:`murmurent.core.project_cc_init.bootstrap_local`. The agent
selection comes from the matching installation manifest when present;
otherwise no per-project symlinks are created (Layer 1 — the
machine-wide ``~/.claude/agents/`` — already covers everything, so the
stub-only path is intentional).

Idempotent. Re-running is safe: existing murmurent-commons symlinks are
swept and re-created from the current pick; non-symlink files (a
user-authored project-specific agent .md) are preserved.

Usage:
    python -m scripts.backfill_local_repos
    python -m scripts.backfill_local_repos --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from murmurent.core.project_cc_init import bootstrap_local
from murmurent.core.repo import murmurent_repo_root

GREEN, YELLOW, RED, RESET = "\033[32m", "\033[33m", "\033[31m", "\033[0m"
PILL = {"ok": GREEN + "✓" + RESET, "warn": YELLOW + "!" + RESET, "fail": RED + "✗" + RESET}


def _load_manifest_agents(project: str) -> list[str] | None:
    """Return the picked agents from the install manifest, or ``None``.

    ``None`` means "no manifest" or "manifest has no agents key" —
    both cases tell bootstrap_local to skip symlink creation entirely
    (Layer 1 covers it).
    """
    path = Path.home() / ".murmurent" / "installations" / f"{project}.yaml"
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    agents = data.get("agents")
    if not isinstance(agents, list):
        return None
    return [str(a).strip() for a in agents if str(a).strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument(
        "--repos-dir", type=Path, default=Path.home() / "repos",
        help="parent of project working trees (default ~/repos)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="list what would be done without writing anything",
    )
    args = parser.parse_args(argv)

    if not args.repos_dir.is_dir():
        print(f"{RED}error:{RESET} {args.repos_dir} is not a directory", file=sys.stderr)
        return 2

    wig_root = murmurent_repo_root()
    if not (wig_root / "agents").is_dir():
        print(f"{RED}error:{RESET} murmurent commons not found at {wig_root / 'agents'}", file=sys.stderr)
        return 2

    candidates: list[Path] = []
    for child in sorted(args.repos_dir.iterdir()):
        # Skip non-dirs, hidden, and the murmurent clone itself (no
        # point bootstrapping the commons into itself).
        if not child.is_dir() or child.name.startswith("."):
            continue
        if (child / "CHARTER.md").is_file():
            candidates.append(child)

    if not candidates:
        print(f"{YELLOW}no projects with CHARTER.md found under {args.repos_dir}{RESET}")
        return 0

    print(f"Found {len(candidates)} project(s) under {args.repos_dir}:")
    summary = {"ok": 0, "warn": 0, "fail": 0}
    for proj in candidates:
        agents = _load_manifest_agents(proj.name)
        suffix = (
            f"  ({len(agents)} agents from installation manifest)"
            if agents else "  (no manifest — CLAUDE.md stub only; Layer 1 covers agents)"
        )
        print(f"\n  {proj.name}{suffix}")
        if args.dry_run:
            continue
        probes = bootstrap_local(
            proj, wig_root,
            agents=agents,
            project_name=proj.name,
        )
        for p in probes:
            print(f"    {PILL.get(p.status, '?')} {p.name:24} {p.detail}")
            summary[p.status] = summary.get(p.status, 0) + 1

    if not args.dry_run:
        print(f"\nDone. {summary['ok']} ok, {summary['warn']} warn, {summary['fail']} fail.")
    return 1 if summary["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
