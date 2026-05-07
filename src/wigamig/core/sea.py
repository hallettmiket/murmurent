"""
Purpose: Skill / Experiment-as-event / Analysis (SEA) registry: file format,
         lifecycle, and project-scoped helpers.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-07
Input: ``<project>/seas/<id>.md`` files (one per SEA) and CLI arguments.
Output: ``Sea`` dataclasses, lifecycle transitions enforced as state-machine,
        renderers for new / updated SEA markdown.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .frontmatter import dump_document, parse_file
from .repo import ProjectRepo

SEAS_SUBDIR = "seas"
VALID_KINDS: tuple[str, ...] = ("skill", "experiment", "analysis")
VALID_STATES: tuple[str, ...] = (
    "requested",
    "claimed",
    "complete",
    "examined",
    "concluded",
    "declined",
)
TERMINAL_STATES: frozenset[str] = frozenset({"declined", "concluded"})
SEA_ID_RE = re.compile(r"^(?P<id>\d+)\.md$")


@dataclass
class Sea:
    """One SEA loaded from disk."""

    id: int
    from_handle: str
    to_handle: str
    kind: str
    description: str
    state: str = "requested"
    claimed_at: str | None = None
    completed_at: str | None = None
    examined_at: str | None = None
    concluded_at: str | None = None
    delivery: str | None = None
    decline_reason: str | None = None
    body: str = ""
    path: Path | None = None

    def to_meta(self) -> dict[str, Any]:
        """Render to the frontmatter dict used by ``render_sea`` / ``write_sea``."""
        meta: dict[str, Any] = {
            "id": self.id,
            "from": self.from_handle,
            "to": self.to_handle,
            "kind": self.kind,
            "description": self.description,
            "state": self.state,
        }
        for key, value in (
            ("claimed_at", self.claimed_at),
            ("completed_at", self.completed_at),
            ("examined_at", self.examined_at),
            ("concluded_at", self.concluded_at),
            ("delivery", self.delivery),
            ("decline_reason", self.decline_reason),
        ):
            if value is not None:
                meta[key] = value
        return meta


def seas_dir(repo: ProjectRepo) -> Path:
    """Return ``<project>/seas/``."""
    return repo.path / SEAS_SUBDIR


def sea_path(repo: ProjectRepo, sea_id: int) -> Path:
    """Return ``<project>/seas/<id>.md``."""
    return seas_dir(repo) / f"{sea_id}.md"


def parse_sea(path: Path) -> Sea:
    """Parse a SEA file into a :class:`Sea`."""
    parsed = parse_file(path)
    meta = parsed.meta
    return Sea(
        id=int(meta["id"]),
        from_handle=str(meta["from"]),
        to_handle=str(meta["to"]),
        kind=str(meta["kind"]),
        description=str(meta.get("description", "")),
        state=str(meta.get("state", "requested")),
        claimed_at=_opt_str(meta.get("claimed_at")),
        completed_at=_opt_str(meta.get("completed_at")),
        examined_at=_opt_str(meta.get("examined_at")),
        concluded_at=_opt_str(meta.get("concluded_at")),
        delivery=_opt_str(meta.get("delivery")),
        decline_reason=_opt_str(meta.get("decline_reason")),
        body=parsed.body,
        path=path,
    )


def iter_seas(repo: ProjectRepo) -> list[Sea]:
    """Return every SEA in ``repo`` ordered by integer id."""
    out: list[Sea] = []
    if not seas_dir(repo).is_dir():
        return out
    for child in seas_dir(repo).iterdir():
        m = SEA_ID_RE.match(child.name)
        if not m:
            continue
        try:
            out.append(parse_sea(child))
        except Exception:
            continue
    out.sort(key=lambda s: s.id)
    return out


def next_sea_id(repo: ProjectRepo, *, start: int = 1) -> int:
    """Return the next free integer SEA id in ``repo``."""
    used = [s.id for s in iter_seas(repo)]
    return (max(used) + 1) if used else start


def render_sea(sea: Sea) -> str:
    """Render a SEA to its markdown form."""
    body = sea.body or _default_body(sea)
    return dump_document(sea.to_meta(), body)


def write_sea(repo: ProjectRepo, sea: Sea) -> Path:
    """Persist ``sea`` to ``<project>/seas/<id>.md`` and return the path."""
    seas_dir(repo).mkdir(parents=True, exist_ok=True)
    path = sea_path(repo, sea.id)
    path.write_text(render_sea(sea), encoding="utf-8")
    sea.path = path
    return path


def _default_body(sea: Sea) -> str:
    return (
        f"# SEA {sea.id}: {sea.description}\n\n"
        f"From: {sea.from_handle}  ->  To: {sea.to_handle}  "
        f"(kind: {sea.kind})\n\n"
        f"## Context\n\n_(elaborate on the request here)_\n\n"
        f"## Delivery\n\n_(populated on `wigamig sea complete`)_\n"
    )


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return str(value)


# ---------------------------------------------------------------------------
# Lifecycle transitions
# ---------------------------------------------------------------------------


class SeaTransitionError(ValueError):
    """Raised when a SEA lifecycle transition is invalid for the current state."""


def _today() -> str:
    return _dt.date.today().isoformat()


def claim(sea: Sea) -> Sea:
    """Move a ``requested`` SEA to ``claimed``."""
    if sea.state != "requested":
        raise SeaTransitionError(
            f"SEA {sea.id} is in state {sea.state!r}; can only claim 'requested' SEAs."
        )
    sea.state = "claimed"
    sea.claimed_at = _today()
    return sea


def complete(sea: Sea, *, delivery: str) -> Sea:
    """Move a ``claimed`` SEA to ``complete`` with ``delivery`` recorded."""
    if sea.state not in {"claimed", "requested"}:
        raise SeaTransitionError(
            f"SEA {sea.id} is in state {sea.state!r}; can only complete 'claimed' SEAs."
        )
    sea.state = "complete"
    sea.completed_at = _today()
    sea.delivery = delivery
    return sea


def decline(sea: Sea, *, reason: str) -> Sea:
    """Move any non-terminal SEA to ``declined`` with a reason."""
    if sea.state in TERMINAL_STATES:
        raise SeaTransitionError(
            f"SEA {sea.id} is in terminal state {sea.state!r}; cannot decline."
        )
    sea.state = "declined"
    sea.decline_reason = reason
    return sea


def mark_examined(sea: Sea) -> Sea:
    """Move a ``complete`` SEA to ``examined`` (analysis-track stage 1)."""
    if sea.state != "complete":
        raise SeaTransitionError(
            f"SEA {sea.id} is in state {sea.state!r}; can only examine 'complete' SEAs."
        )
    sea.state = "examined"
    sea.examined_at = _today()
    return sea


def mark_concluded(sea: Sea) -> Sea:
    """Move an ``examined`` SEA to ``concluded`` (analysis-track stage 2)."""
    if sea.state not in {"examined", "complete"}:
        raise SeaTransitionError(
            f"SEA {sea.id} is in state {sea.state!r}; can only conclude examined SEAs."
        )
    sea.state = "concluded"
    sea.concluded_at = _today()
    return sea


def reopen(sea: Sea) -> Sea:
    """Re-open a concluded SEA. Sends it back to ``examined``."""
    if sea.state != "concluded":
        raise SeaTransitionError(
            f"SEA {sea.id} is in state {sea.state!r}; only concluded SEAs reopen."
        )
    sea.state = "examined"
    sea.concluded_at = None
    return sea


# ---------------------------------------------------------------------------
# Filtering helpers used by the CLI
# ---------------------------------------------------------------------------


def filter_for_member(seas: Iterable[Sea], handle: str, *, direction: str) -> list[Sea]:
    """Return SEAs visible to ``handle`` along ``direction``.

    ``direction`` is one of ``mine`` (incoming or outgoing), ``incoming``,
    ``outgoing``.
    """
    norm = handle.lstrip("@").lower()
    out: list[Sea] = []
    for s in seas:
        from_ = s.from_handle.lstrip("@").lower()
        to_ = s.to_handle.lstrip("@").lower()
        if direction == "incoming" and to_ == norm:
            out.append(s)
        elif direction == "outgoing" and from_ == norm:
            out.append(s)
        elif direction == "mine" and norm in (from_, to_):
            out.append(s)
    return out
