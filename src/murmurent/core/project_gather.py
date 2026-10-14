"""
Purpose: move a project's repositories into one project folder (issue #166).
Author: Mike Hallett (with Claude Code)
Date: 2026-10-14
Input: a project name; this machine's repositories folder; the project record
Output: a GatherPlan (what would move, and what could not be updated), and,
        when applied, the moved folders and this machine's updated record

`murmurent project gather x_y` turns

    <repositories>/x_y   <repositories>/x_y_manuscript   <repositories>/x_y_seminar

into

    <repositories>/x_y/x_y   <repositories>/x_y/x_y_manuscript   <repositories>/x_y/x_y_seminar

Each repository keeps its full name: it is also the GitHub repository's name and
its folder's name under the data root, so only the location changes. The move
is on this machine only. Other members keep their own layout; murmurent finds
each member's copies on their own machine (core.repo_paths).

It never overwrites anything, and it shows its plan first. A move cannot
update things outside murmurent that name the old folders, so the plan lists
them for a person to fix: an editable murmurent install, VS Code workspace
files, Claude Code's per-folder history, and rules that spell out a path.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import repo_paths as _rp
from .repo import repos_root

#: Suffixes of a project's sibling repositories, in the order shown.
SIBLING_SUFFIXES = ("manuscript", "seminar", "data", "infra")


class GatherError(RuntimeError):
    """The gather cannot go ahead; the message says why."""


@dataclass
class Move:
    name: str
    source: Path
    target: Path


@dataclass
class GatherPlan:
    project: str
    folder: Path
    moves: list[Move] = field(default_factory=list)
    already_inside: list[str] = field(default_factory=list)
    not_found: list[str] = field(default_factory=list)
    to_fix_by_hand: list[str] = field(default_factory=list)


def _project_repo_names(project: str) -> list[str]:
    """The project's repositories: from its record when it has one, plus any
    `<project>_manuscript` / `_seminar` / ... sitting in the repositories folder."""
    names: list[str] = []
    try:
        from . import cert_projects as _cp
        record = _cp.get(project)
    except Exception:  # noqa: BLE001 - a project without a record still gathers
        record = None
    if record is not None:
        names += [r.name for r in record.repos if (r.host or "local") == "local" and r.name]
    names.append(project)
    root = repos_root()
    for suffix in SIBLING_SUFFIXES:
        sibling = f"{project}_{suffix}"
        if (root / sibling).is_dir() or (root / project / sibling).is_dir():
            names.append(sibling)
    return list(dict.fromkeys(names))


def _things_naming(old: Path) -> list[str]:
    """Things outside murmurent that name ``old`` and a move cannot update."""
    notes: list[str] = []
    try:
        from .commons import editable_clone_root
        if editable_clone_root().resolve() == old.resolve():
            notes.append(f"murmurent itself runs from {old} (an editable install). After the move, "
                         f"reinstall from the new place: uv tool install --python 3.12 --reinstall -e <new folder>")
    except Exception:  # noqa: BLE001
        pass
    history = Path.home() / ".claude" / "projects" / str(old).replace("/", "-").replace("_", "-")
    if history.is_dir():
        notes.append(f"Claude Code's session history and memory for {old} are filed under {history}. "
                     "A session opened in the new folder starts without them unless that folder is "
                     "renamed to match the new path.")
    for ws in sorted(old.parent.glob("*.code-workspace")):
        try:
            if str(old) in ws.read_text(encoding="utf-8") or old.name in ws.read_text(encoding="utf-8"):
                notes.append(f"VS Code workspace {ws} names {old.name}; update its folder paths.")
        except OSError:
            pass
    rules = Path.home() / ".claude" / "rules"
    for rule in sorted(rules.glob("**/*.md")) if rules.is_dir() else []:
        try:
            if str(old) in rule.read_text(encoding="utf-8"):
                notes.append(f"{rule} spells out {old}; update the path.")
        except OSError:
            pass
    return notes


def plan(project: str) -> GatherPlan:
    """Work out what `gather` would do, without touching anything."""
    root = repos_root()
    folder = root / project
    result = GatherPlan(project=project, folder=folder)
    for name in _project_repo_names(project):
        current = _rp.find(name)
        target = folder / name
        if current is None:
            result.not_found.append(name)
        elif current.resolve() == target.resolve():
            result.already_inside.append(name)
        else:
            result.moves.append(Move(name=name, source=current, target=target))
            result.to_fix_by_hand += _things_naming(current)
    # The code repository usually IS <repositories>/<project>. Then the project
    # folder is created fresh by the move, so nothing inside it can collide.
    # Otherwise each target must be free.
    code_is_the_folder = any(m.source.resolve() == folder.resolve() for m in result.moves)
    if not code_is_the_folder:
        if folder.exists() and not folder.is_dir():
            raise GatherError(f"{folder} exists and is not a folder; nothing was moved.")
        for move in result.moves:
            if move.target.exists():
                raise GatherError(f"{move.target} already exists; nothing was moved. "
                                  "Move it aside and try again.")
    return result


def apply(gather_plan: GatherPlan) -> list[str]:
    """Carry out ``gather_plan``. Returns one line per folder moved.

    The code repository usually has the project's own name, so it IS the
    folder the others move into. It is first renamed to a temporary name,
    the project folder is created, and it moves in under its own name.
    """
    done: list[str] = []
    folder = gather_plan.folder
    moves = list(gather_plan.moves)
    code_move = next((m for m in moves if m.source.resolve() == folder.resolve()), None)
    if code_move is not None:
        holding = folder.with_name(f".{folder.name}.gathering")
        if holding.exists():
            raise GatherError(f"{holding} exists from an earlier, interrupted gather; move it back to {folder} first.")
        folder.rename(holding)
        folder.mkdir()
        holding.rename(code_move.target)
        _rp.record(code_move.name, code_move.target)
        done.append(f"{code_move.source} -> {code_move.target}")
        moves.remove(code_move)
    folder.mkdir(parents=True, exist_ok=True)
    for move in moves:
        if move.target.exists():
            raise GatherError(f"{move.target} already exists; stopped before moving {move.name}.")
        shutil.move(str(move.source), str(move.target))
        _rp.record(move.name, move.target)
        done.append(f"{move.source} -> {move.target}")
    return done
