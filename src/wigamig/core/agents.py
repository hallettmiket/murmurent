"""
Purpose: Read and validate the wigamig agent registry on disk.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-06
Input: ``agents/`` directory inside the wigamig repo (one ``<name>.md`` per agent).
Output: ``AgentRecord`` instances with the new wigamig frontmatter fields
        (``freeze``, ``required_tools``, ``denied_tools``, ``defaults``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .frontmatter import FrontmatterError, parse_file
from .repo import wigamig_repo_root

AGENTS_DIRNAME = "agents"
VALID_FREEZE_VALUES = {"frozen", "personal"}


@dataclass(frozen=True)
class AgentRecord:
    """A single agent definition loaded from the registry."""

    name: str
    freeze: str
    description: str
    required_tools: tuple[str, ...]
    denied_tools: tuple[str, ...]
    defaults: dict[str, Any] = field(default_factory=dict)
    path: Path | None = None


def agents_dir(repo_root: Path | None = None) -> Path:
    """Return the path to the agents directory inside the wigamig repo."""
    base = repo_root if repo_root is not None else wigamig_repo_root()
    return base / AGENTS_DIRNAME


def _coerce_tools(value: Any) -> tuple[str, ...]:
    """Normalise a tool list from frontmatter into a tuple of strings."""
    if value is None:
        return ()
    if isinstance(value, str):
        items = [piece.strip() for piece in value.split(",") if piece.strip()]
        return tuple(items)
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    raise FrontmatterError(
        f"Tool list must be a list or comma-separated string; got {type(value).__name__}."
    )


def load_agent(path: str | Path) -> AgentRecord:
    """Parse a single agent markdown file."""
    doc = parse_file(path)
    meta = doc.meta
    name = meta.get("name") or Path(path).stem
    freeze = meta.get("freeze")
    if freeze not in VALID_FREEZE_VALUES:
        raise FrontmatterError(
            f"Agent {name!r}: 'freeze' must be one of {sorted(VALID_FREEZE_VALUES)}; "
            f"got {freeze!r}."
        )

    defaults = meta.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise FrontmatterError(
            f"Agent {name!r}: 'defaults' must be a mapping; got {type(defaults).__name__}."
        )

    return AgentRecord(
        name=str(name),
        freeze=str(freeze),
        description=str(meta.get("description", "")).strip(),
        required_tools=_coerce_tools(meta.get("required_tools")),
        denied_tools=_coerce_tools(meta.get("denied_tools")),
        defaults=dict(defaults),
        path=Path(path),
    )


def load_registry(directory: str | Path | None = None) -> list[AgentRecord]:
    """Load every ``*.md`` agent in ``directory`` (defaults to the wigamig agents dir)."""
    base = Path(directory) if directory is not None else agents_dir()
    if not base.is_dir():
        return []
    return sorted(
        (load_agent(p) for p in base.glob("*.md")),
        key=lambda a: a.name,
    )
